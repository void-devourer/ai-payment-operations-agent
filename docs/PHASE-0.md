# Phase 0 evidence, contracts, and feasibility

Updated: 2026-10-07. Local contract gate passes. Genuine Stripe integration,
customer validation, database behavior, and the application are not verified yet.

## Delivered

- [Discovery record](DISCOVERY.md): interview guide, privacy boundaries, baseline
  template and unvalidated assumptions. No interviews or outreach are claimed.
- [Contracts](CONTRACTS.md): immutable purchase identities, observation
  completeness, a written happy path, conditional target operation and recovery.
- [Pure policy](../backend/app/detection/policy.py): deterministic versioned
  eligibility over current normalized facts; no network requests or writes.
- [Owned backlog](IMPLEMENTATION-BACKLOG.md): every acceptance ID assigned to
  phased implementation tasks with explicit responsibilities.
- Local Git, credential/tool ignores, line-ending/editor settings, and an initial
  CI workflow pinned to verified official action revisions.

`D-01` through `D-03` and related evidence requirements have initial unit coverage;
they are not release-complete. Persistence, provider adapters, authorization and
case/operation coordination must pass their later integration gates.

## Reproduce the local checks

Run from the repository root with Python 3.13 or 3.14; no dependency installation,
Stripe account, database, Docker, or paid service is needed for these checks.

```powershell
python -m unittest discover -s tests/unit -v
python scripts/check_docs.py
git diff --check
```

Observed locally: 31 policy tests pass on Python 3.14.5. The cases cover money and
timestamp validation, exact scope/identity, missing/incomplete/stale evidence,
payment states, refund/dispute history, multiple successes, distinct equal-value
purchases, grace/freshness boundaries, intentional access blocks, live-mode
exclusion, and existing/unknown repair coordination inputs.

The CI workflow runs policy and document checks on Python 3.13 and 3.14 after
push. Its configured matrix is not evidence of successful hosted runs until those
runs finish. No PostgreSQL, target transaction, provider signature or browser test
has run in this phase.

## Environment evidence and next-phase strategy

| Component | Observed | Strategy |
| --- | --- | --- |
| Git | 2.54.0.windows.1; local `main` initialized; user supplied GitHub remote | Small phase commits and ordinary pushes |
| Python | 3.14.5 from MSYS2 is runnable; policy uses the standard library | Use reproducible CPython 3.13 containers for application dependencies; CI checks core on 3.13/3.14 |
| Node / npm | Node 24.21.0; npm 11.19.0 | Resolve/pin frontend dependencies in Phase 1; use `npm.cmd` on PowerShell |
| PostgreSQL / Docker CLI | Neither available on PATH; no database test run | Phase 1 needs a working Docker engine/CLI and real PostgreSQL before its gate |
| WSL2 | Existing `docker-desktop` distribution is stopped; start-menu shortcut exists, but no usable Docker executable found | Treat as existing setup evidence, not a running container environment; repair/confirm installation in Phase 1 |
| GitHub CLI | Not on PATH | Git itself can commit/push; CLI is not required for the first commit |
| Stripe CLI | 1.53.0 installed locally under ignored `.tools/stripe` | Use project-local config under `.local`; never commit CLI profiles or keys |
| Identity provider | No configured OIDC tenant verified | Local test identities only in development; real OIDC/session integration must meet Phase 1/5 gates |
| Deployment/budget | No paid service or hosting provisioned | Local development and CI first; assume no paid spend until the user chooses it |

The runnable Phase 0 strategy is the standard-library test command above. The
application environment is the Phase 1 Compose stack, with separate console and
reference-app databases and independent simulator state. A stopped WSL distro
does not establish Compose readiness. Never substitute SQLite tests for the
PostgreSQL transaction/RLS gate.

## Stripe feasibility

The official [sandbox documentation](https://docs.stripe.com/sandboxes) describes
temporary sandbox provisioning using the CLI. Installed CLI help was inspected
before use. After the user selected their Git author email, a temporary sandbox
was provisioned with an advertised expiry of **2026-10-14**. No existing live
credentials were read or used. No genuine payment API or webhook check has run.

This is optional integration-test setup. No application component currently
depends on the temporary profile. Expiry disables calls using those temporary
credentials; it does not expire the repository, local tests, future simulator,
or hosted application. Build against the simulator first. For genuine integration,
configure an account-managed sandbox connection or freshly provisioned credentials
and verify it independently. Expired/unavailable connections must appear as
unavailable evidence and must never permit repair from cached facts.

CLI configuration, keys and claim links remain under ignored `.local/`. The
original temporary key appeared in diagnostic output because a new key prefix
was not redacted. It is considered exposed and will not be used by this project.
A replacement attempt returned browser sign-in instructions, not new credentials;
the original key has **not** been revoked. Revocation requires the provider's
account/Dashboard controls; the temporary expiry is not a claim of revocation.
No credential or claim URL is included in this repository. Future diagnostics
must allowlist safe metadata instead of printing redacted raw responses.

Supported APIs, webhook shape/version, key permissions and report availability
remain unverified. Record genuine adapter capability evidence in Phase 2 and
preserve the deterministic simulator regardless of Stripe availability.

## Gate and next phase

The local Phase 0 gate has a written happy path, explicit unsafe cases, executable
policy checks, complete task coverage and an honest environment/provider strategy.
Product discovery and genuine sandbox proof remain open work. Their absence does
not block the synthetic implementation path in the build plan.

Next is Phase 1: reproducible packages/lockfiles/config/Compose; identity and
tenant isolation; purchase registration; the reference application's ordinary
checkout/fulfillment and outbox; conditional access/receipts; and independent
provider simulation. Its real-database gate must pass before Phase 2.
