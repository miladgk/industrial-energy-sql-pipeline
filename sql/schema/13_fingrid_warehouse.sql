-- =============================================================
-- 13_fingrid_warehouse.sql
-- Raw Fingrid Open Data, one row per dataset and time slot, exactly as
-- the API publishes it (no resampling, no gap filling, no clamping).
--
--   fingrid_dataset      what each dataset is (filled by src/fingrid_catalog.py)
--   fingrid_observation  the values; loaded by src/sync_fingrid.py
--   forecast_vs_actual   Fingrid's own forecasts joined to what happened
--
-- Idempotent: safe to run on every setup.
-- =============================================================

CREATE TABLE IF NOT EXISTS fingrid_dataset (
    dataset_id  INTEGER PRIMARY KEY,
    key         VARCHAR(60) NOT NULL UNIQUE,
    name        TEXT        NOT NULL,
    unit        VARCHAR(20) NOT NULL,
    kind        VARCHAR(20) NOT NULL,
    resolution  INTERVAL    NOT NULL
);
-- (Re)defined separately so an existing table picks up new kinds.
ALTER TABLE fingrid_dataset DROP CONSTRAINT IF EXISTS fingrid_dataset_kind_check;
ALTER TABLE fingrid_dataset ADD CONSTRAINT fingrid_dataset_kind_check
    CHECK (kind IN ('actual', 'forecast', 'capacity', 'balancing', 'emission', 'system', 'weather'));

-- Partitioned by month on start_time. Every query here filters one dataset and a
-- time range, so PostgreSQL reads only the months it needs (partition pruning) and,
-- inside each, the primary-key index (dataset_id, start_time).
-- benchmarks/index_benchmark.md measures the effect (scripts/benchmark_warehouse.py).
--
-- A database created before partitioning has a plain table: it is converted in
-- place (rows copied into monthly partitions). Views on the table are dropped first
-- and recreated below and in 14_co2_forecast.sql.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'fingrid_observation' AND relkind = 'r') THEN
        DROP VIEW IF EXISTS forecast_vs_actual;
        DROP VIEW IF EXISTS co2_hourly;
        ALTER TABLE fingrid_observation RENAME TO fingrid_observation_unpartitioned;
        ALTER TABLE fingrid_observation_unpartitioned RENAME CONSTRAINT fingrid_observation_pkey TO fingrid_observation_unpartitioned_pkey;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS fingrid_observation (
    dataset_id  INTEGER          NOT NULL REFERENCES fingrid_dataset (dataset_id),
    start_time  TIMESTAMPTZ      NOT NULL,
    end_time    TIMESTAMPTZ      NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    fetched_at  TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, start_time),
    CONSTRAINT ck_fingrid_observation_slot CHECK (end_time > start_time)
) PARTITION BY RANGE (start_time);

-- Safety net for a row outside every monthly partition. It stays empty, because
-- the sync and the snapshot restore create the months they write first.
CREATE TABLE IF NOT EXISTS fingrid_observation_default PARTITION OF fingrid_observation DEFAULT;

-- Create the monthly partitions (UTC months) covering [first_day, last_day]; existing
-- ones are left alone. Returns how many were created.
CREATE OR REPLACE FUNCTION ensure_fingrid_partitions(first_day date, last_day date)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE
    m       date;
    created int := 0;
BEGIN
    FOR m IN SELECT generate_series(date_trunc('month', first_day), date_trunc('month', last_day),
                                    interval '1 month')::date
    LOOP
        IF to_regclass(format('fingrid_observation_%s', to_char(m, 'YYYY_MM'))) IS NULL THEN
            EXECUTE format('CREATE TABLE %I PARTITION OF fingrid_observation FOR VALUES FROM (%L) TO (%L)',
                           format('fingrid_observation_%s', to_char(m, 'YYYY_MM')),
                           (m::timestamp AT TIME ZONE 'UTC'),
                           ((m + interval '1 month')::timestamp AT TIME ZONE 'UTC'));
            created := created + 1;
        END IF;
    END LOOP;
    RETURN created;
END $$;

SELECT ensure_fingrid_partitions((now() - interval '450 days')::date, (now() + interval '60 days')::date);

DO $$
DECLARE lo date; hi date;
BEGIN
    IF to_regclass('fingrid_observation_unpartitioned') IS NOT NULL THEN
        SELECT min(start_time)::date, max(start_time)::date INTO lo, hi FROM fingrid_observation_unpartitioned;
        IF lo IS NOT NULL THEN
            PERFORM ensure_fingrid_partitions(lo, hi);
        END IF;
        INSERT INTO fingrid_observation SELECT * FROM fingrid_observation_unpartitioned;
        DROP TABLE fingrid_observation_unpartitioned;
    END IF;
END $$;

-- One row per 15-minute slot where both the actual value and a Fingrid forecast exist.
--   day_ahead: published once, the previous day at 12:00 Finnish time (datasets 246, 165)
--   intraday:  updated every 15 minutes; the stored value is the last update before
--              the slot (datasets 245, 166)
-- capacity_mw is the wind capacity Fingrid itself used for the forecast (dataset 268,
-- hourly), so wind errors can be expressed as a share of the fleet.
CREATE OR REPLACE VIEW forecast_vs_actual AS
WITH pairs (variable, product, actual_id, forecast_id) AS (
    VALUES ('wind',        'day_ahead', 75,  246),
           ('wind',        'intraday',  75,  245),
           ('consumption', 'day_ahead', 124, 165),
           ('consumption', 'intraday',  124, 166)
)
SELECT p.variable,
       p.product,
       a.start_time,
       a.value           AS actual_mw,
       f.value           AS forecast_mw,
       a.value - f.value AS error_mw,          -- positive: more than forecast
       c.value           AS capacity_mw        -- wind only, else NULL
FROM pairs p
JOIN fingrid_observation a
  ON a.dataset_id = p.actual_id
JOIN fingrid_observation f
  ON f.dataset_id = p.forecast_id
 AND f.start_time = a.start_time
LEFT JOIN fingrid_observation c
  ON p.variable = 'wind'
 AND c.dataset_id = 268
 AND c.start_time = date_trunc('hour', a.start_time);
