-- =============================================================
-- 26_weather_model_panel.sql
-- One row per UTC hour: what happened, what Fingrid forecast the
-- day before, and the weather as it was forecast two days before:
-- the input of src/weather_model.py.
--
--   wind_mw, consumption_mw      actuals (75, 124), 4 quarters per
--                                hour; NULL for hours still to come
--   fingrid_wind_mw, fingrid_consumption_mw
--                                Fingrid's day-ahead forecasts (246,
--                                165), stored before their day began
--   wind_capacity_mw             capacity behind Fingrid's wind
--                                forecast (268, hourly)
--   temp_c                       mean forecast temperature of Helsinki,
--                                Jyväskylä, Oulu, Rovaniemi
--   temp_<place>, wind_<place>   forecast temperature (°C) and 100 m
--                                wind speed (m/s) per place
--   farm_<place>                 100 m wind speed (m/s) inside the
--                                largest wind-farm areas
--
-- Weather comes from weather_forecast model 'openmeteo_d2': for every
-- hour, the value forecast 48 hours earlier, which was already
-- published when Fingrid issued its day-ahead forecast at 12:00 the
-- day before (src/openmeteo_forecast.py). Every input here was known
-- when that forecast was made, except the actuals the model learns
-- from (which the backtest only uses once they are two days old).
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: FILTER pivot over two tables, LEFT JOIN on the hour
-- =============================================================

WITH fingrid AS (
    SELECT date_trunc('hour', start_time) AS hour_start,
           AVG(value) FILTER (WHERE dataset_id = 75)  AS wind_mw,
           COUNT(*)   FILTER (WHERE dataset_id = 75)  AS n_wind,
           AVG(value) FILTER (WHERE dataset_id = 124) AS consumption_mw,
           COUNT(*)   FILTER (WHERE dataset_id = 124) AS n_cons,
           AVG(value) FILTER (WHERE dataset_id = 246) AS fingrid_wind_mw,
           COUNT(*)   FILTER (WHERE dataset_id = 246) AS n_fwind,
           AVG(value) FILTER (WHERE dataset_id = 165) AS fingrid_consumption_mw,
           COUNT(*)   FILTER (WHERE dataset_id = 165) AS n_fcons,
           AVG(value) FILTER (WHERE dataset_id = 268) AS wind_capacity_mw
    FROM fingrid_observation
    WHERE dataset_id IN (75, 124, 165, 246, 268)
      AND start_time >= %(start)s AND start_time < %(end)s
    GROUP BY 1
),
weather AS (
    SELECT valid_time AS hour_start,
           AVG(value) FILTER (WHERE parameter = 'temperature'
                              AND place IN ('Helsinki', 'Jyväskylä', 'Oulu', 'Rovaniemi')) AS temp_c,
           MAX(value) FILTER (WHERE parameter = 'temperature'  AND place = 'Helsinki')  AS temp_helsinki,
           MAX(value) FILTER (WHERE parameter = 'temperature'  AND place = 'Oulu')      AS temp_oulu,
           MAX(value) FILTER (WHERE parameter = 'temperature'  AND place = 'Vaasa')     AS temp_vaasa,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Vaasa')     AS wind_vaasa,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Kokkola')   AS wind_kokkola,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Pori')      AS wind_pori,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Raahe')     AS wind_raahe,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Oulu')      AS wind_oulu,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Helsinki')  AS wind_helsinki,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Kristinestad') AS farm_kristinestad,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Kalajoki')     AS farm_kalajoki,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Lestijärvi')   AS farm_lestijarvi,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Ii')           AS farm_ii,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Tornio')       AS farm_tornio,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Kyyjärvi')     AS farm_kyyjarvi,
           MAX(value) FILTER (WHERE parameter = 'windspeed100' AND place = 'Pyhäjoki')     AS farm_pyhajoki,
           COUNT(*) AS n_weather
    FROM weather_forecast
    WHERE model = 'openmeteo_d2'
      AND valid_time >= %(start)s AND valid_time < %(end)s
    GROUP BY 1
)
SELECT w.hour_start,
       CASE WHEN f.n_wind = 4 THEN f.wind_mw END                 AS wind_mw,
       CASE WHEN f.n_cons = 4 THEN f.consumption_mw END          AS consumption_mw,
       CASE WHEN f.n_fwind = 4 THEN f.fingrid_wind_mw END        AS fingrid_wind_mw,
       CASE WHEN f.n_fcons = 4 THEN f.fingrid_consumption_mw END AS fingrid_consumption_mw,
       f.wind_capacity_mw,
       w.temp_c, w.temp_helsinki, w.temp_oulu, w.temp_vaasa,
       w.wind_vaasa, w.wind_kokkola, w.wind_pori, w.wind_raahe, w.wind_oulu, w.wind_helsinki,
       w.farm_kristinestad, w.farm_kalajoki, w.farm_lestijarvi, w.farm_ii, w.farm_tornio,
       w.farm_kyyjarvi, w.farm_pyhajoki
FROM weather w
LEFT JOIN fingrid f USING (hour_start)
WHERE w.n_weather = 30                   -- both parameters at all fifteen places
ORDER BY w.hour_start;
