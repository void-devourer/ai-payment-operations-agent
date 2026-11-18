import {beforeEach, test} from 'node:test';
import assert from 'node:assert/strict';
import {amountMinor, safePaymentUrl, publicToken, scopeRequest, invalidateScopeRequests} from '../../../.local/frontend-scope-tests/api.js';
let events;
beforeEach(() => {events = []; invalidateScopeRequests(); globalThis.window = {dispatchEvent: e => events.push(e.type), location: {hash: ''}};});
const response = (status, detail) => new Response(JSON.stringify({detail}), {status, headers: {'Content-Type':'application/json'}});

test('dollar inputs preserve exact cents and reject fractional cents or exponent input', () => {
  assert.equal(amountMinor('120.01'), 12001);
  assert.equal(amountMinor('0.05'), 5);
  for (const value of ['0', '-1', '1e3', '10.001', 'not money']) assert.throws(() => amountMinor(value));
});
test('invoice navigation accepts only the sandbox PayPal host', () => {
  assert.equal(safePaymentUrl('https://www.sandbox.paypal.com/invoice/p/#X'), 'https://www.sandbox.paypal.com/invoice/p/#X');
  for (const value of ['javascript:alert(1)', 'https://www.paypal.com/invoice/x', 'https://sandbox.paypal.com.evil.test', 'https://secret@sandbox.paypal.com/x', 'http://sandbox.paypal.com/x']) assert.equal(safePaymentUrl(value), null);
});
test('review capability is read only from an exact fragment route', () => {
  window.location.hash = '#/review/aB-c_123'; assert.equal(publicToken(), 'aB-c_123');
  window.location.hash = '#/review/a/b'; assert.equal(publicToken(), null);
});
test('public client failure never ends an operator session and omits cookies', async () => {
  let options;
  globalThis.fetch = async (_, supplied) => {options = supplied; return response(401, 'expired');};
  await assert.rejects(scopeRequest('/api/scope/review', {headers:{Authorization:'Bearer token'}}, true));
  assert.equal(options.credentials, 'omit'); assert.equal(options.referrerPolicy, 'no-referrer'); assert.deepEqual(events, []);
});
test('wrong login key stays a sign-in error', async () => {
  globalThis.fetch = async () => response(401, 'Incorrect credentials');
  await assert.rejects(scopeRequest('/dev/sessions/owner_a'), /Incorrect login key/); assert.deepEqual(events, []);
});
test('API billing exhaustion explains the required action without ending the session', async () => {
  globalThis.fetch = async () => response(503, 'openai_quota_exhausted');
  await assert.rejects(scopeRequest('/api/workspaces/ws_a/scope/projects/test/analysis'), /credit or spending limit.*API billing/);
  assert.deepEqual(events, []);
});
test('wrong identity confirmation key does not sign out the operator', async () => {
  globalThis.fetch = async () => response(401, 'Incorrect credentials');
  await assert.rejects(scopeRequest('/api/workspaces/ws_a/sessions/confirm'), /Incorrect login key/); assert.deepEqual(events, []);
});
test('late authentication failure cannot end a newly restored session', async () => {
  let finish;
  globalThis.fetch = () => new Promise(resolve => {finish = resolve;});
  const pending = scopeRequest('/api/workspaces/ws_a/scope/projects');
  invalidateScopeRequests(); finish(response(401, 'expired'));
  await assert.rejects(pending); assert.deepEqual(events, []);
});
test('an aborted workspace read cannot produce a session-ended event', async () => {
  const controller = new AbortController();
  globalThis.fetch = async () => {controller.abort(); return response(401, 'expired');};
  await assert.rejects(scopeRequest('/api/workspaces/ws_a/scope/projects', {signal: controller.signal}), {name:'AbortError'});
  assert.deepEqual(events, []);
});
