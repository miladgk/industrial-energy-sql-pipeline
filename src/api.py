"""
api.py
~~~~~~
FastAPI service over the Fingrid warehouse (fingrid_observation and the SQL in
sql/schema and sql/analysis). Each analytics endpoint runs the same .sql file
the dashboard export uses, so the API and the published numbers cannot drift.

Endpoints
---------
GET /health                      liveness
GET /api/datasets                the datasets kept, with row counts and coverage
GET /api/latest                  newest stored value of every dataset
GET /api/forecast-scorecard      error of Fingrid's day-ahead and intraday forecasts
GET /api/forecast-error-by-hour  the same per hour of the day (Finnish time)
GET /api/co2-forecast            hourly CO2 intensity forecast for one Finnish day
GET /api/grid-events             frequency, nuclear, inertia and price events
GET /api/temperature-sensitivity how much each degree of cold raises consumption

Caching
-------
The warehouse changes once a day, so each query result is kept for
API_CACHE_SECONDS (default 300) and concurrent requests for the same query
wait for one database run instead of each starting their own. Set
API_CACHE_SECONDS=0 to always query (the tests do).

Usage
-----
    uvicorn src.api:app --reload --port 8000
Then open http://localhost:8000/docs (interactive Swagger UI).
"""

import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(__file__))
from analysis_window import default_window, tomorrow_fi  # noqa: E402
from db_connection import get_connection  # noqa: E402

logger = logging.getLogger("energy_api")
ANALYSIS_DIR = os.path.join(os.path.dirname(__file__), "..", "sql", "analysis")

VARIABLE_PATTERN = r"^(wind|consumption)$"
EVENT_KIND_PATTERN = r"^(frequency_low|frequency_high|nuclear_drop|low_inertia|price_spike)$"
MAX_DAYS = 400


def _sql(name: str) -> str:
    with open(os.path.join(ANALYSIS_DIR, name), encoding="utf-8") as fh:
        return fh.read()


# Loaded once at start-up: the endpoints run exactly these files.
SQL = {
    "scorecard": _sql("13_forecast_scorecard.sql"),
    "by_hour": _sql("14_forecast_error_by_hour.sql"),
    "co2": _sql("18_co2_forecast.sql"),
    "events": _sql("20_grid_events.sql"),
    "temperature": _sql("23_temperature_sensitivity.sql"),
}

app = FastAPI(
    title="Finnish Grid Analytics API",
    description="Analytics over real Fingrid Open Data (CC BY 4.0), stored in a partitioned PostgreSQL warehouse.",
    version="2.0.0",
)

allowed_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_cache: dict = {}                    # (sql, params) -> (expires_at, rows)
_cache_locks: dict = {}
_cache_guard = threading.Lock()


def _cache_seconds() -> float:
    return float(os.environ.get("API_CACHE_SECONDS", 300))


def _fetch_rows(sql: str, params=None) -> list[dict]:
    """Rows of *sql*, from the cache while fresh (see Caching above); copies, so callers may change them."""
    ttl = _cache_seconds()
    if ttl <= 0:
        return _query(sql, params)
    key = (sql, tuple(sorted(params.items())) if isinstance(params, dict) else params)
    with _cache_guard:
        lock = _cache_locks.setdefault(key, threading.Lock())
    with lock:                                   # one database run per key, however many requests wait
        hit = _cache.get(key)
        if hit is None or hit[0] < time.monotonic():
            hit = (time.monotonic() + ttl, _query(sql, params))
            _cache[key] = hit
    return [dict(r) for r in hit[1]]


