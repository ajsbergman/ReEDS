#!/usr/bin/env python
"""
poi_comparison_slide.py
=======================

Build a multi-case "slide" comparing ReEDS runs that differ in their POI /
network-reinforcement cost treatment (or any set of ReEDS cases).

Layout (one row per case, baseline = top row):

    | run description | <left metric> level | <left metric> diff vs baseline | <right metric> level | <right metric> diff vs baseline |

Two slide variants are produced:
    * version A : left = capacity,  right = transmission
    * version B : left = capacity,  right = generation

The "diff vs baseline" columns subtract the top-row (baseline) case, by year and
category, and plot the result as an up/down stacked bar (net total drawn as a line).

USAGE
-----
Edit the CASES list at the bottom (or import `make_slide` and pass your own), then:

    python postprocessing/poi_comparison_slide.py

Each case is a dict: {"label", "description", "path"} where `path` is the run
directory that contains an `outputs/` folder. The FIRST case is the baseline.

This is data-driven: rerun it unchanged after the runs have been redone with the
reinforcement-relocation fixes and the figures will update automatically.
"""

import os
import sys
import textwrap
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# ---------------------------------------------------------------------------
# Category grouping + colors — sourced from the canonical ReEDS style files:
#   * postprocessing/tech_aggregation.csv  (raw tech -> display category;
#     applied via reeds.reedsplots.simplify_techs)
#   * postprocessing/bokehpivot/in/reeds2/tech_style.csv   (display -> color, order)
#   * postprocessing/bokehpivot/in/reeds2/trtype_style.csv (trtype  -> color, order)
# so colors/ordering match the rest of the ReEDS plotting stack.
# ---------------------------------------------------------------------------
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)  # so `import reeds` works when run as a script
_STYLE_DIR = os.path.join(THIS_DIR, 'bokehpivot', 'in', 'reeds2')
GREY = '#a6a6a6'
## POI / intra-zone reinforcement reuses the 'Reinforcement' style entry.
POI_CATEGORY = 'Reinforcement'

from reeds.reedsplots import simplify_techs  # uses tech_aggregation.csv


def _load_style(fname):
    """Return (order_list, color_dict) from a bokehpivot *_style.csv."""
    s = pd.read_csv(os.path.join(_STYLE_DIR, fname))
    order = s['order'].astype(str).tolist()
    colors = dict(zip(s['order'].astype(str), s['color'].astype(str)))
    return order, colors


TECH_ORDER, TECH_COLORS = _load_style('tech_style.csv')
TRTYPE_ORDER, TRTYPE_COLORS = _load_style('trtype_style.csv')


def _map_techs(series):
    """Map raw ReEDS tech names -> display categories via tech_aggregation.csv."""
    uniq = list(pd.Series(series).unique())
    return pd.Series(series).map(dict(zip(uniq, simplify_techs(uniq))))


# ---------------------------------------------------------------------------
# Metric loaders -> return DataFrame indexed by year, columns = categories
# ---------------------------------------------------------------------------
def _read(path, fname):
    fp = os.path.join(path, 'outputs', fname)
    return pd.read_csv(fp) if os.path.exists(fp) else None


def load_capacity(path):
    """GW of installed capacity by display tech category and year."""
    d = _read(path, 'cap.csv')
    if d is None:
        return None
    d['g'] = _map_techs(d['i'])
    p = d.pivot_table(index='t', columns='g', values='Value', aggfunc='sum').fillna(0) / 1e3
    return _order_cols(p, TECH_ORDER)


def load_generation(path):
    """TWh of annual generation by display tech category and year."""
    d = _read(path, 'gen_ann.csv')
    if d is None:
        return None
    d['g'] = _map_techs(d['i'])
    p = d.pivot_table(index='t', columns='g', values='Value', aggfunc='sum').fillna(0) / 1e6
    return _order_cols(p, TECH_ORDER)


def load_transmission(path):
    """GW of transmission *capacity* by type and year, incl. POI (intra-zone).

    Inter-zonal transfer capacity (tran_out.csv, MW summed over interfaces) and
    intra-zonal POI / network-reinforcement capacity (poi_capacity.csv, MW) are
    both reported in GW so they are directly comparable and the POI term this
    branch actually moves is visible. POI is labeled 'Reinforcement' to reuse the
    canonical trtype_style entry. (tran_mi_out.csv gives TW-mi instead, but its
    huge inter-zonal mileage drowns out POI on a shared axis.)
    """
    out = {}
    tc = _read(path, 'tran_out.csv')
    if tc is not None:
        g = tc.groupby(['trtype', 't'])['Value'].sum().div(1e3)  # MW -> GW
        for tr, s in g.groupby(level=0):
            out[tr] = s.droplevel(0)
    poi = _read(path, 'poi_capacity.csv')
    if poi is not None:
        out[POI_CATEGORY] = poi.groupby('t')['Value'].sum().div(1e3)  # MW -> GW
    if not out:
        return None
    p = pd.DataFrame(out).fillna(0)
    p.index.name = 't'
    return _order_cols(p, TRTYPE_ORDER)


