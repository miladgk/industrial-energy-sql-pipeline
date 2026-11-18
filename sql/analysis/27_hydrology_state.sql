-- =============================================================
-- 27_hydrology_state.sql
-- One row per day: how full the Finnish reservoirs are and how much
-- water is coming in, each against what is normal for that day of the
-- year. The state variables of src/hydro_flex.py.
--
--   storage_z     mean of the five reservoir/lake z-scores: (level -
--                 that calendar day's 2000-2022 median) / that day's
--                 standard deviation; 0 = a normal level for the date,
--                 +1 = one standard deviation fuller than normal
--   level_<name>_z   the five parts (Lokka, Porttipahta, Oulujärvi,
--                 Saimaa, Näsijärvi)
--   inflow_z      log of the unregulated Tornionjoki's discharge
--                 against that calendar day's 2000-2022 log mean and
--                 standard deviation
--   nve_filling   mean filling of the Norwegian reservoirs (NO1-NO5,
--                 weekly, carried forward to every day of the week)
--
-- Calendar days are matched as month-day, with 29 February folded
-- onto 28 February; each norm pools a +/- 7 day window around the
-- date, so a norm rests on about 15 x 23 values.
--
-- Parameters: start, end (date, end exclusive)
-- Techniques: window-pooled seasonal norms, LATERAL carry-forward
-- =============================================================

WITH doy AS (
    SELECT series, day, value,
           -- day of a 365-day year (29 Feb -> 28 Feb)
           EXTRACT(DOY FROM make_date(2001, EXTRACT(MONTH FROM day)::int,
                   LEAST(EXTRACT(DAY FROM day)::int, CASE WHEN EXTRACT(MONTH FROM day) = 2 THEN 28 ELSE 31 END)))::int AS d,
           CASE WHEN series = 'flow_tornionjoki' THEN ln(GREATEST(value, 1)) ELSE value END AS x
    FROM hydrology_daily
    WHERE series LIKE 'level_%%' OR series = 'flow_tornionjoki'
),
norm AS (                                      -- per series and day of year: 2000-2022 mean and sd, +/- 7 days
    SELECT n.series, n.d,
           AVG(h.x)         AS mean_x,
           STDDEV_SAMP(h.x) AS sd_x
    FROM (SELECT DISTINCT series, d FROM doy) n
    JOIN doy h
      ON h.series = n.series
     AND h.day < DATE '2023-01-01'
     AND LEAST(abs(h.d - n.d), 365 - abs(h.d - n.d)) <= 7
    GROUP BY n.series, n.d
),
z AS (
    SELECT h.series, h.day, (h.x - n.mean_x) / NULLIF(n.sd_x, 0) AS z
    FROM doy h JOIN norm n USING (series, d)
    WHERE h.day >= %(start)s AND h.day < %(end)s
),
days AS (
    SELECT day,
           AVG(z) FILTER (WHERE series LIKE 'level_%%')             AS storage_z,
           COUNT(*) FILTER (WHERE series LIKE 'level_%%')           AS levels,
           MAX(z) FILTER (WHERE series = 'level_lokka')            AS level_lokka_z,
           MAX(z) FILTER (WHERE series = 'level_porttipahta')      AS level_porttipahta_z,
           MAX(z) FILTER (WHERE series = 'level_oulujarvi')        AS level_oulujarvi_z,
           MAX(z) FILTER (WHERE series = 'level_saimaa')           AS level_saimaa_z,
           MAX(z) FILTER (WHERE series = 'level_nasijarvi')        AS level_nasijarvi_z,
           MAX(z) FILTER (WHERE series = 'flow_tornionjoki')       AS inflow_z
    FROM z
    GROUP BY day
)
SELECT d.day, d.storage_z, d.levels, d.level_lokka_z, d.level_porttipahta_z, d.level_oulujarvi_z,
       d.level_saimaa_z, d.level_nasijarvi_z, d.inflow_z, nve.nve_filling
FROM days d
LEFT JOIN LATERAL (                            -- the latest Norwegian week on or before the day
    SELECT AVG(value) AS nve_filling
    FROM hydrology_daily
    WHERE series LIKE 'nve_no%%'
      AND day = (SELECT max(day) FROM hydrology_daily WHERE series = 'nve_no1' AND day <= d.day)
) nve ON true
ORDER BY d.day;
