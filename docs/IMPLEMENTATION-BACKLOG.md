# Owned implementation backlog

Baseline: 2026-10-07. `Codex` owns implementation and verification for every task
below; `Piyush` owns product decisions, user discovery, and review of phase results.
These are responsibilities within this project, not assignments to spawned agents.
Every acceptance ID has a task; mapping an ID does not mean the requirement passed.

The pure Phase 0 policy is an initial contract. Release requirements involving
durable state, network reads, authorization, or real transactions remain open.
Complete one phase, record checks/limitations, commit, and push before advancing.
Use ordinary commits and pushes; never rewrite shared history to hide a failure.

| Task | Phase | Work and owning module | Acceptance IDs | State |
| --- | --- | --- | --- | --- |
| F1-01 | 1 | Packages/lockfiles, config validation, Compose, migrations and CI; `infra`, backend bootstrap | O-01, O-03 | Planned |
| F1-02 | 1 | Memberships, server sessions, roles, scoped repositories and non-owner RLS; `identity`, persistence | S-01, S-02, S-04 | Planned |
| F1-03 | 1 | Immutable purchase/attempt registration, product mapping, conflicts and equal-value scenarios; `purchases` | P-01, P-02 | Planned |
| F1-04 | 1 | Reference checkout, ordinary fulfillment and registration outbox; `reference_app` | P-03 | Planned |
| F1-05 | 1 | Conditional access writes, target receipts/hash conflicts, receipt lookup; `reference_app`, `business_adapter` | A-04, A-05 | Planned |
| F1-06 | 1 | Independent simulator state, signed fixtures and controlled faults; `simulation`, `fixtures` | I-01, E-01, E-02, A-06 | Planned |
| F2-01 | 2 | Raw signed ingress; transactional inbox/job; scoped dedupe and version quarantine; `ingestion` | I-01, I-02, I-03, I-04 | Planned |
| F2-02 | 2 | Leases/heartbeats/fencing, classified retries/dead jobs, budgets/fairness; `jobs` | J-01, J-02 | Planned |
| F2-03 | 2 | Current provider/target reads, all-attempt coverage, reversal pagination, provenance/digests and separate completeness; `provider`, `business_adapter` | E-01, E-02, E-03, E-04, E-05 | Planned |
| F2-04 | 2 | Small genuine sandbox contract suite and pinned event/API/SDK versions; `provider`, integration tests | I-01, I-04, E-01, E-02, E-05 | Fresh/account-managed credentials and API proof pending |
| F3-01 | 3 | Persisted first-success clock; integrate pure policy; explicit unknowns, intentional blocks and reversal review; `detection` | D-01, D-02, D-03, D-05 | Pure contract tested; integration open |
| F3-02 | 3 | Active-case constraints, concurrent detection, dismissal fingerprints/generations and independent resolution; `cases` | D-04, D-05, A-07 | Planned |
| F3-03 | 3 | Independent purchase/resource reconciliation, resumable bounded pages, coverage and older sweeps; `reconciliation` | R-01, R-02, R-03 | Planned |
| F3-04 | 3 | Case inbox/detail, evidence timeline, integration health, accessible states; `frontend` | U-01, U-02 | Planned |
| F4-01 | 4 | Immutable proposals, expiry, approval/rejection and atomic single operation enqueue; `repairs`, `audit` | A-01, A-02, S-05, U-01 | Planned |
| F4-02 | 4 | Refresh authority/evidence/policy/revision before dispatch; bounded scoped adapter execution; `repairs` | A-03, A-04, A-05, S-01, S-04 | Planned |
| F4-03 | 4 | Lost-response receipt lookup with stable identity; worker restart and concurrent normal fulfillment; `repairs` | A-06, A-07, J-01 | Planned |
| F5-01 | 5 | Endpoint/tenant/privacy/CSRF/allowlist matrix; audit permissions and retention; security integration tests | S-01, S-02, S-03, S-04, S-05 | Planned |
| F5-02 | 5 | Previous-schema migrations, isolated backup restore and recovery runbooks; `infra`, operations tests | O-01, O-02, J-01 | Planned |
| F5-03 | 5 | Browser UAT, reproducible demo, fault catalog and clean-checkout CI; `frontend`, `simulation`, `infra` | U-01, U-02, O-03 | Planned |
| F5-04 | 5 | Recorded simulator benchmarks, fairness/queue age, recovery and limitations; `benchmarks` | O-04, J-02 | Planned |
| F6-01 | 6 | Authorized read-only bounded tools, output references, redaction and outage/cost isolation; `assistant` | AI-01, AI-03, S-02, S-03 | Deferred until software gate |
| F6-02 | 6 | Reviewed holdout data, adversarial trials, grounding/usefulness report and enablement decision; AI evaluation | AI-02 | Deferred until software gate |
| F7-01 | 7 | Read-only source amounts, automatic-payout composition, corrections and delayed/unsupported evidence; financial reconciliation | F-01, F-02, F-03 | Deferred until own phase gate |

Phase 5 verifies every `P0` row in [ACCEPTANCE.md](ACCEPTANCE.md) across the earlier
tasks. Phase 6 and Phase 7 have independent gates and do not inflate the software
release's claims. Real PostgreSQL/target tests and genuine provider tests must be
reported separately from unit fixtures and simulator tests.
