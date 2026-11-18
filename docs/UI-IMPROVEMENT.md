# Operator interface and current-record checks

Implemented October 11, 2026, after the performance phase. This is a local demo
improvement; public deployment and the evaluated assistant remain pending.

## Operator workflow

The inbox and investigation now occupy separate full-width views. The inbox
shows a finding, short purchase reference, case status and evidence freshness.
Search and status filters explicitly apply only to loaded cases; pagination
still loads additional records. Short references are display aids, not unique
customer names or authoritative identifiers.

An investigation puts the business finding and last checked time first, then
the current finding, customer purchase/access summary, payment records, access
review, optional case closure, finding history, and activity. Adjacent checks with
equivalent findings and payment/access/reversal/error records are grouped; the
latest five groups are visible. All loaded checks and pagination remain in an
expandable section. Access revisions appear only in technical details. Expired
access previews are collapsed. Full purchase/payment/observation identifiers, hashes and
policy references remain available in technical details. System fonts, a light
background, restrained colors and consistent spacing replace the narrow selector
and dense history layout. Keyboard focus and the mobile single-column layout
are retained.

Explicit label mappings explain known statuses and reasons. An unknown code is
displayed as a technical status instead of being transformed into an invented
business claim. For the two-successful-payment example, the last recorded
assessment says **Multiple successful payment attempts**. Old records remain
visibly out of date; the UI does not claim a duplicate charge or financial
settlement is confirmed.

## Source checks

Stored results update automatically every 15 seconds while the page is visible;
the redundant **Reload view** button was removed. **Check latest records** requests a
new authoritative collection through the existing durable worker. Only an owner
or operator with a valid session and CSRF token may request one. Viewers may
inspect evidence and scoped check status.

`POST /api/workspaces/{workspace}/cases/{case_id}/check` returns HTTP 202 with a
job identifier and server request time. It enqueues one registered attempt:
collection already reads the purchase's complete registered attempt set, within
its existing bounds. Foreground coalescing retains leased-read dirtying, retry
backoff and provider budgets. It does not grant access, approve a proposal, move
money, or bypass freshness/grace rules.

Requests are limited to one per case in 30 seconds and six per workspace in a
rolling minute. An append-only `request_check` audit record persists the request.
A PostgreSQL advisory transaction lock serializes operator requests within the
workspace so simultaneous requests cannot bypass the quota. Migration 008 adds
the audit action and its partial lookup index. Membership/RLS restrict both
enqueue and status lookup; a job from another case is not a valid status target.
These limits are specific to this local operation, not a general production
gateway quota system.

The UI polls scoped status every three seconds. It reloads the assessment only
after the current head contains a collection started at or after the request
time. New records can still be incomplete or ineligible; collection completion
does not imply approval. Retry/dead states are visible. After three minutes the
UI stops polling and tells the operator the job was not canceled. Leaving the
page also stops polling, without canceling durable work; reopening/reloading
shows stored evidence and the request audit trail. Checking again remains
subject to the server cooldown/quota.

`GET /api/workspaces/{workspace}/cases/{case_id}/check-availability` reports the
remaining server-side cooldown, including the workspace quota. The button is
disabled while availability loads, a check is running, or the countdown remains.
Availability is refreshed every five seconds and on focus; navigating away or
reloading cannot reset the quota. HTTP 429 returns the actual remaining delay
through `Retry-After` rather than a fixed 30-second suggestion.

## Session continuity

Migration 009 adds a separate last-authenticated timestamp. Local demo sessions
use a seven-day idle lease, renewed on returning to the console, on focus and
every 15 minutes while visible. `GET /api/session` restores identity, CSRF token
and the confirmation deadline before the workspace appears. CSRF uses a stable
per-session HMAC derived from the opaque cookie and server secret; only its
digest is stored. Existing sessions migrate to this token on their first restore.
Revoked or expired cookies cannot renew.

Approval, repair preparation/recovery, and case closure require authentication
within 30 minutes. After that, browsing and source checks remain available, with
a separate identity confirmation form for changes. Confirmation updates the
existing session rather than replacing its identity and invalidating queued
approvals. The server enforces this with HTTP 428. Wrong login or confirmation
credentials report **Incorrect credentials**, without triggering session expiry.

Notifications have an accessible dismiss button and disappear after eight
seconds. Signing in clears old notices; aborted loads cannot overwrite a later
sign-in/sign-out state. Refresh restores the action token as well as the cookie.

## Verification

- Frontend TypeScript check and production build passed.
- All 85 unit tests passed.
- Three PostgreSQL/HTTP operator-check scenarios passed: authorization and
  case/workspace isolation, four simultaneous requests allowing exactly one,
  publication of a real source read, durable cooldown, unchanged retry due time,
  and the six-request quota across distinct cases.
- Four session regressions passed: refresh and stable CSRF, wrong-then-correct
  credentials, confirmation with browsing preserved, and expired/revoked cookies.
- Six frontend session tests passed, including late/aborted HTTP 401 responses,
  incorrect credentials, identity confirmation and server cooldown propagation.
  These tests also run during the Docker frontend build.
- Fourteen approval/repair integration scenarios passed after the session changes.
- Eight release scenarios passed, including previous-schema upgrade, audit
  permissions, checksum rejection and isolated restore.
- Browser inspection covered the original two-payment finding, compact history,
  collapsed payment/technical references, inbox search, and a real source check
  that updated the recorded assessment while preserving manual review.
- The updated browser workflow verified wrong-then-correct login without refresh,
  restored sessions, notice dismissal/expiry, countdown after reopening a case,
  confirmation with incorrect then correct credentials, and an access preview
  appearing without a reload. Mobile checks at 390px found no horizontal overflow.

Run `python scripts/check_operator_checks.py` separately from benchmarks; it
temporarily pauses workers and restores them in `finally`. It reuses the
declared synthetic Phase 3 grace-clock fixtures to create cases promptly.
No production clock or real money is changed.
