ALTER TABLE connections DROP CONSTRAINT connections_environment_check;
ALTER TABLE connections DROP CONSTRAINT connections_api_version_check;
ALTER TABLE connections ADD COLUMN provider text NOT NULL DEFAULT 'simulator';
ALTER TABLE connections ADD CONSTRAINT connection_provider_scope CHECK (
    (provider='simulator' AND environment='simulated' AND api_version='simulator.v1') OR
    (provider='stripe' AND environment='test' AND api_version='2026-09-30.endive')
);
ALTER TABLE observations DROP CONSTRAINT observations_source_check;
ALTER TABLE observations ADD CONSTRAINT observations_source_check
CHECK(source IN ('simulator_api_and_target','stripe_api_and_target'));
GRANT INSERT ON connections TO console_runtime;
