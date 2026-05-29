"""
Stage 2: Extract X (design inputs) and Y (operational outputs) from ReEDS surrogate runs.

This script processes the 486 surrogate model runs and creates an ML-ready dataset
where:
  - X features: The 6 experimental design dimensions encoded numerically
  - Y outputs: National generation (MWh), CO2 emissions (metric tons), and system
    costs ($) by technology/category and year.

Output files:
  - stage2_generation_ml.csv: X + generation by tech × year
  - stage2_emissions_ml.csv: X + emissions by type × year
  - stage2_systemcost_ml.csv: X + system cost components × year
  - stage2_combined_ml.csv: X + all Y combined (wide format)

Usage:
    python surrogate_stage2_operations.py --runs_dir /path/to/runs --output_dir ./ml_data
"""

import argparse
import os
import re
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Tuple


# ============================================================================
# X DESIGN ENCODING (same as Stage 1)
# ============================================================================
DIMENSION_ENCODING = {
    "Dem": {"Lo": 0, "Md": 1, "Hi": 2},
    "Fuel": {"Lo": 0, "Md": 1, "Hi": 2},
    "REcost": {"Lo": 0, "Md": 1, "Hi": 2},
    "Siting": {"Open": 0, "Ref": 1, "Lim": 2},
    "Batt": {"Lo": 0, "Md": 1, "Hi": 2},
    "Pol": {"IRA": 0, "OBBBA": 1},
}

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


# ============================================================================
# Y OUTPUT EXTRACTORS
# ============================================================================

def extract_generation(run_dir: Path) -> Optional[dict]:
    """
    Extract national generation data from outputs/gen_ann_nat.csv.
    Returns flat dict: {f"gen_{tech}_{year}": value_MWh}
    """
    gen_file = run_dir / "outputs" / "gen_ann_nat.csv"
    if not gen_file.exists():
        return None
    try:
        df = pd.read_csv(gen_file)
        if not {"i", "t", "Value"}.issubset(df.columns):
            return None
        grouped = df.groupby(["i", "t"])["Value"].sum().reset_index()
        result = {}
        for _, row in grouped.iterrows():
            key = f"gen_{row['i']}_{int(row['t'])}"
            result[key] = row["Value"]
        return result
    except Exception as e:
        print(f"  ERROR reading gen_ann_nat.csv in {run_dir.name}: {e}")
        return None


def extract_emissions(run_dir: Path) -> Optional[dict]:
    """
    Extract national emissions data from outputs/emit_nat.csv.
    Returns flat dict: {f"emit_{etype}_{eall}_{year}": value}
    """
    emit_file = run_dir / "outputs" / "emit_nat.csv"
    if not emit_file.exists():
        return None
    try:
        df = pd.read_csv(emit_file)
        if not {"etype", "eall", "t", "Value"}.issubset(df.columns):
            return None
        grouped = df.groupby(["etype", "eall", "t"])["Value"].sum().reset_index()
        result = {}
        for _, row in grouped.iterrows():
            key = f"emit_{row['etype']}_{row['eall']}_{int(row['t'])}"
            result[key] = row["Value"]
        return result
    except Exception as e:
        print(f"  ERROR reading emit_nat.csv in {run_dir.name}: {e}")
        return None


def extract_systemcost(run_dir: Path) -> Optional[dict]:
    """
    Extract system cost data from outputs/systemcost.csv.
    Returns flat dict: {f"cost_{category}_{year}": value_$}
    """
    cost_file = run_dir / "outputs" / "systemcost.csv"
    if not cost_file.exists():
        return None
    try:
        df = pd.read_csv(cost_file)
        if not {"sys_costs", "t", "Value"}.issubset(df.columns):
            return None
        grouped = df.groupby(["sys_costs", "t"])["Value"].sum().reset_index()
        result = {}
        for _, row in grouped.iterrows():
            key = f"cost_{row['sys_costs']}_{int(row['t'])}"
            result[key] = row["Value"]
        return result
    except Exception as e:
        print(f"  ERROR reading systemcost.csv in {run_dir.name}: {e}")
        return None


