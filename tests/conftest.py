"""
conftest.py
~~~~~~~~~~~
Shared pytest fixtures. pytest loads this file automatically, so every test
module can use these fixtures just by naming them as function arguments.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def project_root() -> str:
    return ROOT


@pytest.fixture(scope="session")
def client():
    """
    A FastAPI TestClient: it calls the app in-process (no uvicorn, no open
    port) but goes through the full HTTP stack: routing, validation,
    serialisation, middleware. That is what makes these API tests rather
    than plain function-call tests.
    """
    from fastapi.testclient import TestClient
    from api import app

    return TestClient(app)


@pytest.fixture(scope="session")
def db():
    """One live connection to the configured PostgreSQL for the session."""
    from db_connection import get_connection

    conn = get_connection()
    yield conn
    conn.close()
