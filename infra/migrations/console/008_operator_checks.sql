ALTER TABLE case_audit DROP CONSTRAINT case_audit_action_check;
ALTER TABLE case_audit ADD CONSTRAINT case_audit_action_check
  CHECK (action IN ('dismiss','resolve','propose','approve','reject','repair_result','recover','request_check'));
CREATE INDEX operator_check_rate ON case_audit(workspace_id,created_at)
  WHERE action='request_check';
