-- Restore operators pause new remote effects before starting restored services.
-- This installation-wide switch contains no tenant data; runtime can only read it.
CREATE TABLE execution_control (
    singleton boolean PRIMARY KEY CHECK (singleton),
    enabled boolean NOT NULL DEFAULT true,
    reason text NOT NULL DEFAULT 'Normal local simulator operation'
);
INSERT INTO execution_control(singleton) VALUES (true);
REVOKE ALL ON execution_control FROM PUBLIC;
GRANT SELECT ON execution_control TO console_runtime;
