# Scope & Pay verification

Build dates: 2026-10-15–16. The active feature is freelance scope review, explicit
client acceptance and invoice tracking. This record separates local checks from
real provider acceptance. Older phase records describe the preserved console.

## Completed checks

- Complete offline Python unit suite: **144 tests passed** after invoice
  activation and missing-payment-link recovery fixes.
- Frontend helper regressions: six existing session tests and eight new scope API
  tests passed. They cover exact cents, safe sandbox links, fragment tokens,
  public-cookie isolation and authentication failure handling.
- AI structural evaluator: 13 fixtures passed; `model_calls: 0`, semantic model
  accuracy unmeasured. This is validation evidence, not live AI reasoning evidence.
- Isolated PostgreSQL scope workflow suite: **19 tests passed**, including
  concurrent first decisions and invoice requests, viewer/CSRF/tenant isolation,
  exact quote validation, immutable accepted snapshots, stale/revoked links,
  durable AI quotas and creation/activation uncertainty recovery.
- Existing session-flow suite: **4 tests passed**. Existing PayPal investigation
  suite: **9 tests passed** against scratch databases and mocked provider reads.
- Frontend TypeScript check, production bundle and Docker image build passed.
  Docker also ran all 14 frontend helper regressions successfully.
- Documentation link/legacy requirement coverage check passed. The UI detector
  ran once on the completed scope targets and returned no findings.
- Three services, PostgreSQL and three workers reached healthy state. After a
  later Docker Desktop restart, a transient container-DNS startup failure recovered
  on restart-policy retries; a subsequent Compose readiness check passed.

## Final acceptance

The actual browser walkthrough completed: reopen the saved sample project,
follow a quote to its original message, save a precise $120 proposal, confirm
recent operator identity, create a private link, explicitly accept its exact
version as a synthetic client, check the decision, create the local invoice,
observe worker completion without manual reload, simulate payment, and reload
to verify both session restoration and persisted payment. The accepted brief,
scope, price, name and time remain readable in agreement history. The preserved
console loaded at `/operations`.

Desktop and mobile viewport/scroll-segment captures were inspected. Full-page
browser capture was unavailable; no full-page visual acceptance is claimed.
Independent code review found and fixed the missing-link activation result.
Independent visual review requested one correction: show the source-linked
request sooner by collapsing already-viewed review controls/summary and tightening
project spacing. That correction was rebuilt and recaptured at desktop and mobile
sizes. The independent verdict scored the single material fix **resolved**, with
`disposition: ship` for that fix. It does not claim a new whole-surface review.
Both recaptures show the first interpretation and complete source quote in the
initial viewport; the rerun controls remain accessible in their disclosure.

The design documentation received a separate source-based check: 15 CSS-backed
colors, four type roles, spacing/radius values, three responsive breakpoints and
seven component snippets matched. Default agents used the installed skill's
review/documenter contracts because its named agent types were unavailable.

Phase 4's older global-worker/membership-mutating suite was deliberately not rerun
during the live scope walkthrough. Earlier phase records remain its evidence.
That local walkthrough made no OpenAI/PayPal external requests, invoice emails
or real money movement.

## Provider setup checks — 2026-10-17

- Both ignored credential profiles passed local configuration validation. Secrets
  were excluded from command output and Docker build context.
- OpenAI model retrieval returned HTTP 200. One synthetic review request through
  the actual adapter was rejected as `openai_rate_limited` (HTTP 429); successful
  inference, billing availability and classification quality remain unverified.
  A subsequent bounded diagnostic confirmed `credit_balance_exhausted` with
  `type=insufficient_quota`. Further model retries stopped. The adapter and UI now
  distinguish exhausted billing quota from temporary throttling without exposing
  upstream messages, and both branches have offline regression coverage.
