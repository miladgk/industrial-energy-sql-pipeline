"""Generate and load the full synthetic dataset into a remote PostgreSQL database."""

import os
import sys
from pathlib import Path

from src.generate_data import main as generate_data
from src.ingest import main as ingest_data


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "Set DATABASE_URL to the Render External Database URL before running."
        )

    raw_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("Generating facilities, sensors, and the full 6.3M-row readings dataset...")
    sys.argv = ["generate_data.py"]
    generate_data()

    print("Loading the generated CSV files into Render PostgreSQL...")
    sys.argv = ["ingest.py", "--no-watermark"]
    ingest_data()


if __name__ == "__main__":
    main()
