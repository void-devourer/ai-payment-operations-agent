ALTER TABLE payments ADD COLUMN reversal_generation bigint NOT NULL DEFAULT 0;
ALTER TABLE payments ADD COLUMN read_fault integer NOT NULL DEFAULT 0 CHECK(read_fault IN (0,403,429,503));
ALTER TABLE payments ADD COLUMN page_fault boolean NOT NULL DEFAULT false;
CREATE TABLE reversals (
    workspace_id text NOT NULL,
    payment_intent_id text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('refunds','disputes')),
    resource_id text NOT NULL,
    status text NOT NULL,
    amount_minor bigint NOT NULL CHECK(amount_minor>=0),
    PRIMARY KEY(workspace_id,payment_intent_id,kind,resource_id),
    FOREIGN KEY(workspace_id,payment_intent_id) REFERENCES payments(workspace_id,payment_intent_id)
);
ALTER TABLE reversals ENABLE ROW LEVEL SECURITY;
ALTER TABLE reversals FORCE ROW LEVEL SECURITY;
CREATE POLICY reversal_scope ON reversals USING(workspace_id=current_setting('app.workspace',true));
GRANT SELECT,INSERT ON reversals TO simulator_runtime;
ALTER TABLE events ADD COLUMN delivery_state text NOT NULL DEFAULT 'queued'
CHECK(delivery_state IN ('queued','leased','retry_wait','sent','dead'));
ALTER TABLE events ADD COLUMN delivery_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN due_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE events ADD COLUMN lease_token text;
ALTER TABLE events ADD COLUMN lease_until timestamptz;
ALTER TABLE events ADD COLUMN last_error text;
GRANT UPDATE ON events TO simulator_runtime;
CREATE INDEX event_delivery_due ON events(workspace_id,due_at) WHERE delivery_state IN ('queued','retry_wait','leased');