- PayPal sandbox OAuth returned HTTP 200, but the token had no invoicing scopes.
  A read-only invoice list request returned HTTP 403. App/seller invoicing access
  initially blocked testing. After the user enabled invoicing, another token
  request still reused the earlier permission set. Explicit termination of that
  temporary sandbox token returned HTTP 200; its replacement was different,
  included invoicing permission, and the read-only invoice API returned HTTP 200.
  This resolves the permission check, not draft or payment acceptance.
- No invoices were created or activated by these authentication checks. Seller merchant binding
  and buyer payment remain unverified.
- PostgreSQL was found stopped; restarting its existing container restored the
  database. The combined OpenAI/PayPal Compose deployment then reached healthy
  state. Runtime configuration reported OpenAI mode and workspace A PayPal access.
- The rebuilt app's offline unit suite passed all **146 tests**, including optional
  webhook configuration and rejection of events when no destination is configured.

### First genuine sandbox draft and activation attempt

The user then authorized the sandbox workflow test. Through the running app's
public API, an operator created a separate synthetic project and exact $1
proposal, issued a review capability, recorded a synthetic client's acceptance,
and queued one PayPal draft. The durable worker confirmed the draft as
`INV2-8B2T-B2XR-NCWR-DHR4`. No AI-generated acceptance or price was used.

Activation did not establish a payable invoice. Repeated reads of that same ID
returned `DRAFT`. A controlled diagnostic on the existing invoice, after validating
its exact contents again, captured HTTP 406 `MEDIA_TYPE_NOT_ACCEPTABLE` with
issue `INR_FOREIGN_CURRENCY_BLOCKED`. No second invoice was created. The original
application record retains its conservative unknown-activation state; it was
not rewritten directly to claim success.

The invoice adapter now classifies explicit HTTP 406 rejection as a rejected
request rather than an ambiguous server failure. Workspace B is reserved for a
separate US sandbox seller/app to exercise the USD-only integration without
rewriting Workspace A's immutable seller binding. That setup and buyer payment
remain pending. This is test-environment preparation, not validation of live
cross-border merchant eligibility.

After these error-handling changes, all **148 Python unit tests** passed. The
Docker frontend build ran **15 helper regressions**, TypeScript checking and a
production bundle successfully. The documentation checker passed all 43 documents.

The explicit acceptance helper is `scripts/check_scope_paypal_live.py`. It keeps
progress in ignored `.local` records and refuses another `--create` when a record
exists. `--activate` and `--refresh` operate on that existing invoice. Use
`--workspace ws_b` for the independent USD sandbox seller. No helper records an
external payment or substitutes for buyer checkout.

## External gates

### Gemini free-tier alternative — 2026-10-17

At the user's request to avoid paid API credits, the app gained explicit Gemini
selection using the existing bounded HTTP dependency and shared source validation.
The ignored profile selects `AI_PROVIDER=gemini` and `gemini-3.1-flash-lite`, which
Google lists with a free tier. No billing setting was enabled or changed. There
is no automatic fallback to OpenAI or another model when Gemini fails. Actual
free-tier eligibility and quotas belong to the user's Google project.

Migration 012 expands the allowed review-provider values without rewriting
existing analyses or agreements. The UI shows the selected provider and sends
that exact mode; the API rejects a request for an unselected provider.

Live integration corrected two observed wire differences: Generate Content's
JSON MIME enum is `APPLICATION_JSON`, and text parts may include an opaque
`thoughtSignature`. The parser accepts that metadata but rejects tool calls,
multiple candidates and unvalidated output. A captured synthetic response passed
the corrected parser. The running app then returned HTTP 200, saved a Gemini
review with verified source quotes, and retained it on reload alongside the
existing paid PayPal sandbox invoice. One observed app request took 2.63 seconds;
this single measurement is not a latency guarantee.

The initial eight-case live development trial matched 7/8 labels, misclassifying
the negated/hypothetical request. After clarifying that instruction and excluding
background/test notices, the rerun matched 7/8 overall: seven structurally valid
responses matched their expected labels (including the former negation failure),
while `quoted_approval` timed out and counted as a failure. No partial review was
accepted for that timeout. These are development cases, not independent holdout
or customer-quality evidence. No OpenAI requests occurred in the Gemini trial.

