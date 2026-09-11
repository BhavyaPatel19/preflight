-- Preflight — initial schema.
--
-- One datastore holds both the vectors and the operational metadata, so a
-- retrieval query can filter on "this airport, in force at this instant" in the
-- same statement that ranks by similarity. That is the whole argument for
-- pgvector over a dedicated vector service here; see docs/adr/0001.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------- gazetteer

CREATE TABLE IF NOT EXISTS airports (
    icao        CHAR(4) PRIMARY KEY,
    iata        CHAR(3),
    name        TEXT NOT NULL,
    country     CHAR(2),
    elevation_ft INTEGER,
    lat         DOUBLE PRECISION,
    lon         DOUBLE PRECISION,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runways (
    id          BIGSERIAL PRIMARY KEY,
    icao        CHAR(4) NOT NULL REFERENCES airports(icao) ON DELETE CASCADE,
    ident       TEXT NOT NULL,              -- '28R'
    length_ft   INTEGER,
    width_ft    INTEGER,
    surface     TEXT,
    lighted     BOOLEAN,
    UNIQUE (icao, ident)
);

-- ---------------------------------------------------------------- NOTAMs

CREATE TABLE IF NOT EXISTS notams (
    id              TEXT PRIMARY KEY,
    icao            CHAR(4),
    fir             CHAR(4),
    kind            TEXT NOT NULL DEFAULT 'NEW',
    replaces        TEXT,

    effective_from  TIMESTAMPTZ,
    effective_to    TIMESTAMPTZ,
    permanent       BOOLEAN NOT NULL DEFAULT FALSE,
    estimated_end   BOOLEAN NOT NULL DEFAULT FALSE,

    qcode           CHAR(5),
    qcode_text      TEXT,
    scope           TEXT,
    lower_fl        INTEGER,
    upper_fl        INTEGER,
    radius_nm       INTEGER,

    raw             TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    body_expanded   TEXT NOT NULL DEFAULT '',

    hazard_class    TEXT NOT NULL DEFAULT 'other',
    severity        TEXT NOT NULL DEFAULT 'INFO',
    phases          TEXT[] NOT NULL DEFAULT '{}',

    -- Which layer produced this parse, and how much it trusts itself. Kept on
    -- the row so the extraction eval can slice quality by decoder.
    decoder             TEXT NOT NULL DEFAULT 'rules',
    decode_confidence   REAL NOT NULL DEFAULT 0,

    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding       vector(1024),

    -- Generated so it can never drift from the text it indexes.
    search_tsv      tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(body_expanded, '') || ' ' || coalesce(body, ''))
                    ) STORED
);

-- The hot query: "everything in force at KSFO during this window".
CREATE INDEX IF NOT EXISTS notams_icao_window_idx
    ON notams (icao, effective_from, effective_to);
CREATE INDEX IF NOT EXISTS notams_severity_idx ON notams (severity, hazard_class);
CREATE INDEX IF NOT EXISTS notams_search_idx   ON notams USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS notams_embedding_idx
    ON notams USING hnsw (embedding vector_cosine_ops);

-- Escalation queue for Sprint 2: what the rule layer could not parse well.
CREATE INDEX IF NOT EXISTS notams_low_confidence_idx
    ON notams (decode_confidence) WHERE decode_confidence < 0.6;

CREATE TABLE IF NOT EXISTS notam_entities (
    id          BIGSERIAL PRIMARY KEY,
    notam_id    TEXT NOT NULL REFERENCES notams(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    ref         TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'UNKNOWN',
    cause       TEXT,
    detail      TEXT,
    span_start  INTEGER,
    span_end    INTEGER
);

CREATE INDEX IF NOT EXISTS notam_entities_notam_idx ON notam_entities (notam_id);
CREATE INDEX IF NOT EXISTS notam_entities_lookup_idx ON notam_entities (type, ref, state);

-- ---------------------------------------------------------------- weather

CREATE TABLE IF NOT EXISTS weather_reports (
    id          BIGSERIAL PRIMARY KEY,
    icao        CHAR(4) NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('METAR', 'TAF', 'PIREP', 'SIGMET', 'AIRMET')),
    issued_at   TIMESTAMPTZ NOT NULL,
    valid_from  TIMESTAMPTZ,
    valid_to    TIMESTAMPTZ,
    raw         TEXT NOT NULL,
    parsed      JSONB,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (icao, kind, issued_at)
);

CREATE INDEX IF NOT EXISTS weather_lookup_idx ON weather_reports (icao, kind, issued_at DESC);

-- ---------------------------------------------------------------- corpus

-- ASRS narratives, NTSB findings, FAR/AIM sections — the precedent corpus.
CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('asrs', 'ntsb', 'far_aim', 'ops_note')),
    external_id TEXT NOT NULL,
    title       TEXT,
    published   DATE,
    icao        CHAR(4),
    metadata    JSONB NOT NULL DEFAULT '{}',
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    icao        CHAR(4),
    phases      TEXT[] NOT NULL DEFAULT '{}',
    embedding   vector(1024),
    search_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_search_idx    ON chunks USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_filter_idx    ON chunks (icao);

-- ---------------------------------------------------------------- evaluation

-- The time-travel golden set. `snapshot_at` is what makes a case reproducible:
-- retrieval is replayed against only the records in force at that instant.
CREATE TABLE IF NOT EXISTS eval_cases (
    id              BIGSERIAL PRIMARY KEY,
    label           TEXT NOT NULL CHECK (label IN ('positive', 'negative')),
    source_ref      TEXT,                   -- NTSB/ASRS record this was built from
    departure       CHAR(4) NOT NULL,
    destination     CHAR(4),
    aircraft_type   TEXT,
    snapshot_at     TIMESTAMPTZ NOT NULL,
    implicated_hazard JSONB,                -- NULL for negatives
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id          BIGSERIAL PRIMARY KEY,
    git_sha     TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    metrics     JSONB NOT NULL DEFAULT '{}',
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id     BIGINT NOT NULL REFERENCES eval_cases(id) ON DELETE CASCADE,
    hazard_found BOOLEAN,
    hazard_rank  INTEGER,
    grounded     BOOLEAN,
    abstained    BOOLEAN,
    cost_usd     NUMERIC(10, 6),
    latency_ms   INTEGER,
    detail       JSONB NOT NULL DEFAULT '{}',
    UNIQUE (run_id, case_id)
);
