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
    kind        VARCHAR(20) NOT NULL
                CHECK (kind IN ('actual', 'forecast', 'capacity', 'balancing', 'emission', 'system')),
    resolution  INTERVAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS fingrid_observation (
    dataset_id  INTEGER          NOT NULL REFERENCES fingrid_dataset (dataset_id),
    start_time  TIMESTAMPTZ      NOT NULL,
    end_time    TIMESTAMPTZ      NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    fetched_at  TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, start_time),
    CONSTRAINT ck_fingrid_observation_slot CHECK (end_time > start_time)
);

-- The primary key (dataset_id, start_time) already serves every query here:
-- all of them filter on one dataset and a time range.

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
