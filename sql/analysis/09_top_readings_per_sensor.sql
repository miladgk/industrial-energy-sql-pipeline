-- =============================================================
-- 09_top_readings_per_sensor.sql
-- Find the top 3 highest-value readings per sensor for the most
-- recent month of data (December 2025).
--
-- Techniques: CROSS JOIN LATERAL (per-row correlated subquery with LIMIT)
--
-- Why LATERAL is needed:
-- A standard JOIN cannot reference columns from the outer table (`se.sensor_id`)
-- inside a derived table subquery (`SELECT ... LIMIT 3`). While this could
-- theoretically be written using window functions (`ROW_NUMBER() OVER (...)`)
-- followed by an outer filtering step (`WHERE rn <= 3`), that approach forces
-- PostgreSQL to materialize and sort the entire dataset across all sensors
-- before filtering.
--
-- `CROSS JOIN LATERAL` allows the subquery to act as a correlated for-each loop
-- over `sensors se`, executing the indexed Top-N lookup (`LIMIT 3`) directly
-- per sensor row. This avoids a full scan/sort and is vastly more efficient
-- when retrieving top-N rows per category.
-- =============================================================

SELECT
    s.facility_id,
    s.facility_name,
    se.sensor_id,
    se.sensor_type,
    top.recorded_at,
    top.value
FROM sensors se
JOIN facilities s ON s.facility_id = se.facility_id
CROSS JOIN LATERAL (
    SELECT recorded_at, value
    FROM readings r
    WHERE r.sensor_id = se.sensor_id
      AND r.recorded_at >= '2025-12-01' AND r.recorded_at < '2026-01-01'
      AND r.is_anomaly = FALSE
    ORDER BY r.value DESC
    LIMIT 3
) top
ORDER BY se.sensor_id, top.value DESC;
