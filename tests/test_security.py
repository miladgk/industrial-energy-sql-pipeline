"""
test_security.py: SECURITY TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated checks for the most common web-API weaknesses (think OWASP Top 10),
applied to this project:

  * Injection        : user input must never be executed as SQL.
  * Info leakage     : errors must not reveal database internals to the client.
  * Secrets          : credentials must not be tracked by git.
  * Least privilege  : the API is read-only, so write methods must be refused.

Static analysis (bandit) and the dependency CVE scan (pip-audit) run in the
`security` job of the CI workflow; these tests cover behaviour at runtime.

Run only these:  pytest -m security
"""

import os
import subprocess

import pytest

import api

pytestmark = pytest.mark.security

INJECTION_PAYLOADS = [
    "wind'; DROP TABLE readings; --",
    "' OR '1'='1",
    "wind' UNION SELECT NULL,NULL,NULL--",
    "\\'; SELECT pg_sleep(5); --",
    "wind\x00",
]
STRING_PARAM_ENDPOINTS = ["/api/anomalies", "/api/output-trend"]


@pytest.mark.parametrize("path", STRING_PARAM_ENDPOINTS)
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_injection_payloads_are_treated_as_plain_text(client, db, path, payload):
    """
    A payload must neither succeed in changing the query ('OR 1=1' would return
    everything) nor crash it (a 500 would mean unhandled input). The allow-list
    on facility_type rejects every one of them with 422.
    """
    response = client.get(path, params={"facility_type": payload})
    assert response.status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings")
        assert cur.fetchone()[0] > 0


def test_database_errors_do_not_leak_to_client(client, monkeypatch):
    """If the database fails, the client gets a generic 500, not the raw error text."""
    def broken_connection():
        raise RuntimeError("FATAL: password authentication failed for user admin at 10.0.0.5")

    monkeypatch.setattr(api, "get_connection", broken_connection)
    for path in ("/api/overview", "/api/anomalies", "/api/facilities/ranking",
                 "/api/detection-quality", "/api/output-trend"):
        response = client.get(path)
        assert response.status_code == 500
        assert "password" not in response.text and "10.0.0.5" not in response.text
        assert response.json()["detail"] == "Internal server error"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_refused(client, method):
    assert getattr(client, method)("/api/anomalies").status_code == 405


def test_cors_does_not_allow_write_methods(client):
    response = client.options(
        "/api/anomalies",
        headers={"Origin": "https://example.org", "Access-Control-Request-Method": "DELETE"},
    )
    assert response.status_code == 400  # preflight for DELETE is rejected


def test_credentials_file_is_not_tracked_by_git(project_root):
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=project_root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "config.yaml" not in tracked, "config.yaml holds real credentials"
    assert ".env" not in tracked
    assert os.path.exists(os.path.join(project_root, "config_template.yaml"))
