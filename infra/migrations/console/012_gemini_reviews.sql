-- Preserve actual provider attribution for reviews; existing history stays intact.
ALTER TABLE scope_analyses DROP CONSTRAINT scope_analyses_mode_check;
ALTER TABLE scope_analyses ADD CONSTRAINT scope_analyses_mode_check
  CHECK(mode IN ('sample','openai','gemini'));
