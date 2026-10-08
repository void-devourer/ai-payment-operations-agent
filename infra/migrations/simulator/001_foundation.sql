CREATE TABLE payments (
    workspace_id text NOT NULL,
    payment_intent_id text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'requires_payment_method',
    succeeded_at timestamptz,
    PRIMARY KEY (workspace_id, payment_intent_id)
);
CREATE TABLE events (
    workspace_id text NOT NULL,
    event_id text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (workspace_id, event_id)
);
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments FORCE ROW LEVEL SECURITY;
CREATE POLICY payment_scope ON payments USING (workspace_id = current_setting('app.workspace', true));
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
CREATE POLICY event_scope ON events USING (workspace_id = current_setting('app.workspace', true));
GRANT SELECT, INSERT, UPDATE ON payments TO simulator_runtime;
GRANT SELECT, INSERT ON events TO simulator_runtime;
