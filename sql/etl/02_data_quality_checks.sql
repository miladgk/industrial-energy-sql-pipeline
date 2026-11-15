-- =============================================================
-- 02_data_quality_checks.sql
-- Run after ingestion to verify data integrity.
-- =============================================================

-- ---------------------------------------------------------------
-- Check 1: Sensors with no readings (should return 0 rows)
-- ---------------------------------------------------------------
SELECT
    s.sensor_id,
    s.sensor_type,
    f.facility_name
FROM sensors s
LEFT JOIN readings r ON s.sensor_id = r.sensor_id
JOIN  facilities f   ON s.facility_id = f.facility_id
WHERE r.reading_id IS NULL;


-- ---------------------------------------------------------------
-- Check 2: Readings with NULL values (should be 0)
-- ---------------------------------------------------------------
SELECT COUNT(*) AS null_value_count
FROM readings
WHERE value IS NULL;


-- ---------------------------------------------------------------
-- Check 3: Anomaly rate per facility (expect ~2%)
-- ---------------------------------------------------------------
SELECT
    f.facility_name,
    f.facility_type,
    COUNT(*)                                          AS total_readings,
    COUNT(*) FILTER (WHERE r.is_anomaly = TRUE)       AS anomaly_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE r.is_anomaly = TRUE)
        / NULLIF(COUNT(*), 0),
        2
    )                                                 AS anomaly_pct
FROM readings r
JOIN sensors    s ON r.sensor_id   = s.sensor_id
JOIN facilities f ON s.facility_id = f.facility_id
GROUP BY f.facility_name, f.facility_type
ORDER BY anomaly_pct DESC;


-- ---------------------------------------------------------------
-- Check 4: Timestamp coverage — confirm data spans full year 2025
-- ---------------------------------------------------------------
SELECT
    MIN(recorded_at)                                          AS earliest_reading,
    MAX(recorded_at)                                          AS latest_reading,
    COUNT(DISTINCT DATE_TRUNC('day', recorded_at))            AS days_with_data
FROM readings;
