-- =============================================================
-- 23_temperature_sensitivity.sql
-- How much does each degree of cold raise Finland's electricity use?
--
-- A "hinge" model per day type (weekday / weekend):
--     consumption = base_mw + mw_per_degree * max(balance_point - temp, 0)
-- Above the balance point consumption barely depends on temperature;
-- below it, heating adds a roughly fixed amount per degree. The balance
-- point is not chosen by hand: the line is fitted for every whole degree
-- from 5 to 20 °C and the one with the highest r² is kept.
--
--   mw_per_degree   extra average load for each degree below the
--                   balance point
--   pct_per_degree  the same as a share of the mean consumption
--   base_mw         consumption at or above the balance point
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: generate_series as a parameter grid, regr_slope /
--             regr_intercept / regr_r2, DISTINCT ON to pick the best fit
-- =============================================================

WITH city_days AS (
    SELECT dataset_id, (start_time AT TIME ZONE 'Europe/Helsinki')::date AS day_fi, AVG(value) AS temp_c
    FROM fingrid_observation
    WHERE dataset_id IN (178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY dataset_id, day_fi
    HAVING COUNT(*) >= 400
),
days AS (
    SELECT t.day_fi, t.temp_c, c.consumption_mw,
           CASE WHEN EXTRACT(ISODOW FROM t.day_fi) >= 6 THEN 'weekend' ELSE 'weekday' END AS day_type
    FROM (SELECT day_fi, AVG(temp_c) AS temp_c FROM city_days GROUP BY day_fi HAVING COUNT(*) = 4) t
    JOIN (SELECT (start_time AT TIME ZONE 'Europe/Helsinki')::date AS day_fi, AVG(value) AS consumption_mw
          FROM fingrid_observation
          WHERE dataset_id = 124 AND start_time >= %(start)s AND start_time < %(end)s
          GROUP BY 1 HAVING COUNT(*) >= 92) c USING (day_fi)
),
fits AS (
    SELECT day_type,
           bp                                                        AS balance_point_c,
           regr_slope(consumption_mw, GREATEST(bp - temp_c, 0))      AS mw_per_degree,
           regr_intercept(consumption_mw, GREATEST(bp - temp_c, 0))  AS base_mw,
           regr_r2(consumption_mw, GREATEST(bp - temp_c, 0))         AS r2,
           COUNT(*)                                                  AS days,
           AVG(consumption_mw)                                       AS mean_consumption_mw,
           MIN(temp_c)                                               AS coldest_c,
           MAX(temp_c)                                               AS warmest_c
    FROM days CROSS JOIN generate_series(5, 20) AS bp
    GROUP BY day_type, bp
)
SELECT DISTINCT ON (day_type)
       day_type, balance_point_c, mw_per_degree,
       100 * mw_per_degree / mean_consumption_mw AS pct_per_degree,
       base_mw, r2, days, mean_consumption_mw, coldest_c, warmest_c
FROM fits
WHERE mw_per_degree IS NOT NULL
ORDER BY day_type, r2 DESC;
