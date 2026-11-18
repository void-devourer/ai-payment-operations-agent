ALTER TABLE connections DROP CONSTRAINT connection_provider_scope;
ALTER TABLE connections ADD CONSTRAINT connection_provider_scope CHECK (
    (provider='simulator' AND environment='simulated' AND api_version='simulator.v1') OR
    (provider='stripe' AND environment='test' AND api_version='2026-09-30.endive') OR
    (provider='paypal' AND environment='test' AND api_version='paypal_orders_v2_payments_v2')
);
ALTER TABLE purchases ADD CONSTRAINT purchase_connection_identity UNIQUE(workspace_id,purchase_id,connection_id);
CREATE TABLE paypal_orders (
    workspace_id text NOT NULL,
    purchase_id text NOT NULL,
    connection_id text NOT NULL,
    order_id text NOT NULL CHECK(order_id ~ '^[A-Z0-9]{8,32}$'),
    PRIMARY KEY(workspace_id,connection_id,order_id),
    FOREIGN KEY(workspace_id,purchase_id,connection_id) REFERENCES purchases(workspace_id,purchase_id,connection_id)
);
CREATE TABLE paypal_captures (
    workspace_id text NOT NULL,
    connection_id text NOT NULL,
    order_id text NOT NULL,
    capture_id text NOT NULL CHECK(capture_id ~ '^[A-Z0-9]{8,32}$'),
    PRIMARY KEY(workspace_id,connection_id,capture_id),
    FOREIGN KEY(workspace_id,connection_id,order_id) REFERENCES paypal_orders(workspace_id,connection_id,order_id)
);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['paypal_orders','paypal_captures'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY workspace_scope ON %I USING (workspace_id=current_setting(''app.workspace'',true))',t);
  END LOOP;
END $$;
GRANT SELECT,INSERT ON paypal_orders,paypal_captures TO console_runtime;
ALTER TABLE jobs ALTER COLUMN payment_intent_id DROP NOT NULL;
ALTER TABLE jobs ADD COLUMN purchase_id text;
ALTER TABLE jobs ADD CONSTRAINT job_subject CHECK (
    (payment_intent_id IS NOT NULL AND purchase_id IS NULL) OR
    (payment_intent_id IS NULL AND purchase_id IS NOT NULL)
);
ALTER TABLE jobs ADD FOREIGN KEY(workspace_id,purchase_id,connection_id)
    REFERENCES purchases(workspace_id,purchase_id,connection_id);
CREATE UNIQUE INDEX one_active_purchase_read ON jobs(workspace_id,connection_id,purchase_id)
WHERE state IN ('queued','leased','retry_wait');
ALTER TABLE inbox ADD COLUMN resource_type text CHECK(resource_type IN ('order','capture','refund','dispute'));
ALTER TABLE inbox ADD COLUMN resource_id text;
ALTER TABLE observations DROP CONSTRAINT observations_source_check;
ALTER TABLE observations ADD CONSTRAINT observations_source_check
CHECK(source IN ('simulator_api_and_target','stripe_api_and_target','paypal_api_and_target'));