def _order_cols(p, order):
    cols = [c for c in order if c in p.columns] + [c for c in p.columns if c not in order]
    return p[cols]


METRICS = {
    'capacity': dict(loader=load_capacity, colors=TECH_COLORS, unit='GW', title='Capacity'),
    'generation': dict(loader=load_generation, colors=TECH_COLORS, unit='TWh', title='Generation'),
    'transmission': dict(loader=load_transmission, colors=TRTYPE_COLORS, unit='GW', title='Transmission capacity'),
}


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------
def _stacked(ax, df, colors, width=2.4):
    """Stacked bar of levels (df: index=year, cols=categories, all >=0 expected)."""
    years = df.index.values
    bottom = np.zeros(len(df))
    for c in df.columns:
        v = df[c].values
        if np.allclose(v, 0):
            continue
        ax.bar(years, v, width, bottom=bottom, color=colors.get(c, '#999999'), label=c)
        bottom += v
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years], rotation=90, fontsize=6)
    ax.margins(x=0.02)


def _stacked_diff(ax, df, base, colors, width=2.4):
    """Up/down stacked bar of (df - base) by category, with net-total line."""
    cols = [c for c in df.columns.union(base.columns)]
    cols = [c for c in (list(df.columns) + [c for c in base.columns if c not in df.columns])]
    years = df.index.values
    delta = (df.reindex(columns=cols, fill_value=0)
             - base.reindex(index=df.index, columns=cols, fill_value=0))
    pos_b = np.zeros(len(delta))
    neg_b = np.zeros(len(delta))
    for c in cols:
        v = delta[c].values
        if np.allclose(v, 0):
            continue
        pos = np.clip(v, 0, None)
        neg = np.clip(v, None, 0)
        ax.bar(years, pos, width, bottom=pos_b, color=colors.get(c, '#999999'))
        ax.bar(years, neg, width, bottom=neg_b, color=colors.get(c, '#999999'))
        pos_b += pos
        neg_b += neg
    net = delta.sum(axis=1).values
    ax.plot(years, net, color='k', lw=1.2, marker='o', ms=2.5, label='net')
    ax.axhline(0, color='k', lw=0.6)
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years], rotation=90, fontsize=6)
    ax.margins(x=0.02)


