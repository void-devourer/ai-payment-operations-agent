# Scope & Pay: AI and invoice adapter verification

Updated 2026-10-17. This describes the current scope-review implementation;
the previous payment-investigation AI draft is historical context.

## What is implemented

The configured path calls one explicitly selected provider using the existing
HTTP client dependency. `AI_PROVIDER=gemini` uses `GEMINI_API_KEY` and an explicit
`GEMINI_MODEL` (the example selects `gemini-3.1-flash-lite`, listed with a free
tier). `AI_PROVIDER=openai` uses `OPENAI_API_KEY` and `OPENAI_MODEL`. There is no
automatic model or provider fallback, including no paid OpenAI fallback when
Gemini is unavailable. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)

Both paths request JSON Schema output with no tools and an instruction that
treats the brief/messages as evidence. Google Generate Content requires the
`APPLICATION_JSON` MIME enum in `responseFormat.text`; opaque text signature
metadata is accepted but never treated as review content or tool authority.
The OpenAI Responses path uses `store: false`, which is not a promise of zero
provider retention. Google's free tier may use content to improve its products;
use synthetic data for the demo and only material authorized for processing.
[Gemini API reference](https://ai.google.dev/api/generate-content),
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

The output contains a summary and up to ten candidate interpretations. Each
candidate has one classification (`included`, `addition` or `unclear`), a
rationale and exact message quotes. Application validation rejects unknown
message IDs, quotes absent from the referenced source, unknown schema fields,
unsupported classifications and unbounded text. Prices and acceptance are
absent from the output schema. Model interpretation cannot mutate a proposal,
record client acceptance or create an invoice.

An exact quote establishes source membership, **not semantic truth**. A model
can cite a real sentence while interpreting it incorrectly. The freelancer
must review interpretations; a client must separately accept the exact proposal
version and amount. In particular, a historical message containing “I approve”
is not an application acceptance event.

The optional sample path works only for the unchanged seeded brief and three
messages. Its result says `mode: sample`. It is a curated interpretation and
never a general-purpose heuristic presented as AI. Adding or changing a message
disables this path until the original sample is restored.

## Budgets and error behavior

- At most 32 KiB of serialized brief/messages, 50 messages, and 8,000 characters
  in an individual message; no hidden workspace records are sent.
- At most 2,200 output tokens, one model request, a 20-second HTTP timeout and a
  checked streaming-response budget. HTTP timeouts apply per network operation;
  these are bounds, not a measured end-to-end latency guarantee.
- At most 1 MiB response data. Redirects are disabled. Model requests use fixed
  origins: `https://api.openai.com/v1/responses` or Google's
  `https://generativelanguage.googleapis.com/v1beta/models/` Generate Content path.
  Gemini model identifiers cannot contain path separators or URL parameters;
  keys are sent in headers, never in the URL.
- Refusals, incomplete generations, malformed JSON, foreign citations, bad
  schemas, network errors and rate limits are errors; no partial answer silently
  becomes a successful review. Upstream error bodies and secrets are omitted.
- Request throttling and tenant/actor authorization belong to the API boundary;
  a model being configured does not bypass that boundary.

No tracing vendor, vector database, agent framework or model SDK is necessary
for this one-call extraction boundary. This keeps the service contract small
and avoids granting the model invoice or acceptance tools.

## Tests actually run

Run from the repository root:

```powershell
python -m unittest discover -s tests/unit -p test_scope_ai.py -v
python -m unittest discover -s tests/unit -p test_scope_invoicing.py -v
python scripts/evaluate_scope_ai.py
```

The current adapter pass produced **20 AI/sample unit tests and 17 invoice unit
tests passing**, plus **13 structural evaluator fixtures passing**. The tests
use `httpx.MockTransport`; no OpenAI or PayPal account is contacted.

The fixtures cover ordinary scope distinctions, negation, deferred requests,
quoted approvals and prompt-injection text. Validator attacks cover foreign
source IDs, invented quotes, fabricated price/consent fields, unknown classes,
oversized input/output, refusal/incomplete responses, redirects and secret-bearing
upstream errors. Tests that inject a mocked correct classification demonstrate
transport/validation behavior; they do not demonstrate that a live model reaches
that interpretation.

The offline evaluator prints `model_calls: 0` and
`semantic_model_accuracy: null` to make this distinction machine-readable.

For an explicitly authorized model trial, fill the ignored `.env.scope` profile
and run:

```powershell
python scripts/evaluate_scope_ai.py --live --acknowledge-provider-requests
```

That command loads the selected provider from `.env.scope` (or `--profile`) and
makes up to eight requests using synthetic development cases. Provider tier and
quotas apply; it does not enable billing or submit customer conversations. It
stops on a rate/quota error instead of continuing to retry the remaining cases.
Its result is a development-set label check, not an independent model evaluation.
Before a production or hackathon quality claim, label a separate unseen set,
include error/refusal cases in the denominator, inspect explanations for
misrepresented consent and invented facts, and record the chosen model and
observed cost/latency. The 2026-10-17 Gemini live trial initially matched **7/8**
development labels: the negated/hypothetical request was misclassified as an
addition. The instruction was clarified to distinguish present quote requests
from explicitly negated, cancelled, deferred or hypothetical work, and to exclude
background/test-data notices from candidate work. See the current verification
record for full results. The rerun matched 7/8 overall: seven valid responses
matched their expected labels, including negation, and the quoted-approval case
timed out and counted as a failure. This is prompt development, not an independent
holdout measurement. The actual app also saved a citation-validated Gemini review
and preserved both that review after reload and the existing paid sandbox invoice.

## PayPal invoice boundary

The adapter supports OAuth, creating one sandbox **draft**, reading its
status and separately authorized activation of a sandbox share link. Drafts are
not payable until activated with PayPal's separate send operation. Drafts
deliberately expose no payment URL.
[Create draft invoice](https://developer.paypal.com/api/invoicing/v2/invoices-create)

Each request uses a deterministic invoice number derived from the local invoice
ID and a `scope:<invoice_id>` reference. Returned invoice number, reference,
recipient, one exact accepted line item, gross amount, USD currency, outstanding
amount and requested provider ID are checked. Values use decimal conversion
from integer minor units. The line-item description is limited to PayPal's
1,000-character contract; accepted text is never silently truncated.
[Invoice schema](https://developer.paypal.com/api/invoicing/v2/schema.json)

The provider connection is the workspace's sandbox OAuth identity. The invoice
response does not expose a merchant ID for independent comparison with the
configured merchant ID; do not claim that check happened. The database pins the
workspace/provider connection and exact accepted payload. Genuine account-level
seller validation remains part of external acceptance.

Only documented `PAID` maps to the app's paid status, with zero outstanding
amount. Manual paid markers, partial payment, pending, cancellation and reversal
states require operator review. No `PAID` result is a bank-settlement claim.
An unpaid invoice's optional recipient URL is exposed only for the fixed HTTPS
sandbox PayPal domain; HATEOAS URLs never choose API request destinations.
Activation can complete as unpaid only when that verified payment URL is present.
A missing or unsafe URL after activation remains an uncertain result; a status
refresh cannot clear it until a usable link or confirmed paid state is established.
[Show invoice details](https://developer.paypal.com/api/invoicing/v2/invoices-get)

This create endpoint's current operation schema does not document an idempotency
guarantee. A stable application key is not treated as proof that repeating a
POST is safe. A timeout, server error or invalid successful-create response is
`uncertain: true`; the worker must persist `outcome_unknown` and never automatically
repeat it. Recovery currently requires operator review using the deterministic
number/reference. No invoice search recovery, email sending, payment collection
or real PayPal request was performed. The local invoice demonstration is a
separate, explicitly simulated provider.

`activate_invoice` is a separate write, not an automatic side effect of draft
creation. It pre-reads and validates the invoice binding and current draft,
rejects any additional recipients and then calls `/send` with
`send_to_recipient: false`, `send_to_invoicer: false` and
`additional_recipients: []`. Already unpaid/paid invoices are read without another
write. A successful POST is followed by a read that must confirm the matching
payable or paid invoice; a failed or unconfirmed read is an uncertain activation,
with the known provider ID retained for read-only recovery.
[Send invoice](https://developer.paypal.com/api/invoicing/v2/invoices-send)

The no-recipient-notification flag does not apply to future scheduled issue
dates. Draft creation therefore explicitly uses the current civil date in
UTC−12, the earliest date worldwide; activation rejects a missing, malformed or
later date. The date can be the previous day relative to the user's local date.
This conservative sandbox policy avoids assuming a merchant timezone. It is not
a configurable arbitrary timezone or a claim of verified PayPal behavior. Direct
concurrent edits in the PayPal Dashboard between the pre-read and activation are
outside the application's transaction boundary; real account acceptance must
exercise this path before enabling it for an actual seller. No external draft
creation or activation was executed during development.

## Optional local configuration

Copy `.env.scope.example` to ignored `.env.scope` and set the OpenAI key and
chosen model only when authorized to use the API. Add `-f compose.scope.yml`
to the existing compose invocation; only the console receives these credentials.
PayPal uses its separate `.env.paypal` and `compose.paypal.yml` profile. Neither
credential template nor adapter availability demonstrates genuine provider
acceptance or makes this application a production financial service.
