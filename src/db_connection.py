"""
db_connection.py
~~~~~~~~~~~~~~~~
Provides a single function, get_connection(), that reads database
credentials from config.yaml and returns a live psycopg2 connection.

Design decisions
----------------
* Credentials live in config.yaml (git-ignored). config_template.yaml
  is committed so new developers know the required structure.
* The caller is responsible for conn.close(); this module only creates
  the connection so it stays lightweight and easy to test.
"""

import os
import yaml
import psycopg2
from psycopg2.extensions import connection as PgConnection


_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


def get_connection(config_path: str = _CONFIG_PATH) -> PgConnection:
    """
    Read database credentials from *config_path* and return an open
    psycopg2 connection.

    Parameters
    ----------
    config_path : str
        Path to the YAML credentials file.  Defaults to ``config.yaml``
        in the project root.

    Returns
    -------
    psycopg2.extensions.connection

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    KeyError
        If the required keys are missing from the config file.
    psycopg2.OperationalError
        If the database cannot be reached with the supplied credentials.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return psycopg2.connect(
            database_url,
            sslmode=os.environ.get("DATABASE_SSLMODE", "prefer"),
            # TCP keepalives — prevent the SSL socket from being silently
            # dropped by firewalls / proxies during long-running bulk loads.
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Database config not found at '{config_path}'.\n"
            "Copy config_template.yaml → config.yaml and fill in your credentials."
        )

    with open(config_path, "r") as fh:
        cfg = yaml.safe_load(fh)

    db = cfg["database"]
    conn = psycopg2.connect(
        host    = db["host"],
        port    = int(db["port"]),
        dbname  = db["dbname"],
        user    = db["user"],
        password= db["password"],
    )
    return conn
