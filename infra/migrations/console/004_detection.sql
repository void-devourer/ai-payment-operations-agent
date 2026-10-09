CREATE TABLE success_clocks (
    workspace_id text NOT NULL,
    connection_id text NOT NULL,
    payment_intent_id text NOT NULL,
    first_confirmed_at timestamptz NOT NULL,
    observation_id text NOT NULL,
    PRIMARY KEY(workspace_id,connection_id,payment_intent_id),
    FOREIGN KEY(workspace_id,connection_id,payment_intent_id)
        REFERENCES payment_attempts(workspace_id,connection_id,payment_intent_id),
    FOREIGN KEY(workspace_id,observation_id) REFERENCES observations(workspace_id,observation_id)
);
CREATE TABLE evaluations (
    workspace_id text NOT NULL,
    observation_id text NOT NULL,
    purchase_id text NOT NULL,
    policy_version text NOT NULL,
    outcome text NOT NULL CHECK(outcome IN ('eligible','pending','healthy','blocked','awaiting_evidence','manual_review','operation_in_progress')),
    reasons jsonb NOT NULL,
    fingerprint text NOT NULL,
    evaluated_at timestamptz NOT NULL,
    PRIMARY KEY(workspace_id,observation_id),
    FOREIGN KEY(workspace_id,observation_id) REFERENCES observations(workspace_id,observation_id),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id)
);
CREATE TABLE cases (
    workspace_id text NOT NULL,
    case_id text NOT NULL,
    purchase_id text NOT NULL,
    discrepancy_code text NOT NULL CHECK(discrepancy_code IN ('PAID_ACCESS_MISSING','REVERSAL_ACCESS_REVIEW','PAYMENT_REVIEW')),
    generation integer NOT NULL CHECK(generation>0),
    state text NOT NULL CHECK(state IN ('open','awaiting_evidence','resolved','dismissed')),
    fingerprint text NOT NULL,
    first_observation_id text NOT NULL,
    latest_observation_id text NOT NULL,
    opened_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,case_id),
    UNIQUE(workspace_id,purchase_id,discrepancy_code,generation),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id),
    FOREIGN KEY(workspace_id,first_observation_id) REFERENCES observations(workspace_id,observation_id),
    FOREIGN KEY(workspace_id,latest_observation_id) REFERENCES observations(workspace_id,observation_id)
);
CREATE UNIQUE INDEX one_active_case ON cases(workspace_id,purchase_id,discrepancy_code)
WHERE state IN ('open','awaiting_evidence');
CREATE TABLE case_audit (
    workspace_id text NOT NULL,
    audit_id text NOT NULL,
    case_id text NOT NULL,
    subject text NOT NULL,
    action text NOT NULL CHECK(action IN ('dismiss','resolve')),
    reason text NOT NULL,
    fingerprint text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,audit_id),
    FOREIGN KEY(workspace_id,case_id) REFERENCES cases(workspace_id,case_id)
);
CREATE TABLE reconciliation_runs (
    workspace_id text NOT NULL,
    run_id text NOT NULL,
    connection_id text NOT NULL,
    state text NOT NULL CHECK(state IN ('scanning','scheduled')),
    cutoff_at timestamptz NOT NULL DEFAULT now(),
    after_purchase_id text NOT NULL DEFAULT '',
    scheduled_purchases integer NOT NULL DEFAULT 0,
    unbound_purchases integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    PRIMARY KEY(workspace_id,run_id),
    FOREIGN KEY(workspace_id,connection_id) REFERENCES connections(workspace_id,connection_id)
);
CREATE UNIQUE INDEX one_active_scan ON reconciliation_runs(workspace_id,connection_id) WHERE state='scanning';
CREATE INDEX evaluation_purchase ON evaluations(workspace_id,purchase_id,evaluated_at DESC);
CREATE INDEX case_inbox ON cases(workspace_id,case_id);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['success_clocks','evaluations','cases','case_audit','reconciliation_runs'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id=current_setting(''app.workspace'',true))',t);
  END LOOP;
END $$;
GRANT SELECT,INSERT ON success_clocks,evaluations,case_audit TO console_runtime;
GRANT SELECT,INSERT,UPDATE ON cases,reconciliation_runs TO console_runtime;
