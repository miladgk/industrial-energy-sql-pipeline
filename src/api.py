"""
api.py
~~~~~~
A lightweight FastAPI service that serves the engineered data over HTTP.
This transforms the project from a "collection of scripts" into a
deployable data product.

Endpoints
---------
GET /api/anomalies
    Returns statistical anomalies (z-score > threshold) detected in the
    readings table, with optional query parameters for filtering.

GET /api/detection-quality
    Scores the z-score detector against the faults injected by the data
    generator: precision and recall per sensor type, split into spikes and
    zero-value dropouts.

GET /api/facilities/ranking
    Returns all facilities ranked by average output as a share of nameplate
    capacity (capacity factor) over the available data window.

GET /health
    Simple liveness check.

Usage
-----
    uvicorn src.api:app --reload --port 8000

Then open:  http://localhost:8000/docs  (auto-generated Swagger UI)
"""

import os
import sys
from typing import Optional

import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(__file__))
from db_connection import get_connection


app = FastAPI(
    title="Energy Facility Analytics API",
    description=(
        "Serves operational analytics from the energy facility "
        "PostgreSQL database."
    ),
    version="1.0.0",
)

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
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

def _fetch_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Execute *sql* and return all rows as a list of dicts."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health_check():
    """Liveness probe — returns 200 if the API process is running."""
    return {"status": "ok"}


