# Payment Reliability

This context investigates disagreements between a business's payment records and
the access its application gives customers. It supports evidence-based decisions
and controlled repairs.

## Language

**Workspace**:
The business whose purchases, customers, payment evidence, and cases are managed
together. A person may belong to more than one workspace.
_Avoid_: Account when referring to the business.

**Operator**:
A person authorized by a workspace to investigate cases or approve repairs.
_Avoid_: Customer when referring to the person using the console.

**Customer**:
The person or organization buying access to the business's product.
_Avoid_: Operator, user when the distinction matters.

**Purchase**:
A business commitment identifying the customer, product, and expected payment
that should result in access. It is distinct from a payment attempt.
_Avoid_: Transaction, payment when referring to the business commitment.

**Payment attempt**:
An attempt to collect money for a purchase; a purchase can have multiple attempts.
_Avoid_: Purchase, order.

**Payment evidence**:
An observation of payment, refund, or dispute facts from the payment provider.
Its scope and freshness determine what conclusions it supports.
_Avoid_: Proof of access, balance when referring to payment facts.

**Provider connection**:
The relationship between a workspace and a specific payment-provider account and
environment.
_Avoid_: Account without identifying whether it belongs to the provider or the business.

**Access grant**:
The business application's authorization for a customer to use a purchased
product. A payment success alone is not an access grant.
_Avoid_: Payment, subscription when referring to application access.

**Discrepancy**:
A disagreement between expected business state and observed payment or access
facts. A discrepancy can be temporary or intentional and is not itself a diagnosis.
_Avoid_: Fraud, lost money, root cause without supporting evidence.

**Case**:
An investigation of a discrepancy, including its evidence, operator decisions,
and observed resolution.
_Avoid_: Refund request, repair when referring to the whole investigation.

**Repair proposal**:
A specific suggested change to application access with an explanation and the
conditions under which it would be permitted.
_Avoid_: Approval, executed repair.

**Approval**:
An operator's decision permitting a particular repair proposal under its stated
conditions. Approval does not guarantee that those conditions still hold later.
_Avoid_: Payment authorization, unconditional permission.

**Repair operation**:
An attempt to carry out an approved application-access change and establish its
outcome.
_Avoid_: Charge, refund when the action changes only application access.

**Unknown outcome**:
A repair for which the application may have accepted the change but the console
has not established the result.
_Avoid_: Failed, safe to retry with a new identity.

**Resolution**:
Evidence that a case's discrepancy has ceased or an operator's documented
decision that no repair should be performed.
_Avoid_: Job completion as a synonym for business resolution.

**Payout**:
A transfer from the provider's balance to the business's external account. A
payout is distinct from the customer's payment and may cover many transactions.
_Avoid_: Payment, revenue.
