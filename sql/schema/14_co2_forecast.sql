-- =============================================================
-- 14_co2_forecast.sql
-- Forecast of the CO2 intensity of electricity consumed in Finland,
-- per hour of a Finnish calendar day. Fingrid publishes the intensity
-- only as it happens (dataset 396); this predicts it a day ahead.
--
-- Input: Fingrid's own day-ahead forecasts (published at 12:00 Finnish
-- time for the next day), combined into the residual load:
--     residual load = consumption (165) - wind (246) - solar (247)
-- Demand that wind and solar do not cover is met by imports and
-- thermal plants, so the intensity rises with it (r = 0.84 over the
-- last year).
--
-- Model, refitted for every target day D using only what was known
-- when D's forecast was made:
--   1. least-squares line  co2 = a + b * residual_load  over the 60
--      days that end two days before D (regr_intercept, regr_slope)
--   2. level correction: the line's mean error on day D-2, which
--      captures slow changes the residual load does not see (a nuclear
--      outage, import conditions)
--   3. floor: never below the lowest intensity seen in the training
--      window. On very windy days the line otherwise extrapolates below
--      anything ever measured (7% of hours; their error drops from
--      9.8 to 3.4 g). co2_unclamped keeps the line's own value, which
--      still orders the hours when several sit on the floor.
-- co2_naive is the baseline to beat: the same hour two days earlier.
--
-- Used by sql/analysis/18 (tomorrow) and 19 (backtest), so the live
-- forecast and its track record run the exact same SQL.
-- Techniques: views with FILTER aggregates, a set-returning SQL
--             function, regr_slope / regr_intercept, generate_series
-- =============================================================

CREATE OR REPLACE VIEW co2_hourly AS
SELECT
    date_trunc('hour', start_time)                                         AS hour_start,
    (date_trunc('hour', start_time) AT TIME ZONE 'Europe/Helsinki')::date  AS day_fi,
    CASE WHEN COUNT(*) FILTER (WHERE dataset_id = 396) = 4                 -- a complete hour only
         THEN AVG(value) FILTER (WHERE dataset_id = 396) END              AS co2_actual,
    AVG(value) FILTER (WHERE dataset_id = 165)
      - AVG(value) FILTER (WHERE dataset_id = 246)
      - COALESCE(AVG(value) FILTER (WHERE dataset_id = 247), 0)            AS residual_load_mw
FROM fingrid_observation
WHERE dataset_id IN (396, 165, 246, 247)
GROUP BY date_trunc('hour', start_time);


-- Dropped first: CREATE OR REPLACE cannot change the columns a function returns.
DROP FUNCTION IF EXISTS co2_forecast(date, date, int);
CREATE FUNCTION co2_forecast(first_day date, last_day date, training_days int DEFAULT 60)
RETURNS TABLE (
    day_fi            date,
    hour_start        timestamptz,
    hour_fi           int,
    residual_load_mw  double precision,
    co2_forecast      double precision,
    co2_unclamped     double precision,
    co2_naive         double precision,
    co2_actual        double precision
)
LANGUAGE sql STABLE AS $$
    WITH days AS (
        SELECT generate_series(first_day, last_day - 1, interval '1 day')::date AS d
    ),
    fit AS (
        SELECT days.d,
               regr_intercept(x.co2_actual, x.residual_load_mw) AS a,
               regr_slope(x.co2_actual, x.residual_load_mw)     AS b,
               MIN(x.co2_actual)                                AS floor_g
        FROM days
        JOIN co2_hourly x
          ON x.day_fi >= days.d - (training_days + 1)
         AND x.day_fi <  days.d - 1
        WHERE x.co2_actual IS NOT NULL AND x.residual_load_mw IS NOT NULL
        GROUP BY days.d
    ),
    level AS (
        SELECT f.d, AVG(x.co2_actual - (f.a + f.b * x.residual_load_mw)) AS correction
        FROM fit f
        JOIN co2_hourly x ON x.day_fi = f.d - 2
        WHERE x.co2_actual IS NOT NULL AND x.residual_load_mw IS NOT NULL
        GROUP BY f.d
    )
    SELECT f.d,
           t.hour_start,
           EXTRACT(HOUR FROM t.hour_start AT TIME ZONE 'Europe/Helsinki')::int,
           t.residual_load_mw,
           GREATEST(f.a + f.b * t.residual_load_mw + COALESCE(l.correction, 0), f.floor_g),
           f.a + f.b * t.residual_load_mw + COALESCE(l.correction, 0),
           p.co2_actual,
           t.co2_actual
    FROM fit f
    JOIN co2_hourly t ON t.day_fi = f.d AND t.residual_load_mw IS NOT NULL
    LEFT JOIN level l ON l.d = f.d
    LEFT JOIN co2_hourly p ON p.hour_start = t.hour_start - interval '48 hours'
    WHERE f.b IS NOT NULL
$$;
