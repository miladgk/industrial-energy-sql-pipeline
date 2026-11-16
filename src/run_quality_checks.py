"""
run_quality_checks.py
~~~~~~~~~~~~~~~~~~~~~
Runs the checks in sql/etl/02_data_quality_checks.sql against the Fingrid
warehouse and prints each result. A check marked [fail] passes when it returns
no rows; [info] checks only report.

Usage:
    python src/run_quality_checks.py

Exit code 1 when any [fail] check returns rows.
"""

import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from db_connection import get_connection  # noqa: E402

CHECKS_PATH = os.path.join(os.path.dirname(__file__), "..", "sql", "etl", "02_data_quality_checks.sql")
CHECK_HEADER = re.compile(r"^-- Check: (.+?) \[(fail|info)\]\s*$", re.MULTILINE)


def load_checks(path: str = CHECKS_PATH) -> list[tuple[str, str, str]]:
    """Return (label, mode, sql) for every '-- Check: ... [fail|info]' block."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    heads = list(CHECK_HEADER.finditer(text))
    checks = []
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        checks.append((m.group(1), m.group(2), body.strip()))
    return checks


def run_quality_checks(conn) -> bool:
    """Run every check; True when all [fail] checks return no rows."""
    passed = True
    print("=" * 60 + "\nDATA QUALITY REPORT\n" + "=" * 60)
    for label, mode, sql in load_checks():
        with conn.cursor() as cur:
            cur.execute(sql)
            df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        conn.rollback()
        failed = mode == "fail" and len(df) > 0
        passed &= not failed
        status = "✗ FAIL" if failed else ("✓ pass" if mode == "fail" else "· info")
        print(f"\n{status}  {label}")
        if len(df):
            print(df.to_string(index=False))
    print("\n" + ("All checks passed." if passed else "Some checks FAILED."))
    return passed


def main() -> None:
    conn = get_connection()
    try:
        ok = run_quality_checks(conn)
    finally:
        conn.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
