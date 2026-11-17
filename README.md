# Grid in SQL: Finland's electricity grid in a PostgreSQL warehouse

[![CI Pipeline](https://github.com/miladgk/industrial-energy-sql-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/miladgk/industrial-energy-sql-pipeline/actions/workflows/ci.yml)
![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)
![PostgreSQL 14-16](https://img.shields.io/badge/postgres-14--16-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

**Live site:** [miladgk.github.io/industrial-energy-sql-pipeline](https://miladgk.github.io/industrial-energy-sql-pipeline/)
· **Data download:** [warehouse snapshot](https://github.com/miladgk/industrial-energy-sql-pipeline/releases/tag/warehouse-snapshot) (CSV)

Fingrid, Finland's electricity transmission system operator, publishes hundreds of
measurements and forecasts as [open data](https://data.fingrid.fi), one chart at a
time. This project keeps 28 of them in a partitioned PostgreSQL warehouse, refreshed
every day, and answers questions no single chart does:

| Question | Answer over the last 12 months | Where |
|---|---|---|
| How far off are Fingrid's own forecasts? | Day-ahead wind misses by 442 MW on average (4.7% of the fleet) and runs 171 MW too high; the intraday update halves the miss. Consumption: 328 MW (3.3%). | `sql/analysis/13-17` |
| When will electricity be cleanest tomorrow? | A day-ahead CO2-intensity forecast in SQL. Replayed over 338 days: 4.5 g/kWh mean error vs 7.1 for a naive baseline; the hour it picks emitted 14.8% less than an average hour (19.7% for a perfect pick). | `sql/schema/14`, `sql/analysis/18-19` |
| What unusual happened on the grid? | 802 frequency excursions, 6 fast nuclear drops, 14 low-inertia periods, 12 imbalance-price spikes. The minute before a full hour is out of band 2.1x as often as an average minute. | `sql/schema/15`, `sql/analysis/20-21` |
| How much does cold raise demand? | Below about 15 °C each degree colder adds 154 MW on a weekday (1.5% of average use; r² 0.89). The coldest day (-25 °C) used 14.8 GW, 1.8x the warmest. | `sql/analysis/22-23` |
| Where does an extra MW of wind go? | About 54% replaces imports (74% in summer), 11% replaces hydro, 15% other production (25% in winter, when CHP runs) and 20% is matched by higher consumption. Extra nuclear brings the same +20% consumption, which points to demand following cheap power rather than to wind chill. | `sql/analysis/24`, `src/wind_allocation.py` |

Numbers as of November 2026; the site always shows the current ones.

Everything is real data. Where the data does not support a claim, the site says so:
solar forecasts are not scored because Fingrid publishes no measured solar output;
the CO2 forecast is a guide to *which* hours are cleaner, not an exact value; and
Finnish nuclear drops and the Nordic-wide frequency rarely confirm each other, so
nuclear trips are not used as labels for the event detector.

---

## Architecture

```mermaid
flowchart LR
    F[Fingrid Open Data API<br/>28 datasets] -->|sync_fingrid.py<br/>incremental, idempotent| W[(PostgreSQL<br/>fingrid_observation<br/>monthly partitions)]
    W --> Q[Quality gate<br/>02_data_quality_checks.sql]
    W --> S[SQL views, functions<br/>sql/analysis/*.sql]
    S --> E[export_dashboard_data.py] --> J[docs/data/*.json] --> P[GitHub Pages<br/>static dashboard]
    S --> A[FastAPI<br/>src/api.py]
    W -->|warehouse_snapshot.py dump| R[Release asset<br/>fingrid_observation.csv.gz]
    R -->|restore| W
```

**Daily refresh** (`.github/workflows/refresh_fingrid.yml`, 10:53 UTC, after Fingrid
publishes the next day's forecasts at 12:00 Finnish time): start PostgreSQL, restore
yesterday's warehouse from the release asset, sync the last 7 days from Fingrid,
publish the new snapshot, run the analyses, commit the dashboard JSON and redeploy
Pages. A normal run takes about 2 minutes and some 30 API requests. No server runs between
refreshes.

**Hourly** (`pages.yml`): the newest wind and consumption values are fetched and
deployed with the page, without a commit.

**CI** (`ci.yml`, every pull request): restores the same public snapshot, so every
test runs against real data and needs no Fingrid key.

---

## The warehouse

```
fingrid_dataset (28 rows)                fingrid_observation (~2 M rows, ~1.8 M more a year)
  dataset_id  PK                           dataset_id  FK -> fingrid_dataset   ┐ primary key
  key, name, unit                          start_time  partition key           ┘
  kind  actual | forecast | capacity |     end_time
        balancing | emission |              value       exactly as published
        system | weather
  resolution                               fetched_at
                                         PARTITION BY RANGE (start_time): one table per month + default
```

- **Raw values only.** One row per dataset and time slot, as Fingrid publishes it: no
  resampling, no gap filling, no clamping. Analyses decide how to treat gaps.
- **Incremental and idempotent** (`src/sync_fingrid.py`): an empty dataset is backfilled
  400 days; otherwise the sync re-reads from the newest stored slot minus 7 days, because
  Fingrid revises recent values. Rows are upserted on the primary key and an unchanged
  value is not rewritten, so a second run changes nothing. Request windows are sized
  from each dataset's resolution so one window fits one API page (1-minute frequency
  goes in 13-day windows).
- **Only ended slots**, except the three day-ahead forecasts (consumption, wind, solar),
  which are published once for the next day and never revised; the CO2 forecast for
  tomorrow needs them (`fingrid_catalog.STORE_FUTURE`).
- **Partitioned by month.** Every query filters one dataset and a time range, so
  PostgreSQL reads only the months it needs. `ensure_fingrid_partitions()` creates
  months on demand (the sync and the restore call it before writing); a default
  partition catches anything else and is checked to stay empty.
- **JIT off** for every session (`src/db_connection.py`): on the partitioned table the
  planner's cost estimate crossed the JIT threshold and compiling cost more than it
  saved, making the analyses 3-6x slower.
- **Snapshot** (`src/warehouse_snapshot.py`): the whole table as one gzip CSV (~9 MB).
  Restoring keeps rows already present, creates only the months it needs, and skips
  datasets the running code does not know, so an older checkout can always read a
  newer snapshot. Only `main` publishes it.

### Benchmark

`scripts/benchmark_warehouse.py` runs the same query (one week of 1-minute frequency,
10,068 of 1,304,158 rows) on three layouts of the real data and writes
[`benchmarks/index_benchmark.md`](benchmarks/index_benchmark.md):

| Layout | Median |
|---|---:|
| Flat table, no index (reads and discards 1.29 M rows) | 52.3 ms |
| Flat table, primary-key index | 2.3 ms |
| Monthly partitions + index (reads one partition) | 2.0 ms |

The index makes the query ~23x faster. Partitioning is about as fast on a single
lookup; it pays off as the table grows (small per-month indexes, old months dropped
whole). `tests/test_performance.py` checks the plans with EXPLAIN in CI.

### The datasets

| Purpose | Fingrid datasets |
|---|---|
| What happened | 74 production, 75 wind, 124 consumption, 188 nuclear, 191 hydro, 398 battery discharge (3-min) |
| Trade | 194 measured net export (3-min; positive = export, so it is negated into net imports) |
| Fingrid's forecasts | 165/166 consumption, 245/246 wind, 247/248 solar (day-ahead / every 15 min) |
| Capacity behind them | 267 solar, 268 wind |
| Balancing | 319 imbalance price, 375/376 activated mFRR up/down, 377 mFRR need |
| CO2 and stability | 396 CO2 intensity of consumption, 260 kinetic energy, 422/423 frequency deviation, 177 frequency (1-min) |
| Weather | 178 Helsinki, 182 Jyväskylä, 196 Oulu, 185 Rovaniemi temperature (3-min) |

Listed with their purpose in `src/fingrid_catalog.py`.

---

## The analyses

All logic lives in SQL; the API, the reports and the dashboard export run the same files.

| File | What it does | Techniques |
|---|---|---|
| `sql/schema/13_fingrid_warehouse.sql` | tables, partitions, `forecast_vs_actual` view | declarative partitioning, PL/pgSQL, in-place migration |
| `sql/analysis/13_forecast_scorecard.sql` | MAE, bias, RMSE, P95, WAPE per forecast | ordered-set aggregates |
| `sql/analysis/14-16` | error by Finnish hour, by month, the worst days | `AT TIME ZONE`, `ROW_NUMBER()` |
| `sql/analysis/17_forecast_error_vs_balancing.sql` | day-ahead surprise vs mFRR need and activation, imbalance price | binning, `corr()` |
| `sql/schema/14_co2_forecast.sql` | `co2_forecast()`: line of CO2 intensity on residual load, refitted per day on the 60 days ending two days earlier, level-corrected, floored at the training minimum | set-returning SQL function, `regr_slope`, `regr_intercept` |
| `sql/analysis/18-19` | tomorrow's hours and cleanest 3-hour window; the backtest | window frames, `RANK()` |
| `sql/schema/15_grid_events.sql` | `grid_events()`: frequency outside 49.9-50.1 Hz, nuclear drops of 400 MW in 15 min, lowest-1% inertia, price spikes; each nuclear drop cross-checked against frequency | `RANGE` window frames, gaps and islands, `LATERAL` |
| `sql/analysis/21_frequency_by_minute.sql` | out-of-band frequency by minute of the hour | `FILTER` aggregates |
| `sql/analysis/22_temperature_daily.sql` | daily four-city temperature and national consumption | two-level aggregation, `HAVING` |
| `sql/analysis/23_temperature_sensitivity.sql` | hinge model per day type; the balance point (5-20 °C) is searched in SQL, best r² kept | `generate_series` grid, `regr_r2`, `DISTINCT ON` |
| `sql/analysis/24_wind_allocation_panel.sql` + `src/wind_allocation.py` | the hourly power balance (consumption = wind + nuclear + hydro + other + net imports); each part regressed on wind, nuclear and heating degrees with hour, weekday and month fixed effects, Newey-West (HAC) 95% intervals, per season | `FILTER` pivot, completeness rules; numpy OLS + HAC |
| `sql/etl/02_data_quality_checks.sql` | default partition empty, no empty or stale dataset, 30-day coverage, 0 Hz gap markers | |

---

## API

`make api`, then open http://localhost:8000/docs.

| Endpoint | Returns |
|---|---|
| `GET /api/datasets` | every dataset with its row count and coverage |
| `GET /api/latest` | the newest stored value of each dataset |
| `GET /api/forecast-scorecard?days=365` | forecast errors (13) |
| `GET /api/forecast-error-by-hour?variable=wind` | the same per Finnish hour (14) |
| `GET /api/co2-forecast?day=YYYY-MM-DD` | hourly CO2 forecast for one day (18); default tomorrow |
| `GET /api/grid-events?days=30&kind=nuclear_drop` | grid events, newest first (20) |
| `GET /api/temperature-sensitivity?days=365` | MW per degree of cold, balance point, r² per day type (23) |

Every parameter is validated (ranges, allow-lists, typed dates); queries run in
read-only transactions; database errors reach the client as a generic 500. The API is
not hosted: the site reads static JSON built from the same SQL, so it never waits for
a server.

---

## Tests

137 tests in eight layers, all run in CI on Python 3.11/3.12 and PostgreSQL 14/15/16,
against the restored real warehouse:

| Layer | What it guards |
|---|---|
| smoke | database, warehouse, API routes and dashboard files are alive |
| api | response shapes, validation, every number equals its SQL file |
| integration | sync, idempotency, revisions, snapshot round trip, partition layout, quality gate |
| regression | hand-made datasets with exact answers through the scorecard, CO2 model, event detector and wind-allocation model (incl. Newey-West vs OLS) |
| performance | EXPLAIN shows pruning and index use; generous latency budgets |
| security | injection payloads rejected, no error leakage, read-only sessions, no secrets in git |
| data | published JSON is internally consistent and matches the SQL in the repo |
| e2e | Chromium: numbers come from the data files, no foreign requests, charts, keyboard, inspector drawer, theme, phone layout, one broken file does not break the page |

Plus a Locust load test, bandit and pip-audit in CI.

---

## Run it yourself

```bash
git clone https://github.com/miladgk/industrial-energy-sql-pipeline.git
cd industrial-energy-sql-pipeline
cp config_template.yaml config.yaml          # database credentials match docker-compose.yml
pip install -r requirements.txt
docker compose up -d                         # PostgreSQL
make db-setup snapshot-restore quality-checks   # the published warehouse, no API key needed
make api                                     # http://localhost:8000/docs
make test                                    # e2e needs: pip install playwright && playwright install chromium
```

To sync new data yourself, add a free key from [data.fingrid.fi](https://data.fingrid.fi)
as `fingrid_api_key` in `config.yaml` (git-ignored) and run `make sync`; an empty
warehouse backfills 400 days in about 15 minutes. `make export` rebuilds the dashboard
files, `make report` writes every analysis to `outputs/*.csv`, `make benchmark`
re-measures the layouts.

For the daily workflow on a fork, add the key as the repository secret
`FINGRID_API_KEY` (Settings -> Secrets and variables -> Actions).

---

## Project structure

```
├── .github/workflows/
│   ├── ci.yml                  # tests, security scan, load test on every PR
│   ├── refresh_fingrid.yml     # daily: restore, sync, snapshot, analyses, redeploy
│   └── pages.yml               # deploy + hourly latest values
├── benchmarks/index_benchmark.md
├── docs/                       # the static dashboard (GitHub Pages)
│   ├── index.html
│   └── data/*.json             # built by scripts/export_dashboard_data.py
├── scripts/
│   ├── export_dashboard_data.py
│   └── benchmark_warehouse.py
├── sql/
│   ├── schema/                 # 13 warehouse, 14 CO2 model, 15 event detector
│   ├── analysis/               # 13-24, one query per file
│   └── etl/02_data_quality_checks.sql
├── src/
│   ├── fingrid_api.py          # API client (key, paging, retries, 429 back-off)
│   ├── fingrid_catalog.py      # the 28 datasets and why
│   ├── sync_fingrid.py         # incremental, idempotent sync
│   ├── warehouse_snapshot.py   # dump / restore as CSV.gz
│   ├── setup_db.py             # applies sql/schema
│   ├── run_quality_checks.py   # the quality gate
│   ├── run_report.py           # every analysis -> outputs/*.csv
│   ├── analysis_window.py      # default parameters for the analysis SQL
│   ├── wind_allocation.py      # fixed-effects regression with Newey-West intervals
│   ├── db_connection.py
│   └── api.py                  # FastAPI
└── tests/                      # eight layers + load/locustfile.py
```

---

Data: [Fingrid Open Data](https://data.fingrid.fi), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Code: MIT.
