# Project Brief: Grid in SQL · Finland's Living Energy Observatory

*Last updated: November 2026. Every metric and finding below is measured from the live multi-source warehouse, automated pipelines, analytical models, and the 222-test automated test suite.*

---

## 1. Executive Summary

**Grid in SQL** is a production-grade time-series data warehouse, econometric modeling engine, and interactive observatory built on real, multi-source open energy data. It ingests 36 live datasets from Fingrid (Finland's transmission system operator), numerical weather predictions from FMI and Open-Meteo, hydrological reservoir levels from SYKE and NVE, wholesale electricity prices from ENTSO-E, pan-European power and emissions benchmarks from Ember, industrial output indices from Statistics Finland, and electric vehicle fleet statistics from Traficom.

Rather than merely displaying raw charts, the platform answers systemic questions across power grid physics, market dynamics, and forecasting accuracy:
- **How far off are TSO forecasts?** Day-ahead wind forecasts miss by 442 MW on average (4.7% of fleet capacity) with an upward bias of +171 MW; intraday updates halve the error.
- **When will electricity be cleanest tomorrow?** A day-ahead SQL linear regression model identifies the cleanest 3-hour charging windows, outperforming naive baselines by 37%.
- **Where does an extra MW of wind go?** Econometric panel regressions with Newey-West (HAC) standard errors reveal that ~54% replaces imports (leaving primarily via northern Sweden), 11% displaces hydro, 15% displaces thermal/CHP plants, and 20% induces higher consumption.
- **Does wind depress wholesale prices?** Across three years of ENTSO-E day-ahead hourly prices, each additional GW of forecast wind lowers Finnish power prices by 18.5 €/MWh, with stronger dampening when reservoirs are full (20.8 €/MWh/GW).
- **How did major industrial strikes impact national demand?** A machine-learning counterfactual analysis of the 4-week March-April 2024 Finnish transport and port strikes shows a 1,148 MW demand reduction (11%, or 769 GWh), confirmed via 40-period placebo tests.
- **How does Finland compare across Europe?** Analysis of 34 countries shows Finland having the lowest wholesale price (55.5 €/MWh) and 4th cleanest grid (74 gCO2e/kWh), powered largely by nuclear (38%) and hydro (16%).

The system is backed by a monthly partitioned PostgreSQL 15 warehouse, automated daily CI/CD refresh pipelines on GitHub Actions, a React 19 + TypeScript + Vite cockpit on GitHub Pages, and 222 automated tests in eight layers.

| | |
|---|---|
| Repository | `miladgk/industrial-energy-sql-pipeline` |
| Live Site | [miladgk.github.io/industrial-energy-sql-pipeline](https://miladgk.github.io/industrial-energy-sql-pipeline/) |
| Release Asset | [Warehouse Snapshot (CSV.gz)](https://github.com/miladgk/industrial-energy-sql-pipeline/releases/tag/warehouse-snapshot) |
| Local API | `http://localhost:8000/docs` (FastAPI / Swagger) |

---

## 2. Multi-Source Live Data Architecture

The observatory completely discards synthetic data in favor of 100% real, live telemetry and forecasts refreshed through automated workflows:

```mermaid
flowchart TD
    subgraph Data_Sources["Live Data Providers"]
        FG["Fingrid Open Data API<br/>(36 datasets: power, trade, grid, balancing)"]
        FMI["Finnish Meteorological Institute<br/>(Harmonie & edited forecast archives)"]
        OM["Open-Meteo Previous Runs API<br/>(48h-ahead weather: 15 locations)"]
        HYD["SYKE & NVE APIs<br/>(Reservoirs, lakes, snow, river discharge)"]
        ENT["ENTSO-E Transparency Platform<br/>(Day-ahead power prices: FI, SE1, SE3, EE, NO4)"]
        EMB["Ember Energy API<br/>(34 European countries: prices, generation, CO2)"]
        STAT["Statistics Finland (Tilastokeskus)<br/>(Monthly industrial manufacturing output)"]
        TRAF["Traficom Statistics Database<br/>(EV/PHEV fleet counts & inspection mileage)"]
        CAL["Finnish Calendar Engine<br/>(Astronomical sun elevation & holidays)"]
    end

    subgraph Pipeline["Ingestion & Quality Layer"]
        SYNC["sync_fingrid.py / fmi_forecast.py / openmeteo_forecast.py / hydrology.py / entsoe_prices.py / ember.py / ev_charging.py"]
        GATE["Data Quality Gate<br/>(sql/etl/02_data_quality_checks.sql)"]
    end

    subgraph Warehouse["PostgreSQL 15 Warehouse (JIT = off)"]
        OBS[("fingrid_observation<br/>Monthly Range Partitions<br/>PK: dataset_id, start_time")]
        TABLES[("Specialized Tables<br/>weather_forecast · hydrology_daily<br/>entsoe_price · ember_*")]
    end

    subgraph Analytics["Analytics & Econometric Models"]
        SQL["19 SQL Analysis Modules<br/>(sql/analysis/13_*.sql to 31_*.sql)"]
        MODELS["Python Econometric & ML Models<br/>(Newey-West HAC · Conformal Prediction · GBDT · Diebold-Mariano)"]
    end

    subgraph Delivery["Delivery & Presentation"]
        EXP["export_dashboard_data.py"]
        JSON[("docs/data/*.json")]
        REACT["React 19 + TypeScript Cockpit<br/>(web/ built to web/dist/ on GitHub Pages)"]
        API["FastAPI Local Service<br/>(src/api.py)"]
        SNAP["Daily Snapshot Release<br/>(fingrid_observation.csv.gz)"]
    end

    Data_Sources --> SYNC --> OBS & TABLES
    OBS & TABLES --> GATE --> SQL & MODELS
    SQL & MODELS --> EXP --> JSON --> REACT
    SQL & MODELS --> API
    OBS --> SNAP
```

### The 9 Data Sources
1. **Fingrid Open Data API (36 Datasets):**
   - *Generation & Consumption:* Total production (74), wind power (75), total consumption (124), nuclear power (188), hydro power (191), solar capacity (267), wind capacity (268), battery energy storage discharge (398), and electric boilers (371, 1-minute resolution).
   - *Forecasts:* Day-ahead and intraday consumption (165, 166), wind (246, 245), and solar (247, 248).
   - *Cross-Border Flows & Plant Types:* Net exports (194), Northern Sweden SE1 (60), Central Sweden SE3 (61), Estonia EE (55), Norway NO4 (57), district heating CHP (201), industrial CHP (202), reserve plants (205).
   - *Balancing & Grid Stability:* Imbalance price (319), mFRR up (375), mFRR down (376), mFRR need (377), grid frequency (177, 1-minute), frequency deviations (422, 423), kinetic energy (260), CO2 intensity of consumption (396).
   - *Temperature:* Helsinki (178), Jyväskylä (182), Oulu (196), Rovaniemi (185).
2. **Finnish Meteorological Institute (FMI):** Daily archives of Harmonie numerical forecasts and edited forecasts for 8 Finnish cities and key wind farm regions.
3. **Open-Meteo Previous Runs API:** Hourly temperature and 100-meter wind speed forecasts issued 48 hours in advance for 15 locations across Finland since September 2025.
4. **SYKE (Finland) & NVE (Norway) Hydrology:** Daily reservoir storage for Lokka, Porttipahta, Oulujärvi, Saimaa, and Näsijärvi; snow water equivalent; unregulated Tornionjoki river flow; and Norwegian weekly price-area reservoir levels since 1995.
5. **ENTSO-E Transparency Platform:** Day-ahead wholesale electricity prices (EUR/MWh) for Finland and interconnected zones (SE1, SE3, EE, NO4) at clearing resolution (hourly transitioning to 15-minute).
6. **Ember Energy:** Monthly wholesale day-ahead prices, generation breakdown by source, and lifecycle emissions for 34 European nations since 2015.
7. **Statistics Finland (Tilastokeskus):** Monthly industrial manufacturing output index used to isolate structural changes from weather/calendar variations during labor disputes.
8. **Traficom:** Quarterly vehicle registrations (BEV and PHEV) and mean odometer readings at periodic inspections.
9. **Finnish Astronomical & Calendar Engine:** Computational calendar implementing the Meeus Easter algorithm, statutory holidays, bridge days, and solar elevation angles.

---

## 3. Warehouse Engineering & Benchmarks

### Declarative Partitioning & Optimization
- **Monthly Range Partitioning:** Table `fingrid_observation` is partitioned by month on `start_time` with a composite primary key `(dataset_id, start_time)`. Over 8.9 million rows are managed seamlessly across 40+ partitions.
- **Dynamic Partition Management:** `ensure_fingrid_partitions()` provisions month tables on demand during sync or restore; a default partition catches outliers and is checked to remain empty.
- **Session-Level JIT Disabled:** PostgreSQL JIT compilation is explicitly disabled (`SET jit = off`) via connection options. Because queries span partitioned tables, JIT compilation cost exceeded execution savings, slowing queries by 3× to 6× (e.g. grid event detection slowed from 0.33s to 2.1s with JIT on).
- **Idempotent Ingestion:** The sync pipeline (`src/sync_fingrid.py`) employs an upsert mechanism (`ON CONFLICT (dataset_id, start_time) DO UPDATE`) with a rolling 7-day revision window to absorb Fingrid's retroactively corrected values without duplicate writes.
- **Automated Snapshot Lifecycle:** Daily workflows compress the entire warehouse into a portable gzip CSV (`fingrid_observation.csv.gz`). CI workflows restore this public release artifact, ensuring fast, deterministic testing without hitting third-party API rate limits.

### Index & Partitioning Benchmark
Measured via `scripts/benchmark_warehouse.py` on 1,304,158 rows of real grid frequency (dataset 177, 1-minute resolution, 10,068 matching rows):

| Layout | Median Latency | Speedup vs None | Scan Plan | Partitions Read | Rows Discarded |
|---|---:|---:|---|---|---:|
| Flat table, no index | 52.31 ms | 1.0× | Seq Scan (Parallel) | Entire table | 1,294,089 |
| Flat table, composite PK index | 2.25 ms | 23.3× | Bitmap Index Scan | Entire table | 0 |
| **Monthly partitions + PK index** | **2.00 ms** | **26.1×** | **Bitmap Index Scan** | **fingrid_observation_2026_09** | **0** |

*Key finding:* While the composite index delivers the primary 23× speedup, partition pruning guarantees that index sizes remain bounded and historical data can be archived with zero lock contention.

---

## 4. Analytical Capabilities & Statistical Models

The warehouse implements 19 dedicated analytical queries (`sql/analysis/13` to `31`) and integrated Python scientific modules:

1. **Forecast Scorecard (`sql/analysis/13-17`):** Computes MAE, Bias, RMSE, P95, and WAPE across day-ahead and intraday forecasts. Evaluates net forecast surprise against mFRR balancing activation needs and market imbalance clearing prices.
2. **CO2 Intensity Forecasting (`sql/schema/14`, `sql/analysis/18-19`):** A day-ahead linear model (`regr_slope`, `regr_intercept`) trained on the preceding 60 days of residual load to predict the cleanest charging hours. Replayed over 338 days: 4.5 g/kWh mean error (vs 7.1 g/kWh naive baseline); selects hours emitting 14.8% less CO2 than the daily mean.
3. **Grid Event Detection (`sql/schema/15`, `sql/analysis/20-21`):** Identifies frequency excursions (< 49.9 Hz or > 50.1 Hz), fast nuclear plant trips (> 400 MW drop in 15 min), low-inertia periods (< 120 GWs), and balancing price spikes using SQL `RANGE` window frames and island-gap detection.
4. **Temperature Sensitivity Hinge Model (`sql/analysis/22-23`):** Sweeps heating degree balance points (5–20 °C) via `generate_series` and `regr_r2`. Identifies a 15 °C balance point below which each 1 °C drop adds 154 MW to weekday demand (r² = 0.89).
5. **Wind Allocation Econometric Panel (`sql/analysis/24`, `src/wind_allocation.py`):** Decomposes national power balance ($Consumption = Wind + Nuclear + Hydro + Other + NetImports$) via OLS regression with Newey-West (HAC) heteroskedasticity- and autocorrelation-consistent standard errors. Determines marginal reallocation per border and plant category.
6. **Calibrated Forecast Prediction Ranges (`sql/analysis/25`, `src/forecast_ranges.py`):** Constructs 80% and 95% conformal prediction bands around TSO day-ahead forecasts. Evaluated across 341 days: achieves 79.5% / 93.5% empirical coverage for wind and 79.1% / 93.6% for consumption, improving interval scores by 4–8% over static quantiles.
7. **Weather Model vs TSO Benchmark (`sql/analysis/26`, `src/weather_model.py`):** Trains HistGradientBoosting models on 48h-ahead Open-Meteo forecasts across 15 sites. Rigorous Diebold-Mariano tests confirm Fingrid's proprietary models outperform public weather GBDTs (p = 0.85 and 0.75).
8. **Hydrology & Wind Flexibility Interaction (`sql/analysis/27`, `src/hydro_flex.py`):** Normalizes reservoir levels into z-scores against 2000–2022 historical norms. Proves that hydro flexibility decreases when reservoirs are full: on dry days hydro absorbs 16% of extra wind; on full days it absorbs only 9% (due to spillway and mandatory run-of-river constraints).
9. **Industrial Strike Event Study (`sql/analysis/28`, `src/strike_effect.py`):** Evaluates the 4-week March-April 2024 Finnish transport strike. GBDT counterfactual demand modeling establishes a statistically significant drop of 1,148 MW (11% of consumption, 769 GWh), confirmed against 40 strike-free placebo windows.
10. **Merit-Order & Capture Price Analysis (`sql/analysis/29`, `src/price_wind.py`):** Regresses ENTSO-E spot prices on forecast wind and reservoir interactions. Shows wind reduces spot price by 18.5 €/MWh per GW, earning 66% of base price in 2024 and 55% in 2025.
11. **Pan-European Market Benchmark (`sql/analysis/30`, `src/europe.py`):** Evaluates 34 countries on clean generation, wholesale price, and CO2 emissions. Confirms dirtier grids correlate with higher prices (Spearman r = 0.42, p = 0.03).
12. **Electric Vehicle Charging Grid Impact (`sql/analysis/31`, `src/ev_charging.py`):** Combines Traficom odometer inspection records with 1-minute electric boiler data to decompose nocturnal consumption growth. Confirms EV fleet charging adds ~26 MW to national baseload with distinct nocturnal bias.

---

## 5. Verification & Testing Strategy

The repository is protected by **222 automated tests organized across eight distinct layers**, executing against the restored production warehouse snapshot in CI:

| Layer | Marker | Count | Scope & Verification |
|---|---|---:|---|
| **Smoke** | `smoke` | 15 | Verifies database connectivity, warehouse population, API routes, OpenAPI schema, and integrity of all `docs/data/*.json` files. |
| **API Contract** | `api` | 17 | Validates endpoint schemas, query parameters, type safety, 404/422 handling, caching headers, and SQL equivalency. |
| **Integration** | `integration` | 39 | Verifies ingestion idempotency, partition provisioning, quality checks, snapshot roundtrips, and foreign key integrity. |
| **Regression** | `regression` | 38 | Tests mathematical and statistical algorithms on synthetic test matrices: Newey-West vs OLS, conformal coverage, GBDT convergence, Diebold-Mariano tests, and hinge models. |
| **Performance** | `performance` | 13 | Executes `EXPLAIN (ANALYZE, BUFFERS)` to enforce partition pruning, composite index usage, and strict latency budgets. |
| **Security** | `security` | 23 | Validates injection resistance across all endpoints, error masking (no leaked tracebacks), read-only database roles, and absence of tracked secrets. |
| **Data Contract** | `data` | 12 | Guarantees that exported JSON data files are self-consistent, internally consistent, and byte-for-byte identical to repo SQL definitions. |
| **End-to-End** | `e2e` | 39 | Headless Chromium tests via Playwright: validates live KPI rendering, drawer interactions, SQL lens viewing, keyboard navigation, theme switching, responsive phone layouts (375px), and offline resilience. |
| **Load Testing** | — | — | Locust scenario simulating 20 concurrent users over 30s: p95 latency < 10 ms with cache (CI local). |
| **Static Security** | — | — | Bandit static AST code security scanning and pip-audit automated dependency CVE audits. |

**CI Matrix:** Python 3.11 and 3.12 across PostgreSQL 14, 15, and 16.

---

## 6. Frontend Presentation Cockpit

The web frontend (`web/`) is a high-performance single-page cockpit built with modern technologies:
- **Core Stack:** React 19, TypeScript, Vite, Tailwind CSS, Lucide icons, Framer Motion.
- **Architectural Philosophy:** Zero-server runtime on GitHub Pages. The page loads pre-computed analytical JSON files from `docs/data/` generated directly by `scripts/export_dashboard_data.py`.
- **User Interface Features:**
  - *Cockpit Layout:* Bento grid with deep analytical slide-out drawers.
  - *Interactive Data Exploration:* Conformal prediction band toggles, merit-order price curve explorers, Newey-West regression parameter breakdowns, and strike counterfactual charts.
  - *SQL Lens:* Side-by-side inspection of the raw SQL queries producing each visualization.
  - *Accessibility & Themes:* Full keyboard navigation, ARIA attributes, and seamless switching between Daylight Paper and Obsidian Aurora themes.

---

## 7. Key Measured Facts

*All figures measured over the last 12-month evaluation window (ending November 2026):*

- **Warehouse Volume:** 8.9+ million observations across 40 monthly partitions.
- **Wind Forecast Error:** Mean absolute error of 442 MW (4.7% of total fleet capacity); intraday revisions reduce error to 218 MW.
- **Cold Weather Sensitivity:** +154 MW per degree below 15 °C on weekdays; coldest day (−25 °C) reached 14.8 GW peak demand.
- **Wind Absorption Marginal Shares:** +1 MW of wind = +0.54 MW export, −0.11 MW hydro, −0.15 MW thermal/CHP, +0.20 MW domestic consumption.
- **Merit-Order Price Impact:** −18.5 €/MWh spot price reduction per GW of day-ahead wind forecast.
- **2024 Industrial Strike Impact:** −1,148 MW average consumption loss (769 GWh total, p < 0.001) during the 4-week transport strike.
- **European Wholesale Price Ranking:** Finland wholesale price: 55.5 €/MWh (#1 lowest in Europe; EU demand-weighted mean: 106.5 €/MWh). Grid carbon intensity: 74 gCO2e/kWh (4th cleanest in Europe).
- **EV Fleet Grid Impact:** 218k BEVs and 197k PHEVs consume ~1.1 TWh annually (~1.3% of national demand), adding +26 MW net baseload with dominant nocturnal charging patterns.
