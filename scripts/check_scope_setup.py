"""Check local provider configuration without printing secrets or making requests."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.scope_ai import AIConfig, AnalysisError
from backend.app.paypal_provider import PayPalSandboxConnection


def read_values(path):
    values = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or name in values:
            raise ValueError('invalid_profile')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[name] = value
    return values


def check(path, required, validate):
    if not path.exists():
        return {'status': 'missing_file', 'missing_fields': required}
    try:
        values = read_values(path)
        missing = [name for name in required if not values.get(name)]
        if missing:
            return {'status': 'incomplete', 'missing_fields': missing}
        validate(values)
    except (OSError, UnicodeError, ValueError, AnalysisError):
        return {'status': 'invalid_configuration'}
    return {'status': 'configured_locally', 'provider_verified': False}


def paypal(values):
    if values.get('PAYPAL_ENABLED') != '1':
        raise ValueError('paypal_disabled')
    PayPalSandboxConnection(values['PAYPAL_WORKSPACE_A_CLIENT_ID'],
        values['PAYPAL_WORKSPACE_A_CLIENT_SECRET'], values['PAYPAL_WORKSPACE_A_MERCHANT_ID'],
        environment=values['PAYPAL_ENVIRONMENT'], webhook_id=values.get('PAYPAL_WORKSPACE_A_WEBHOOK_ID') or None)


def ai_profile():
    path = ROOT / '.env.scope'
    try:
        provider = read_values(path).get('AI_PROVIDER', 'openai')
    except (OSError, UnicodeError, ValueError):
        return {'status': 'invalid_configuration'}
    if provider not in ('openai', 'gemini'):
        return {'status': 'invalid_configuration'}
    prefix = provider.upper()
    result = check(path, [prefix + '_API_KEY', prefix + '_MODEL'],
        lambda v: AIConfig(v[prefix + '_API_KEY'], v[prefix + '_MODEL'], provider))
    return {'provider': provider, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init', action='store_true', help='Create missing ignored profiles from templates; never overwrite existing files.')
    args = parser.parse_args()
    if args.init:
        for filename in ('.env.scope', '.env.paypal'):
            try:
                with (ROOT / filename).open('x', encoding='utf-8') as target:
                    target.write((ROOT / (filename + '.example')).read_text(encoding='utf-8'))
            except FileExistsError:
                pass
    result = {
        'scope': 'local_file_configuration_only',
        'external_requests': 0,
        'ai': ai_profile(),
        'paypal': check(ROOT / '.env.paypal', ['PAYPAL_ENABLED', 'PAYPAL_ENVIRONMENT',
            'PAYPAL_WORKSPACE_A_CLIENT_ID', 'PAYPAL_WORKSPACE_A_CLIENT_SECRET',
            'PAYPAL_WORKSPACE_A_MERCHANT_ID'], paypal),
    }
    print(json.dumps(result, indent=2))
    return 0 if all(result[name]['status'] == 'configured_locally' for name in ('ai', 'paypal')) else 2


if __name__ == '__main__':
    sys.exit(main())
