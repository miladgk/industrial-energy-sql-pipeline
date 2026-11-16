-- =============================================================
-- 15_forecast_error_by_month.sql
-- Does forecast quality change with the seasons?
-- Monthly error per variable and product (months in Finnish time).
-- Wind MAE is also given as a share of the assumed wind capacity,
-- because the fleet grows during the year and raw MW would mislead.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: to_char on local time, NULLIF
-- =============================================================

SELECT
    variable,
    product,
    to_char(start_time AT TIME ZONE 'Europe/Helsinki', 'YYYY-MM')  AS month_fi,
    COUNT(*)                                                       AS slots,
    AVG(ABS(error_mw))                                             AS mae_mw,
    AVG(error_mw)                                                  AS bias_mw,
    100 * SUM(ABS(error_mw)) / NULLIF(SUM(actual_mw), 0)           AS wape_pct,
    100 * AVG(ABS(error_mw)) / NULLIF(AVG(capacity_mw), 0)         AS mae_pct_of_capacity,
    AVG(actual_mw)                                                 AS mean_actual_mw
FROM forecast_vs_actual
WHERE start_time >= %(start)s
  AND start_time <  %(end)s
GROUP BY variable, product, month_fi
ORDER BY variable, product, month_fi;
