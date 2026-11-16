-- =============================================================
-- 19_co2_forecast_backtest.sql
-- How well would co2_forecast() have done? Every day in the window is
-- forecast exactly as it would have been at the time (training data
-- ends two days before the target day) and compared with what Fingrid
-- later measured.
--
--   mae_model_g / mae_naive_g   mean absolute error, model vs the
--                               same hour two days earlier
--   pick_in_top3_pct            days on which the hour the model calls
--                               cleanest was really among the 3 cleanest
--   co2_at_pick_g               actual intensity in the picked hour
--   day_mean_g, best_hour_g     the day's average and its cleanest hour
--   saving_pct                  using the picked hour instead of an
--                               average hour, as a share of the day mean
--   achievable_pct              the same for a perfect pick
--
-- Parameters: start, end (timestamptz, end exclusive; whole UTC days)
-- Techniques: set-returning function, window functions over each day
--             (RANK, ROW_NUMBER, AVG, MIN OVER PARTITION BY)
-- =============================================================

WITH f AS (
    SELECT *
    FROM co2_forecast((%(start)s::timestamptz AT TIME ZONE 'UTC')::date,
                      (%(end)s::timestamptz   AT TIME ZONE 'UTC')::date)
    WHERE co2_actual IS NOT NULL AND co2_naive IS NOT NULL
),
ranked AS (
    SELECT f.*,
           RANK()       OVER (PARTITION BY day_fi ORDER BY co2_actual)          AS actual_rank,
           ROW_NUMBER() OVER (PARTITION BY day_fi ORDER BY co2_unclamped, hour_start) AS model_rank,
           AVG(co2_actual) OVER (PARTITION BY day_fi)                           AS day_mean,
           MIN(co2_actual) OVER (PARTITION BY day_fi)                           AS day_best
    FROM f
),
picks AS (
    SELECT * FROM ranked WHERE model_rank = 1
)
SELECT
    (SELECT COUNT(DISTINCT day_fi) FROM f)                      AS days,
    (SELECT COUNT(*) FROM f)                                    AS hours,
    (SELECT AVG(ABS(co2_actual - co2_forecast)) FROM f)         AS mae_model_g,
    (SELECT AVG(ABS(co2_actual - co2_naive)) FROM f)            AS mae_naive_g,
    (SELECT AVG(co2_actual - co2_forecast) FROM f)              AS bias_model_g,
    100.0 * AVG((actual_rank <= 3)::int)                        AS pick_in_top3_pct,
    AVG(co2_actual)                                             AS co2_at_pick_g,
    AVG(day_mean)                                               AS day_mean_g,
    AVG(day_best)                                               AS best_hour_g,
    100 * (AVG(day_mean) - AVG(co2_actual)) / AVG(day_mean)     AS saving_pct,
    100 * (AVG(day_mean) - AVG(day_best)) / AVG(day_mean)       AS achievable_pct
FROM picks;
