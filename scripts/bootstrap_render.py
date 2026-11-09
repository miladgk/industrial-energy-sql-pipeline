"""Initialize the Render PostgreSQL schema from the repository SQL migrations."""

import os
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = (
    ROOT / "sql/schema/01_create_tables.sql",
    ROOT / "sql/schema/07_add_grid_data.sql",
)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for Render bootstrap")

    with psycopg2.connect(
        database_url,
        sslmode=os.environ.get("DATABASE_SSLMODE", "prefer"),
    ) as connection:
        with connection.cursor() as cursor:
            for schema_file in SCHEMA_FILES:
                cursor.execute(schema_file.read_text())
    print("Database schema is ready.")


if __name__ == "__main__":
    main()
