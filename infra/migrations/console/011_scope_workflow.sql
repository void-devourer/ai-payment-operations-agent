CREATE TABLE scope_projects (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  name text NOT NULL,
  client_name text NOT NULL,
  client_email text NOT NULL,
  brief text NOT NULL,
  brief_revision integer NOT NULL DEFAULT 1 CHECK(brief_revision>0),
  base_amount_minor bigint NOT NULL CHECK(base_amount_minor BETWEEN 1 AND 100000000),
  currency text NOT NULL CHECK(currency='usd'),
  demo boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,project_id)
);
CREATE UNIQUE INDEX one_scope_demo ON scope_projects(workspace_id) WHERE demo;
CREATE TABLE scope_messages (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  message_id text NOT NULL,
  text text NOT NULL,
  text_digest text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(workspace_id,message_id),
  UNIQUE(workspace_id,project_id,text_digest),
  FOREIGN KEY(workspace_id,project_id) REFERENCES scope_projects
);
CREATE TABLE scope_analyses (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  analysis_id text NOT NULL,
  brief_revision integer NOT NULL,
  source_digest text NOT NULL,
  mode text NOT NULL CHECK(mode IN ('sample','openai')),
  summary text NOT NULL,
  candidates jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,analysis_id),
  FOREIGN KEY(workspace_id,project_id) REFERENCES scope_projects
);
CREATE TABLE scope_analysis_requests (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  request_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(workspace_id,request_id),
  FOREIGN KEY(workspace_id,project_id) REFERENCES scope_projects
);
CREATE INDEX scope_analysis_rate ON scope_analysis_requests(workspace_id,created_at);
CREATE TABLE scope_proposals (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  proposal_id text NOT NULL,
  title text NOT NULL,
  description text NOT NULL,
  amount_minor bigint NOT NULL CHECK(amount_minor BETWEEN 1 AND 100000000),
  currency text NOT NULL CHECK(currency='usd'),
  version integer NOT NULL DEFAULT 1 CHECK(version>0),
  brief_revision integer NOT NULL,
  status text NOT NULL CHECK(status IN ('draft','shared','accepted','declined','superseded')),
  proposal_digest text NOT NULL,
  evidence jsonb NOT NULL,
  accepted_by text,
  accepted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,proposal_id),
  UNIQUE(workspace_id,project_id,proposal_id),
  FOREIGN KEY(workspace_id,project_id) REFERENCES scope_projects
);
CREATE TABLE scope_shares (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  proposal_id text NOT NULL,
  token_digest text NOT NULL,
  proposal_version integer NOT NULL,
  proposal_digest text NOT NULL,
  proposal_snapshot jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  decision text CHECK(decision IN ('accepted','declined')),
  decision_name text,
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,token_digest),
  FOREIGN KEY(workspace_id,project_id,proposal_id) REFERENCES scope_proposals(workspace_id,project_id,proposal_id)
);
CREATE UNIQUE INDEX one_scope_share ON scope_shares(workspace_id,proposal_id) WHERE revoked_at IS NULL;
-- Global directory contains only a high-entropy capability hash and tenant routing.
-- It grants no project/proposal access. Public requests look up one exact hash,
-- then access the remaining records with ordinary FORCE RLS tenant context.
CREATE TABLE scope_capability_directory (
  token_digest text PRIMARY KEY CHECK(token_digest ~ '^[a-f0-9]{64}$'),
  workspace_id text NOT NULL
);
GRANT SELECT,INSERT ON scope_capability_directory TO console_runtime;
CREATE TABLE scope_invoices (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  invoice_id text NOT NULL,
  proposal_id text NOT NULL,
  proposal_version integer NOT NULL,
  proposal_digest text NOT NULL,
  provider text NOT NULL CHECK(provider IN ('local','paypal_sandbox')),
  provider_connection_digest text,
  provider_invoice_id text,
  status text NOT NULL CHECK(status IN ('draft','creating','unpaid','paid','outcome_unknown','failed')),
  amount_minor bigint NOT NULL CHECK(amount_minor BETWEEN 1 AND 100000000),
  currency text NOT NULL CHECK(currency='usd'),
  payload jsonb NOT NULL,
  payment_url text,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,invoice_id),
  UNIQUE(workspace_id,proposal_id),
  FOREIGN KEY(workspace_id,project_id,proposal_id) REFERENCES scope_proposals(workspace_id,project_id,proposal_id)
);
CREATE TABLE scope_invoice_jobs (
  workspace_id text NOT NULL,
  invoice_id text NOT NULL,
  state text NOT NULL CHECK(state IN ('queued','leased','done','unknown','failed')),
  operation text NOT NULL DEFAULT 'create' CHECK(operation IN ('create','activate')),
  lease_token text,
  lease_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,invoice_id),
  FOREIGN KEY(workspace_id,invoice_id) REFERENCES scope_invoices
);
CREATE TABLE scope_events (
  workspace_id text NOT NULL,
  project_id text NOT NULL,
  event_id text NOT NULL,
  kind text NOT NULL,
  text text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(workspace_id,event_id),
  FOREIGN KEY(workspace_id,project_id) REFERENCES scope_projects
);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['scope_projects','scope_messages','scope_analyses','scope_analysis_requests','scope_proposals','scope_shares','scope_invoices','scope_invoice_jobs','scope_events'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id=current_setting(''app.workspace'',true)) WITH CHECK (workspace_id=current_setting(''app.workspace'',true))',t);
  END LOOP;
END $$;
GRANT SELECT,INSERT,UPDATE ON scope_projects,scope_proposals,scope_invoices,scope_invoice_jobs TO console_runtime;
GRANT SELECT,INSERT ON scope_shares TO console_runtime;
GRANT UPDATE(revoked_at,decision,decision_name,decided_at) ON scope_shares TO console_runtime;
GRANT SELECT,INSERT ON scope_messages,scope_analyses,scope_analysis_requests,scope_events TO console_runtime;
