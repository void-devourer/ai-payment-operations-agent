CREATE TABLE connections (
    workspace_id text NOT NULL,
    connection_id text NOT NULL,
    account_id text NOT NULL,
    environment text NOT NULL CHECK (environment = 'simulated'),
    api_version text NOT NULL CHECK (api_version = 'simulator.v1'),
    next_request_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, connection_id)
);
INSERT INTO connections(workspace_id,connection_id,account_id,environment,api_version) VALUES
('ws_a','sim_ws_a','sim_acct_ws_a','simulated','simulator.v1'),
('ws_b','sim_ws_b','sim_acct_ws_b','simulated','simulator.v1');
CREATE TABLE inbox (
    workspace_id text NOT NULL,
    connection_id text NOT NULL,
    event_id text NOT NULL,
    event_type text NOT NULL,
    api_version text NOT NULL,
    raw_body bytea NOT NULL,
    body_digest text NOT NULL,
    payment_intent_id text,
    state text NOT NULL CHECK (state IN ('accepted','quarantined','ignored')),
    received_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL DEFAULT 'authenticated_webhook' CHECK (source='authenticated_webhook'),
    PRIMARY KEY (workspace_id,connection_id,event_id),
    FOREIGN KEY (workspace_id,connection_id) REFERENCES connections(workspace_id,connection_id)
);
CREATE TABLE jobs (
    workspace_id text NOT NULL,
    job_id text NOT NULL,
    connection_id text NOT NULL,
    payment_intent_id text NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','leased','retry_wait','completed','dead')),
    request_seq bigint NOT NULL DEFAULT 1,
    claimed_seq bigint,
    attempts integer NOT NULL DEFAULT 0,
    due_at timestamptz NOT NULL DEFAULT now(),
    lease_token text,
    lease_until timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,job_id),
    FOREIGN KEY(workspace_id,connection_id) REFERENCES connections(workspace_id,connection_id)
);
CREATE UNIQUE INDEX one_active_read ON jobs(workspace_id,connection_id,payment_intent_id)
WHERE state IN ('queued','leased','retry_wait');
CREATE INDEX due_jobs ON jobs(workspace_id,due_at) WHERE state IN ('queued','retry_wait','leased');
CREATE TABLE evidence_heads (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    generation bigint NOT NULL DEFAULT 0,
    observation_id text,
    PRIMARY KEY(workspace_id,purchase_id),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id)
);
CREATE TABLE observations (
    workspace_id text NOT NULL,
    observation_id text NOT NULL,
    purchase_id text NOT NULL,
    job_id text NOT NULL,
    generation bigint NOT NULL,
    facts jsonb NOT NULL,
    content_digest text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    source text NOT NULL CHECK(source='simulator_api_and_target'),
    api_version text NOT NULL,
    normalizer_version text NOT NULL,
    PRIMARY KEY(workspace_id,observation_id),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id),
    FOREIGN KEY(workspace_id,job_id) REFERENCES jobs(workspace_id,job_id)
);
CREATE TABLE job_audit (
    workspace_id text NOT NULL,
    audit_id text NOT NULL,
    job_id text NOT NULL,
    subject text NOT NULL,
    action text NOT NULL CHECK(action='redrive'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,audit_id),
    FOREIGN KEY(workspace_id,job_id) REFERENCES jobs(workspace_id,job_id)
);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['connections','inbox','jobs','evidence_heads','observations','job_audit'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id = current_setting(''app.workspace'',true))',t);
  END LOOP;
END $$;
GRANT SELECT,UPDATE ON connections TO console_runtime;
GRANT SELECT,INSERT ON inbox,observations,job_audit TO console_runtime;
GRANT SELECT,INSERT,UPDATE ON jobs,evidence_heads TO console_runtime;