def _query(sql: str, params=None) -> list[dict]:
    """Run *sql* in a read-only transaction and return the rows as JSON-safe dicts."""
    conn = get_connection()
    try:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_make_json_safe(dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()


def _make_json_safe(row: dict) -> dict:
    """Datetimes become ISO strings and Decimals floats; everything else is left alone."""
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            row[key] = value.isoformat()
        elif isinstance(value, Decimal):
            row[key] = float(value)
        elif isinstance(value, timedelta):
            row[key] = value.total_seconds()
    return row


def _internal_error(exc: Exception) -> HTTPException:
    """Log the real error server-side; give the client a generic message
    (raw database errors can reveal table names, queries and host details)."""
    logger.exception("Request failed: %s", exc)
    return HTTPException(status_code=500, detail="Internal server error")


def _window(days: int) -> dict:
    w = default_window(days=days)
    return {"start": w["start"], "end": w["end"]}


def _window_json(w: dict) -> dict:
    return {"start": w["start"].date().isoformat(), "end_exclusive": w["end"].date().isoformat()}


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health_check():
    """Liveness probe: 200 if the API process is running."""
    return {"status": "ok"}


@app.get("/api/datasets", tags=["warehouse"])
def datasets():
    """Every Fingrid dataset in the warehouse with its row count and time coverage."""
    try:
        # Counts come from fingrid_dataset_summary (sql/schema/18), refreshed by every load:
        # counting ten million rows per request would take seconds.
        rows = _fetch_rows("""
            SELECT d.dataset_id, d.key, d.name, d.unit, d.kind, d.resolution,
                   COALESCE(s.rows, 0) AS rows, s.first_start, s.last_end
            FROM fingrid_dataset d
            LEFT JOIN fingrid_dataset_summary s USING (dataset_id)
            ORDER BY d.dataset_id
        """)
    except Exception as exc:
        raise _internal_error(exc)
    return {"datasets": rows, "total_rows": sum(r["rows"] for r in rows)}


@app.get("/api/latest", tags=["warehouse"])
def latest():
    """The newest stored value of every dataset (slots that have ended; day-ahead forecasts may lie ahead)."""
    try:
        rows = _fetch_rows("""
            SELECT d.dataset_id, d.key, d.unit, o.start_time, o.end_time, o.value
            FROM fingrid_dataset d
            CROSS JOIN LATERAL (
                SELECT start_time, end_time, value FROM fingrid_observation x
                WHERE x.dataset_id = d.dataset_id ORDER BY start_time DESC LIMIT 1
            ) o
            ORDER BY d.dataset_id
        """)
    except Exception as exc:
        raise _internal_error(exc)
    return {"latest": rows}


@app.get("/api/forecast-scorecard", tags=["analytics"])
def forecast_scorecard(days: int = Query(365, ge=1, le=MAX_DAYS, description="Window: the last N complete UTC days")):
    """How far Fingrid's own forecasts were from what happened (sql/analysis/13_forecast_scorecard.sql)."""
    w = _window(days)
    try:
        rows = _fetch_rows(SQL["scorecard"], w)
    except Exception as exc:
        raise _internal_error(exc)
    return {"window": _window_json(w), "products": rows}


@app.get("/api/forecast-error-by-hour", tags=["analytics"])
def forecast_error_by_hour(
    variable: str = Query("wind", pattern=VARIABLE_PATTERN),
    days: int = Query(365, ge=1, le=MAX_DAYS),
):
    """Mean absolute error and bias per hour of the day, Finnish time (sql/analysis/14)."""
    w = _window(days)
    try:
        rows = [r for r in _fetch_rows(SQL["by_hour"], w) if r["variable"] == variable]
    except Exception as exc:
        raise _internal_error(exc)
    return {"window": _window_json(w), "variable": variable, "hours": rows}


@app.get("/api/co2-forecast", tags=["analytics"])
def co2_forecast(day: Optional[date] = Query(None, description="Finnish calendar day (default: tomorrow)")):
    """Hourly CO2 intensity forecast for one day (sql/analysis/18 -> co2_forecast() in sql/schema/14)."""
    tomorrow = tomorrow_fi()                 # Finnish dates: the day boundary is Helsinki midnight
    day = day or tomorrow
    if not (tomorrow - timedelta(days=MAX_DAYS + 1) <= day <= tomorrow + timedelta(days=1)):
        raise HTTPException(status_code=422,
                            detail=f"day must be within {MAX_DAYS} days back and the day after tomorrow (Finnish time)")
    try:
        rows = _fetch_rows(SQL["co2"], {"day": day})
    except Exception as exc:
        raise _internal_error(exc)
    if not rows:
        raise HTTPException(status_code=404, detail="No forecast inputs for that day (yet)")
    return {"day": day.isoformat(), "unit": "gCO2/kWh", "hours": rows}


@app.get("/api/grid-events", tags=["analytics"])
def grid_events(
    days: int = Query(30, ge=1, le=MAX_DAYS),
    kind: Optional[str] = Query(None, pattern=EVENT_KIND_PATTERN),
    limit: int = Query(100, ge=1, le=1000),
):
    """Unusual moments on the grid, newest first (sql/analysis/20 -> grid_events() in sql/schema/15)."""
    w = _window(days)
    try:
        rows = _fetch_rows(SQL["events"], w)
    except Exception as exc:
        raise _internal_error(exc)
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return {"window": _window_json(w), "count": len(rows), "events": rows[:limit]}


@app.get("/api/temperature-sensitivity", tags=["analytics"])
def temperature_sensitivity(days: int = Query(365, ge=30, le=MAX_DAYS)):
    """Extra consumption per degree of cold below the fitted balance point, per day type (sql/analysis/23)."""
    w = _window(days)
    try:
        rows = _fetch_rows(SQL["temperature"], w)
    except Exception as exc:
        raise _internal_error(exc)
    return {"window": _window_json(w), "fits": rows}
