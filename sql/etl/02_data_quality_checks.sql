-- =============================================================
-- 02_data_quality_checks.sql
-- Health of the Fingrid warehouse, run by src/run_quality_checks.py
-- (and by CI after the snapshot restore).
--
-- Each check starts with a line "-- Check: <label> [fail]" or "[info]".
-- A [fail] check passes when it returns no rows; [info] only reports.
-- =============================================================

-- Check: Rows that fell into the default partition [fail]
-- The sync and the restore create the monthly partition before writing,
-- so anything here means a month was missed.
SELECT dataset_id, COUNT(*) AS rows, MIN(start_time) AS first_start
FROM fingrid_observation_default
GROUP BY dataset_id;

-- Check: Datasets in the catalogue without any data [fail]
SELECT d.dataset_id, d.key
FROM fingrid_dataset d
WHERE NOT EXISTS (SELECT 1 FROM fingrid_observation o WHERE o.dataset_id = d.dataset_id);

-- Check: Datasets whose newest slot is more than 7 days old [fail]
-- The daily sync re-reads the last 7 days; an older newest slot means the
-- sync has stopped or Fingrid stopped publishing the dataset.
SELECT d.dataset_id, d.key, MAX(o.end_time) AS newest
FROM fingrid_dataset d
JOIN fingrid_observation o USING (dataset_id)
GROUP BY d.dataset_id, d.key
HAVING MAX(o.end_time) < now() - interval '7 days';

-- Check: Coverage of the last 30 days per dataset [info]
-- Stored slots as a share of the slots the resolution implies.
SELECT d.dataset_id, d.key, d.resolution,
       COUNT(o.start_time) AS slots,
       ROUND(100.0 * COUNT(o.start_time)
             / (EXTRACT(EPOCH FROM interval '30 days') / EXTRACT(EPOCH FROM d.resolution))::numeric, 1) AS coverage_pct
FROM fingrid_dataset d
LEFT JOIN fingrid_observation o
       ON o.dataset_id = d.dataset_id
      AND o.start_time >= date_trunc('day', now()) - interval '30 days'
      AND o.start_time <  date_trunc('day', now())
GROUP BY d.dataset_id, d.key, d.resolution
ORDER BY coverage_pct;

-- Check: Frequency samples Fingrid wrote as 0 Hz (its gap marker) [info]
-- They are skipped by every analysis.
SELECT COUNT(*) AS zero_hz_samples, MIN(start_time) AS first, MAX(start_time) AS last
FROM fingrid_observation
WHERE dataset_id = 177 AND value < 45;
