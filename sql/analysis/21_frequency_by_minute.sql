-- =============================================================
-- 21_frequency_by_minute.sql
-- Is the grid frequency less stable at particular minutes of the hour?
-- For each minute (0-59) the share of valid 1-minute samples outside
-- the Nordic normal band 49.9-50.1 Hz. Over the last year the last
-- minute before a full hour is out of band about twice as often as an
-- average minute: generation schedules change on the hour.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: FILTER aggregates, EXTRACT
-- =============================================================

SELECT
    EXTRACT(MINUTE FROM start_time)::int                                   AS minute_of_hour,
    COUNT(*)                                                               AS samples,
    COUNT(*) FILTER (WHERE value < 49.9)                                   AS below_band,
    COUNT(*) FILTER (WHERE value > 50.1)                                   AS above_band,
    100.0 * COUNT(*) FILTER (WHERE value < 49.9 OR value > 50.1) / COUNT(*) AS pct_outside
FROM fingrid_observation
WHERE dataset_id = 177
  AND value >= 45                     -- Fingrid writes missing samples as 0
  AND start_time >= %(start)s
  AND start_time <  %(end)s
GROUP BY minute_of_hour
ORDER BY minute_of_hour;
