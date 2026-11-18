-- =============================================================
-- 18_dataset_summary.sql
-- Row count and time coverage of every dataset, for GET /api/datasets.
--
-- Counting ten million rows on every request takes seconds, so the
-- summary is computed once per load instead: src/sync_fingrid.py and
-- src/warehouse_snapshot.py refresh it (refresh_dataset_summary) after
-- they write. Between loads the table does not change, so the view is
-- exact; rows written by hand need a refresh to show up.
-- =============================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS fingrid_dataset_summary AS
SELECT d.dataset_id,
       COUNT(o.start_time) AS rows,
       MIN(o.start_time)   AS first_start,
       MAX(o.end_time)     AS last_end
FROM fingrid_dataset d
LEFT JOIN fingrid_observation o USING (dataset_id)
GROUP BY d.dataset_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fingrid_dataset_summary_pk ON fingrid_dataset_summary (dataset_id);
