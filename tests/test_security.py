"""
test_security.py: SECURITY TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime checks for the most common web-API weaknesses (think OWASP Top 10):

  * Injection        : user input never reaches SQL as code (allow-lists, typed params)
  * Info leakage     : errors do not reveal database internals to the client
  * Least privilege  : the API only reads (read-only transactions, GET only)
  * Secrets          : credentials are not tracked by git

Static analysis (bandit) and the dependency CVE scan (pip-audit) run in the
`security` job of the CI workflow.

Run only these:  pytest -m security
"""

import os
import subprocess

import pytest

import api

pytestmark = pytest.mark.security

INJECTION_PAYLOADS = [
    "wind'; DROP TABLE fingrid_observation; --",
    "' OR '1'='1",
    "nuclear_drop' UNION SELECT NULL--",
    "\\'; SELECT pg_sleep(5); --",
    "wind\x00",
]
STRING_PARAMS = [("/api/grid-events", "kind"), ("/api/forecast-error-by-hour", "variable"), ("/api/co2-forecast", "day")]


@pytest.mark.parametrize("path,param", STRING_PARAMS)
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_injection_payloads_are_rejected(client, db, path, param, payload):
    """Every string parameter is an allow-list or a typed date: payloads get 422, never a 500."""
    response = client.get(path, params={param: payload})
    assert response.status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fingrid_observation")
        assert cur.fetchone()[0] > 0
    db.rollback()


def test_database_errors_do_not_leak_to_client(client, monkeypatch):
    def broken_connection():
        raise RuntimeError("FATAL: password authentication failed for user admin at 10.0.0.5")

    monkeypatch.setattr(api, "get_connection", broken_connection)
    for path in ("/api/datasets", "/api/latest", "/api/forecast-scorecard", "/api/grid-events", "/api/co2-forecast"):
        response = client.get(path)
        assert response.status_code == 500, path
        assert "password" not in response.text and "10.0.0.5" not in response.text
        assert response.json()["detail"] == "Internal server error"


def test_api_queries_run_read_only():
    """Even if a query string were wrong, the session could not write."""
    with pytest.raises(Exception, match="read-only"):
        api._fetch_rows("DELETE FROM fingrid_observation WHERE false")


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_refused(client, method):
    assert getattr(client, method)("/api/grid-events").status_code == 405


def test_cors_does_not_allow_write_methods(client):
    response = client.options(
        "/api/grid-events",
        headers={"Origin": "https://example.org", "Access-Control-Request-Method": "DELETE"},
    )
    assert response.status_code == 400


def test_credentials_file_is_not_tracked_by_git(project_root):
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=project_root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "config.yaml" not in tracked, "config.yaml holds real credentials"
    assert ".env" not in tracked
    assert ".claude/settings.local.json" not in tracked
    assert os.path.exists(os.path.join(project_root, "config_template.yaml"))
