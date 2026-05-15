import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
from scipy.stats import gaussian_kde
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from adjustText import adjust_text

# -----------------------------
# LOAD + CLEAN 
# -----------------------------
# import data files
disc_cost = pd.read_csv("cmm_disc_cost.csv")
risk = pd.read_csv("cmm_supplyrisk.csv")

# clean up system costs
disc_cost[['Scenario','Material_name']] = disc_cost['Scen'].str.split("_", expand=True)

ref_lookup = disc_cost[disc_cost['Material_name'] == 'Reference'].set_index('Scenario')['Disc_Cost']
ref_lookup['Restrict'] = ref_lookup['Reference']

disc_cost['ref_cost'] = disc_cost['Scenario'].map(ref_lookup)
disc_cost = disc_cost.dropna(subset=["ref_cost"])

disc_cost['Pct_Diff'] = ((disc_cost['Disc_Cost'] - disc_cost['ref_cost']) / disc_cost['ref_cost']) * 100

disc_cost["Pct_Diff"] = (
    disc_cost["Pct_Diff"].astype(float).round(6)
)

disc_cost["Pct_Diff"] = disc_cost["Pct_Diff"].clip(lower=0)

disc_cost = disc_cost[['Scenario', 'Material_name', 'Pct_Diff']]


# clean up supply risk data

symbol_to_full = {
    "Ag": "Silver","Co": "Cobalt","Dy": "Dysprosium","Ga": "Gallium",
    "Hf": "Hafnium","In": "Indium","Li": "Lithium","Mg": "Magnesium",
    "Mn": "Manganese","Nd": "Neodymium","Ni": "Nickel","Pr": "Praseodymium",
    "Sn": "Tin","Tb": "Terbium","Te": "Tellurium","V": "Vanadium","Y": "Yttrium",
    "Cu":"Copper","Al":"Aluminum"
}

risk["Material_name"] = risk["Material"].map(symbol_to_full)
risk = risk.dropna(subset=["Material_name"])
risk = risk[['Material','Material_name', 'APD (60%)', 'COD (20%)', 'RDS (20%)','Supply Risk']]

df = disc_cost.merge(risk, on="Material_name", how="inner")

materials = sorted(df["Material_name"].unique())
cmap = plt.cm.get_cmap("tab20", len(materials))
color_map = {m: cmap(i) for i, m in enumerate(materials)}

# -----------------------------
# SPLIT CASES
# -----------------------------
# baseline (no restrict)
df_without_restrict = df[
    ~df["Scenario"].str.contains("Restrict", case=False, na=False)
]

# augmented (everything, including restrict)
df_with_restrict = df.copy()

df_only_restrict = df[
    df["Scenario"].str.contains("Restrict", case=False, na=False)
]

