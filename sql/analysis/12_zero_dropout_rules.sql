-- =============================================================
-- 12_zero_dropout_rules.sql
-- Can a rule other than z > 3 catch zero-value dropouts?
--
-- The z-score detector (11_detection_quality.sql) misses every injected
-- zero on sensors whose normal range contains zero (power, temperature,
-- wind speed, irradiance). This query scores three alternative rules
-- against the injected zeros (is_anomaly AND value = 0):
--
--   flatline_3       value is 0 and the two previous readings were 0 too
--                    (a "stuck sensor" rule, common on real equipment)
--   neighbour_drop   value is below 5 % of the smaller neighbouring reading
--   exact_zero       value is exactly 0
--
-- Why the results look the way they do: the generator injects faults as
-- isolated single readings (a random 2 % mask), and draws normal values
-- uniformly at random. So a stuck-sensor rule finds almost nothing, the
-- neighbour rule fires on any naturally low value, and exact_zero is perfect
-- only because clean synthetic readings are never exactly 0.0, which would
-- not hold for real telemetry.
--
-- The labels (is_anomaly) are used only for scoring, never by the rules.
-- Techniques: LAG/LEAD window functions, named WINDOW, FILTER aggregates
-- =============================================================

WITH neighbours AS (
    SELECT
        se.sensor_type,
        r.value,
        r.is_anomaly AND r.value = 0                 AS injected_zero,
        LAG(r.value, 1)  OVER w                      AS prev_1,
        LAG(r.value, 2)  OVER w                      AS prev_2,
        LEAD(r.value, 1) OVER w                      AS next_1
    FROM readings r
    JOIN sensors se ON se.sensor_id = r.sensor_id
    WINDOW w AS (PARTITION BY r.sensor_id ORDER BY r.recorded_at)
),
rules AS (
    SELECT sensor_type, injected_zero, 'flatline_3' AS rule,
           (value = 0 AND prev_1 = 0 AND prev_2 = 0) AS flagged
    FROM neighbours
    UNION ALL
    SELECT sensor_type, injected_zero, 'neighbour_drop',
           COALESCE(value < 0.05 * LEAST(prev_1, next_1), FALSE)
    FROM neighbours
    UNION ALL
    SELECT sensor_type, injected_zero, 'exact_zero', value = 0
    FROM neighbours
)
SELECT
    rule,
    sensor_type,
    COUNT(*) FILTER (WHERE injected_zero)                         AS injected_zeros,
    COUNT(*) FILTER (WHERE injected_zero AND flagged)             AS caught,
    COUNT(*) FILTER (WHERE flagged)                               AS flagged,
    ROUND(100.0 * COUNT(*) FILTER (WHERE injected_zero AND flagged)
          / NULLIF(COUNT(*) FILTER (WHERE injected_zero), 0), 1)  AS recall_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE injected_zero AND flagged)
          / NULLIF(COUNT(*) FILTER (WHERE flagged), 0), 1)        AS precision_pct
FROM rules
GROUP BY rule, sensor_type
ORDER BY rule, sensor_type;
