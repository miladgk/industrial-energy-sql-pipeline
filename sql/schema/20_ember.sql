-- =============================================================
-- 20_ember.sql
-- Monthly electricity data for Europe from Ember (CC BY 4.0),
-- loaded by src/ember.py: the input of "Finland in Europe"
-- (sql/analysis/30).
--
--   ember_area        one row per country (and the 'EU' aggregate)
--                     with Ember's EU membership flag
--   ember_generation  per area, month and source ('Total generation',
--                     'Demand', 'Net imports', 'Wind and solar',
--                     'Clean', 'Fossil', 'Nuclear', 'Hydro', ...):
--                     generation (TWh) and its emissions (MtCO2e,
--                     life-cycle), so intensity = emissions / generation
--   ember_price       monthly wholesale day-ahead price per country
--                     (EUR/MWh), from ENTSO-E as cleaned by Ember; the
--                     current month is partial until it ends
--
-- Ember keeps the whole history, so the tables are replaced on every
-- run rather than archived. Sources: Ember monthly electricity data
-- and European wholesale electricity price data
-- (https://ember-energy.org/data/), CC BY 4.0.
-- =============================================================

CREATE TABLE IF NOT EXISTS ember_area (
    area       TEXT    PRIMARY KEY,
    iso3       TEXT,
    eu_member  BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS ember_generation (
    area            TEXT             NOT NULL REFERENCES ember_area (area),
    month           DATE             NOT NULL,
    source          TEXT             NOT NULL,
    generation_twh  DOUBLE PRECISION,
    emissions_mt    DOUBLE PRECISION,
    PRIMARY KEY (area, month, source),
    CONSTRAINT ck_ember_generation_month CHECK (EXTRACT(DAY FROM month) = 1)
);

CREATE TABLE IF NOT EXISTS ember_price (
    area     TEXT             NOT NULL REFERENCES ember_area (area),
    month    DATE             NOT NULL,
    eur_mwh  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (area, month),
    CONSTRAINT ck_ember_price_month CHECK (EXTRACT(DAY FROM month) = 1)
);
