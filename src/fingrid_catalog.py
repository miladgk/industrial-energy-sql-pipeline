"""
fingrid_catalog.py
~~~~~~~~~~~~~~~~~~
The Fingrid Open Data datasets this warehouse keeps, and why.

Names and units are copied from the API's own catalogue
(GET https://data.fingrid.fi/api/datasets); resolutions are what the data
actually contains (frequency, listed there as 3 min, arrives every minute).
The sync uses the resolution to size its request windows so that each one
fits in a single API page.

ensure_catalog() writes the list into the fingrid_dataset table; the sync and
the snapshot restore call it first, because observations reference it.
"""

from datetime import timedelta

M1 = timedelta(minutes=1)
M3 = timedelta(minutes=3)
Q = timedelta(minutes=15)
H = timedelta(hours=1)

# (dataset_id, key, name, unit, kind, resolution)
DATASETS = [
    # What actually happened
    (74,  "production",              "Electricity production in Finland",                          "MW",       "actual",    Q),
    (75,  "wind",                    "Wind power generation - 15 min data",                        "MW",       "actual",    Q),
    (124, "consumption",             "Electricity consumption in Finland",                         "MW",       "actual",    Q),
    # Fingrid's own forecasts (scored in sql/analysis/13-17)
    (165, "consumption_fc_day_ahead", "Electricity consumption forecast - updated once a day",     "MW",       "forecast",  Q),
    (166, "consumption_fc_intraday", "Electricity consumption forecast - updated every 15 minutes", "MW",       "forecast",  Q),
    (245, "wind_fc_intraday",        "Wind power generation forecast - updated every 15 minutes",  "MW",       "forecast",  Q),
    (246, "wind_fc_day_ahead",       "Wind power generation forecast - updated once a day",        "MW",       "forecast",  Q),
    (247, "solar_fc_day_ahead",      "Solar power generation forecast - updated once a day",       "MW",       "forecast",  Q),
    (248, "solar_fc_intraday",       "Solar power generation forecast - updated every 15 minutes", "MW",       "forecast",  Q),
    # Installed capacity Fingrid uses in those forecasts
    (267, "solar_capacity",          "Total production capacity used in the solar power forecast", "MW",       "capacity",  H),
    (268, "wind_capacity",           "Total production capacity used in the wind power forecast",  "MW",       "capacity",  H),
    # What balancing the grid cost
    (319, "imbalance_price",         "Imbalance price",                                            "EUR/MWh",  "balancing", Q),
    (375, "mfrr_up",                 "Activated mFRR balancing regulation upward sum",             "MW",       "balancing", Q),
    (376, "mfrr_down",               "Activated mFRR balancing regulation downward sum",           "MW",       "balancing", Q),
    (377, "mfrr_need",               "mFRR need",                                                  "MW",       "balancing", Q),
    # For the next phases: CO2 intensity and grid stability
    (396, "co2_consumed",            "Emission factor for electricity consumed in Finland - updated every 15 minutes", "gCO2/kWh", "emission", Q),
    (260, "kinetic_energy",          "Kinetic energy of the Nordic power system - real time data", "GWs",      "system",    Q),
    (422, "under_frequency",         "Average under-frequency deviation",                          "Hz",       "system",    Q),
    (423, "over_frequency",          "Average over-frequency deviation",                           "Hz",       "system",    Q),
    # Grid events (sql/schema/15_grid_events.sql)
    (188, "nuclear",                 "Nuclear power production - real-time data",                  "MW",       "actual",    M3),
    (177, "frequency",               "Frequency - real-time data",                                 "Hz",       "system",    M1),
]

BY_ID = {d[0]: d for d in DATASETS}

# Day-ahead forecasts are published once (at 12:00 Finnish time, for the next day)
# and never revised, so their future slots can be stored safely. The CO2 forecast
# for tomorrow (sql/schema/14_co2_forecast.sql) needs them. Every other dataset,
# including the 15-minute-updated forecasts, is stored only once its slot has ended.
STORE_FUTURE = {165, 246, 247}

_UPSERT = """
    INSERT INTO fingrid_dataset (dataset_id, key, name, unit, kind, resolution)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (dataset_id) DO UPDATE SET
        key = EXCLUDED.key, name = EXCLUDED.name, unit = EXCLUDED.unit,
        kind = EXCLUDED.kind, resolution = EXCLUDED.resolution
"""


def ensure_catalog(conn, datasets=DATASETS) -> None:
    """Insert or update the dataset rows (idempotent)."""
    with conn.cursor() as cur:
        cur.executemany(_UPSERT, datasets)
    conn.commit()
