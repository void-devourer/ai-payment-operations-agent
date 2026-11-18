import {beforeEach, test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, invalidateRequests, request} from '../../.local/frontend-tests/api.js';

let events;
beforeEach(() => {
  events = [];
  invalidateRequests();
  globalThis.window = {dispatchEvent: event => events.push(event.type)};
});
const reply = (status, detail, headers = {}) => new Response(JSON.stringify({detail}), {
  status, headers: {'Content-Type': 'application/json', ...headers},
});

test('wrong credentials report their own error without ending a session', async () => {
  globalThis.fetch = async () => reply(401, 'Incorrect credentials');
  await assert.rejects(request('/dev/sessions/owner_a'), /Incorrect credentials/);
  assert.deepEqual(events, []);
});
test('genuine expiry on an authenticated request ends the session', async () => {
  globalThis.fetch = async () => reply(401, 'Session expired or revoked');
  await assert.rejects(request('/api/workspaces/ws_a/cases'), ApiError);
  assert.deepEqual(events, ['session-ended']);
});
test('a late failure from before sign-in cannot log out the new session', async () => {
  let finish;
  globalThis.fetch = () => new Promise(resolve => {finish = resolve;});
  const pending = request('/api/workspaces/ws_a/cases');
  invalidateRequests();
  finish(reply(401, 'Session expired or revoked'));
  await assert.rejects(pending, ApiError);
  assert.deepEqual(events, []);
});
test('an aborted request cannot trigger a stale expiry notification', async () => {
  const controller = new AbortController();
  globalThis.fetch = async () => {controller.abort(); return reply(401, 'Session expired');};
  await assert.rejects(request('/api/workspaces', {signal: controller.signal}), {name:'AbortError'});
  assert.deepEqual(events, []);
});
test('sensitive-action confirmation does not end browsing', async () => {
  globalThis.fetch = async () => reply(428, 'Confirm your identity to continue');
  await assert.rejects(request('/api/workspaces/ws_a/cases/c_a/dismiss'), error => error.status === 428);
  assert.deepEqual(events, ['session-confirmation']);
});
test('cooldown errors retain the server delay for the disabled button', async () => {
  globalThis.fetch = async () => reply(429, 'Wait', {'Retry-After':'47'});
  await assert.rejects(request('/api/workspaces/ws_a/cases/c_a/check'), error => error.retryAfter === 47);
  assert.deepEqual(events, []);
});
