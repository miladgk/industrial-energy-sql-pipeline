-- =============================================================
-- 30_europe_comparison.sql
-- One row per country (and the EU aggregate) over a window of
-- months: its wholesale price and how clean and how self-sufficient
-- its electricity is. The input of "Finland in Europe"
-- (src/europe.py), run once for the last twelve complete months and
-- once per calendar year.
--
--   price_eur_mwh       mean of the monthly day-ahead prices (Ember)
--   price_months        months with a price in the window
--   generation_months   months with generation data in the window
--   intensity_g_kwh     emissions / generation (gCO2e per kWh
--                       generated, life-cycle, Ember)
--   wind_solar_share, clean_share, fossil_share, nuclear_share,
--   hydro_share         share of generation
--   net_import_share    net imports / demand (negative = exporter)
--   demand_twh          electricity demand in the window
--   complete            every month of the window has a price and
--                       generation data; only these are ranked
--
-- Parameters: start, end (first day of the first and of the last
-- month, inclusive)
-- Techniques: conditional aggregation (FILTER), NULLIF guards,
-- LEFT JOIN of two aggregates, interval arithmetic for the month count
-- =============================================================

WITH window_months AS (
    SELECT (EXTRACT(YEAR FROM age(%(end)s::date, %(start)s::date)) * 12
            + EXTRACT(MONTH FROM age(%(end)s::date, %(start)s::date)) + 1)::int AS n
),
gen AS (
    SELECT area,
           COUNT(DISTINCT month)                                                       AS generation_months,
           SUM(generation_twh) FILTER (WHERE source = 'Total generation')              AS total_twh,
           SUM(emissions_mt)   FILTER (WHERE source = 'Total generation')              AS emissions_mt,
           SUM(generation_twh) FILTER (WHERE source = 'Wind and solar')                AS wind_solar_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Clean')                         AS clean_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Fossil')                        AS fossil_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Nuclear')                       AS nuclear_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Hydro')                         AS hydro_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Net imports')                   AS net_imports_twh,
           SUM(generation_twh) FILTER (WHERE source = 'Demand')                        AS demand_twh
    FROM ember_generation
    WHERE month BETWEEN %(start)s AND %(end)s
    GROUP BY area
),
price AS (
    SELECT area, AVG(eur_mwh) AS price_eur_mwh, COUNT(*) AS price_months
    FROM ember_price
    WHERE month BETWEEN %(start)s AND %(end)s
    GROUP BY area
)
SELECT a.area,
       a.iso3,
       a.eu_member,
       p.price_eur_mwh,
       COALESCE(p.price_months, 0)                                 AS price_months,
       COALESCE(g.generation_months, 0)                            AS generation_months,
       1000 * g.emissions_mt / NULLIF(g.total_twh, 0)              AS intensity_g_kwh,
       g.wind_solar_twh / NULLIF(g.total_twh, 0)                   AS wind_solar_share,
       g.clean_twh      / NULLIF(g.total_twh, 0)                   AS clean_share,
       g.fossil_twh     / NULLIF(g.total_twh, 0)                   AS fossil_share,
       g.nuclear_twh    / NULLIF(g.total_twh, 0)                   AS nuclear_share,
       g.hydro_twh      / NULLIF(g.total_twh, 0)                   AS hydro_share,
       g.net_imports_twh / NULLIF(g.demand_twh, 0)                 AS net_import_share,
       g.demand_twh,
       (COALESCE(p.price_months, 0) = w.n AND COALESCE(g.generation_months, 0) = w.n) AS complete
FROM ember_area a
CROSS JOIN window_months w
LEFT JOIN gen g   ON g.area = a.area
LEFT JOIN price p ON p.area = a.area
WHERE g.area IS NOT NULL OR p.area IS NOT NULL
ORDER BY p.price_eur_mwh NULLS LAST, a.area;
