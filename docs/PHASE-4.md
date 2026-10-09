# Phase 4: approval and access-repair recovery

Scope: the deterministic simulator and independent reference application's
one-time access grant. No provider writes, money movement, AI execution or live
customer data. Full account-managed Stripe acceptance remains open.

## Implementation and invariants

- Prepare a preview only from a fresh, complete, current, eligible missing-access
  case. Freeze customer/product/purchase, revision, observation, material
  fingerprint, policy, expiry, operation identity and canonical payload digest.
  Ten-minute expiry does not remove the requirement for current evidence.
- Approval or rejection requires owner/operator membership, session, CSRF, an
  exact payload digest and a meaningful reason. Identical approval retries return
  the existing operation. Conflicting decisions fail. Approval, operation enqueue,
  case transition and audit commit in one database transaction.
- Database constraints permit one pending proposal and one active/unknown repair
  per purchase. Triggers freeze proposal payloads and operation identities;
  application roles cannot update/delete approval, attempt or audit records.
- The durable operation row is the repair queue. Workers claim it with a
  30-second fenced lease and at most eight attempts per recovery round. Each
  workspace receives one repair opportunity per worker round alongside read jobs.
- Before dispatch, refresh the existing bounded payment/reversal/access reader.
  Repeat policy, material fingerprint, proposal expiry, access precondition,
  approving subject membership and session validity checks. Repeat the checks
  at the final dispatch-intent transaction. Target calls use the configured local
  allowlisted adapter URL and workspace credential, never a browser-supplied URL.
- Commit dispatch intent before the network call. The target commits access and
  its immutable payload-bound receipt atomically. A process death after intent is
  uncertain, including a death before sending. Reclaimed workers only look up the
  same operation; a 404 does not establish absence of an effect.
- Validate the primary receipt's target identity, payload digest, result and
  revision. A historical grant receipt is not current business recovery. Refresh
  authoritative facts again and record success only when current complete evidence
  establishes active purchased access. Recheck the observation under the head lock
  when committing the result. Later suspension or reversal remains visible.
- Unknown or unverifiable outcomes continue to block a new repair. After bounded
  automatic attempts, an authorized operator can retry lookup/verification with
  the same operation identity. Exhausted undispatched work is blocked safely.

## Console workflow

Case detail includes **Access repair** with a target/precondition/expiry preview,
an explicit review checkbox, reason, approve/reject actions, queued/unknown/result
states, target receipt and decision/attempt history. Viewer and restored sessions
remain read-only. Refresh evidence to load worker progress; no claim that approving
alone restores access. Historical verified success refers to its recorded
observation; the case summary reports current evidence.

Routes:

- `POST /api/workspaces/{workspace}/cases/{case}/proposals`
- `GET /api/workspaces/{workspace}/cases/{case}/repairs`
- `POST /api/workspaces/{workspace}/proposals/{proposal}/decisions`
- `POST /api/workspaces/{workspace}/operations/{operation}/recover`

All console records are workspace scoped with forced PostgreSQL RLS and private
API responses. Approval session digests and service credentials are not returned.

## Verification

Run the unit/build checks and real PostgreSQL/HTTP suite after normal setup:

```powershell
python -m unittest discover -s tests/unit
python scripts/check_phase4.py
cd frontend
npm run build
```

The integration runner pauses local workers and restores them in `finally`.
Controlled clocks, membership revocations and access mutations affect only its
synthetic fixtures through the administrative test connection. Its crash test
starts a separate Python worker and terminates it after a real target transaction
commits, then recovers through a new lease without a second dispatch.

Verified locally on 2026-10-09:

- 77 unit contracts, including exact receipt identity/payload/revision validation.
- 14 Phase 4 PostgreSQL/HTTP scenarios: approval concurrency and retry, payload
  conflict, permissions/CSRF/workspace denial, rejection, refund/suspension/revision
  changes, membership/session revocation, actual process death after remote commit,
  missing-receipt uncertainty, concurrent ordinary fulfillment, post-grant
  suspension, immutability/RLS/fencing, expiry/policy change, atomic approval rollback
  expired-preview denial and competing approvals from two different actors.
- Regression suites: 8 Phase 1, 16 Phase 2 plus automatic webhook/evidence delivery,
  10 Phase 3 and 4 offline Stripe contracts; console-outage recovery passed.
- Frontend type check and production build passed. In-app browser verified viewer
  unknown-outcome denial, exact preview, reason/review confirmation, approval queue,
  background execution, target receipt revision 1 and fresh active-access resolution.
  A 390-pixel responsive check found no horizontal overflow and retained back navigation.

Hosted CI now runs the Phase 4 suite after the earlier phase checks. Phase 5 still owns
the full release security/accessibility matrix, prior-schema restore exercise,
deployment, broader chaos and measured performance/fairness evidence. The local
fixture identity system is not production OIDC. Independent payment and target
systems cannot commit atomically: a reversal or authorization change can still
race after the last check. Reconciliation surfaces subsequent facts.
