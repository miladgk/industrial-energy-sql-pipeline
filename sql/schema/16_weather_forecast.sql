-- =============================================================
-- 16_weather_forecast.sql
-- An archive of FMI weather forecasts, kept as they were issued.
--
-- FMI's open data serves today's forecasts but no archive of past
-- ones. A forecasting model that is tested with the weather that
-- actually happened looks better than it can ever be in practice,
-- so src/fmi_forecast.py saves the forecast every day and this
-- table grows into the honest history the weather-based models are
-- trained and tested on.
--
--   model       FMI stored query, e.g. 'edited' (FMI's own edited
--               forecast) or 'harmonie' (the raw model)
--   place       place name sent to FMI ('Helsinki', 'Vaasa', ...)
--   parameter   'temperature' (°C) or 'windspeedms' (m/s at 10 m)
--   issued_at   when this project fetched it (UTC, to the minute):
--               the forecast as anyone could have known it then
--   valid_time  the hour the value is for (UTC)
--
-- Source: Finnish Meteorological Institute open data, CC BY 4.0.
-- =============================================================

CREATE TABLE IF NOT EXISTS weather_forecast (
    model       TEXT             NOT NULL,
    place       TEXT             NOT NULL,
    parameter   TEXT             NOT NULL,
    issued_at   TIMESTAMPTZ      NOT NULL,
    valid_time  TIMESTAMPTZ      NOT NULL,
    value       DOUBLE PRECISION,
    PRIMARY KEY (model, place, parameter, issued_at, valid_time)
);

CREATE INDEX IF NOT EXISTS weather_forecast_valid_idx ON weather_forecast (valid_time);
