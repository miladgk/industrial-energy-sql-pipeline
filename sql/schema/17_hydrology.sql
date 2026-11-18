-- =============================================================
-- 17_hydrology.sql
-- Daily state of the water behind Finnish (and Norwegian) hydropower:
-- the input of the "does hydro make more room for wind when the
-- reservoirs are full?" analysis.
--
--   series   what is measured (src/hydrology.py SERIES), e.g.
--            'level_lokka'      water level of Lokka reservoir (cm)
--            'flow_tornionjoki' discharge of the unregulated
--                               Tornionjoki at Karunki (m3/s)
--            'snow_kemijoki'    snow water equivalent over the
--                               Kemijoki basin (mm)
--            'nve_no1' .. 'nve_no5'  Norwegian reservoir filling per
--                               price area (share 0-1, weekly)
--   day      the day the value is for (weekly series: the week's
--            reference day as NVE publishes it)
--
-- Water levels and snow have strong yearly cycles, so the analysis
-- compares each day with the same calendar day's 2000-2022 median
-- (hydrology_norm in sql/analysis/27). Regulated outlet discharges are
-- deliberately not stored: they are what the hydro plants released,
-- an outcome of the decisions being studied, not a cause.
--
-- Sources: SYKE Hydrology API (Finnish Environment Institute, CC BY
-- 4.0); NVE reservoir statistics (Norwegian Water Resources and Energy
-- Directorate, NLOD).
-- =============================================================

CREATE TABLE IF NOT EXISTS hydrology_daily (
    series  TEXT             NOT NULL,
    day     DATE             NOT NULL,
    value   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (series, day)
);
