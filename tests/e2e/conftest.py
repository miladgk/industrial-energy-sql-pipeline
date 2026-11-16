"""
conftest.py (e2e)
~~~~~~~~~~~~~~~~~
Fixtures that assemble the full stack for the end-to-end tests:

    real Chromium  ->  docs/index.html (static server)  ->  real FastAPI  ->  real PostgreSQL

The dashboard has the production API address (the Render deployment) written
into its JavaScript. Instead of editing the page, Playwright intercepts those
requests and forwards them to a FastAPI process started here on a local port,
so the browser exercises the real code path against the local database.
"""

import functools
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="pip install playwright")

PRODUCTION_API = "https://industrial-energy-api.onrender.com"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture(scope="session")
def static_url():
    """Serve docs/ exactly like GitHub Pages does: plain static files."""
    handler = functools.partial(_QuietHandler, directory=os.path.join(ROOT, "docs"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def api_url():
    """Start the real FastAPI app (uvicorn) on a free port; stop it afterwards."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--app-dir", os.path.join(ROOT, "src"),
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if proc.poll() is not None:
                pytest.fail("uvicorn exited during start-up")
            try:
                urllib.request.urlopen(url + "/health", timeout=1)  # nosec B310
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("API did not become healthy in 30 s")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


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
def open_dashboard(browser, static_url, api_url):
    """
    Factory: open_dashboard(api="live" | "down", viewport=None, block_data=False) -> Page

    * "live": requests to the production API host are forwarded to the local FastAPI.
    * "down": the API is unreachable, so the page must fall back to its bundled snapshot.
    * block_data=True also blocks docs/data/*.json, to see what the bare HTML shows.
    * latest="missing" answers data/fingrid_latest.json with 404 instead of SAMPLE_LATEST.

    The returned page has `page.problems`, a list of console errors / uncaught JS exceptions.
    """
    contexts = []

    def _open(api="live", viewport=None, block_data=False, latest="sample"):
        context = browser.new_context(viewport=viewport or {"width": 1400, "height": 900})
        contexts.append(context)
        page = context.new_page()
        page.problems = []
        page.on("pageerror", lambda exc: page.problems.append(f"uncaught: {exc}"))
        page.on("console", lambda m: page.problems.append(f"console: {m.text}") if m.type == "error" else None)

        if api == "live":
            def forward(route):
                target = route.request.url.replace(PRODUCTION_API, api_url)
                try:
                    route.fulfill(response=route.fetch(url=target))
                except playwright_sync.Error:
                    pass  # the test finished and closed the page while this request was in flight
            page.route(PRODUCTION_API + "/**", forward)
        else:
            page.route(PRODUCTION_API + "/**", lambda route: route.abort())
        # fingrid_latest.json is git-ignored and only built by the hourly Pages deploy,
        # so serve a sample here the way production would (or a 404 when asked to).
        if latest == "missing":
            page.route("**/data/fingrid_latest.json", lambda route: route.fulfill(status=404))
        else:
            page.route("**/data/fingrid_latest.json", lambda route: route.fulfill(json=SAMPLE_LATEST))
        if block_data:
            page.route("**/data/*.json", lambda route: route.abort())
        page.goto(static_url + "/index.html")
        return page

    yield _open
    for context in contexts:
        for page in context.pages:
            # Let requests still in flight finish quietly so their errors are not
            # reported against whichever test happens to run next.
            page.unroute_all(behavior="ignoreErrors")
        context.close()
