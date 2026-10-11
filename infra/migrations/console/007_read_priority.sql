-- Distinguish new evidence hints/deadlines from independent inventory sweeps.
-- Existing queued work remains background; new explicit requests promote it.
ALTER TABLE jobs ADD COLUMN foreground boolean NOT NULL DEFAULT false;
CREATE INDEX priority_due_jobs ON jobs(workspace_id,foreground,due_at,created_at)
WHERE state IN ('queued','retry_wait','leased');
