"""
Stage 1: Extract X (design inputs) and Y (capacity outputs) from ReEDS surrogate runs.

This script processes the 486 surrogate model runs and creates an ML-ready dataset
where:
  - X features: The 6 experimental design dimensions encoded numerically
  - Y outputs: National capacity (MW) by technology and year (from cap_nat.csv)

Output: A single CSV file with one row per run, columns for X features and flattened
        Y capacity values (tech_year format).

Usage:
    python surrogate_stage1_capacity.py --runs_dir /path/to/runs --output stage1_capacity.csv
"""

import argparse
import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional


# ============================================================================
# X DESIGN ENCODING
# ============================================================================
# Map dimension level names to numeric codes (ordinal encoding: Lo=0, Md=1, Hi=2)
DIMENSION_ENCODING = {
    "Dem": {"Lo": 0, "Md": 1, "Hi": 2},
    "Fuel": {"Lo": 0, "Md": 1, "Hi": 2},
    "REcost": {"Lo": 0, "Md": 1, "Hi": 2},
    "Siting": {"Open": 0, "Ref": 1, "Lim": 2},
    "Batt": {"Lo": 0, "Md": 1, "Hi": 2},
    "Pol": {"IRA": 0, "OBBBA": 1},
}

# Pattern to parse case name: prefix_DemX_FuelX_REcostX_SitingX_BattX_PolX
CASE_PATTERN = re.compile(
    r"^(?P<prefix>[^_]+)_"
    r"Dem(?P<Dem>Lo|Md|Hi)_"
    r"Fuel(?P<Fuel>Lo|Md|Hi)_"
    r"REcost(?P<REcost>Lo|Md|Hi)_"
    r"Siting(?P<Siting>Open|Ref|Lim)_"
    r"Batt(?P<Batt>Lo|Md|Hi)_"
    r"Pol(?P<Pol>IRA|OBBBA)$"
)


def parse_case_name(case_name: str) -> Optional[dict]:
    """Parse a surrogate case directory name into X feature values."""
    match = CASE_PATTERN.match(case_name)
    if not match:
        return None
    features = {}
    for dim, levels in DIMENSION_ENCODING.items():
        level = match.group(dim)
        features[f"x_{dim}"] = levels[level]
        features[f"x_{dim}_label"] = level
    return features


def extract_capacity(run_dir: Path) -> Optional[pd.DataFrame]:
    """
    Extract national capacity data from a run's outputs/cap_nat.csv.

    Returns a DataFrame with columns: i (tech), t (year), Value (MW)
    """
    cap_file = run_dir / "outputs" / "cap_nat.csv"
    if not cap_file.exists():
        return None
    try:
        df = pd.read_csv(cap_file)
        # Expected columns: i, t, Value
        if not {"i", "t", "Value"}.issubset(df.columns):
            print(f"  WARNING: Unexpected columns in {cap_file}: {df.columns.tolist()}")
            return None
        return df
    except Exception as e:
        print(f"  ERROR reading {cap_file}: {e}")
        return None


def pivot_capacity(df: pd.DataFrame) -> dict:
    """
    Pivot capacity DataFrame into a flat dict: {f"cap_{tech}_{year}": value_MW}.
    Aggregates across all regions if any remain (cap_nat should already be national).
    """
    # Group by tech and year, sum values
    grouped = df.groupby(["i", "t"])["Value"].sum().reset_index()
    result = {}
    for _, row in grouped.iterrows():
        key = f"cap_{row['i']}_{int(row['t'])}"
        result[key] = row["Value"]
    return result


