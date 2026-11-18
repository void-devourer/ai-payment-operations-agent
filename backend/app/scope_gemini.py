"""Fixed-origin Gemini review; shared citations, schema and authority boundaries."""
import time

import httpx

from .ingestion import decode_json
from .scope_ai import AnalysisError, INSTRUCTIONS, MAX_RESPONSE_BYTES, Review, validate_review


def analyze_gemini(sources, bundle, *, http, config):
    request = {'systemInstruction': {'parts': [{'text': INSTRUCTIONS}]},
        'contents': [{'role': 'user', 'parts': [{'text': bundle}]}],
        'generationConfig': {'maxOutputTokens': 2200,
            'responseFormat': {'text': {'mimeType': 'APPLICATION_JSON', 'schema': Review.model_json_schema()}}}}
    started = time.monotonic()
    try:
        with http.stream('POST', 'https://generativelanguage.googleapis.com/v1beta/models/' + config.model + ':generateContent',
                json=request, timeout=20, follow_redirects=False,
                headers={'x-goog-api-key': config.api_key, 'Accept': 'application/json'}) as response:
            if response.status_code in (401, 403):
                raise AnalysisError('gemini_authentication_failed')
            if response.status_code == 429:
                raise AnalysisError('gemini_rate_limited')
            if response.status_code != 200:
                raise AnalysisError('gemini_unavailable')
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise AnalysisError('analysis_response_budget')
                if time.monotonic() - started > 22:
                    raise AnalysisError('gemini_timeout')
        envelope = decode_json(raw)
        if not isinstance(envelope, dict):
            raise AnalysisError('analysis_output_invalid')
        if envelope.get('promptFeedback', {}).get('blockReason'):
            raise AnalysisError('analysis_refused')
        candidates = envelope.get('candidates')
        if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise AnalysisError('analysis_output_invalid')
        candidate = candidates[0]
        if candidate.get('finishReason') != 'STOP':
            raise AnalysisError('analysis_incomplete')
        content = candidate.get('content')
        if not isinstance(content, dict) or content.get('role') != 'model':
            raise AnalysisError('analysis_output_invalid')
        parts = content.get('parts')
        if (not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], dict)
                or not set(parts[0]).issubset({'text', 'thoughtSignature'})
                or not isinstance(parts[0].get('text'), str)
                or 'thoughtSignature' in parts[0] and not isinstance(parts[0]['thoughtSignature'], str)):
            raise AnalysisError('analysis_output_invalid')
        return {'mode': 'gemini', **validate_review(decode_json(parts[0]['text']), sources)}
    except httpx.TimeoutException:
        raise AnalysisError('gemini_timeout') from None
    except httpx.RequestError:
        raise AnalysisError('gemini_network_error') from None
    except (ValueError, TypeError, RecursionError, AttributeError):
        raise AnalysisError('analysis_output_invalid') from None
