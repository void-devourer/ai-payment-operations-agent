ALTER TABLE sessions ADD COLUMN authenticated_at timestamptz NOT NULL DEFAULT now();
GRANT UPDATE (expires_at, csrf_digest, authenticated_at) ON sessions TO console_runtime;
