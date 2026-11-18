"""Gemini wire/security contracts; all provider responses are offline fixtures."""
import copy
import json
import os
import unittest
from unittest.mock import patch

import httpx

from backend.app.scope_ai import AIConfig, AnalysisError, analyze, configuration


BRIEF = 'One static landing page. Contact forms are excluded.'
MESSAGES = [{'message_id': 'm_test', 'text': 'Please quote adding a contact form.'}]
REVIEW = {'summary': 'Review this addition before quoting.', 'candidates': [
    {'title': 'Contact form', 'classification': 'addition', 'rationale': 'Excluded from the brief.',
     'evidence': [{'message_id': 'm_test', 'quote': MESSAGES[0]['text']}]}]}


def envelope(value=None):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model',
        'parts': [{'text': json.dumps(REVIEW if value is None else value)}]}}]}


class GeminiReviewTests(unittest.TestCase):
    config = AIConfig('fixture-google-key', 'gemini-3.1-flash-lite', 'gemini')

    def client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        self.addCleanup(client.close)
        return client

    def run_review(self, body):
        return analyze(BRIEF, MESSAGES, config=self.config,
            http=self.client(lambda request: httpx.Response(200, json=body)))

    def test_fixed_google_origin_header_key_schema_no_tools_or_paid_fallback(self):
        seen = []
        def handler(request):
            seen.append(request)
            self.assertEqual(str(request.url), 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent')
            self.assertEqual(request.headers['x-goog-api-key'], 'fixture-google-key')
            self.assertNotIn('fixture-google-key', str(request.url))
            body = json.loads(request.content)
            self.assertNotIn('tools', body)
            self.assertEqual(body['generationConfig']['maxOutputTokens'], 2200)
            self.assertEqual(body['generationConfig']['responseFormat']['text']['mimeType'], 'APPLICATION_JSON')
            self.assertIn('Never set a price', body['systemInstruction']['parts'][0]['text'])
            return httpx.Response(200, json=envelope())
        result = analyze(BRIEF, MESSAGES, config=self.config, http=self.client(handler))
        self.assertEqual(result['mode'], 'gemini')
        self.assertEqual(len(seen), 1)

    def test_same_citation_and_authority_validation_as_openai(self):
        for field, value in [('evidence', [{'message_id': 'foreign', 'quote': 'Invented'}]),
                             ('amount_minor', 100), ('accepted', True), ('classification', 'accepted')]:
            review = copy.deepcopy(REVIEW)
            review['candidates'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AnalysisError):
                self.run_review(envelope(review))

    def test_signed_text_metadata_is_allowed_but_tools_are_not(self):
        value = envelope()
        value['candidates'][0]['content']['parts'][0]['thoughtSignature'] = 'fixture-opaque-signature'
        self.assertEqual(self.run_review(value)['mode'], 'gemini')
        value['candidates'][0]['content']['parts'][0]['functionCall'] = {'name': 'invoice'}
        with self.assertRaises(AnalysisError):
            self.run_review(value)

    def test_incomplete_blocked_tools_and_multiple_outputs_fail_closed(self):
        incomplete = envelope(); incomplete['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        tools = envelope(); tools['candidates'][0]['content']['parts'] = [{'functionCall': {'name': 'invoice'}}]
        multiple = envelope(); multiple['candidates'].append(copy.deepcopy(multiple['candidates'][0]))
        for value in (incomplete, tools, multiple, {'promptFeedback': {'blockReason': 'SAFETY'}}, {'promptFeedback': None}):
            with self.subTest(value=value), self.assertRaises(AnalysisError):
                self.run_review(value)

    def test_errors_and_redirects_never_leak_upstream_or_retry(self):
        for status, expected in [(401, 'gemini_authentication_failed'), (403, 'gemini_authentication_failed'),
                (429, 'gemini_rate_limited'), (500, 'gemini_unavailable'), (307, 'gemini_unavailable')]:
            seen = []
            def handler(request):
                seen.append(request)
                return httpx.Response(status, text='fixture-google-key private body', headers={'location': 'https://evil.invalid'})
            with self.subTest(status=status), self.assertRaises(AnalysisError) as caught:
                analyze(BRIEF, MESSAGES, config=self.config, http=self.client(handler))
            self.assertEqual(str(caught.exception), expected)
            self.assertEqual(len(seen), 1)

    def test_bounded_output_and_malformed_json_fail_closed(self):
        for raw in (b'x' * (1024 * 1024 + 1), b'not json', b'{"candidates":[],"candidates":[]}'):
            with self.subTest(length=len(raw)), self.assertRaises(AnalysisError):
                analyze(BRIEF, MESSAGES, config=self.config,
                    http=self.client(lambda request: httpx.Response(200, content=raw)))

    def test_explicit_provider_selection_never_uses_openai_when_gemini_missing(self):
        values = {'AI_PROVIDER': 'gemini', 'OPENAI_API_KEY': 'unused-openai-secret', 'OPENAI_MODEL': 'unused-model'}
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(configuration(), {'mode': 'unavailable'})
            with self.assertRaises(AnalysisError) as caught:
                analyze(BRIEF, MESSAGES, http=self.client(lambda request: self.fail('No provider should be called')))
            self.assertEqual(str(caught.exception), 'gemini_not_configured')
        for model in ('../openai', 'gemini-test/../../', 'gemini-test?key=other'):
            with self.assertRaises(AnalysisError):
                AIConfig('fixture-google-key', model, 'gemini')
