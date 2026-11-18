-- =============================================================
-- 31_consumption_boilers_hourly.sql
-- One row per UTC hour: consumption, the part of it that electric
-- boilers use, and temperature: the input of "do electric cars show
-- up in Finland's consumption?" (src/ev_charging.py).
--
--   consumption_mw   dataset 124 (15 min)
--   boilers_mw       dataset 371, measured consumption of electric
--                    boilers (1 min, published since 4 December
--                    2024); NULL unless 45 minutes of the hour are
--                    covered
--   temp_c           mean of Helsinki, Jyväskylä, Oulu, Rovaniemi
--                    (178, 182, 196, 185), all four present
--
-- Hourly means are weighted by how long each slot lasts, as in
-- sql/analysis/29, so 1-minute, 3-minute and 15-minute data mix.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: duration-weighted aggregation, FILTER pivot
-- =============================================================

WITH obs AS (
    SELECT dataset_id,
           date_trunc('hour', start_time) AS hour_start,
           value,
           EXTRACT(EPOCH FROM LEAST(end_time, date_trunc('hour', start_time) + interval '1 hour') - start_time) AS secs
    FROM fingrid_observation
    WHERE dataset_id IN (124, 371, 178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
),
hourly AS (
    SELECT dataset_id, hour_start, SUM(value * secs) / SUM(secs) AS value
    FROM obs
    GROUP BY dataset_id, hour_start
    HAVING SUM(secs) >= 2700
),
wide AS (
    SELECT hour_start,
           MAX(value) FILTER (WHERE dataset_id = 124) AS consumption_mw,
           MAX(value) FILTER (WHERE dataset_id = 371) AS boilers_mw,
           AVG(value) FILTER (WHERE dataset_id IN (178, 182, 196, 185)) AS temp_c,
           COUNT(*)   FILTER (WHERE dataset_id IN (178, 182, 196, 185)) AS cities
    FROM hourly
    GROUP BY hour_start
)
SELECT hour_start,
       (hour_start AT TIME ZONE 'Europe/Helsinki')::date AS day_fi,
       EXTRACT(HOUR FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS hour_fi,
       consumption_mw,
       boilers_mw,
       temp_c
FROM wide
WHERE consumption_mw IS NOT NULL AND cities = 4
ORDER BY hour_start;
