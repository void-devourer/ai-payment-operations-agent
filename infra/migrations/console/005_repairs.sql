ALTER TABLE cases DROP CONSTRAINT cases_state_check;
ALTER TABLE cases ADD CHECK (state IN ('open','awaiting_evidence','awaiting_approval','repair_in_progress','outcome_unknown','resolved','dismissed'));
DROP INDEX one_active_case;
CREATE UNIQUE INDEX one_active_case ON cases(workspace_id,purchase_id,discrepancy_code)
WHERE state IN ('open','awaiting_evidence','awaiting_approval','repair_in_progress','outcome_unknown');
ALTER TABLE case_audit DROP CONSTRAINT case_audit_action_check;
ALTER TABLE case_audit ADD CHECK (action IN ('dismiss','resolve','propose','approve','reject','repair_result','recover'));

CREATE TABLE repair_proposals (
    workspace_id text NOT NULL,
    proposal_id text NOT NULL,
    case_id text NOT NULL,
    purchase_id text NOT NULL,
    created_by text NOT NULL,
    observation_id text NOT NULL,
    fingerprint text NOT NULL,
    policy_version text NOT NULL,
    payload jsonb NOT NULL,
    payload_digest text NOT NULL,
    expires_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected','expired','superseded')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,proposal_id),
    FOREIGN KEY(workspace_id,case_id) REFERENCES cases(workspace_id,case_id),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id),
    FOREIGN KEY(workspace_id,observation_id) REFERENCES observations(workspace_id,observation_id)
);
CREATE UNIQUE INDEX one_pending_proposal ON repair_proposals(workspace_id,purchase_id) WHERE state='pending';
CREATE TABLE repair_approvals (
    workspace_id text NOT NULL,
    proposal_id text NOT NULL,
    subject text NOT NULL,
    session_digest text NOT NULL,
    decision text NOT NULL CHECK(decision IN ('approve','reject')),
    payload_digest text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,proposal_id),
    FOREIGN KEY(workspace_id,proposal_id) REFERENCES repair_proposals(workspace_id,proposal_id)
);
CREATE TABLE repair_operations (
    workspace_id text NOT NULL,
    operation_id text NOT NULL,
    proposal_id text NOT NULL,
    purchase_id text NOT NULL,
    state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','executing','verifying','outcome_unknown','succeeded','blocked','conflict','applied_not_recovered')),
    attempts integer NOT NULL DEFAULT 0,
    due_at timestamptz NOT NULL DEFAULT now(),
    lease_token text,
    lease_until timestamptz,
    dispatch_started_at timestamptz,
    receipt jsonb,
    verification_observation_id text,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,operation_id),
    UNIQUE(workspace_id,proposal_id),
    FOREIGN KEY(workspace_id,proposal_id) REFERENCES repair_approvals(workspace_id,proposal_id),
    FOREIGN KEY(workspace_id,purchase_id) REFERENCES purchases(workspace_id,purchase_id),
    FOREIGN KEY(workspace_id,verification_observation_id) REFERENCES observations(workspace_id,observation_id)
);
CREATE UNIQUE INDEX one_active_repair ON repair_operations(workspace_id,purchase_id)
WHERE state IN ('queued','executing','verifying','outcome_unknown');
CREATE INDEX due_repairs ON repair_operations(workspace_id,due_at);
CREATE TABLE repair_attempts (
    workspace_id text NOT NULL,
    attempt_id text NOT NULL,
    operation_id text NOT NULL,
    lease_token text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('dispatch','lookup','verify','result')),
    result text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(workspace_id,attempt_id),
    FOREIGN KEY(workspace_id,operation_id) REFERENCES repair_operations(workspace_id,operation_id)
);
CREATE FUNCTION freeze_repair_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='repair_proposals' THEN
    IF (to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state') THEN
      RAISE EXCEPTION 'Immutable proposal';
    END IF;
  ELSE
    IF ROW(NEW.workspace_id,NEW.operation_id,NEW.proposal_id,NEW.purchase_id,NEW.created_at)
       IS DISTINCT FROM ROW(OLD.workspace_id,OLD.operation_id,OLD.proposal_id,OLD.purchase_id,OLD.created_at) THEN
      RAISE EXCEPTION 'Immutable operation identity';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER immutable_proposal BEFORE UPDATE ON repair_proposals FOR EACH ROW EXECUTE FUNCTION freeze_repair_identity();
CREATE TRIGGER immutable_operation BEFORE UPDATE ON repair_operations FOR EACH ROW EXECUTE FUNCTION freeze_repair_identity();
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['repair_proposals','repair_approvals','repair_operations','repair_attempts'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id=current_setting(''app.workspace'',true))',t);
  END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON repair_proposals,repair_operations TO console_runtime;
GRANT SELECT,INSERT ON repair_approvals,repair_attempts TO console_runtime;
