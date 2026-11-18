# Scope & Pay

This context records agreed freelance work, proposed additions and explicit client
decisions before creating an invoice. The original payment investigation context
is preserved separately in the context map.

## Language

**Workspace**:
The independent professional or studio whose projects and client records are
managed together.
_Avoid_: PayPal account, client account.

**Client**:
The person reviewing a project addition and deciding whether to accept its stated
work and price. Possessing a review link does not verify the person's identity.
_Avoid_: Operator, authenticated buyer.

**Brief**:
The recorded baseline describing the project's included work. A revision changes
that baseline and invalidates outstanding proposals based on the earlier brief.
_Avoid_: Conversation, proposal.

**Client message**:
A preserved source text supplied for review against the brief. A pasted message
is a claim about a conversation, not independently authenticated evidence.
_Avoid_: Approval, verified instruction.

**Request review**:
A suggested classification of a message as included work, an addition or unclear,
with exact source quotes. It cannot set a price or authorize billing.
_Avoid_: Decision, client acceptance.

**Change proposal**:
A versioned description and price chosen by the professional for additional
work, tied to a specific brief revision and source quotes.
_Avoid_: Invoice, automatic charge.

**Client acceptance**:
An explicit decision submitted through a current review link for the exact
proposal version and digest. It is recorded separately from inferred intent.
_Avoid_: Message sentiment, AI approval, payment authorization.

**Review link**:
An expiring, revocable capability allowing its holder to view and decide on one
proposal. Its token stays in the browser fragment and authorization header;
stored records contain the hash.
_Avoid_: Client login, identity verification.

**Invoice**:
A provider-bound record of the accepted work and requested payment. A PayPal
draft is not payable until the provider's separate sending step occurs.
_Avoid_: Payment, money received.

**Unknown invoice outcome**:
A creation attempt that may have reached the provider without a confirmed result.
It requires reconciliation rather than another blind creation attempt.
_Avoid_: Failed payment, safe to retry.

**Local demonstration**:
A labelled, persistent workflow using synthetic sample review and simulated
invoices. Its paid state does not represent money movement.
_Avoid_: Live AI, PayPal payment, sandbox acceptance.
