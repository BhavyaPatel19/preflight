-- Hourly arrival-delay aggregates per airport, from BTS On-Time Performance.
-- hour_local is the scheduled-arrival hour in the airport's local time (BTS
-- reports local times). One row per (airport, local hour).

CREATE TABLE IF NOT EXISTS delay_hourly (
    icao            CHAR(4) NOT NULL,
    hour_local      TIMESTAMP NOT NULL,
    flights         INTEGER NOT NULL,
    cancelled       INTEGER NOT NULL DEFAULT 0,
    diverted        INTEGER NOT NULL DEFAULT 0,
    mean_arr_delay  REAL,               -- minutes, over flights that arrived
    p90_arr_delay   REAL,
    PRIMARY KEY (icao, hour_local)
);

CREATE INDEX IF NOT EXISTS delay_hourly_icao_idx ON delay_hourly (icao, hour_local DESC);
