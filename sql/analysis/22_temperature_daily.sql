-- =============================================================
-- 22_temperature_daily.sql
-- One row per Finnish calendar day: the mean temperature of four
-- cities across the country and the mean electricity consumption.
--
--   temp_c        average of the daily means of Helsinki (178),
--                 Jyväskylä (182), Oulu (196) and Rovaniemi (185),
--                 3-minute readings; a day needs all four cities with
--                 at least 400 of their 480 readings
--   consumption_mw mean of dataset 124 (at least 92 of 96 quarters)
--   weekend       Saturday or Sunday (public holidays are not removed)
--
-- An unweighted four-city mean, south to north; Helsinki alone fits
-- the consumption about as well (r² 0.880 vs 0.876 on weekdays).
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: two-level aggregation, FILTER, HAVING, ISODOW
-- =============================================================

WITH city_days AS (
    SELECT dataset_id,
           (start_time AT TIME ZONE 'Europe/Helsinki')::date  AS day_fi,
           AVG(value)                                        AS temp_c
    FROM fingrid_observation
    WHERE dataset_id IN (178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY dataset_id, day_fi
    HAVING COUNT(*) >= 400
),
temperature AS (
    SELECT day_fi, AVG(temp_c) AS temp_c
    FROM city_days
    GROUP BY day_fi
    HAVING COUNT(*) = 4
),
consumption AS (
    SELECT (start_time AT TIME ZONE 'Europe/Helsinki')::date AS day_fi,
           AVG(value)                                       AS consumption_mw
    FROM fingrid_observation
    WHERE dataset_id = 124
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY day_fi
    HAVING COUNT(*) >= 92
)
SELECT t.day_fi,
       t.temp_c,
       c.consumption_mw,
       EXTRACT(ISODOW FROM t.day_fi) >= 6 AS weekend
FROM temperature t
JOIN consumption c USING (day_fi)
ORDER BY t.day_fi;
