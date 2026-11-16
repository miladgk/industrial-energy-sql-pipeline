"""
conftest.py (e2e)
~~~~~~~~~~~~~~~~~
Fixtures for the end-to-end tests:  real Chromium  ->  docs/ (static server).

The dashboard is a static page: it reads the JSON files in docs/data/, built
from the warehouse by scripts/export_dashboard_data.py, and calls no API. The
static server here serves docs/ exactly like GitHub Pages does.
"""

import functools
import http.server
import os
import threading

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="pip install playwright")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture(scope="session")
def static_url():
    """Serve docs/ like GitHub Pages: plain static files."""
    handler = functools.partial(_QuietHandler, directory=os.path.join(ROOT, "docs"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def browser():
    with playwright_sync.sync_playwright() as p:
        try:
            chromium = p.chromium.launch(headless=True)
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"Chromium not available ({exc.__class__.__name__}); run: playwright install chromium")
        yield chromium
        chromium.close()


# Shape of docs/data/fingrid_latest.json (scripts/export_dashboard_data.py, part fingrid-latest).
SAMPLE_LATEST = {
    "source": "sample for the e2e tests",
    "generated_at": "2026-11-16T06:46:21+00:00",
    "unit": "MW",
    "consumption": {"dataset_id": 124, "value_mw": 11454.5,
                    "start_time": "2026-11-16T06:15:00+00:00", "end_time": "2026-11-16T06:30:00+00:00"},
    "wind_production": {"dataset_id": 75, "value_mw": 6603.0,
                        "start_time": "2026-11-16T06:15:00+00:00", "end_time": "2026-11-16T06:30:00+00:00"},
}


@pytest.fixture
def open_dashboard(browser, static_url):
    """
    Factory: open_dashboard(viewport=None, block=(), latest="sample") -> Page

    * block: data file names (e.g. "co2_forecast.json", or "*" for all of them) answered with 404
    * latest="missing" answers data/fingrid_latest.json with 404 instead of SAMPLE_LATEST
      (that file is git-ignored and only built by the hourly Pages deploy)

    The page has `page.problems` (console errors, uncaught exceptions) and
    `page.foreign_requests` (every request that left the static server).
    """
    contexts = []

    def _open(viewport=None, block=(), latest="sample"):
        context = browser.new_context(viewport=viewport or {"width": 1400, "height": 900})
        contexts.append(context)
        page = context.new_page()
        page.problems, page.foreign_requests = [], []
        page.on("pageerror", lambda exc: page.problems.append(f"uncaught: {exc}"))
        page.on("console", lambda m: page.problems.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("request", lambda r: None if r.url.startswith(static_url) else page.foreign_requests.append(r.url))

        if latest == "missing":
            page.route("**/data/fingrid_latest.json", lambda route: route.fulfill(status=404))
        else:
            page.route("**/data/fingrid_latest.json", lambda route: route.fulfill(json=SAMPLE_LATEST))
        for name in block:
            page.route(f"**/data/{name}", lambda route: route.fulfill(status=404))
        page.goto(static_url + "/index.html")
        return page

    yield _open
    for context in contexts:
        context.close()
