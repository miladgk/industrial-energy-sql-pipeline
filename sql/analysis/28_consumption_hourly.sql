-- =============================================================
-- 28_consumption_hourly.sql
-- One row per UTC hour: Finland's consumption and the measured
-- temperature, the input of the counterfactual "what would Finland
-- have used without the strike?" (src/strike_effect.py).
--
--   consumption_mw   dataset 124, all 4 quarters of the hour
--   temp_c           mean of Helsinki, Jyväskylä, Oulu, Rovaniemi
--                    (178, 182, 196, 185), each with >= 16 of its
--                    20 three-minute readings
--   day_fi, hour_fi  Finnish calendar day and hour
--
-- Measured (not forecast) temperatures: this looks back at events
-- that are over, so the weather that happened is the right control.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: FILTER pivot, HAVING completeness rules, AT TIME ZONE
-- =============================================================

WITH hourly AS (
    SELECT dataset_id,
           date_trunc('hour', start_time) AS hour_start,
           AVG(value)                     AS value
    FROM fingrid_observation
    WHERE dataset_id IN (124, 178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY dataset_id, hour_start
    HAVING COUNT(*) >= CASE WHEN dataset_id = 124 THEN 4 ELSE 16 END
),
wide AS (
    SELECT hour_start,
           MAX(value) FILTER (WHERE dataset_id = 124)                     AS consumption_mw,
           AVG(value) FILTER (WHERE dataset_id IN (178, 182, 196, 185))   AS temp_c,
           COUNT(*)   FILTER (WHERE dataset_id IN (178, 182, 196, 185))   AS cities
    FROM hourly
    GROUP BY hour_start
)
SELECT hour_start,
       (hour_start AT TIME ZONE 'Europe/Helsinki')::date                  AS day_fi,
       EXTRACT(HOUR FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int  AS hour_fi,
       consumption_mw,
       temp_c
FROM wide
WHERE consumption_mw IS NOT NULL AND cities = 4
ORDER BY hour_start;
