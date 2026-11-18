# AI-SPEC — H3: evidence-grounded merchant investigation

Historical design, superseded on 2026-10-15 by the
[Scope & Pay AI contract](SCOPE-AI-SPEC.md). Retained to explain the earlier
merchant-investigation direction; it is not the current implementation plan.

Design draft, 2026-10-14. OpenAI provider selected by the user. This is an inline
design in the repository's existing PLAN.md workflow, using the AI integration
skill's framework/domain/evaluation structure; the repo has no GSD `.planning`
phase state, so this is not a completed GSD-generated phase contract.
SDK version, model snapshot and measured results remain H3 gates. No AI runtime
is implemented or enabled by this document.

## 1. System classification

Conversational investigation with structured generation over a server-assembled
case snapshot. The merchant operator supplies a complaint/question. The assistant
connects the claim to known payment and access evidence, explains contradictions,
names unknowns, suggests bounded investigation steps and drafts an editable reply.

Critical failures: evidence from another workspace, a secret in a prompt/output,
invented root cause or bank settlement, a stale/incomplete snapshot described as
current certainty, or any generated text being accepted as action authorization.

## 1b. Domain context

Audience: support/operations operators at small digital-product merchants.
Payment, capture, refund, dispute and customer access are distinct records.
A customer complaint is a claim to investigate, not an authenticated fact. The
PayPal capture contract identifies a captured payment and related order/seller;
it does not by itself establish complete reversal history or bank settlement.

| Dimension | Good: reviewer accepts | Bad: reviewer rejects | Consequence |
| --- | --- | --- | --- |
| Payment interpretation | Separates approved order, pending capture and completed capture | Calls an approval a received payment | Incorrect support advice or premature access |
| Duplicate claim | Reports multiple observed captures and what remains unverified | Announces a duplicate charge or chooses a refund without evidence | Unjustified financial advice |
| Coverage | Distinguishes missing records from confirmed empty history | Claims no refunds/disputes because collection failed | Unsafe repair recommendation |
| Recovery | Distinguishes historical grant receipt from current active access | Calls a queue completion or timeout verified recovery | False resolution |
| Explanation | States supported facts and a precise next check | Invents why fulfillment failed | Misleading diagnosis |

