CREATE TABLE memberships (
    workspace_id text NOT NULL,
    subject text NOT NULL,
    role text NOT NULL CHECK (role IN ('owner', 'operator', 'viewer')),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (workspace_id, subject)
);
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY membership_subject ON memberships USING (subject = current_setting('app.subject', true));
CREATE TABLE sessions (
    token_digest text PRIMARY KEY,
    subject text NOT NULL,
    csrf_digest text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX session_expiry ON sessions(expires_at);
CREATE TABLE purchases (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    customer_id text NOT NULL,
    product_id text NOT NULL,
    expected_amount_minor bigint NOT NULL CHECK (expected_amount_minor > 0),
    currency text NOT NULL CHECK (currency ~ '^[a-z]{3}$'),
    connection_id text NOT NULL,
    provider_customer_id text NOT NULL,
    payload jsonb NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, purchase_id)
);
CREATE TABLE payment_attempts (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    connection_id text NOT NULL,
    payment_intent_id text NOT NULL,
    PRIMARY KEY (workspace_id, connection_id, payment_intent_id),
    FOREIGN KEY (workspace_id, purchase_id) REFERENCES purchases(workspace_id, purchase_id)
);
ALTER TABLE purchases ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchases FORCE ROW LEVEL SECURITY;
CREATE POLICY purchase_scope ON purchases USING (workspace_id = current_setting('app.workspace', true));
ALTER TABLE payment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY attempt_scope ON payment_attempts USING (workspace_id = current_setting('app.workspace', true));
GRANT SELECT ON memberships TO console_runtime;
GRANT SELECT, INSERT, DELETE ON sessions TO console_runtime;
GRANT SELECT, INSERT ON purchases, payment_attempts TO console_runtime;
INSERT INTO memberships(workspace_id, subject, role) VALUES
    ('ws_a', 'owner_a', 'owner'), ('ws_a', 'operator_a', 'operator'),
    ('ws_a', 'viewer_a', 'viewer'), ('ws_b', 'owner_b', 'owner');
