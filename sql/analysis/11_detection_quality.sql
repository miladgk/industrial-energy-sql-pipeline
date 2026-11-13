-- =============================================================
-- 11_detection_quality.sql
-- How good is the z-score detector (04_anomaly_detection.sql)?
--
-- The synthetic generator labels every fault it injects (is_anomaly):
-- either a zero-value dropout or a spike at 3x the sensor's normal
-- maximum. As in 04_anomaly_detection.sql, the labels are used only to
-- build a clean baseline (monthly mean and standard deviation of the
-- non-injected readings); the flag itself is z > 3 on the value alone.
-- Comparing flags with labels gives precision and recall per sensor
-- type and fault kind.
--
-- Typical result: precision is 100% and every spike is caught, but a
-- zero reading is only caught when zero lies far outside the sensor's
-- normal range (bus voltage). For power, temperature, irradiance and
-- wind speed, zero is an ordinary value, so a dropout there is
-- statistically invisible and needs a different rule.
--
-- Techniques: CTEs, aggregate FILTER clauses, boolean expressions
-- Served by: GET /api/detection-quality
-- =============================================================

WITH sensor_monthly_stats AS (
    SELECT
        sensor_id,
        DATE_TRUNC('month', recorded_at)  AS month,
        AVG(value)                        AS mean_val,
        STDDEV(value)                     AS stddev_val
    FROM readings
    WHERE is_anomaly = FALSE
    GROUP BY sensor_id, DATE_TRUNC('month', recorded_at)
),
scored AS (
    SELECT
        se.sensor_type,
        r.is_anomaly                                         AS injected,
        (s.stddev_val > 0
         AND ABS(r.value - s.mean_val) / s.stddev_val > 3)   AS flagged,
        r.value < s.mean_val                                 AS below_baseline
    FROM readings r
    JOIN sensor_monthly_stats s
      ON  r.sensor_id = s.sensor_id
      AND DATE_TRUNC('month', r.recorded_at) = s.month
    JOIN sensors se ON r.sensor_id = se.sensor_id
)
SELECT
    sensor_type,
    COUNT(*) FILTER (WHERE injected)                                  AS injected,
    COUNT(*) FILTER (WHERE flagged)                                   AS flagged,
    ROUND(100.0 * COUNT(*) FILTER (WHERE injected AND flagged)
          / NULLIF(COUNT(*) FILTER (WHERE flagged), 0), 1)            AS precision_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE injected AND flagged)
          / NULLIF(COUNT(*) FILTER (WHERE injected), 0), 1)           AS recall_pct,
    COUNT(*) FILTER (WHERE injected AND NOT below_baseline AND flagged) || ' / ' ||
    COUNT(*) FILTER (WHERE injected AND NOT below_baseline)           AS spikes_caught,
    COUNT(*) FILTER (WHERE injected AND below_baseline AND flagged)   || ' / ' ||
    COUNT(*) FILTER (WHERE injected AND below_baseline)               AS drops_caught
FROM scored
GROUP BY sensor_type
ORDER BY sensor_type;