Verification: **155 offline Python unit tests**, **20 isolated PostgreSQL workflow
tests**, **13 structural fixtures**, **15 frontend helper regressions**, TypeScript
and production build passed. The workflow tests include saved Gemini attribution
and rejection of the wrong provider; adapter tests cover fixed origin/header keys,
redirects, refusal/incomplete output, signature metadata and citation/authority
violations.

### Workspace B genuine USD sandbox acceptance — 2026-10-17

The user configured a distinct US sandbox seller/app for Workspace B. Local
credential validation, sandbox OAuth, invoicing permission and a read-only
invoice list all passed. The app and worker were restarted with both connections.

Through the public application routes, `owner_b` created a separate synthetic
project, $1 proposal and explicit synthetic client acceptance. The worker created
draft `INV2-E6Y4-ERWC-GJVL-BP87`, then the separate activation action succeeded.
Read-back confirmed `UNPAID`, an exact $1 USD amount and a sandbox-only payment
link, with no application error. Both notification flags were false and the
additional-recipient list was empty in the activation request.

The user completed buyer checkout using the separate Personal sandbox account.
The application's refresh route then fetched the existing invoice from PayPal,
validated the exact reference, recipient, item, $1 USD amount and zero due balance,
and persisted `PAID` without an error. A fresh operator session restored normally
and two subsequent project reads retained the paid state, single invoice and
accepted agreement. The invoice provider is `paypal_sandbox` and no `demo_payment`
event exists. This verifies a genuine sandbox buyer payment rather than the local
simulation. It does not establish live merchant eligibility, bank settlement,
refund/dispute handling or production readiness.

| Gate | Status |
| --- | --- |
| Gemini live review quality and independent evaluation | Live app review and persistence passed; latest development trial 7/8 overall, including one timeout; independent holdout pending |
| OpenAI live classification quality, measured latency and cost | Model retrieval passed; inference blocked by exhausted API credit balance; labelled evaluation pending |
| PayPal genuine seller draft, activation, buyer payment and status read | Workspace B US seller: $1 draft, activation, user buyer checkout, validated PAID read-back and fresh-session persistence passed |
| Hosted TLS, client link reachability and production identity | Not deployed |
| Public capability/AI abuse controls under distributed load | Not established |
| Independent user pilot and demonstrated demand | Not established |

The app does not move real money, verify a link holder's legal identity or provide
a financial ledger. A recorded client decision is application evidence, not a
claim that electronic-signature or local contract-law requirements are satisfied.
Unknown invoice writes remain explicit and block blind creation/activation.

### PayPal-inspired workspace and client UI — 2026-10-17

Applied the user's dashboard reference to the signed-in workspace, project
navigation and public client review: pale navigation rail, white canvas, black
pill actions, blue selection, outline icons and clearer type and spacing.
Home shows original project value and real project counts; it does not claim a
PayPal account balance. Sample projects are excluded from the value total.

The console image build passed 15 frontend helper regressions, TypeScript and
the Vite production build, and the restarted console became healthy. Live CUA
inspection covered desktop Home/project/client review and narrow mobile layouts,
including the lower project list and client decision form. Filling and clearing
the client's name and confirmation correctly toggled decision availability; no
client decision, AI call or invoice was submitted by this design verification.

An independent reviewer using the default-agent substitute for Impeccable's
reviewer found three material issues. The final correction fixed mobile nav word
wrapping, inactive tab underlines and the All projects return destination. The
implementing agent confirmed all three live after rebuilding: intact mobile
labels, transparent inactive borders with a blue selected border, and Home to
project to the searchable projects index. The independent post-fix browser
session was unavailable, so that final confirmation is not an independent pass.
Current screenshots were inspected through the tool but could not be persisted
with the available capture interface; older review images are not evidence of
this redesign. Production hosting and end-user acceptance remain separate gates.
