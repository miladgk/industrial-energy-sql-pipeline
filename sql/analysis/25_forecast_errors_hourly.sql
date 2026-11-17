-- =============================================================
-- 25_forecast_errors_hourly.sql
-- Fingrid's day-ahead forecasts next to what happened, per hour:
-- the input of the uncertainty ranges in src/forecast_ranges.py.
--
--   variable      'wind'        day-ahead forecast 246, actual 75
--                 'consumption' day-ahead forecast 165, actual 124
--   forecast_mw   mean of the four quarter-hour forecasts
--   actual_mw     mean of the four measured quarters; NULL for hours
--                 that have not happened yet (tomorrow), so the same
--                 query returns the history and the day to forecast
--   day_fi, hour_fi   Finnish calendar day and hour
--
-- The day-ahead forecasts are stored once, before their day starts
-- (fingrid_catalog.STORE_FUTURE), so every row is the forecast as
-- it stood when it was issued: no later revision leaks in.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: FILTER pivot, LEFT JOIN for the future, AT TIME ZONE
-- =============================================================

WITH hourly AS (
    SELECT dataset_id,
           date_trunc('hour', start_time) AS hour_start,
           AVG(value)                     AS value
    FROM fingrid_observation
    WHERE dataset_id IN (75, 124, 165, 246)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY dataset_id, hour_start
    HAVING COUNT(*) = 4
),
pairs AS (
    SELECT f.hour_start, v.variable, f.value AS forecast_mw, a.value AS actual_mw
    FROM (VALUES ('wind', 246, 75), ('consumption', 165, 124)) AS v (variable, forecast_id, actual_id)
    JOIN hourly f ON f.dataset_id = v.forecast_id
    LEFT JOIN hourly a ON a.dataset_id = v.actual_id AND a.hour_start = f.hour_start
)
SELECT variable,
       hour_start,
       (hour_start AT TIME ZONE 'Europe/Helsinki')::date          AS day_fi,
       EXTRACT(HOUR FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS hour_fi,
       forecast_mw,
       actual_mw
FROM pairs
ORDER BY variable, hour_start;
