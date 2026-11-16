-- =============================================================
-- 18_co2_forecast.sql
-- Hour-by-hour CO2 intensity forecast for one Finnish calendar day,
-- from co2_forecast() in sql/schema/14_co2_forecast.sql.
--
--   co2_forecast      predicted gCO2/kWh of electricity consumed
--   mean_next_3h_g    average of this hour and the next two, to find
--                     the cleanest 3-hour window (e.g. for charging)
--   rank_cleanest     1 = the hour expected to be cleanest (ordered by
--                     the unclamped line, so hours on the floor still
--                     have an order)
--
-- Parameter: day (date, Finnish calendar day)
-- Techniques: set-returning function, window frames (ROWS BETWEEN),
--             RANK()
-- =============================================================

SELECT
    day_fi,
    hour_start,
    hour_fi,
    residual_load_mw,
    co2_forecast,
    co2_unclamped,
    co2_naive,
    co2_actual,
    CASE WHEN COUNT(*) OVER w3 = 3 THEN AVG(co2_forecast) OVER w3 END  AS mean_next_3h_g,
    CASE WHEN COUNT(*) OVER w3 = 3 THEN AVG(co2_unclamped) OVER w3 END AS mean_next_3h_unclamped,
    RANK() OVER (ORDER BY co2_unclamped)                               AS rank_cleanest
FROM co2_forecast(%(day)s::date, %(day)s::date + 1)
WINDOW w3 AS (ORDER BY hour_start ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING)
ORDER BY hour_start;
