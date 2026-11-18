"""Tenant-bound sandbox drafts and explicit share-link activation. No collections.

The API's draft-create endpoint does not document an idempotency guarantee. An
ambiguous write is therefore terminal for automatic execution: manual recovery
must identify the deterministic invoice number/reference before another write.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import re
from urllib.parse import urlsplit

import httpx

from .ingestion import decode_json
from .jobs import ReadFailure
from .paypal_provider import API_BASE, MAX_BODY, PayPalSandboxClient, PayPalSandboxConnection

INVOICE_ID = re.compile(r'INV2-[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}')


class InvoiceError(Exception):
    def __init__(self, code, uncertain=False, retryable=False):
        self.code, self.uncertain, self.retryable = code, uncertain, retryable
        super().__init__(code)


def _require(condition):
    if not condition:
        raise InvoiceError('paypal_invoice_binding_invalid')


def invoice_number(payload):
    return 'SP-' + hashlib.sha256(payload['invoice_id'].encode()).hexdigest()[:22].upper()


def _safe_issue_date():
    # UTC-12 is the earliest civil date worldwide. A date no later than this
    # cannot become a future scheduled issue date in another merchant zone.
    return (datetime.now(UTC) - timedelta(hours=12)).date()


def _payload(payload):
    if not isinstance(payload, dict):
        raise InvoiceError('invoice_payload_invalid')
    limits = {'invoice_id': 100, 'recipient_email': 254, 'client_name': 200,
              'project_name': 200, 'title': 120, 'description': 1000}
    for name, maximum in limits.items():
        value = payload.get(name)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or '\x00' in value:
            raise InvoiceError('invoice_payload_invalid')
    if (not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', payload['invoice_id']) or
            not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', payload['recipient_email']) or
            type(payload.get('amount_minor')) is not int or not 0 < payload['amount_minor'] <= 10**10 or
            payload.get('currency') != 'usd'):
        raise InvoiceError('invoice_payload_invalid')
    return payload


def _money(value):
    _require(isinstance(value, dict) and value.get('currency_code') == 'USD')
    text = value.get('value')
    _require(isinstance(text, str) and re.fullmatch(r'[0-9]{1,11}(?:\.[0-9]{1,2})?', text) is not None)
    return int(Decimal(text) * 100)


def _normalize(body, payload, expected_id=None):
    _require(isinstance(body, dict))
    identifier = body.get('id')
    _require(isinstance(identifier, str) and INVOICE_ID.fullmatch(identifier) is not None)
    _require(expected_id is None or identifier == expected_id)
    detail = body.get('detail')
    _require(isinstance(detail, dict) and detail.get('invoice_number') == invoice_number(payload)
             and detail.get('reference') == 'scope:' + payload['invoice_id']
             and detail.get('currency_code') == 'USD')
    recipients = body.get('primary_recipients')
    _require(isinstance(recipients, list) and len(recipients) == 1 and isinstance(recipients[0], dict))
    billing = recipients[0].get('billing_info')
    _require(isinstance(billing, dict) and billing.get('email_address') == payload['recipient_email'])
    _require(_money(body.get('amount')) == payload['amount_minor'])
    items = body.get('items')
    _require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict))
    item = items[0]
    _require(item.get('name') == payload['title'] and item.get('description') == payload['description'])
    quantity = item.get('quantity')
    _require(isinstance(quantity, str) and re.fullmatch(r'1(?:\.0{1,5})?', quantity) is not None)
    _require(_money(item.get('unit_amount')) == payload['amount_minor'])
    status = body.get('status')
    # Never collapse manual, partial, pending or reversed payment states into paid.
    if not isinstance(status, str) or status not in {'DRAFT', 'SENT', 'UNPAID', 'SHARED', 'PAID'}:
        raise InvoiceError('paypal_invoice_state_requires_review')
    due = _money(body.get('due_amount'))
    _require(due == (0 if status == 'PAID' else payload['amount_minor']))
    state = 'draft' if status == 'DRAFT' else 'paid' if status == 'PAID' else 'unpaid'
    payment_url = None
    if state == 'unpaid':
        metadata = detail.get('metadata', {})
        candidate = metadata.get('recipient_view_url') if isinstance(metadata, dict) else None
        if (isinstance(candidate, str) and len(candidate) <= 2048
                and not any(ord(character) <= 32 for character in candidate)):
            try:
                url = urlsplit(candidate)
            except ValueError:
                url = None
            # A sandbox invoice never displays a live-domain or arbitrary link.
            if (url is not None and url.scheme == 'https' and url.netloc == 'www.sandbox.paypal.com'
                    and url.path.startswith('/invoice/p') and not url.query):
                payment_url = candidate
    return {'provider_invoice_id': identifier, 'status': state, 'amount_minor': payload['amount_minor'],
            'currency': 'usd', 'payment_url': payment_url}


class _InvoiceClient(PayPalSandboxClient):
    def _json(self, method, path, **kwargs):
        if method == 'POST' and path == '/v1/oauth2/token':
            return super()._json(method, path, **kwargs)
        is_create = method == 'POST' and path == '/v2/invoicing/invoices'
        is_activate = method == 'POST' and path.startswith('/v2/invoicing/invoices/') and path.endswith('/send') and INVOICE_ID.fullmatch(
            path.removeprefix('/v2/invoicing/invoices/').removesuffix('/send')) is not None
        is_read = method == 'GET' and path.startswith('/v2/invoicing/invoices/') and INVOICE_ID.fullmatch(
            path.removeprefix('/v2/invoicing/invoices/')) is not None
        if not (is_create or is_read or is_activate):
            raise InvoiceError('paypal_invoice_operation_invalid')
        is_write = is_create or is_activate
        started = self.clock()
        try:
            with self.http.stream(method, API_BASE + path, timeout=8, follow_redirects=False, **kwargs) as response:
                status = response.status_code
                if status == 401:
                    raise ReadFailure('paypal_authentication_failed', False)
                if status in (400, 403, 404, 406, 422):
                    raise InvoiceError('paypal_invoice_request_rejected')
                if status == 429:
                    raise InvoiceError('paypal_invoice_rate_limited', retryable=not is_write)
                if status not in ((201,) if is_create else (200, 202) if is_activate else (200,)):
                    raise InvoiceError('paypal_invoice_unavailable', uncertain=is_write, retryable=not is_write)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY or self.clock() - started > 12:
                        raise InvoiceError('paypal_invoice_response_budget', uncertain=is_write, retryable=not is_write)
                if is_activate and not raw:
                    return {}
                value = decode_json(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                return value
        except httpx.RequestError:
            raise InvoiceError('paypal_invoice_network_error', uncertain=is_write, retryable=not is_write) from None
        except (ValueError, RecursionError):
            raise InvoiceError('paypal_invoice_response_invalid', uncertain=is_write) from None


def _client(connection, http):
    if not isinstance(connection, PayPalSandboxConnection) or connection.environment != 'sandbox':
        raise InvoiceError('paypal_invoice_not_configured')
    return _InvoiceClient(connection, http)


def _read_failure(error):
    return InvoiceError(error.code, retryable=error.retryable)


def create_draft(connection, http, payload, key):
    payload = _payload(payload)
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_:-]{1,150}', key):
        raise InvoiceError('invoice_payload_invalid')
    amount = format(Decimal(payload['amount_minor']) / 100, '.2f')
    body = {'detail': {'invoice_number': invoice_number(payload), 'reference': 'scope:' + payload['invoice_id'],
                       'currency_code': 'USD', 'invoice_date': _safe_issue_date().isoformat()},
            'primary_recipients': [{'billing_info': {'email_address': payload['recipient_email']}}],
            'items': [{'name': payload['title'], 'description': payload['description'], 'quantity': '1',
                       'unit_amount': {'currency_code': 'USD', 'value': amount}}],
            'configuration': {'partial_payment': {'allow_partial_payment': False}, 'allow_tip': False}}
    client = _client(connection, http)
    # The stable application key is intentionally not treated as a documented
    # provider idempotency guarantee. The database owns one logical write.
    try:
        token = client._token()
        result = client._json('POST', '/v2/invoicing/invoices', json=body,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json', 'Prefer': 'return=representation'})
    except ReadFailure as error:
        raise _read_failure(error) from None
    try:
        normalized = _normalize(result, payload)
        _require(normalized['status'] == 'draft')
        return normalized
    except InvoiceError as error:
        # Even a 201 response with missing/bad binding may represent a created
        # invoice. Never repeat it automatically.
        raise InvoiceError(error.code, uncertain=True) from None


def read_invoice(connection, http, provider_invoice_id, payload):
    payload = _payload(payload)
    if not isinstance(provider_invoice_id, str) or INVOICE_ID.fullmatch(provider_invoice_id) is None:
        raise InvoiceError('paypal_invoice_binding_invalid')
    try:
        body = _client(connection, http).authorized('GET', '/v2/invoicing/invoices/' + provider_invoice_id)
    except ReadFailure as error:
        raise _read_failure(error) from None
    return _normalize(body, payload, provider_invoice_id)


def activate_invoice(connection, http, provider_invoice_id, payload):
    """Make an existing sandbox draft payable without requesting notification.

    Caller must durably fence this separately authorized write. Its known provider
    ID allows a read after uncertain activation; never replace it with a new draft.
    """
    payload = _payload(payload)
    if not isinstance(provider_invoice_id, str) or INVOICE_ID.fullmatch(provider_invoice_id) is None:
        raise InvoiceError('paypal_invoice_binding_invalid')
    client = _client(connection, http)
    path = '/v2/invoicing/invoices/' + provider_invoice_id
    try:
        body = client.authorized('GET', path)
    except ReadFailure as error:
        raise _read_failure(error) from None
    before = _normalize(body, payload, provider_invoice_id)
    if before['status'] in ('unpaid', 'paid'):
        if before['status'] == 'unpaid' and not before['payment_url']:
            raise InvoiceError('paypal_invoice_activation_unconfirmed', uncertain=True)
        return before
    # PayPal ignores the no-recipient-email flag for a future scheduled issue
    # date. Use the earliest worldwide civil date, independent of merchant zone.
    issue = body['detail'].get('invoice_date')
    try:
        if not isinstance(issue, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', issue) is None:
            raise ValueError()
        if date.fromisoformat(issue) > _safe_issue_date():
            raise ValueError()
    except ValueError:
        raise InvoiceError('paypal_invoice_issue_date_requires_review') from None
    if body.get('additional_recipients', []) != []:
        raise InvoiceError('paypal_invoice_notification_scope_invalid')
    try:
        token = client._token()
    except ReadFailure as error:
        raise _read_failure(error) from None
    try:
        client._json('POST', path + '/send', json={'send_to_recipient': False,
            'send_to_invoicer': False, 'additional_recipients': []},
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    except ReadFailure as error:
        # A rejected authentication response is not a confirmed activation.
        raise _read_failure(error) from None
    # Once POST succeeded, even a failed read-back is an unknown write outcome.
    try:
        result = _normalize(client.authorized('GET', path), payload, provider_invoice_id)
        if result['status'] not in ('unpaid', 'paid') or (result['status'] == 'unpaid' and not result['payment_url']):
            raise InvoiceError('paypal_invoice_activation_unconfirmed')
        return result
    except (ReadFailure, InvoiceError):
        raise InvoiceError('paypal_invoice_activation_unconfirmed', uncertain=True) from None
