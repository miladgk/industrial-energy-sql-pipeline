-- =============================================================
-- 14_forecast_error_by_hour.sql
-- When in the day do Fingrid's forecasts miss the most?
-- Mean absolute error and bias per hour of the day, Finnish local time
-- (so DST shifts do not smear the morning and evening ramps).
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: AT TIME ZONE, EXTRACT, GROUP BY on expressions
-- =============================================================

SELECT
    variable,
    product,
    EXTRACT(HOUR FROM start_time AT TIME ZONE 'Europe/Helsinki')::int  AS hour_fi,
    COUNT(*)                                                           AS slots,
    AVG(ABS(error_mw))                                                 AS mae_mw,
    AVG(error_mw)                                                      AS bias_mw
FROM forecast_vs_actual
WHERE start_time >= %(start)s
  AND start_time <  %(end)s
GROUP BY variable, product, hour_fi
ORDER BY variable, product, hour_fi;
