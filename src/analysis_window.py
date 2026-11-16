"""
analysis_window.py
~~~~~~~~~~~~~~~~~~
The time window used by the Fingrid analysis queries (sql/analysis/13-17).

Those files take two named parameters, %(start)s and %(end)s. Callers that
run every analysis file (run_report.py, the integration tests) use
params_for(sql), which returns the default window for such files and None for
the others, so files without placeholders run exactly as before.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_DAYS = 365


def default_window(now: datetime | None = None, days: int = DEFAULT_DAYS) -> dict:
    """The last *days* complete UTC days: start inclusive, end (today 00:00 UTC) exclusive."""
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"start": end - timedelta(days=days), "end": end}


def params_for(sql: str, now: datetime | None = None) -> dict | None:
    return default_window(now) if "%(start)s" in sql else None
