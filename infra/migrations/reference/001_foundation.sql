CREATE TABLE orders (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    customer_id text NOT NULL,
    product_id text NOT NULL,
    payment_intent_id text NOT NULL,
    payload jsonb NOT NULL,
    fault_mode text NOT NULL CHECK (fault_mode IN ('none', 'pause_fulfillment')),
    fulfillment_payload jsonb,
    fulfillment_state text NOT NULL DEFAULT 'pending' CHECK (fulfillment_state IN ('pending', 'succeeded', 'blocked')),
    last_error text,
    PRIMARY KEY (workspace_id, purchase_id)
);
CREATE TABLE access_grants (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    customer_id text NOT NULL,
    product_id text NOT NULL,
    status text NOT NULL DEFAULT 'inactive' CHECK (status IN ('inactive', 'active', 'suspended', 'revoked')),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    ever_activated boolean NOT NULL DEFAULT false,
    PRIMARY KEY (workspace_id, purchase_id),
    UNIQUE (workspace_id, customer_id, product_id),
    FOREIGN KEY (workspace_id, purchase_id) REFERENCES orders(workspace_id, purchase_id)
);
CREATE TABLE operation_receipts (
    workspace_id text NOT NULL,
    operation_id text NOT NULL,
    payload_digest text NOT NULL,
    response_status integer NOT NULL,
    receipt jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, operation_id)
);
CREATE TABLE registration_outbox (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('purchase', 'attempt')),
    payload jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'sending', 'sent', 'dead')),
    attempts integer NOT NULL DEFAULT 0,
    due_at timestamptz NOT NULL DEFAULT now(),
    lease_id text,
    lease_until timestamptz,
    last_error text,
    PRIMARY KEY (workspace_id, purchase_id, kind),
    FOREIGN KEY (workspace_id, purchase_id) REFERENCES orders(workspace_id, purchase_id)
);
CREATE INDEX outbox_due ON registration_outbox(workspace_id, state, due_at);
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['orders','access_grants','operation_receipts','registration_outbox'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id = current_setting(''app.workspace'', true))', table_name);
    END LOOP;
END $$;
GRANT SELECT, INSERT, UPDATE ON orders, access_grants, registration_outbox TO reference_runtime;
GRANT SELECT, INSERT ON operation_receipts TO reference_runtime;
