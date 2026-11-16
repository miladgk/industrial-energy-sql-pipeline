"""
run_report.py
~~~~~~~~~~~~~
Executes each SQL analysis file in order, writes results to
outputs/<query_name>_<YYYYMMDD_HHMMSS>.csv, and prints a summary line.

Usage:
    python src/run_report.py
"""

import os
import sys
import glob
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from db_connection import get_connection
from analysis_window import params_for

ANALYSIS_DIR = os.path.join(os.path.dirname(__file__), "..", "sql", "analysis")
OUTPUTS_DIR  = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


def run_query(conn, sql: str) -> pd.DataFrame:
    """Execute a SELECT query and return results as a DataFrame.
    Files with %(start)s / %(end)s get the default window (the last 365 complete days)."""
    return pd.read_sql_query(sql, conn, params=params_for(sql))


def main():
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Energy Analytics Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = get_connection()

    # Collect SQL files in lexicographic order (03_, 04_, 05_, 06_)
    sql_files = sorted(glob.glob(os.path.join(ANALYSIS_DIR, "*.sql")))

    if not sql_files:
        print("No SQL files found in sql/analysis/. Exiting.")
        conn.close()
        return

    for sql_path in sql_files:
        filename   = os.path.basename(sql_path)               # e.g. 03_rolling_averages.sql
        query_name = os.path.splitext(filename)[0]             # e.g. 03_rolling_averages
        short_name = query_name.replace("_", " ").title()

        with open(sql_path, "r") as fh:
            sql = fh.read()

        try:
            df = run_query(conn, sql)
        except Exception as exc:
            print(f"  ✗ {short_name}: FAILED — {exc}")
            continue

        out_filename = f"{query_name}_{run_ts}.csv"
        out_path     = os.path.join(OUTPUTS_DIR, out_filename)
        df.to_csv(out_path, index=False)

        print(f"  ✓ {short_name}: {len(df):,} rows → outputs/{out_filename}")

        if query_name == "08_real_vs_synthetic_comparison":
            try:
                from scipy import stats
                r, pval = stats.pearsonr(df['real_avg'], df['synthetic_avg'])
                dof = len(df) - 2
                print(f"    └─ Daily Correlation Significance Test:")
                print(f"       • Sample size (n)        : {len(df)}")
                print(f"       • Degrees of Freedom (df): {dof}")
                print(f"       • Pearson r              : {r:.4f}")
                print(f"       • p-value                : {pval:.4e} (Alpha = 0.05)")
                sig = "Statistically Significant" if pval < 0.05 else "Not Statistically Significant"
                print(f"       • Conclusion             : {sig}")
            except Exception as e:
                print(f"    └─ Error running significance test: {e}")

    conn.close()
    print("=" * 60)
    print("Report complete.")


if __name__ == "__main__":
    main()