Sources: [PayPal capture details](https://developer.paypal.com/api/payments/v2/captures-get),
[Payments schema](https://developer.paypal.com/api/payments/v2/schema.json),
and this project's [domain vocabulary](../CONTEXT.md).
This sandbox prototype is not a tax, regulatory, settlement or financial-advice
product. Product/legal review would be separate work before real merchant data.
Initial reviewers should include a backend developer and a support/operator user;
until their review exists, synthetic engineering labels are not practitioner validation.

## 2. Framework decision

Selected: official OpenAI Python SDK, Responses API and Pydantic output schema.
One bounded call first. The application already owns durable workflows; the model
does not need another workflow engine or a multi-agent team to explain a bounded
case snapshot. OpenAI SDK version and exact model remain unpinned until H3 setup
checks available access and measures representative cases and cost.

| Alternative | Why not the first implementation |
| --- | --- |
| OpenAI Agents SDK | Useful if scoped tool loops become necessary; not required for one assembled snapshot |
| LangGraph | Adds state/orchestration before a demonstrated branching/retrieval need |
| Vector retrieval | Case IDs already provide exact scoped retrieval; similarity search could add irrelevant or cross-case evidence |

Provider lock-in is accepted for the initial implementation, with a small typed
model-call interface and deterministic console functionality preserved separately.

## 3. Framework quick reference

[Official structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs)
documents Pydantic `text_format` and the Responses parse helper. The following is
an implementation pattern, not an installed dependency or exercised model call:

```python
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statement: str
    evidence_ids: list[str]

class InvestigationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str
    claims: list[EvidenceClaim]
    unknowns: list[str]
    next_checks: list[str]
    draft_reply: str

async def explain(client: AsyncOpenAI, model: str, instructions: str, bundle: str):
    response = await client.responses.parse(
        model=model,
        input=[{"role": "developer", "content": instructions},
               {"role": "user", "content": bundle}],
        text_format=InvestigationAnswer,
        store=False,
        max_output_tokens=1200,
    )
    return response.output_parsed
```

Construct the client once per service lifespan, with an explicit 20-second timeout
and `max_retries=0` initially. Require configured API key and model; do not fall
back to an expensive model silently. Pin the SDK and model in the evaluated
release. Handle refusals, incomplete/truncated responses, missing parsed output,
timeouts and HTTP failures as distinct unavailable/uncertain states.
`store=False` is not a claim of zero provider retention; review actual API data
controls before sending real customer data.

## 4. Implementation guidance and best practices

1. Authenticate and authorize the workspace/case before loading any evidence.
2. Load bounded authorized facts, selected historical changes, provider coverage,
   policy version and deterministic action availability. Redact keys, tokens,
   emails, addresses, raw webhook headers and unnecessary customer identifiers.
3. Treat the complaint, merchant notes and metadata as untrusted data, even if
   they contain instructions. Supply no executable tools or arbitrary URL access.
4. Bind the request to observation IDs, evidence generation and policy version.
   Send at most a 16 KiB redacted bundle and a 2,000-character question initially.
5. Make one bounded async call. No hidden retries, internet retrieval, money
   mutation, approval, repair, SQL or automatic message sending.
6. Validate schema, length limits, evidence-ID membership and allowlisted next
   checks. A valid citation is necessary but does not prove factual entailment.
7. Recheck the head before publication. If it changed, mark the answer as an
   earlier snapshot rather than current guidance. Display deterministic freshness
   and action eligibility independently from the generated text.

Version prompt, policy excerpt, output schema and redaction rules. Do not request
hidden chain of thought; show concise supported explanations. Stream only if
validated content can be staged safely; the first release awaits the full parsed
answer. React renders plain text and explicit application-owned evidence links.

Proposed endpoint: `POST /api/workspaces/{workspace}/cases/{case_id}/assistant`.
The viewer may inspect deterministic evidence; model invocation permissions and
per-workspace cost quotas must be implemented explicitly before exposing it.
Budget exhaustion and disabled AI leave the ordinary case page usable. A configured
credential permits testing, not a claim that evaluation passed.

## 5. Evaluation strategy

Build 24 development scenarios and 12 independently reviewed holdout scenarios.
Run three trials per scenario using recorded model/prompt/schema/policy versions.
Freeze the holdout before tuning and do not silently rewrite difficult scenarios.
Dataset rows include question, authorized snapshot, expected supported findings,
required unknowns, forbidden claims and acceptable next checks. Label initial
cases manually from the evidence; any model-assisted judging must be calibrated
against these labels and cannot be the sole safety judge.

Cover missing access, pending/failed captures, approval without capture, multiple
captures, refunds, unavailable dispute reads, stale/partial evidence, wrong order,
wrong seller/buyer, currency/amount mismatch, intentionally blocked access,
unknown repair outcome, changed snapshot and injected instructions in notes.

| Dimension | Gate before enabling an experimental demo |
| --- | --- |
| Tenant/secret isolation | Zero observed leaks across all adversarial tests; server scope tests must pass |
| Action boundary | Zero executable actions/tools, eligibility overrides or automatically sent replies |
| Grounding | Zero critical unsupported claims; at least 95% of noncritical factual claims supported by cited evidence |
| Citations | 100% belong to the authorized snapshot; fabricated/cross-case citations rejected before display |
| Required uncertainty | At least 95% of required unknowns explicitly acknowledged; zero confident bank-settlement or unobserved-cause claims |
| Useful next check | At least 85% of reviewed answers suggest an acceptable, specific investigation step |
| Structure | Every displayed answer passes server validation; rejected generations remain in the failure denominator |
| Availability/latency | At least 95% of requests produce a validated answer within 20 seconds; retain timeouts/refusals as failures |
| Cost | Publish observed token/cost distributions after selecting the model; enforce configured limits before calling |

These are proposed gates, not measured results or guarantees. Compare with the
existing deterministic view on the same cases. Use operator-rated decision
quality and timed tasks to study usefulness; synthetic scores alone cannot
establish saved support time, revenue or demand. Report every case/trial, not just
successful generations. A failed holdout requires a documented correction and
fresh unseen confirmation evidence before declaring improvement.

## 6. Guardrails

Online: scope before retrieval, redaction, fixed evidence snapshot, request/output
limits, schema/citation/next-check validation, quotas and timeouts. Reject unsafe
output rather than repairing it into plausible prose. Generated text cannot
change any proposal or execution rule. Mark stale responses; keep replies editable.

Offline: manually inspect all critical failures, ambiguous payment interpretations,
unsupported causes and complaint-to-evidence mismatches. Track useful abstention
separately from generic refusal. Recheck the frozen evaluation when prompts,
models, provider mappings or policies change.

## 7. Monitoring and rollout

Record request ID, scoped case/snapshot IDs, prompt/schema/model version, elapsed
time, token counts, configured cost estimate, outcome and validation failure
category. Do not place credentials or unredacted complaint text in telemetry.
Use local structured evaluation records first; a separate tracing service is not
a dependency for this bounded hackathon demo. Evaluate a tracing tool only when
it adds useful diagnosis without duplicating stored sensitive content.

Keep AI disabled by default until the demo gate passes. Immediately disable the
assistant for a scope/secret violation; application investigation continues.
Operator feedback and measured limitations accompany the demonstration.

## Design checklist

- [x] User chose OpenAI.
- [x] Framework approach and alternatives documented.
- [x] Domain-specific good/bad examples and critical failure modes documented.
- [x] Structured-output pattern and independent server validation specified.
- [x] Evaluation dataset, repeated trials and explicit gates specified.
- [ ] Pin SDK version/model and verify actual API access.
- [ ] Implement authenticated evidence assembly and UI.
- [ ] Run real model evaluations and record failures, latency and cost.
- [ ] Validate actual operator usefulness; do not claim it from synthetic tests.
