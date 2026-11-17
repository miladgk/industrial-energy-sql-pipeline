-- =============================================================
-- 24_wind_allocation_panel.sql
-- One row per UTC hour: Finland's power balance split into its
-- parts, the input of the "where does an extra MW of wind go?"
-- regression in src/wind_allocation.py.
--
--   consumption_mw   dataset 124, 4 quarters per hour
--   wind_mw          dataset 75, 4 quarters
--   nuclear_mw       dataset 188, 3-minute readings (>= 16 of 20)
--   hydro_mw         dataset 191, 3-minute readings (>= 16 of 20)
--   other_mw         production (74) - wind - nuclear - hydro:
--                    CHP, condensing power, solar, batteries, ...
--   net_import_mw    consumption - production, which is how Fingrid
--                    defines consumption (124 = production + import
--                    - export)
--   net_import_measured_mw
--                    -1 x dataset 194, the measured net export, as an
--                    independent check of net_import_mw
--   battery_mw       dataset 398, battery discharge (>= 16 of 20)
--   temp_c           mean of Helsinki, Jyväskylä, Oulu, Rovaniemi
--                    (178, 182, 196, 185), all four cities present
--   hour_fi, isodow_fi, month_fi   Finnish local calendar, for the
--                    hour-of-day, weekday and month fixed effects
--
-- By construction consumption = wind + nuclear + hydro + other
-- + net_import, so the four responses to +1 MW of wind add up to
-- 1 MW: whatever wind does not push out of imports, hydro or other
-- production must show up as extra consumption.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: FILTER pivot, HAVING completeness rules, AT TIME ZONE
-- =============================================================

WITH hourly AS (
    SELECT dataset_id,
           date_trunc('hour', start_time) AS hour_start,
           AVG(value)                     AS value,
           COUNT(*)                       AS n
    FROM fingrid_observation
    WHERE dataset_id IN (74, 75, 124, 188, 191, 194, 398, 178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY dataset_id, hour_start
    HAVING COUNT(*) >= CASE WHEN dataset_id IN (74, 75, 124) THEN 4 ELSE 16 END
),
wide AS (
    SELECT hour_start,
           MAX(value) FILTER (WHERE dataset_id = 124) AS consumption_mw,
           MAX(value) FILTER (WHERE dataset_id = 74)  AS production_mw,
           MAX(value) FILTER (WHERE dataset_id = 75)  AS wind_mw,
           MAX(value) FILTER (WHERE dataset_id = 188) AS nuclear_mw,
           MAX(value) FILTER (WHERE dataset_id = 191) AS hydro_mw,
           -MAX(value) FILTER (WHERE dataset_id = 194) AS net_import_measured_mw,
           MAX(value) FILTER (WHERE dataset_id = 398) AS battery_mw,
           AVG(value) FILTER (WHERE dataset_id IN (178, 182, 196, 185)) AS temp_c,
           COUNT(*)   FILTER (WHERE dataset_id IN (178, 182, 196, 185)) AS cities
    FROM hourly
    GROUP BY hour_start
)
SELECT hour_start,
       EXTRACT(HOUR   FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS hour_fi,
       EXTRACT(ISODOW FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS isodow_fi,
       EXTRACT(MONTH  FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS month_fi,
       consumption_mw,
       wind_mw,
       nuclear_mw,
       hydro_mw,
       production_mw - wind_mw - nuclear_mw - hydro_mw AS other_mw,
       consumption_mw - production_mw                  AS net_import_mw,
       net_import_measured_mw,
       battery_mw,
       temp_c
FROM wide
WHERE consumption_mw IS NOT NULL AND production_mw IS NOT NULL
  AND wind_mw IS NOT NULL AND nuclear_mw IS NOT NULL AND hydro_mw IS NOT NULL
  AND cities = 4
ORDER BY hour_start;
