-- =============================================================
-- 16_forecast_biggest_misses.sql
-- The five days on which each day-ahead forecast missed the most.
-- A day is a Finnish calendar day and must have at least 90 of its
-- 15-minute slots (92 or 100 on DST days, 96 otherwise).
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: CTEs, HAVING, ROW_NUMBER() window function
-- =============================================================

WITH daily AS (
    SELECT
        variable,
        (start_time AT TIME ZONE 'Europe/Helsinki')::date  AS day_fi,
        COUNT(*)                                           AS slots,
        AVG(ABS(error_mw))                                 AS mae_mw,
        AVG(error_mw)                                      AS bias_mw,
        AVG(actual_mw)                                     AS mean_actual_mw,
        AVG(forecast_mw)                                   AS mean_forecast_mw,
        MAX(ABS(error_mw))                                 AS worst_slot_abs_error_mw
    FROM forecast_vs_actual
    WHERE product = 'day_ahead'
      AND start_time >= %(start)s
      AND start_time <  %(end)s
    GROUP BY variable, day_fi
    HAVING COUNT(*) >= 90
),
ranked AS (
    SELECT daily.*,
           ROW_NUMBER() OVER (PARTITION BY variable ORDER BY mae_mw DESC) AS rank
    FROM daily
)
SELECT *
FROM ranked
WHERE rank <= 5
ORDER BY variable, rank;
