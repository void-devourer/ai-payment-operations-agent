# Context map

## Contexts

- [Scope & Pay](CONTEXT.md): freelance brief, source messages, change proposals,
  client decisions and invoices. This is the active product.
- [Payment Reliability](docs/PAYMENT-CONTEXT.md): the preserved purchase,
  payment-evidence, application-access and repair workflow at `/operations`.

## Relationships

Both contexts use workspace membership, sessions and PostgreSQL isolation. They
have separate domain tables and jobs. A Scope & Pay invoice is not a legacy
purchase or an access-repair approval. No automatic synchronization or shared
financial ledger is implied.
