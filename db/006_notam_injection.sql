-- Injection-detector verdict, recorded at ingest so suspicious NOTAM text is
-- marked before any model sees it (see src/preflight/safety).
ALTER TABLE notams ADD COLUMN IF NOT EXISTS injection_score REAL;
CREATE INDEX IF NOT EXISTS notams_suspicious_idx ON notams (injection_score) WHERE injection_score >= 0.5;