def process_runs(runs_dir: Path, batch_prefix: Optional[str] = None) -> pd.DataFrame:
    """
    Process all surrogate runs in the given directory.

    Args:
        runs_dir: Path to the runs directory
        batch_prefix: If set, only process runs starting with this prefix

    Returns:
        DataFrame with X features and Y capacity outputs, one row per run.
    """
    rows = []
    run_dirs = sorted(runs_dir.iterdir()) if runs_dir.is_dir() else []

    print(f"Scanning runs in: {runs_dir}")
    n_found = 0
    n_processed = 0
    n_skipped = 0

    for run_path in run_dirs:
        if not run_path.is_dir():
            continue
        case_name = run_path.name

        # Filter by batch prefix if specified
        if batch_prefix and not case_name.startswith(batch_prefix):
            continue

        # Parse X features from case name
        features = parse_case_name(case_name)
        if features is None:
            continue  # Not a surrogate case

        n_found += 1

        # Extract Y capacity
        cap_df = extract_capacity(run_path)
        if cap_df is None:
            print(f"  Skipping {case_name}: no capacity output found")
            n_skipped += 1
            continue

        # Pivot to flat dict
        y_values = pivot_capacity(cap_df)

        # Combine X and Y
        row = {"case_name": case_name}
        row.update(features)
        row.update(y_values)
        rows.append(row)
        n_processed += 1

    print(f"\nSummary: Found {n_found} surrogate cases, processed {n_processed}, skipped {n_skipped}")

    if not rows:
        print("WARNING: No data extracted!")
        return pd.DataFrame()

    # Build DataFrame
    df = pd.DataFrame(rows)

    # Sort columns: case_name, X features (numeric), X labels, Y outputs
    x_num_cols = [c for c in df.columns if c.startswith("x_") and not c.endswith("_label")]
    x_label_cols = [c for c in df.columns if c.endswith("_label")]
    y_cols = sorted([c for c in df.columns if c.startswith("cap_")])

    col_order = ["case_name"] + sorted(x_num_cols) + sorted(x_label_cols) + y_cols
    df = df[col_order]

    # Fill missing Y columns with 0 (technology not present in that run)
    df[y_cols] = df[y_cols].fillna(0.0)

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Extract capacity (Y) data from ReEDS surrogate runs into ML-ready format."
    )
    parser.add_argument(
        "--runs_dir",
        type=str,
        default=None,
        help="Path to runs directory. Default: auto-detect from script location.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="stage1_capacity_ml.csv",
        help="Output CSV filename (saved in current directory or specified path).",
    )
    parser.add_argument(
        "--batch_prefix",
        type=str,
        default=None,
        help="Only process runs whose name starts with this prefix (e.g., 'test0').",
    )
    parser.add_argument(
        "--parquet",
        action="store_true",
        help="Also save output as parquet (requires pyarrow).",
    )
    args = parser.parse_args()

    # Determine runs directory
    if args.runs_dir:
        runs_dir = Path(args.runs_dir)
    else:
        # Default: <repo_root>/runs
        repo_root = Path(__file__).resolve().parent.parent
        runs_dir = repo_root / "runs"

    if not runs_dir.exists():
        print(f"ERROR: Runs directory not found: {runs_dir}")
        return

    # Process all runs
    df = process_runs(runs_dir, batch_prefix=args.batch_prefix)

    if df.empty:
        return

    # Print dataset summary
    x_cols = [c for c in df.columns if c.startswith("x_") and not c.endswith("_label")]
    y_cols = [c for c in df.columns if c.startswith("cap_")]
    print(f"\nDataset shape: {df.shape}")
    print(f"  X features (numeric): {len(x_cols)} columns")
    print(f"  Y outputs (capacity): {len(y_cols)} columns")
    print(f"  Runs: {len(df)} rows")

    # Print X feature summary
    print("\nX Feature Ranges:")
    for col in sorted(x_cols):
        print(f"  {col}: {df[col].min()} - {df[col].max()} (unique: {df[col].nunique()})")

    # Save outputs
    output_path = Path(args.output)
    df.to_csv(output_path, index=False)
    print(f"\nSaved CSV: {output_path.resolve()}")

    if args.parquet:
        parquet_path = output_path.with_suffix(".parquet")
        df.to_parquet(parquet_path, index=False)
        print(f"Saved Parquet: {parquet_path.resolve()}")

    # Also save a "numeric only" version (no labels, no case_name) for direct ML use
    ml_cols = x_cols + y_cols
    df_ml = df[ml_cols].copy()
    ml_path = output_path.with_stem(output_path.stem + "_numeric")
    df_ml.to_csv(ml_path, index=False)
    print(f"Saved numeric-only CSV: {ml_path.resolve()}")


if __name__ == "__main__":
    main()
