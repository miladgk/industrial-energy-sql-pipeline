-- =============================================================
-- 13_forecast_scorecard.sql
-- How far were Fingrid's own forecasts from what actually happened?
--
-- One row per variable (wind, consumption) and forecast product:
--   day_ahead  published the previous day at 12:00 Finnish time
--   intraday   updated every 15 minutes (last update before the slot)
--
--   mae_mw               mean absolute error per 15-minute slot
--   bias_mw              mean error; positive = reality above forecast
--   rmse_mw              punishes large misses more than MAE
--   p95_abs_error_mw     95 in 100 slots missed by less than this
--   wape_pct             total absolute error / total actual, in percent
--   mae_pct_of_capacity  wind only: MAE as a share of the wind fleet
--                        that Fingrid assumed (dataset 268)
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: views, ordered-set aggregates (PERCENTILE_CONT), NULLIF
-- =============================================================

SELECT
    variable,
    product,
    COUNT(*)                                                     AS slots,
    AVG(ABS(error_mw))                                           AS mae_mw,
    AVG(error_mw)                                                AS bias_mw,
    SQRT(AVG(error_mw * error_mw))                               AS rmse_mw,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ABS(error_mw))  AS p95_abs_error_mw,
    100 * SUM(ABS(error_mw)) / NULLIF(SUM(actual_mw), 0)         AS wape_pct,
    100 * AVG(ABS(error_mw)) / NULLIF(AVG(capacity_mw), 0)       AS mae_pct_of_capacity,
    AVG(actual_mw)                                               AS mean_actual_mw,
    AVG(capacity_mw)                                             AS mean_capacity_mw
FROM forecast_vs_actual
WHERE start_time >= %(start)s
  AND start_time <  %(end)s
GROUP BY variable, product
ORDER BY variable, product;
