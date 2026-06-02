"""
ReEDS Surrogate Model: ML Training & Evaluation Pipeline

Tests multiple ML models on the surrogate X-Y dataset:
  - Ridge / Lasso regression
  - Random Forest
  - Gradient Boosting (XGBoost)
  - Neural Network (MLP)

Approach:
  - Train final model on ALL samples (486 full factorial)
  - Evaluate via k-fold CV out-of-fold (OOF) predictions
  - Each sample gets a prediction from a model that never saw it
  - Per-output and aggregate error metrics (R², RMSE, MAE, NRMSE)
  - Visualization of results (parity plots, error distributions)

Usage:
    python surrogate_ml_models.py --data stage1_system_ml_numeric.csv
    python surrogate_ml_models.py --data stage2_regional_ml_numeric.csv --models ridge rf xgb
    python surrogate_ml_models.py --data stage1_system_ml_numeric.csv --n_folds 486  # LOO-CV
"""

import argparse
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from sklearn.model_selection import KFold, LeaveOneOut
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, Lasso
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.multioutput import MultiOutputRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

# Try importing XGBoost (optional)
try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class Config:
    """Pipeline configuration."""
    data_path: str = "surrogate_ml_data/stage1_system_ml_numeric.csv"
    output_dir: str = "surrogate_ml_results"
    random_state: int = 42
    n_folds: int = 10  # Set to n_samples for LOO-CV
    models: list = field(default_factory=lambda: ["ridge", "lasso", "rf", "xgb", "nn"])
    # Filter: only keep Y columns with sufficient variance
    min_variance_threshold: float = 1e-10
    # Neural network config
    nn_hidden_layers: tuple = (128, 64, 32)
    nn_max_iter: int = 1000


# ============================================================================
# MODEL DEFINITIONS
# ============================================================================

def get_model(name: str, n_outputs: int, config: Config):
    """Get a scikit-learn model by name."""
    if name == "ridge":
        return Ridge(alpha=1.0), "Ridge Regression"
    elif name == "lasso":
        return Lasso(alpha=0.1, max_iter=5000), "Lasso Regression"
    elif name == "rf":
        return RandomForestRegressor(
            n_estimators=200, max_depth=None, min_samples_leaf=2,
            random_state=config.random_state, n_jobs=-1
        ), "Random Forest"
    elif name == "xgb":
        if HAS_XGBOOST:
            base = XGBRegressor(
                n_estimators=200, max_depth=6, learning_rate=0.1,
                random_state=config.random_state, n_jobs=-1, verbosity=0
            )
        else:
            # Fallback to sklearn GradientBoosting
            base = GradientBoostingRegressor(
                n_estimators=200, max_depth=6, learning_rate=0.1,
                random_state=config.random_state
            )
        if n_outputs > 1:
            return MultiOutputRegressor(base), "XGBoost (Gradient Boosting)"
        return base, "XGBoost (Gradient Boosting)"
    elif name == "nn":
        return MLPRegressor(
            hidden_layer_sizes=config.nn_hidden_layers,
            activation="relu", solver="adam",
            max_iter=config.nn_max_iter,
            early_stopping=True, validation_fraction=0.1,
            random_state=config.random_state
        ), "Neural Network (MLP)"
    else:
        raise ValueError(f"Unknown model: {name}")


# ============================================================================
# DATA LOADING & PREPARATION
# ============================================================================

def load_data(config: Config):
    """Load and split data into X (features) and Y (outputs)."""
    df = pd.read_csv(config.data_path)
    print(f"Loaded data: {df.shape[0]} samples, {df.shape[1]} columns")

    # Identify X and Y columns
    x_cols = [c for c in df.columns if c.startswith("x_")]
    y_cols = [c for c in df.columns if not c.startswith("x_")]

    X = df[x_cols].values.astype(np.float64)
    Y = df[y_cols].values.astype(np.float64)

    print(f"  X features: {X.shape[1]} ({x_cols})")
    print(f"  Y outputs: {Y.shape[1]}")

    # Filter out constant Y columns (zero variance)
    y_var = Y.var(axis=0)
    valid_mask = y_var > config.min_variance_threshold
    n_removed = (~valid_mask).sum()
    if n_removed > 0:
        print(f"  Removed {n_removed} constant Y columns (zero variance)")
    Y = Y[:, valid_mask]
    y_cols = [c for i, c in enumerate(y_cols) if valid_mask[i]]
    print(f"  Final Y outputs: {Y.shape[1]}")

    return X, Y, x_cols, y_cols


# ============================================================================
# TRAINING & EVALUATION
# ============================================================================

