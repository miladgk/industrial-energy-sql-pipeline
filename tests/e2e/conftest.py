"""
conftest.py (e2e)
~~~~~~~~~~~~~~~~~
Fixtures for the end-to-end tests:  real Chromium  ->  the built dashboard.

The dashboard is a static page (React + Vite, source in web/): it reads the
JSON files in docs/data/, built from the warehouse by
scripts/export_dashboard_data.py, and calls no API. GitHub Pages serves the
build (web/dist/) with docs/data/ copied next to it; the server here does the
same, except that it reads data/ and assets/ straight from docs/, so the tests
always check the page against the data files in the repository, even when the
build is older than the last export.

Build the page first:   npm --prefix web ci && npm --prefix web run build
"""

import functools
import http.server
import os
import threading
from urllib.parse import unquote, urlsplit

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="pip install playwright")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DIST = os.path.join(ROOT, "web", "dist")
DOCS = os.path.join(ROOT, "docs")


class _DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """web/dist/ for the page and its bundle, docs/ for data/ and assets/ (as in the Pages artifact)."""

    def translate_path(self, path):
        rel = unquote(urlsplit(path).path).lstrip("/")
        if rel.startswith(("data/", "assets/")):
            return os.path.join(DOCS, *rel.split("/"))
        return super().translate_path(path)

    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture(scope="session")
def static_url():
    """Serve the dashboard like GitHub Pages: plain static files."""
    if not os.path.exists(os.path.join(DIST, "index.html")):
        pytest.skip("web/dist/ is not built; run: npm --prefix web ci && npm --prefix web run build")
    handler = functools.partial(_DashboardHandler, directory=DIST)
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
    Factory: open_dashboard(viewport=None, block=(), latest="sample", chapter=None) -> Page

    * chapter: open on that chapter (the URL hash, e.g. "europe"); default the overview

    * block: data file names (e.g. "co2_forecast.json", or "*" for all of them) answered with 404
    * latest="missing" answers data/fingrid_latest.json with 404 instead of SAMPLE_LATEST
      (that file is git-ignored and only built by the hourly Pages deploy)

    The page has `page.problems` (console errors, uncaught exceptions) and
    `page.foreign_requests` (every request that left the static server).
    """
    contexts = []

    def _open(viewport=None, block=(), latest="sample", chapter=None):
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
        page.goto(static_url + "/index.html" + (f"#{chapter}" if chapter else ""))
        return page

    yield _open
    for context in contexts:
        context.close()
