-- One row per scheduled or manual ingest run. "When did we last successfully
-- fetch X?" is the first question in any data incident, and the time-travel
-- eval needs to know which snapshots exist.

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,              -- 'weather' | 'notams'
    source      TEXT NOT NULL,              -- 'aviationweather' | 'file:x' | 'nasa-dip'
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'skipped', 'error')),
    counts      JSONB NOT NULL DEFAULT '{}',
    error       TEXT
);

CREATE INDEX IF NOT EXISTS ingest_runs_kind_idx ON ingest_runs (kind, started_at DESC);