def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray, y_cols: list) -> dict:
    """Compute per-output and aggregate metrics from OOF predictions."""
    n_outputs = y_true.shape[1] if y_true.ndim > 1 else 1

    if n_outputs == 1:
        y_true = y_true.reshape(-1, 1)
        y_pred = y_pred.reshape(-1, 1)

    per_output = {}
    r2_list = []
    for i in range(n_outputs):
        yt = y_true[:, i]
        yp = y_pred[:, i]
        r2 = r2_score(yt, yp)
        rmse = np.sqrt(mean_squared_error(yt, yp))
        mae = mean_absolute_error(yt, yp)
        y_range = yt.max() - yt.min()
        nrmse = rmse / y_range if y_range > 0 else 0.0
        per_output[y_cols[i]] = {"r2": r2, "rmse": rmse, "mae": mae, "nrmse": nrmse}
        r2_list.append(r2)

    aggregate = {
        "r2_mean": float(np.mean(r2_list)),
        "r2_median": float(np.median(r2_list)),
        "r2_min": float(np.min(r2_list)),
        "r2_max": float(np.max(r2_list)),
        "n_outputs_r2_above_0.9": int(np.sum(np.array(r2_list) > 0.9)),
        "n_outputs_r2_above_0.95": int(np.sum(np.array(r2_list) > 0.95)),
        "n_outputs_total": n_outputs,
    }

    return {"per_output": per_output, "aggregate": aggregate}


def compute_oof_predictions(X, Y, model_name, config: Config):
    """
    Compute out-of-fold (OOF) predictions using k-fold CV on ALL data.
    Each sample gets a prediction from a model that never saw it.
    Returns an array of predictions with same shape as Y.
    """
    n_samples, n_outputs = Y.shape
    oof_preds = np.zeros_like(Y)

    # Use LOO if n_folds >= n_samples
    if config.n_folds >= n_samples:
        splitter = LeaveOneOut()
        n_splits = n_samples
    else:
        splitter = KFold(n_splits=config.n_folds, shuffle=True,
                         random_state=config.random_state)
        n_splits = config.n_folds

    for fold, (train_idx, val_idx) in enumerate(splitter.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        Y_train, Y_val = Y[train_idx], Y[val_idx]

        # Scale features
        scaler_x = StandardScaler()
        X_train_s = scaler_x.fit_transform(X_train)
        X_val_s = scaler_x.transform(X_val)

        # Get model
        model, _ = get_model(model_name, n_outputs, config)

        # Train and predict
        if model_name == "nn":
            scaler_y = StandardScaler()
            Y_train_s = scaler_y.fit_transform(Y_train)
            model.fit(X_train_s, Y_train_s)
            Y_pred_s = model.predict(X_val_s)
            oof_preds[val_idx] = scaler_y.inverse_transform(Y_pred_s)
        else:
            model.fit(X_train_s, Y_train)
            oof_preds[val_idx] = model.predict(X_val_s)

    return oof_preds


def train_final_model(X, Y, model_name, config: Config):
    """Train final model on ALL data. This is the production surrogate."""
    scaler_x = StandardScaler()
    X_s = scaler_x.fit_transform(X)

    n_outputs = Y.shape[1]
    model, display_name = get_model(model_name, n_outputs, config)

    if model_name == "nn":
        scaler_y = StandardScaler()
        Y_s = scaler_y.fit_transform(Y)
        model.fit(X_s, Y_s)
    else:
        scaler_y = None
        model.fit(X_s, Y)

    return model, scaler_x, scaler_y, display_name


# ============================================================================
# VISUALIZATION
# ============================================================================

def plot_model_comparison(all_results: dict, output_dir: Path):
    """Bar chart comparing OOF R² across models."""
    fig, ax = plt.subplots(figsize=(10, 5))

    model_names = []
    r2_means = []
    r2_medians = []

    for name, res in all_results.items():
        model_names.append(res["display_name"])
        r2_means.append(res["metrics"]["aggregate"]["r2_mean"])
        r2_medians.append(res["metrics"]["aggregate"]["r2_median"])

    x = np.arange(len(model_names))
    width = 0.35
    bars1 = ax.bar(x - width/2, r2_means, width, color="steelblue", alpha=0.8, label="Mean R²")
    bars2 = ax.bar(x + width/2, r2_medians, width, color="coral", alpha=0.8, label="Median R²")
    ax.set_xticks(x)
    ax.set_xticklabels(model_names, rotation=15, ha="right")
    ax.set_ylabel("R² (OOF predictions)")
    ax.set_title("Model Comparison: Out-of-Fold R² (all 486 samples)")
    ax.set_ylim(min(0, min(r2_means) - 0.1), 1.05)
    ax.axhline(0.9, color="red", linestyle="--", alpha=0.5, label="R²=0.9")
    ax.axhline(0.95, color="green", linestyle="--", alpha=0.5, label="R²=0.95")
    ax.legend()

    for bar, val in zip(bars1, r2_means):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"{val:.3f}", ha="center", va="bottom", fontsize=8)
    for bar, val in zip(bars2, r2_medians):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"{val:.3f}", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_dir / "model_comparison_r2.png", dpi=150)
    plt.close()