def make_slide(cases, right_metric='transmission', left_metric='capacity',
               outpath=None, title=None):
    """Render the comparison slide. `cases[0]` is the baseline (top row)."""
    lm = METRICS[left_metric]
    rm = METRICS[right_metric]
    base_label = cases[0]['label']

    # Pre-load everything; share y-limits per column for honest comparison.
    data = []
    for c in cases:
        data.append({
            'case': c,
            'L': lm['loader'](c['path']),
            'R': rm['loader'](c['path']),
        })
    base_L = data[0]['L']
    base_R = data[0]['R']

    def _ylim_level(key):
        tot = [d[key].sum(axis=1).max() for d in data if d[key] is not None]
        return (0, max(tot) * 1.08) if tot else (0, 1)

    def _ylim_diff(key, base):
        m = 0.0
        for d in data:
            if d[key] is None or base is None:
                continue
            cols = list(d[key].columns)
            dl = d[key].reindex(columns=cols, fill_value=0) - base.reindex(
                index=d[key].index, columns=cols, fill_value=0)
            pos = dl.clip(lower=0).sum(axis=1).max()
            neg = dl.clip(upper=0).sum(axis=1).min()
            m = max(m, abs(pos), abs(neg))
        m = (m or 1) * 1.12
        return (-m, m)

    yl_L, yl_R = _ylim_level('L'), _ylim_level('R')
    yd_L, yd_R = _ylim_diff('L', base_L), _ylim_diff('R', base_R)

    n = len(cases)
    fig, axes = plt.subplots(
        n, 5, figsize=(20, 2.5 * n + 0.5),
        gridspec_kw=dict(width_ratios=[1.5, 2.2, 2.2, 2.2, 2.2], wspace=0.28, hspace=0.45),
    )
    if n == 1:
        axes = axes[None, :]

    col_titles = ['', f'{lm["title"]} ({lm["unit"]})', f'Δ {lm["title"]} vs {base_label}',
                  f'{rm["title"]} ({rm["unit"]})', f'Δ {rm["title"]} vs {base_label}']

    for j, t in enumerate(col_titles):
        if t:
            axes[0, j].set_title(t, fontsize=11, fontweight='bold', pad=12)

    for i, d in enumerate(data):
        c = d['case']
        # --- col 0: description ---
        ax = axes[i, 0]
        ax.axis('off')
        tag = '  (baseline)' if i == 0 else ''
        ax.text(0.02, 0.95, c['label'] + tag, fontsize=10, fontweight='bold',
                va='top', ha='left', transform=ax.transAxes)
        ax.text(0.02, 0.78, '\n'.join(textwrap.wrap(c.get('description', ''), 34)),
                fontsize=8, va='top', ha='left', transform=ax.transAxes, color='#333333')

        # --- col 1: left metric level ---
        ax = axes[i, 1]
        if d['L'] is not None:
            _stacked(ax, d['L'], lm['colors'])
        ax.set_ylim(*yl_L)
        ax.set_ylabel(lm['unit'], fontsize=8)

        # --- col 2: left metric diff ---
        ax = axes[i, 2]
        if i == 0:
            ax.axis('off')
            ax.text(0.5, 0.5, 'reference', ha='center', va='center',
                    fontsize=10, color='#999999', style='italic', transform=ax.transAxes)
        elif d['L'] is not None and base_L is not None:
            _stacked_diff(ax, d['L'], base_L, lm['colors'])
            ax.set_ylim(*yd_L)

        # --- col 3: right metric level ---
        ax = axes[i, 3]
        if d['R'] is not None:
            _stacked(ax, d['R'], rm['colors'])
        ax.set_ylim(*yl_R)
        ax.set_ylabel(rm['unit'], fontsize=8)

        # --- col 4: right metric diff ---
        ax = axes[i, 4]
        if i == 0:
            ax.axis('off')
            ax.text(0.5, 0.5, 'reference', ha='center', va='center',
                    fontsize=10, color='#999999', style='italic', transform=ax.transAxes)
        elif d['R'] is not None and base_R is not None:
            _stacked_diff(ax, d['R'], base_R, rm['colors'])
            ax.set_ylim(*yd_R)

    # --- legends (shared) ---
    def _legend(metric_key, data_key, anchor):
        present = []
        for d in data:
            if d[data_key] is not None:
                present += [c for c in d[data_key].columns if c not in present]
        order = METRICS[metric_key]['colors']
        present = [c for c in (list(TECH_ORDER) + list(TRTYPE_ORDER)) if c in present] + \
                  [c for c in present if c not in TECH_ORDER and c not in TRTYPE_ORDER]
        handles = [Patch(facecolor=order.get(c, '#999999'), label=c) for c in present]
        fig.legend(handles=handles, loc='lower center', bbox_to_anchor=anchor,
                   ncol=min(len(handles), 10), fontsize=7, frameon=False)

    _legend(left_metric, 'L', (0.32, -0.01))
    _legend(right_metric, 'R', (0.78, -0.01))

    fig.suptitle(title or f'POI cost comparison — {lm["title"]} & {rm["title"]}',
                 fontsize=14, fontweight='bold', y=0.99)
    fig.subplots_adjust(top=0.92, bottom=0.10)

    if outpath:
        fig.savefig(outpath, dpi=130, bbox_inches='tight')
        print(f'wrote {outpath}')
    return fig


# ---------------------------------------------------------------------------
# Example configuration — best completed runs for the 4 transmission_test cases.
# Replace `path` values after re-running with the reinforcement fixes.
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'runs')
    CASES = [
        dict(label='ERCOT_defualt', path=os.path.join(RUNS, 'TUSC_3_ERCOT_defualt'),
             description='Legacy flat $65/kW POI (= main baseline). Single unlimited bin; '
                         'reV reinforcement kept in the resource supply curve.'),
        dict(label='ERCOT_0', path=os.path.join(RUNS, 'TUSC_3_ERCOT_0'),
             description='POI tracked at ~$0 cost (GSw_TransIntraCost=0.001). Reinforcement '
                         'effectively free but still accounted, so POI capacity is reported — '
                         'lower-bound / max-VRE case.'),
        dict(label='ERCOT_regional', path=os.path.join(RUNS, 'TUSC_4_ERCOT_regional'),
             description='Binned zonal POI curve (numpoibins=3, regional). Increasing cost, '
                         'one curve per zone; reinforcement relocated to INV_POI.'),
        dict(label='ERCOT_tech', path=os.path.join(RUNS, 'TUSC_6_ERCOT_tech'),
             description='Tech-specific POI curves (numpoibins=9). Wind/PV on reV-derived '
                         'reinforcement curves, other techs flat $65.'),
    ]
    outdir = os.path.dirname(os.path.abspath(__file__))
    make_slide(CASES, right_metric='transmission',
               outpath=os.path.join(outdir, 'poi_slide_transmission.png'))
    make_slide(CASES, right_metric='generation',
               outpath=os.path.join(outdir, 'poi_slide_generation.png'))
