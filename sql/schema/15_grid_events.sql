-- =============================================================
-- 15_grid_events.sql
-- A log of unusual moments on the Finnish grid, from raw Fingrid data.
--
-- Four kinds of event, each with a threshold that is an operating
-- definition or stated relative to the data, not tuned by eye:
--   frequency_low / frequency_high
--       a 1-minute frequency sample (177) outside the Nordic normal
--       band 49.9-50.1 Hz; samples below 45 Hz are invalid (Fingrid
--       writes gaps as 0) and are skipped
--   nuclear_drop
--       Finnish nuclear output (188, 3-minute) at least 400 MW below
--       its highest value of the previous 15 minutes: a unit tripping
--       or being cut back fast
--   low_inertia
--       kinetic energy of the Nordic system (260) in the lowest 1% of
--       the requested window: little spinning mass to slow a frequency
--       fall, the situation fast reserves exist for
--   price_spike
--       imbalance price (319) of 1,000 EUR/MWh or more
--
-- Flagged samples of one kind are merged into a single event when the
-- gap between them is short (3 min for frequency, 30 min for nuclear,
-- none for the 15-minute series): the gaps-and-islands pattern.
--
-- For nuclear drops, freq_min_nearby is the lowest valid frequency
-- within 15 minutes of the event. It is a cross-check between two
-- independent sensors, and over the last year it shows that Finnish
-- nuclear drops rarely move the (Nordic-wide) frequency far: either
-- they were controlled ramps, or the brief nadir fell between the
-- 1-minute samples.
--
-- Techniques: set-returning SQL function, window frames with RANGE
--             intervals, gaps and islands (LAG + running SUM),
--             PERCENTILE_CONT, LATERAL subquery
-- =============================================================

DROP FUNCTION IF EXISTS grid_events(timestamptz, timestamptz);
CREATE FUNCTION grid_events(from_ts timestamptz, to_ts timestamptz)
RETURNS TABLE (
    kind             text,
    start_time       timestamptz,
    end_time         timestamptz,
    peak             double precision,
    threshold        double precision,
    unit             text,
    samples          int,
    freq_min_nearby  double precision
)
LANGUAGE sql STABLE AS $$
    WITH
    freq AS (
        SELECT start_time, end_time, value
        FROM fingrid_observation
        WHERE dataset_id = 177 AND value >= 45
          AND start_time >= from_ts AND start_time < to_ts
    ),
    nuclear AS (
        SELECT start_time, end_time,
               value - MAX(value) OVER (ORDER BY start_time
                                        RANGE BETWEEN interval '15 minutes' PRECEDING
                                                  AND interval '1 second' PRECEDING) AS drop_mw
        FROM fingrid_observation
        WHERE dataset_id = 188
          AND start_time >= from_ts - interval '15 minutes' AND start_time < to_ts
    ),
    inertia AS (
        SELECT start_time, end_time, value
        FROM fingrid_observation
        WHERE dataset_id = 260 AND start_time >= from_ts AND start_time < to_ts
    ),
    inertia_limit AS (
        SELECT PERCENTILE_CONT(0.01) WITHIN GROUP (ORDER BY value) AS lim FROM inertia
    ),
    flagged AS (
        SELECT CASE WHEN value < 49.9 THEN 'frequency_low' ELSE 'frequency_high' END AS kind,
               start_time, end_time, value,
               CASE WHEN value < 49.9 THEN 49.9 ELSE 50.1 END AS threshold
        FROM freq WHERE value < 49.9 OR value > 50.1
        UNION ALL
        SELECT 'nuclear_drop', start_time, end_time, drop_mw, -400
        FROM nuclear WHERE drop_mw <= -400 AND start_time >= from_ts
        UNION ALL
        SELECT 'low_inertia', i.start_time, i.end_time, i.value, l.lim
        FROM inertia i CROSS JOIN inertia_limit l WHERE i.value < l.lim
        UNION ALL
        SELECT 'price_spike', start_time, end_time, value, 1000
        FROM fingrid_observation
        WHERE dataset_id = 319 AND value >= 1000
          AND start_time >= from_ts AND start_time < to_ts
    ),
    starts AS (
        SELECT flagged.*,
               CASE WHEN start_time - LAG(end_time) OVER (PARTITION BY kind ORDER BY start_time)
                         <= CASE kind WHEN 'nuclear_drop' THEN interval '30 minutes'
                                      WHEN 'frequency_low' THEN interval '3 minutes'
                                      WHEN 'frequency_high' THEN interval '3 minutes'
                                      ELSE interval '0' END
                    THEN 0 ELSE 1 END AS is_new
        FROM flagged
    ),
    islands AS (
        SELECT starts.*, SUM(is_new) OVER (PARTITION BY kind ORDER BY start_time) AS event_no
        FROM starts
    ),
    events AS (
        SELECT kind,
               MIN(start_time) AS start_time,
               MAX(end_time)   AS end_time,
               CASE WHEN kind IN ('frequency_high', 'price_spike') THEN MAX(value) ELSE MIN(value) END AS peak,
               MIN(threshold)  AS threshold,
               COUNT(*)::int   AS samples
        FROM islands
        GROUP BY kind, event_no
    )
    SELECT e.kind, e.start_time, e.end_time, e.peak, e.threshold,
           CASE e.kind WHEN 'nuclear_drop' THEN 'MW' WHEN 'low_inertia' THEN 'GWs'
                       WHEN 'price_spike' THEN 'EUR/MWh' ELSE 'Hz' END,
           e.samples,
           f.freq_min
    FROM events e
    LEFT JOIN LATERAL (
        SELECT MIN(x.value) AS freq_min
        FROM fingrid_observation x
        WHERE e.kind = 'nuclear_drop'
          AND x.dataset_id = 177 AND x.value >= 45
          AND x.start_time BETWEEN e.start_time - interval '15 minutes' AND e.end_time + interval '15 minutes'
    ) f ON true
$$;
