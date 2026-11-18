-- =============================================================
-- 29_price_wind_panel.sql
-- One row per UTC hour: Finland's day-ahead price, its neighbours'
-- prices and what the auction knew the day before, the input of
-- "does wind make electricity cheaper?" (src/price_wind.py).
--
--   price_fi, price_se1, price_se3, price_ee, price_no4
--                    day-ahead price (EUR/MWh, ENTSO-E, table
--                    entsoe_price), the time-weighted mean of the
--                    hour's slots: one hourly price until September
--                    2025, four 15-minute prices since
--   wind_fc_mw       Fingrid's day-ahead wind forecast (246), made
--                    before the auction closes, so it is what bidders
--                    could know (hourly until spring 2024, 15 min since)
--   consumption_fc_mw  Fingrid's day-ahead consumption forecast (165)
--   wind_mw          measured wind production (75)
--   nuclear_mw       measured nuclear production (188)
--   temp_c           mean of Helsinki, Jyväskylä, Oulu, Rovaniemi
--                    (178, 182, 196, 185), all four present
--   hour_fi, isodow_fi, month_fi, year_fi, day_fi
--                    the Finnish local calendar
--
-- Every series is averaged over the hour weighted by how long each
-- slot lasts, so hourly and 15-minute data mix correctly; an hour
-- counts only if its slots cover at least 45 minutes (prices: all 60).
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: duration-weighted aggregation, FILTER pivot, UNION ALL
-- of two sources, AT TIME ZONE
-- =============================================================

WITH obs AS (
    SELECT dataset_id::text AS series,
           date_trunc('hour', start_time) AS hour_start,
           value,
           EXTRACT(EPOCH FROM LEAST(end_time, date_trunc('hour', start_time) + interval '1 hour') - start_time) AS secs
    FROM fingrid_observation
    WHERE dataset_id IN (246, 165, 75, 188, 178, 182, 196, 185)
      AND start_time >= %(start)s AND start_time < %(end)s
    UNION ALL
    SELECT 'price_' || lower(area),
           date_trunc('hour', start_time),
           eur_mwh,
           EXTRACT(EPOCH FROM LEAST(end_time, date_trunc('hour', start_time) + interval '1 hour') - start_time)
    FROM entsoe_price
    WHERE start_time >= %(start)s AND start_time < %(end)s
),
hourly AS (
    SELECT series, hour_start, SUM(value * secs) / SUM(secs) AS value
    FROM obs
    GROUP BY series, hour_start
    HAVING SUM(secs) >= CASE WHEN series LIKE 'price%%' THEN 3600 ELSE 2700 END
),
wide AS (
    SELECT hour_start,
           MAX(value) FILTER (WHERE series = 'price_fi')  AS price_fi,
           MAX(value) FILTER (WHERE series = 'price_se1') AS price_se1,
           MAX(value) FILTER (WHERE series = 'price_se3') AS price_se3,
           MAX(value) FILTER (WHERE series = 'price_ee')  AS price_ee,
           MAX(value) FILTER (WHERE series = 'price_no4') AS price_no4,
           MAX(value) FILTER (WHERE series = '246') AS wind_fc_mw,
           MAX(value) FILTER (WHERE series = '165') AS consumption_fc_mw,
           MAX(value) FILTER (WHERE series = '75')  AS wind_mw,
           MAX(value) FILTER (WHERE series = '188') AS nuclear_mw,
           AVG(value) FILTER (WHERE series IN ('178', '182', '196', '185')) AS temp_c,
           COUNT(*)   FILTER (WHERE series IN ('178', '182', '196', '185')) AS cities
    FROM hourly
    GROUP BY hour_start
)
SELECT hour_start,
       EXTRACT(HOUR   FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS hour_fi,
       EXTRACT(ISODOW FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS isodow_fi,
       EXTRACT(MONTH  FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS month_fi,
       EXTRACT(YEAR   FROM hour_start AT TIME ZONE 'Europe/Helsinki')::int AS year_fi,
       (hour_start AT TIME ZONE 'Europe/Helsinki')::date                     AS day_fi,
       price_fi, price_se1, price_se3, price_ee, price_no4,
       wind_fc_mw, consumption_fc_mw, wind_mw, nuclear_mw,
       CASE WHEN cities = 4 THEN temp_c END AS temp_c
FROM wide
WHERE price_fi IS NOT NULL
ORDER BY hour_start;
