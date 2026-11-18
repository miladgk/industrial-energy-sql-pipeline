-- =============================================================
-- 19_entsoe_price.sql
-- Day-ahead electricity prices (EUR/MWh) from the ENTSO-E
-- Transparency Platform (document type A44), loaded by
-- src/entsoe_prices.py.
--
--   area        bidding zone: 'FI', and the zones Finland is
--               connected to: 'SE1', 'SE3', 'EE', 'NO4'
--   start_time  start of the price slot (UTC)
--   end_time    its end: one hour until 30 September 2025,
--               15 minutes since the day-ahead auction moved to
--               15-minute products on 1 October 2025
--   eur_mwh     clearing price; it can be negative
--
-- Prices are stored at the resolution they were cleared at, so an
-- hourly mean of 15-minute prices is computed in the analyses, not
-- stored. Source: ENTSO-E Transparency Platform
-- (https://transparency.entsoe.eu), free to reuse with attribution.
-- =============================================================

CREATE TABLE IF NOT EXISTS entsoe_price (
    area        TEXT             NOT NULL,
    start_time  TIMESTAMPTZ      NOT NULL,
    end_time    TIMESTAMPTZ      NOT NULL,
    eur_mwh     DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (area, start_time),
    CONSTRAINT ck_entsoe_price_slot CHECK (end_time > start_time)
);
