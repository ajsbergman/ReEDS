"""Build fed_land_fraction_{tech}.csv from the raw federal-lands supply curve data.

Writes one row per sc_point_gid giving the fraction of that point's area which is
federally owned. writesupplycurves.py reads these files and uses them to scale the
federal share of capital_adder_per_mw when GSw_FedLandAdderMult is below 1.

    python inputs/supply_curve/make_fed_land_fraction.py

Rerun this whenever the source files under postprocessing/land_use/inputs change.
The outputs are small and checked in, so a run should normally produce no diff.

The source files carry a JSON dict per point mapping a land-ownership code to an
amount of area, e.g. {"0": 12.81} or {"255.0": 11305.61}. The code for non-federal
land differs by tech -- "0" for onshore wind, "255.0" for UPV -- so it is declared
per tech in TECHS below rather than inferred. Every other code is a federal owner
(BLM, USFS, USFWS, DoD and so on), and the fraction is federal area over total area.

The federal-lands data is taken from the "open" siting scenario, which is a superset
of the others, so a single file per tech serves limited/reference/open alike. That is
verified by --check, which reports coverage against each supply curve.
"""
#%% Imports
import os
import json
import argparse
import pandas as pd

#%%### Constants
### source file, JSON column, and the ownership code meaning "not federal"
TECHS = {
    'wind-ons': ('onswind_fed_lands.csv', 'federal_land_by_categories', '0'),
    'upv': ('upv_fed_lands.csv', 'fed_land_owner', '255.0'),
}
SRCDIR = os.path.join('postprocessing', 'land_use', 'inputs')
OUTDIR = os.path.join('inputs', 'supply_curve')


#%%### Functions
def fed_fraction(srcpath, col, nonfed):
    """Federal share of area for each sc_point_gid in one source file"""
    df = pd.read_csv(srcpath)
    rows = []
    for gid, cell in zip(df.sc_point_gid, df[col]):
        try:
            shares = json.loads(cell) if isinstance(cell, str) else {}
        except (TypeError, ValueError):
            shares = {}
        total = sum(shares.values())
        ## Compare as strings: the codes are dict keys, and the two techs write them
        ## differently ("0" vs "255.0"), so no numeric coercion is safe here
        fed = sum(v for k, v in shares.items() if str(k) != nonfed)
        rows.append((int(gid), round(fed / total, 6) if total > 0 else 0.0))
    return (
        pd.DataFrame(rows, columns=['sc_point_gid', 'fed_frac'])
        .drop_duplicates('sc_point_gid')
        .sort_values('sc_point_gid')
        .reset_index(drop=True)
    )


def check_coverage(tech, frac, reeds_path):
    """Report how well the fractions cover each siting scenario's supply curve"""
    for scen in ['limited', 'reference', 'open']:
        scpath = os.path.join(
            reeds_path, OUTDIR, f'supplycurve_{tech}-{scen}.csv')
        if not os.path.isfile(scpath):
            continue
        sc = pd.read_csv(scpath)
        matched = sc.sc_point_gid.isin(set(frac.sc_point_gid))
        weighted = (
            sc.sc_point_gid.map(frac.set_index('sc_point_gid').fed_frac).fillna(0)
            * sc.capacity).sum() / sc.capacity.sum()
        print(f'    {scen:10s} {matched.mean()*100:5.1f}% of points matched, '
              f'capacity-weighted federal share {weighted*100:4.1f}%')


#%% Procedure
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n')[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--reeds_path', '-p', type=str,
        default=os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        help='path to the ReEDS repo root')
    parser.add_argument(
        '--check', '-c', action='store_true',
        help='also report coverage against each siting scenario supply curve')
    args = parser.parse_args()

    for tech, (srcfile, col, nonfed) in TECHS.items():
        srcpath = os.path.join(args.reeds_path, SRCDIR, srcfile)
        if not os.path.isfile(srcpath):
            raise FileNotFoundError(f'missing source data: {srcpath}')
        frac = fed_fraction(srcpath, col, nonfed)
        outpath = os.path.join(args.reeds_path, OUTDIR,
                               f'fed_land_fraction_{tech}.csv')
        frac.to_csv(outpath, index=False)
        print(f'{outpath}')
        print(f'    {len(frac)} points, mean federal fraction '
              f'{frac.fed_frac.mean():.4f}, '
              f'{(frac.fed_frac == 0).sum()} fully non-federal, '
              f'{(frac.fed_frac == 1).sum()} fully federal')
        if args.check:
            check_coverage(tech, frac, args.reeds_path)