@app.get("/api/overview", tags=["analytics"])
def get_overview():
    """Return the current dashboard KPIs and latest reading timestamp."""
    sql = """
        SELECT
            (SELECT COUNT(*) FROM facilities) AS facility_count,
            (SELECT COUNT(*) FROM sensors) AS sensor_count,
            (SELECT COUNT(*) FROM readings) AS reading_count,
            (SELECT COUNT(*) FROM readings WHERE is_anomaly = TRUE) AS anomaly_count,
            (SELECT MAX(recorded_at) FROM readings) AS latest_reading_at,
            (SELECT AVG(value) FROM readings r
             JOIN sensors s ON s.sensor_id = r.sensor_id
             WHERE s.sensor_type = 'power_output'
               AND r.is_anomaly = FALSE) AS avg_power_output_mw
    """
    try:
        row = _fetch_rows(sql)[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    for key, value in row.items():
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
        elif hasattr(value, "__float__"):
            row[key] = float(value)
    row["anomaly_rate_pct"] = (
        round(row["anomaly_count"] / row["reading_count"] * 100, 2)
        if row["reading_count"]
        else 0
    )
    return row


@app.get("/api/output-trend", tags=["analytics"])
def get_output_trend(
    hours: int = Query(default=24, ge=1, le=168),
    facility_type: Optional[str] = Query(default=None),
):
    """Return hourly average power output for the dashboard trend chart."""
    type_filter = "AND f.facility_type = %s" if facility_type else ""
    params: tuple = (facility_type,) if facility_type else ()
    sql = f"""
        SELECT
            DATE_TRUNC('hour', r.recorded_at) AS recorded_at,
            ROUND(AVG(r.value)::NUMERIC, 2) AS avg_output_mw,
            COUNT(*) AS reading_count
        FROM readings r
        JOIN sensors s ON s.sensor_id = r.sensor_id
        JOIN facilities f ON f.facility_id = s.facility_id
        WHERE s.sensor_type = 'power_output'
          AND r.is_anomaly = FALSE
          AND r.recorded_at >= (
              SELECT MAX(recorded_at) FROM readings
          ) - (%s * INTERVAL '1 hour')
          {type_filter}
        GROUP BY DATE_TRUNC('hour', r.recorded_at)
        ORDER BY recorded_at
    """
    try:
        rows = _fetch_rows(sql, (hours,) + params)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    for row in rows:
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            elif hasattr(value, "__float__"):
                row[key] = float(value)
    return {"hours": hours, "facility_type": facility_type, "points": rows}


@app.get("/api/anomalies", tags=["analytics"])
def get_anomalies(
    z_threshold: float = Query(
        default=3.0,
        ge=1.0,
        le=10.0,
        description="Z-score threshold above which a reading is flagged as anomalous.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of anomalies to return.",
    ),
    facility_type: Optional[str] = Query(
        default=None,
        description="Filter by facility type: 'wind', 'solar', or 'substation'.",
    ),
):
    """
    Return statistical anomalies detected via z-score analysis.

    A reading is considered anomalous when its value deviates more than
    *z_threshold* standard deviations from that sensor's monthly mean,
    calculated using only non-flagged (clean) readings as the baseline.
    """
    type_filter = "AND f.facility_type = %s" if facility_type else ""
    params: tuple = (facility_type,) if facility_type else ()

    sql = f"""
        WITH sensor_monthly_stats AS (
            SELECT
                sensor_id,
                DATE_TRUNC('month', recorded_at)  AS month,
                AVG(value)                        AS mean_val,
                STDDEV(value)                     AS stddev_val
            FROM readings
            WHERE is_anomaly = FALSE
            GROUP BY sensor_id, DATE_TRUNC('month', recorded_at)
        ),
        scored AS (
            SELECT
                r.reading_id,
                r.sensor_id,
                r.recorded_at,
                r.value,
                r.is_anomaly                         AS pre_labelled,
                CASE
                    WHEN s.stddev_val > 0
                    THEN ABS(r.value - s.mean_val) / s.stddev_val
                    ELSE 0
                END                                  AS z_score,
                f.facility_name,
                f.facility_type,
                se.sensor_type,
                se.unit
            FROM readings r
            JOIN sensor_monthly_stats s
              ON  r.sensor_id = s.sensor_id
              AND DATE_TRUNC('month', r.recorded_at) = s.month
            JOIN sensors    se ON r.sensor_id    = se.sensor_id
            JOIN facilities f  ON se.facility_id = f.facility_id
            WHERE 1=1 {type_filter}
        )
        SELECT *
        FROM scored
        WHERE z_score > %s
        ORDER BY z_score DESC
        LIMIT %s
    """

    try:
        rows = _fetch_rows(sql, params + (z_threshold, limit))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Convert Decimal / datetime to JSON-serialisable types
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            elif hasattr(v, "__float__"):
                row[k] = float(v)

    return {
        "z_threshold"    : z_threshold,
        "facility_type"  : facility_type,
        "count"          : len(rows),
        "anomalies"      : rows,
    }


@app.get("/api/detection-quality", tags=["analytics"])
def get_detection_quality(
    z_threshold: float = Query(
        default=3.0,
        ge=1.0,
        le=10.0,
        description="Z-score threshold used by the detector (same rule as /api/anomalies).",
    ),
):
    """
    Score the z-score detector against the injected faults (ground truth).

    The synthetic generator labels every fault it injects (is_anomaly), and a
    fault is either a zero-value dropout or a spike at three times the sensor's
    normal maximum. The labels are used only to build a clean baseline (the
    monthly mean and standard deviation of non-injected readings); a reading
    is flagged when it lies more than *z_threshold* standard deviations from
    that baseline. Comparing flags with labels gives precision (how many flags
    are real faults) and recall (how many faults are flagged), per sensor type
    and per fault kind. Same SQL as sql/analysis/11_detection_quality.sql.
    """
    sql = """
        WITH sensor_monthly_stats AS (
            SELECT
                sensor_id,
                DATE_TRUNC('month', recorded_at)  AS month,
                AVG(value)                        AS mean_val,
                STDDEV(value)                     AS stddev_val
            FROM readings
            WHERE is_anomaly = FALSE
            GROUP BY sensor_id, DATE_TRUNC('month', recorded_at)
        ),
        scored AS (
            SELECT
                se.sensor_type,
                r.is_anomaly                                   AS injected,
                (s.stddev_val > 0
                 AND ABS(r.value - s.mean_val) / s.stddev_val > %s) AS flagged,
                r.value < s.mean_val                           AS below_baseline
            FROM readings r
            JOIN sensor_monthly_stats s
              ON  r.sensor_id = s.sensor_id
              AND DATE_TRUNC('month', r.recorded_at) = s.month
            JOIN sensors se ON r.sensor_id = se.sensor_id
        )
        SELECT
            sensor_type,
            COUNT(*)                                                     AS readings,
            COUNT(*) FILTER (WHERE injected)                             AS injected,
            COUNT(*) FILTER (WHERE flagged)                              AS flagged,
            COUNT(*) FILTER (WHERE injected AND flagged)                 AS true_positives,
            COUNT(*) FILTER (WHERE injected AND NOT below_baseline)      AS spikes,
            COUNT(*) FILTER (WHERE injected AND NOT below_baseline AND flagged) AS spikes_flagged,
            COUNT(*) FILTER (WHERE injected AND below_baseline)          AS drops,
            COUNT(*) FILTER (WHERE injected AND below_baseline AND flagged)     AS drops_flagged
        FROM scored
        GROUP BY sensor_type
        ORDER BY sensor_type
    """

    try:
        rows = _fetch_rows(sql, (z_threshold,))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    def _pct(part: int, whole: int) -> Optional[float]:
        return round(part / whole * 100, 1) if whole else None

    totals = {key: 0 for key in ("readings", "injected", "flagged", "true_positives",
                                 "spikes", "spikes_flagged", "drops", "drops_flagged")}
    for row in rows:
        for key in totals:
            row[key] = int(row[key])
            totals[key] += row[key]
    for row in rows + [totals]:
        row["precision_pct"] = _pct(row["true_positives"], row["flagged"])
        row["recall_pct"] = _pct(row["true_positives"], row["injected"])

    return {"z_threshold": z_threshold, "sensors": rows, "total": totals}


@app.get("/api/facilities/ranking", tags=["analytics"])
def get_facility_ranking():
    """
    Return all facilities ranked by average power output as a share of
    nameplate capacity (capacity factor), over all non-anomalous readings in
    the available data window. The response field is named
    avg_efficiency_pct for backward compatibility.
    """
    sql = """
        WITH monthly_output AS (
            SELECT
                f.facility_id,
                f.facility_name,
                f.facility_type,
                f.capacity_mw,
                f.country,
                AVG(r.value)   AS avg_output_mw
            FROM readings r
            JOIN sensors    s ON r.sensor_id   = s.sensor_id
            JOIN facilities f ON s.facility_id = f.facility_id
            WHERE s.sensor_type = 'power_output'
              AND r.is_anomaly  = FALSE
            GROUP BY
                f.facility_id, f.facility_name, f.facility_type,
                f.capacity_mw, f.country
        )
        SELECT
            facility_name,
            facility_type,
            country,
            ROUND(capacity_mw::NUMERIC, 2)                              AS capacity_mw,
            ROUND((avg_output_mw / NULLIF(capacity_mw, 0) * 100)::NUMERIC, 2)
                                                                        AS avg_efficiency_pct,
            RANK() OVER (ORDER BY avg_output_mw / NULLIF(capacity_mw, 0) DESC)
                                                                        AS overall_rank
        FROM monthly_output
        ORDER BY overall_rank
    """

    try:
        rows = _fetch_rows(sql)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    for row in rows:
        for k, v in row.items():
            if hasattr(v, "__float__"):
                row[k] = float(v)

    return {"count": len(rows), "facilities": rows}
