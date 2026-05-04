import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import ConvexHull
from scipy.stats import gaussian_kde
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

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

        # add shortened label on plot
        ax.text(
            x,
            y_mid,
            short_label,
            fontsize=11,
            ha='center',
            va='center'
        )

    ax.set_xlabel("Composite supply risk (60/20/20)", fontsize=16)
    ax.set_ylabel("% Difference in Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

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

            ax.text(
                x0,
                y0,
                short_label,
                fontsize=11,
                ha='center',
                va='center'
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

            ax.text(
                center[0],
                center[1],
                short_label,
                fontsize=11,
                ha='center',
                va='center'
            )

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

            ax.text(
                x0,
                y0,
                short_label,
                fontsize=11,
                ha='center',
                va='center'
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

    ax.set_xlabel("Composite supply risk", fontsize=16)
    ax.set_ylabel("% Difference in Discounted System Cost", fontsize=16)

    if title is not None:
        ax.set_title(title, fontsize=18)
    else:
        ax.set_title(os.path.splitext(filename)[0], fontsize=18)

    ax.grid(True)

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
