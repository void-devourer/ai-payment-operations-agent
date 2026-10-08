# Local Phase 1 development

This stack uses synthetic payments and generated local credentials. It has no
Stripe dependency and never reads the temporary Stripe CLI profile. All published
ports bind to `127.0.0.1`. Do not expose this development stack publicly: local
fixture identities are deliberately unavailable outside development mode.

## Start and verify

Use Python 3.13/3.14, Docker Desktop with the Linux engine running, and Docker
Compose. Generate secrets once, then start the services:

```powershell
python scripts/setup_local.py
docker compose --progress plain up -d --build --quiet-pull --wait --wait-timeout 180
python -m pip install -r requirements.lock
python -m unittest discover -s tests/unit -v
python scripts/check_phase1.py
python scripts/check_outage.py
python scripts/check_phase2.py
python scripts/check_docs.py
```

`setup_local.py` refuses to replace an existing `.env`. Preserve this file with
its local database volume; changing a runtime password in `.env` does not change
the existing PostgreSQL role password. The generated file is ignored by Git and
excluded from Docker build contexts. The database setup passes each service only
its required credentials; runtime roles cannot connect to the other service DBs.

The integration checks leave synthetic rows in the local databases and use unique
identifiers each run. The outage check briefly stops only the console and restores
it in a `finally` block. It verifies ordinary fulfillment continues and both
registration messages eventually arrive after the console restarts.

Stop containers while preserving local data:

```powershell
docker compose down
```

Do not use `down -v` during ordinary development; it deletes the local database
volume. No volume deletion is required by these verification commands.

## Services and first workflow

| Service | Local URL | Owns |
| --- | --- | --- |
| Console API | `http://127.0.0.1:8000/docs` | Memberships/sessions and immutable purchase/attempt registration |
| Reference app API | `http://127.0.0.1:8001/docs` | Checkout, access state, conditional grants, receipts and registration outbox |
| Simulator API | `http://127.0.0.1:8002/docs` | Independent synthetic payment state and signed event fixtures |
| Reference worker | Background process | Outbox relay and ordinary fulfillment; no console repair executor |
| Simulator worker | Background process | Durable signed synthetic webhook delivery |
| Console worker | Background process | Leased current-evidence reads, retries and fenced publication |
| PostgreSQL | `127.0.0.1:15432` by default | Three separate databases and three restricted runtime roles |

The first checkout product is `digital_pass`, priced by the reference backend at
2,500 USD minor units. Clients cannot override the product price. These are API
flows; a customer UI and operator console are later frontend work.

Set `POSTGRES_PORT` in `.env` if Windows reserves the default host port. The
integration scripts use the same setting; no database-volume deletion is needed.
The reference worker has a heartbeat health check: startup clears a stale marker,
then the processing loop refreshes it. A missing/stalled heartbeat becomes
unhealthy. This reports worker progress separately from an individual job's success.

1. Call reference `POST /demo/checkouts` with a unique `purchase_id`, `customer_id`,
   and optionally `fault_mode: pause_fulfillment`. Authenticate using that
   workspace's generated `CHECKOUT` key as a bearer credential.
2. Call `POST /demo/checkouts/{purchase_id}/pay` with the same credential. The
   simulator creates/confirms one scoped payment idempotently.
3. The reference worker observes success and normally grants access atomically
   with a receipt. `pause_fulfillment` deliberately leaves access inactive.
4. Read `/internal/access/{purchase_id}` using the workspace's `ADAPTER` key.
5. The independent outbox registers immutable purchase expectations and then the
   payment attempt at the console, with retries if the console is unavailable.

Each purpose has a separate credential. A registration key cannot grant access;
workspace A's adapter key cannot read workspace B's access or receipts. Never paste
keys into an issue, log, Git commit, or public demo. The scripts load `.env` without
printing its values. Local fixture login uses `X-Demo-Login-Key` with predefined
subjects `owner_a`, `operator_a`, `viewer_a`, and `owner_b`; it issues an opaque
HttpOnly/SameSite cookie and a CSRF token. Logout validates CSRF and revokes the
server session. Membership changes take effect on the next authorization check.

## Contracts and limits

Target grants require exact binding, inactive/never-activated access, expected
revision, unexpired request and a stable operation identity. Identical operation
replays return the stored result. Changed payloads conflict; failed preconditions
also retain identity. Access and its receipt commit in one PostgreSQL transaction.
Receipt lookup remains necessary after uncertainty; a missing receipt cannot
prove no effect. Phase 4 adds console proposal/approval/execution around this
target contract. Direct adapter access is an internal service capability.

The outbox has a 30-second lease, fenced completion, finite exponential retry,
and a dead state after permanent errors or 12 attempts. Read scoped counts via
`GET /internal/registration-health`. After correcting a dead registration, a
trusted adapter can request `POST /internal/registrations/{purchase_id}/retry`;
the immutable registration and provider IDs are preserved. UI/audit treatment
and broader job controls are later phases.

Migration jobs run before API startup, using administrative credentials unavailable
to API processes. Runtime roles cannot bypass RLS. Versioned SQL migrations are
transactional, advisory-locked, and checksum-verified; never edit an applied file.
This foundation uses direct psycopg2 transactions rather than the initially
proposed SQLAlchemy/Alembic stack to keep these boundaries explicit and small.
The application is not ready for production OIDC, Stripe ingestion, subscriptions,
performance claims or GenAI. Those retain their phase gates. Phase 2 implements
synthetic refund/dispute pagination and controlled provider-read failures; see
[PHASE-2.md](PHASE-2.md) for bounds, inspection APIs and test behavior.
