-- =============================================================
-- 20_grid_events.sql
-- Every grid event in the window, newest first, from grid_events()
-- in sql/schema/15_grid_events.sql.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: set-returning function
-- =============================================================

SELECT kind, start_time, end_time, peak, threshold, unit, samples, freq_min_nearby
FROM grid_events(%(start)s, %(end)s)
ORDER BY start_time DESC;
