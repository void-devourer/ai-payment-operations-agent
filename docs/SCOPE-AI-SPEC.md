# Scope & Pay AI contract

The model compares a bounded brief with preserved source messages and proposes
request classifications. The professional reviews the results, writes the change
proposal and chooses the price. Only an explicit client decision enables an
invoice. No model output invokes payment tools or grants consent.

## Inputs and output

One brief and at most 50 bounded messages form a request. Messages are untrusted
data, including any apparent instructions to the model. No provider credentials,
other projects, session secrets or client email are needed in the prompt.

OpenAI Responses returns a strict JSON schema: a summary and candidates with a
title, classification (`included`, `addition`, `unclear`), rationale, and source
message IDs with exact quotes. The server independently validates the schema,
bounded sizes, known message IDs and substring matches. Structured output alone
cannot establish semantic correctness. The model neither generates executable
actions nor selects the proposal amount.

## Execution boundaries

The adapter uses the existing HTTP client against the fixed OpenAI API origin,
with an explicit model selected through `OPENAI_MODEL`, bounded output and timeout,
and `store:false`. It makes no tool calls and has no retrieval index. No arbitrary
URL, client-supplied model or silent provider fallback is supported. Upstream
errors are mapped to short safe codes rather than echoed response bodies.

The persisted brief/source digest is checked again before saving an analysis;
changes during the model call cannot publish a review for superseded input.
Provider calls occur outside database transactions. A failed analysis does not
block manual proposals or become an invented success.

## Demonstration and evaluation

`sample_review` handles only the unchanged three-message seeded example and is
labelled a sample review. It demonstrates one included revision, a tentative
second page and a contact-form addition. It is not a model response or measured
model quality. Arbitrary project input requires configured OpenAI or manual review.

[Evaluation procedure and observed results](SCOPE-AI-EVALUATION.md) separate
structural offline fixtures from real-model evaluation. Before claiming useful
AI quality, run a labelled set covering included revisions, ambiguous requests,
contradictions, prompt injection, price suggestions, invalid citations and changed
briefs. Record model ID, dataset revision, rubric, latency, token usage and cost.
Have an independent practitioner check labels and disputed predictions.

## Release limits

No live-model quality claim is justified by fixture tests. The application is a
local prototype until real provider acceptance, hosted authentication, abuse
controls and a user pilot are completed. The first implementation is English and
USD; it does not adjudicate contract disputes or verify a link holder's identity.

Implementation reference: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