def plot_r2_distribution(all_results: dict, output_dir: Path):
    """Histogram of per-output R² for each model."""
    n_models = len(all_results)
    fig, axes = plt.subplots(1, n_models, figsize=(4 * n_models, 4), squeeze=False)

    for idx, (name, res) in enumerate(all_results.items()):
        ax = axes[0, idx]
        r2_values = [v["r2"] for v in res["metrics"]["per_output"].values()]
        ax.hist(r2_values, bins=20, color="steelblue", alpha=0.7, edgecolor="black")
        ax.set_xlabel("R²")
        ax.set_ylabel("Count")
        ax.set_title(f"{res['display_name']}\n(median={np.median(r2_values):.3f})")
        ax.axvline(0.9, color="red", linestyle="--", alpha=0.7)
        ax.set_xlim(-0.5, 1.05)

    plt.tight_layout()
    plt.savefig(output_dir / "r2_distribution_per_output.png", dpi=150)
    plt.close()


def plot_parity(Y_true, Y_pred, y_cols, model_name, output_dir: Path, n_plots=6):
    """Parity plots (predicted vs actual) for top/bottom outputs."""
    r2_per_output = []
    for i in range(Y_true.shape[1]):
        r2_per_output.append(r2_score(Y_true[:, i], Y_pred[:, i]))
    r2_arr = np.array(r2_per_output)

    # Select top 3 and bottom 3 by R²
    sorted_idx = np.argsort(r2_arr)
    bottom_idx = sorted_idx[:3]
    top_idx = sorted_idx[-3:]
    selected_idx = np.concatenate([top_idx, bottom_idx])

    fig, axes = plt.subplots(2, 3, figsize=(14, 9))
    axes = axes.flatten()

    for plot_i, out_i in enumerate(selected_idx):
        ax = axes[plot_i]
        yt = Y_true[:, out_i]
        yp = Y_pred[:, out_i]
        r2 = r2_arr[out_i]

        ax.scatter(yt, yp, alpha=0.4, s=15, color="steelblue")
        lims = [min(yt.min(), yp.min()), max(yt.max(), yp.max())]
        ax.plot(lims, lims, "r--", alpha=0.7)
        ax.set_xlabel("Actual")
        ax.set_ylabel("Predicted (OOF)")
        col_name = y_cols[out_i] if len(y_cols[out_i]) < 30 else y_cols[out_i][:27] + "..."
        label = "BEST" if plot_i < 3 else "WORST"
        ax.set_title(f"{label}: {col_name}\nR²={r2:.4f}", fontsize=9)

    plt.suptitle(f"Parity Plots (OOF) — {model_name}", fontsize=12)
    plt.tight_layout()
    safe_name = model_name.replace(" ", "_").replace("(", "").replace(")", "")
    plt.savefig(output_dir / f"parity_{safe_name}.png", dpi=150)
    plt.close()


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def run_pipeline(config: Config):
    """Run the full ML surrogate model pipeline."""
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("ReEDS SURROGATE MODEL — ML PIPELINE")
    print("=" * 70)

    # 1. Load data
    print("\n[1/4] Loading data...")
    X, Y, x_cols, y_cols = load_data(config)
    n_samples = X.shape[0]

    cv_type = "LOO-CV" if config.n_folds >= n_samples else f"{config.n_folds}-fold CV"
    print(f"\n[2/4] Evaluation strategy: {cv_type} on all {n_samples} samples")
    print(f"       Final model: trained on all {n_samples} samples")

    # 2. Compute OOF predictions and train final models
    print(f"\n[3/4] Training models: {config.models}")
    all_results = {}

    for model_name in config.models:
        if model_name == "xgb" and not HAS_XGBOOST:
            print(f"\n  --- {model_name.upper()} (using sklearn GradientBoosting) ---")
        else:
            print(f"\n  --- {model_name.upper()} ---")

        # OOF predictions for evaluation
        print(f"    Computing OOF predictions ({cv_type})...")
        oof_preds = compute_oof_predictions(X, Y, model_name, config)

        # Evaluate OOF predictions
        metrics = evaluate_predictions(Y, oof_preds, y_cols)
        agg = metrics["aggregate"]
        print(f"    OOF R² mean: {agg['r2_mean']:.4f}, median: {agg['r2_median']:.4f}")
        print(f"    Outputs with R²>0.9: {agg['n_outputs_r2_above_0.9']}/{agg['n_outputs_total']}")
        print(f"    Outputs with R²>0.95: {agg['n_outputs_r2_above_0.95']}/{agg['n_outputs_total']}")

        # Train final model on ALL data
        print(f"    Training final model on all {n_samples} samples...")
        model, scaler_x, scaler_y, display_name = train_final_model(
            X, Y, model_name, config
        )

        all_results[model_name] = {
            "display_name": display_name,
            "metrics": metrics,
            "oof_preds": oof_preds,
            "model": model,
            "scaler_x": scaler_x,
            "scaler_y": scaler_y,
        }

        # Parity plots using OOF predictions
        plot_parity(Y, oof_preds, y_cols, display_name, output_dir)

    # 3. Visualization & summary
    print(f"\n[4/4] Generating comparison plots...")
    plot_model_comparison(all_results, output_dir)
    plot_r2_distribution(all_results, output_dir)

    # Identify best model by mean R²
    best_model = max(all_results.keys(),
                     key=lambda k: all_results[k]["metrics"]["aggregate"]["r2_mean"])

    # Save summary JSON
    summary = {
        "config": {
            "data_path": config.data_path,
            "n_folds": config.n_folds,
            "cv_type": cv_type,
            "n_samples": int(n_samples),
            "n_x_features": int(X.shape[1]),
            "n_y_outputs": int(Y.shape[1]),
            "evaluation": "Out-of-fold predictions (all samples used for both training and evaluation)",
        },
        "models": {},
    }
    for name, res in all_results.items():
        agg = res["metrics"]["aggregate"]
        summary["models"][name] = {
            "display_name": res["display_name"],
            "oof_r2_mean": agg["r2_mean"],
            "oof_r2_median": agg["r2_median"],
            "oof_r2_min": agg["r2_min"],
            "oof_r2_max": agg["r2_max"],
            "n_outputs_r2_above_0.9": agg["n_outputs_r2_above_0.9"],
            "n_outputs_r2_above_0.95": agg["n_outputs_r2_above_0.95"],
        }

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Save per-output metrics for best model
    best_metrics_df = pd.DataFrame(all_results[best_model]["metrics"]["per_output"]).T
    best_metrics_df.index.name = "output"
    best_metrics_df.to_csv(output_dir / f"per_output_metrics_{best_model}.csv")

    # Final report
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"\nEvaluation: {cv_type} out-of-fold predictions on {n_samples} samples")
    print(f"Final models trained on: all {n_samples} samples")
    print(f"\n{'Model':<30} {'OOF R² mean':>12} {'OOF R² med':>11} {'R²>0.9':>8} {'R²>0.95':>8}")
    print("-" * 72)
    for name, res in all_results.items():
        agg = res["metrics"]["aggregate"]
        print(f"{res['display_name']:<30} {agg['r2_mean']:>12.4f} {agg['r2_median']:>11.4f} "
              f"{agg['n_outputs_r2_above_0.9']:>4}/{agg['n_outputs_total']:<4} "
              f"{agg['n_outputs_r2_above_0.95']:>4}/{agg['n_outputs_total']:<4}")

    print(f"\nBest model: {all_results[best_model]['display_name']} "
          f"(OOF R² mean = {all_results[best_model]['metrics']['aggregate']['r2_mean']:.4f})")
    print(f"\nOutputs saved to: {output_dir.resolve()}")
    print(f"  - summary.json")
    print(f"  - model_comparison_r2.png")
    print(f"  - r2_distribution_per_output.png")
    print(f"  - parity_*.png (per model)")
    print(f"  - per_output_metrics_{best_model}.csv")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ReEDS Surrogate Model: ML Training & Evaluation Pipeline"
    )
    parser.add_argument(
        "--data", type=str, default="surrogate_ml_data/stage1_system_ml_numeric.csv",
        help="Path to the ML-ready CSV (numeric X+Y columns).",
    )
    parser.add_argument(
        "--output_dir", type=str, default="surrogate_ml_results",
        help="Directory to save results and plots.",
    )
    parser.add_argument(
        "--models", nargs="+", default=["ridge", "lasso", "rf", "xgb", "nn"],
        choices=["ridge", "lasso", "rf", "xgb", "nn"],
        help="Models to test.",
    )
    parser.add_argument(
        "--n_folds", type=int, default=10,
        help="Number of CV folds (default: 10). Set to n_samples for LOO-CV.",
    )
    parser.add_argument(
        "--random_state", type=int, default=42,
        help="Random seed for reproducibility.",
    )
    args = parser.parse_args()

    config = Config(
        data_path=args.data,
        output_dir=args.output_dir,
        n_folds=args.n_folds,
        random_state=args.random_state,
        models=args.models,
    )

    run_pipeline(config)


if __name__ == "__main__":
    main()