# -----------------------------
# FIXED RISK FUNCTION
# -----------------------------
def plot_fixed(df_input, filename, title=None):
    df_fixed = df_input.copy()

    df_fixed["Composite_Risk"] = (
        0.6 * df_fixed["APD (60%)"] +
        0.2 * df_fixed["COD (20%)"] +
        0.2 * df_fixed["RDS (20%)"]
    )

    fig, ax = plt.subplots(figsize=(12, 9))
    legend_handles = []

    # Store labels so we can adjust them after all points/ranges are drawn
    texts = []
    label_xs = []
    label_ys = []

    for mat in materials:
        sub = df_fixed[df_fixed["Material_name"] == mat]
        if sub.empty:
            continue

        color = color_map[mat]

        short_label = sub["Material"].iloc[0]
        long_label = sub["Material_name"].iloc[0]
        legend_label = f"{short_label}: {long_label}"

        x = sub["Composite_Risk"].iloc[0]
        n_obs = len(sub)

        y_min = sub["Pct_Diff"].min()
        y_max = sub["Pct_Diff"].max()

        # midpoint used for label placement
        if n_obs == 1:
            y_mid = sub["Pct_Diff"].iloc[0]
        else:
            y_mid = (y_min + y_max) / 2

        # draw a point if only one observation or zero-height range
        if n_obs == 1 or np.isclose(y_min, y_max):
            ax.scatter(
                x,
                y_mid,
                color=color,
                s=80,
                zorder=3
            )

            legend_handles.append(
                Line2D(
                    [0], [0],
                    marker='o',
                    linestyle='None',
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )
            )
        else:
            ax.plot(
                [x, x],
                [y_min, y_max],
                color=color,
                linewidth=2.5
            )

            legend_handles.append(
                Line2D(
                    [0], [0],
                    color=color,
                    linewidth=2.5,
                    label=legend_label
                )
            )

        # add shortened label on plot, but store it for later adjustment
        txt = ax.text(
            x,
            y_mid,
            short_label,
            fontsize=11,
            ha='center',
            va='center',
            zorder=5,
            bbox=dict(
                facecolor='white',
                edgecolor='none',
                alpha=0.75,
                pad=1
            )
        )

        texts.append(txt)
        label_xs.append(x)
        label_ys.append(y_mid)

    ax.set_xlabel("Composite supply risk (60/20/20)", fontsize=16)
    ax.set_ylabel("% Difference in Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

    # Adjust labels to reduce overlap
    if texts:
        adjust_text(
            texts,
            x=label_xs,
            y=label_ys,
            ax=ax,
            expand=(1.2, 1.4),
            force_text=(0.5, 0.8),
            force_static=(0.2, 0.4),
            arrowprops=dict(
                arrowstyle='-',
                linewidth=0.6,
                alpha=0.6
            )
        )

    if legend_handles:
        ax.legend(
            handles=legend_handles,
            title="Material",
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            fontsize=10,
            title_fontsize=11,
            frameon=True
        )

    fig.tight_layout()
    fig.savefig(filename, dpi=300, bbox_inches="tight")
    plt.close(fig)


# -----------------------------
# POLYGON FUNCTION
# -----------------------------
def plot_polygons(df_input, filename, title=None, use_density=False):
    # weight grid
    apd_vals = np.linspace(0.5, 0.7, 25)
    cod_vals = np.linspace(0.1, 0.25, 25)

    rows = []
    for a in apd_vals:
        for c in cod_vals:
            r = 1 - a - c
            if r <= 0:
                continue

            tmp = df_input.copy()
            tmp["Composite_Risk"] = (
                a * tmp["APD (60%)"] +
                c * tmp["COD (20%)"] +
                r * tmp["RDS (20%)"]
            )
            rows.append(tmp)

    df_all = pd.concat(rows, ignore_index=True)

    fig, ax = plt.subplots(figsize=(12, 9))
    legend_handles = []

    # Store labels so we can adjust them after all polygons/points are drawn
    texts = []
    label_xs = []
    label_ys = []

    for mat in materials:
        sub = df_all[df_all["Material_name"] == mat]
        if sub.empty:
            continue

        color = color_map[mat]

        short_label = sub["Material"].iloc[0]
        long_label = sub["Material_name"].iloc[0]
        legend_label = f"{short_label}: {long_label}"

        # use actual (risk, cost) pairs
        pts = sub[["Composite_Risk", "Pct_Diff"]].drop_duplicates().to_numpy()

        if len(pts) == 0:
            continue

        x = pts[:, 0]
        y = pts[:, 1]

        # -----------------------------
        # DENSITY (optional)
        # -----------------------------
        if use_density and len(pts) > 1:
            try:
                kde = gaussian_kde(np.vstack([x, y]))
                xi, yi = np.mgrid[
                    x.min():x.max():100j,
                    y.min():y.max():100j
                ]
                zi = kde(np.vstack([xi.flatten(), yi.flatten()]))
                zi = zi.reshape(xi.shape)

                ax.contourf(
                    xi,
                    yi,
                    zi,
                    levels=6,
                    alpha=0.25
                )
            except Exception:
                pass

        # -----------------------------
        # POINT FALLBACK
        # -----------------------------
        # If there is only one point, or not enough unique points
        # to form a polygon, just plot a point
        if len(pts) < 3:
            x0 = sub["Composite_Risk"].mean()
            y0 = sub["Pct_Diff"].mean()

            ax.scatter(
                x0,
                y0,
                color=color,
                s=80,
                zorder=3
            )

            txt = ax.text(
                x0,
                y0,
                short_label,
                fontsize=11,
                ha='center',
                va='center',
                zorder=5,
                bbox=dict(
                    facecolor='white',
                    edgecolor='none',
                    alpha=0.75,
                    pad=1
                )
            )

            texts.append(txt)
            label_xs.append(x0)
            label_ys.append(y0)

            legend_handles.append(
                Line2D(
                    [0], [0],
                    marker='o',
                    linestyle='None',
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )
            )
            continue

        # -----------------------------
        # HULL
        # -----------------------------
        try:
            hull = ConvexHull(pts)
            hull_pts = pts[hull.vertices]

            center = hull_pts.mean(axis=0)
            angles = np.arctan2(
                hull_pts[:, 1] - center[1],
                hull_pts[:, 0] - center[0]
            )
            hull_pts = hull_pts[np.argsort(angles)]
            hull_pts = np.vstack([hull_pts, hull_pts[0]])

            ax.plot(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                linewidth=2
            )

            ax.fill(
                hull_pts[:, 0],
                hull_pts[:, 1],
                color=color,
                alpha=0.35
            )

            txt = ax.text(
                center[0],
                center[1],
                short_label,
                fontsize=11,
                ha='center',
                va='center',
                zorder=5,
                bbox=dict(
                    facecolor='white',
                    edgecolor='none',
                    alpha=0.75,
                    pad=1
                )
            )

            texts.append(txt)
            label_xs.append(center[0])
            label_ys.append(center[1])

            legend_handles.append(
                Patch(
                    facecolor=color,
                    edgecolor=color,
                    alpha=0.35,
                    label=legend_label
                )
            )

        except Exception:
            # fallback to a point if hull fails
            x0 = sub["Composite_Risk"].mean()
            y0 = sub["Pct_Diff"].mean()

            ax.scatter(
                x0,
                y0,
                color=color,
                s=80,
                zorder=3
            )

            txt = ax.text(
                x0,
                y0,
                short_label,
                fontsize=11,
                ha='center',
                va='center',
                zorder=5,
                bbox=dict(
                    facecolor='white',
                    edgecolor='none',
                    alpha=0.75,
                    pad=1
                )
            )

            texts.append(txt)
            label_xs.append(x0)
            label_ys.append(y0)

            legend_handles.append(
                Line2D(
                    [0], [0],
                    marker='o',
                    linestyle='None',
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=legend_label
                )
            )

    ax.set_xlabel("Composite supply risk", fontsize=16)
    ax.set_ylabel("% Difference in Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

    # Adjust labels to reduce overlap
    if texts:
        adjust_text(
            texts,
            x=label_xs,
            y=label_ys,
            ax=ax,
            expand=(1.2, 1.4),
            force_text=(0.5, 0.8),
            force_static=(0.2, 0.4),
            arrowprops=dict(
                arrowstyle='-',
                linewidth=0.6,
                alpha=0.6
            )
        )

    if legend_handles:
        ax.legend(
            handles=legend_handles,
            title="Material",
            loc="center left",
            bbox_to_anchor=(1.02, 0.5),
            fontsize=10,
            title_fontsize=11,
            frameon=True
        )

    fig.tight_layout()
    fig.savefig(filename, dpi=300, bbox_inches="tight")
    plt.close(fig)

# -----------------------------
# CREATE ALL 6 PLOTS
# -----------------------------

# 1) fixed
plot_fixed(df_with_restrict, "1_fixed_with_restrict.png", title="Outcome Range at Fixed Supply Risk, Including Strict Unavailability")
plot_fixed(df_without_restrict, "1_fixed_without_restrict.png",title="Outcome Range at Fixed Supply Risk, Excluding Strict Unavailability")

# 2) polygons no density
plot_polygons(df_with_restrict, "2_range_no_density_with_restrict.png", use_density=False, title="Outcome Envelope Across Supply Risk Sensitivities, Including Strict Unavailability")
plot_polygons(df_without_restrict, "2_range_no_density_without_restrict.png", use_density=False, title="Outcome Envelope Across Supply Risk Sensitivities, Excluding Strict Unavailability")

# 3) polygons with density
plot_polygons(df_with_restrict, "3_range_with_density_with_restrict.png", use_density=True, title="Outcome Envelope Across Supply Risk Sensitivities, Including Strict Unavailability")
plot_polygons(df_without_restrict, "3_range_with_density_without_restrict.png", use_density=True, title="Outcome Envelope Across Supply Risk Sensitivities, Excluding Strict Unavailability")


# 4) points for restrict only 
plot_fixed(df_only_restrict, "4_points_only_restrict.png", title="Strict Unavailability at Fixed Supply Risk")


# ------------------------------
# COPPER TEST PLOT
# ------------------------------
copper = pd.read_csv("cmm_copper_temp.csv")
copper[['Scenario','Material_name']] = copper['scenario'].str.split("_", expand=True)

ref_cost = copper.loc[copper["Scenario"] == "Reference", "disc_cost"].iloc[0]

copper['Pct_Diff'] = ((copper['disc_cost'] - ref_cost) / ref_cost) * 100

copper["Pct_Diff"] = (
    copper["Pct_Diff"].astype(float).round(6)
)

copper["Pct_Diff"] = copper["Pct_Diff"].clip(lower=0)

copper = copper[['Scenario', 'Material_name', 'Pct_Diff','min_avail']]

def plot_min_avail(df_input, filename, title=None):
    df_plot = df_input.copy()

    # Check required columns
    required_cols = ["min_avail", "Pct_Diff", "Scenario"]
    missing_cols = [col for col in required_cols if col not in df_plot.columns]

    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Drop rows where the point or label cannot be plotted
    df_plot = df_plot.dropna(subset=["min_avail", "Pct_Diff", "Scenario"]).copy()

    # Make sure Scenario labels are strings
    df_plot["Scenario"] = df_plot["Scenario"].astype(str)

    fig, ax = plt.subplots(figsize=(12, 9))

    texts = []
    label_xs = []
    label_ys = []

    # Plot all points
    ax.scatter(
        df_plot["min_avail"],
        df_plot["Pct_Diff"],
        s=80,
        color="steelblue",
        edgecolor="black",
        linewidth=0.7,
        zorder=3
    )

    # Add labels
    for _, row in df_plot.iterrows():
        x = row["min_avail"]
        y = row["Pct_Diff"]
        label = row["Scenario"]

        txt = ax.text(
            x,
            y,
            label,
            fontsize=11,
            ha="center",
            va="center",
            zorder=5,
            clip_on=False,  # prevents labels from disappearing at plot edges
            bbox=dict(
                facecolor="white",
                edgecolor="none",
                alpha=0.75,
                pad=1
            )
        )

        texts.append(txt)
        label_xs.append(x)
        label_ys.append(y)

    ax.set_xlabel("Share of Global Copper Supply", fontsize=16)
    ax.set_ylabel("% Difference in Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

    # Add extra space around the plotted points so labels have room
    x_min = df_plot["min_avail"].min()
    x_max = df_plot["min_avail"].max()
    y_min = df_plot["Pct_Diff"].min()
    y_max = df_plot["Pct_Diff"].max()

    x_range = x_max - x_min
    y_range = y_max - y_min

    if x_range == 0:
        x_range = 1
    if y_range == 0:
        y_range = 1

    ax.set_xlim(
        x_min - 0.12 * x_range,
        x_max + 0.12 * x_range
    )

    ax.set_ylim(
        y_min - 0.12 * y_range,
        y_max + 0.12 * y_range
    )

    # Adjust labels to reduce overlap
    if texts:
        adjust_text(
            texts,
            x=label_xs,
            y=label_ys,
            ax=ax,
            expand=(1.3, 1.5),
            force_text=(0.6, 0.9),
            force_static=(0.3, 0.5),
            arrowprops=dict(
                arrowstyle="-",
                linewidth=0.6,
                alpha=0.6
            )
        )

    fig.tight_layout()
    fig.savefig(filename, dpi=300, bbox_inches="tight")
    plt.close(fig)

plot_min_avail(copper, "5_points_availability.png", title='Change in Discounted System Costs Across Copper Supply Scenarios')