def extract_curtailment(run_dir: Path) -> Optional[dict]:
    """
    Extract annual curtailment from outputs/curt_ann.csv.
    Returns flat dict: {f"curt_{year}": value_MWh}
    """
    curt_file = run_dir / "outputs" / "curt_ann.csv"
    if not curt_file.exists():
        return None
    try:
        df = pd.read_csv(curt_file)
        # curt_ann typically has columns: r, t, Value (or just t, Value for national)
        if "t" not in df.columns or "Value" not in df.columns:
            return None
        grouped = df.groupby("t")["Value"].sum().reset_index()
        result = {}
        for _, row in grouped.iterrows():
            key = f"curt_total_{int(row['t'])}"
            result[key] = row["Value"]
        return result
    except Exception as e:
        print(f"  ERROR reading curt_ann.csv in {run_dir.name}: {e}")
        return None


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def process_runs(
    runs_dir: Path,
    batch_prefix: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Process all surrogate runs for Stage 2 operational outputs.

    Returns:
        (df_gen, df_emit, df_cost, df_combined) - DataFrames for each output type
    """
    gen_rows = []
    emit_rows = []
    cost_rows = []
    combined_rows = []

    run_dirs = sorted(runs_dir.iterdir()) if runs_dir.is_dir() else []

    print(f"Scanning runs in: {runs_dir}")
    n_found = 0
    n_processed = 0

    for run_path in run_dirs:
        if not run_path.is_dir():
            continue
        case_name = run_path.name

        if batch_prefix and not case_name.startswith(batch_prefix):
            continue

        features = parse_case_name(case_name)
        if features is None:
            continue

        n_found += 1

        # Check that outputs directory exists
        if not (run_path / "outputs").exists():
            print(f"  Skipping {case_name}: no outputs/ directory")
            continue

        # Extract all Y outputs
        gen_data = extract_generation(run_path)
        emit_data = extract_emissions(run_path)
        cost_data = extract_systemcost(run_path)
        curt_data = extract_curtailment(run_path)

        if gen_data is None and emit_data is None and cost_data is None:
            print(f"  Skipping {case_name}: no operational outputs found")
            continue

        n_processed += 1
        base_row = {"case_name": case_name}
        base_row.update(features)

        # Generation
        if gen_data:
            row = base_row.copy()
            row.update(gen_data)
            gen_rows.append(row)

        # Emissions
        if emit_data:
            row = base_row.copy()
            row.update(emit_data)
            emit_rows.append(row)

        # System costs
        if cost_data:
            row = base_row.copy()
            row.update(cost_data)
            cost_rows.append(row)

        # Combined (all outputs in one row)
        combined = base_row.copy()
        if gen_data:
            combined.update(gen_data)
        if emit_data:
            combined.update(emit_data)
        if cost_data:
            combined.update(cost_data)
        if curt_data:
            combined.update(curt_data)
        combined_rows.append(combined)

    print(f"\nSummary: Found {n_found} surrogate cases, processed {n_processed}")

    # Build DataFrames
    df_gen = _build_df(gen_rows, "gen_")
    df_emit = _build_df(emit_rows, "emit_")
    df_cost = _build_df(cost_rows, "cost_")
    df_combined = _build_df(combined_rows, None)

    return df_gen, df_emit, df_cost, df_combined


def _build_df(rows: list, y_prefix: Optional[str]) -> pd.DataFrame:
    """Build a sorted DataFrame from rows, organizing columns."""
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    x_num_cols = sorted([c for c in df.columns if c.startswith("x_") and not c.endswith("_label")])
    x_label_cols = sorted([c for c in df.columns if c.endswith("_label")])

    if y_prefix:
        y_cols = sorted([c for c in df.columns if c.startswith(y_prefix)])
    else:
        # Combined: everything that isn't case_name or x_
        y_cols = sorted([
            c for c in df.columns
            if c not in (["case_name"] + x_num_cols + x_label_cols)
        ])

    col_order = ["case_name"] + x_num_cols + x_label_cols + y_cols
    # Only keep columns that exist
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]

    # Fill missing Y values with 0
    for c in y_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0.0)

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2: Extract operational outputs (Y) from ReEDS surrogate runs into ML-ready format."
    )
    parser.add_argument(
        "--runs_dir",
        type=str,
        default=None,
        help="Path to runs directory. Default: auto-detect from script location.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=".",
        help="Directory to save output CSV files.",
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
        repo_root = Path(__file__).resolve().parent.parent
        runs_dir = repo_root / "runs"

    if not runs_dir.exists():
        print(f"ERROR: Runs directory not found: {runs_dir}")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process all runs
    df_gen, df_emit, df_cost, df_combined = process_runs(runs_dir, batch_prefix=args.batch_prefix)

    # Save individual DataFrames
    datasets = {
        "stage2_generation_ml": df_gen,
        "stage2_emissions_ml": df_emit,
        "stage2_systemcost_ml": df_cost,
        "stage2_combined_ml": df_combined,
    }

    for name, df in datasets.items():
        if df.empty:
            print(f"\n{name}: EMPTY (no data)")
            continue

        x_cols = [c for c in df.columns if c.startswith("x_") and not c.endswith("_label")]
        y_cols = [c for c in df.columns if not c.startswith("x_") and c != "case_name"]
        print(f"\n{name}:")
        print(f"  Shape: {df.shape}")
        print(f"  X features: {len(x_cols)}, Y outputs: {len(y_cols)}, Runs: {len(df)}")

        # Save CSV
        csv_path = output_dir / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        print(f"  Saved: {csv_path.resolve()}")

        # Save numeric-only version
        numeric_cols = x_cols + [c for c in y_cols if not c.endswith("_label")]
        df_numeric = df[numeric_cols].copy()
        numeric_path = output_dir / f"{name}_numeric.csv"
        df_numeric.to_csv(numeric_path, index=False)
        print(f"  Saved numeric: {numeric_path.resolve()}")

        # Optionally save parquet
        if args.parquet:
            pq_path = output_dir / f"{name}.parquet"
            df.to_parquet(pq_path, index=False)
            print(f"  Saved parquet: {pq_path.resolve()}")

    # Print combined summary
    if not df_combined.empty:
        print("\n" + "=" * 60)
        print("COMBINED DATASET SUMMARY")
        print("=" * 60)
        x_cols = [c for c in df_combined.columns if c.startswith("x_") and not c.endswith("_label")]
        print(f"Total runs: {len(df_combined)}")
        print(f"X features (numeric): {len(x_cols)}")
        print(f"\nX Feature Ranges:")
        for col in sorted(x_cols):
            print(f"  {col}: [{df_combined[col].min()}, {df_combined[col].max()}] "
                  f"(unique: {df_combined[col].nunique()})")

        gen_cols = [c for c in df_combined.columns if c.startswith("gen_")]
        emit_cols = [c for c in df_combined.columns if c.startswith("emit_")]
        cost_cols = [c for c in df_combined.columns if c.startswith("cost_")]
        curt_cols = [c for c in df_combined.columns if c.startswith("curt_")]
        print(f"\nY outputs breakdown:")
        print(f"  Generation columns: {len(gen_cols)}")
        print(f"  Emission columns:   {len(emit_cols)}")
        print(f"  Cost columns:       {len(cost_cols)}")
        print(f"  Curtailment columns: {len(curt_cols)}")
        print(f"  Total Y columns:    {len(gen_cols) + len(emit_cols) + len(cost_cols) + len(curt_cols)}")


if __name__ == "__main__":
    main()
