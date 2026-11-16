"""
analysis_window.py
~~~~~~~~~~~~~~~~~~
Default parameters for the Fingrid analysis queries (sql/analysis/13-19).

Most take a window, %(start)s and %(end)s; 18_co2_forecast.sql takes a Finnish
calendar day, %(day)s. Callers that run every analysis file (run_report.py,
the integration tests) use params_for(sql), which returns the defaults for such
files and None for the others, so files without placeholders run as before.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")

DEFAULT_DAYS = 365


def default_window(now: datetime | None = None, days: int = DEFAULT_DAYS) -> dict:
    """The last *days* complete UTC days: start inclusive, end (today 00:00 UTC) exclusive."""
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"start": end - timedelta(days=days), "end": end}


def tomorrow_fi(now: datetime | None = None) -> date:
    """The next calendar day in Finland."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(HELSINKI).date() + timedelta(days=1)


def params_for(sql: str, now: datetime | None = None) -> dict | None:
    if "%(day)s" in sql:
        return {"day": tomorrow_fi(now)}
    return default_window(now) if "%(start)s" in sql else None
