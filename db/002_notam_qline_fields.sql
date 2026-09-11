-- Q-line traffic/purpose and the D) schedule were parsed but never stored;
-- the round-trip test caught it. `purpose` matters: ICAO 'B' means
-- "operationally significant, include in briefing".

ALTER TABLE notams
    ADD COLUMN IF NOT EXISTS traffic  TEXT,
    ADD COLUMN IF NOT EXISTS purpose  TEXT,
    ADD COLUMN IF NOT EXISTS schedule TEXT;
