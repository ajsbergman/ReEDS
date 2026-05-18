#%% IMPORTS
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import gdxpds

sys.path.append(str(Path(__file__).parent.parent.parent.parent))
import reeds


#%% FUNCTIONS

def get_hr(cf_val, gas_or_coal, sw):
    """Return heat rate multiplier based on capacity factor.
    Gas-CC uses exponential curve; coal uses steeper curve; Gas-CT has no adjustment.
    Result is damped by GSw_HR_AdjStep.
    """
    adj_bool = float(sw.GSw_CF_Heatrate_adj)
    if adj_bool == 0:
        return 1.0
    if gas_or_coal == 'gas':
        a, b, c, y_c = 2.6, 5.29, 7.075, 7.32
        hr_mod = (a * np.exp(-b * cf_val) + c) / y_c
    elif gas_or_coal == 'coal':
        a, b, c, y_c = 8.588, 27.226, 10.962, 10.7
        hr_mod = (a * np.exp(-b * cf_val) + c) / y_c
    else:
        hr_mod = 1.0
    return (hr_mod - 1) * float(sw.GSw_HR_AdjStep) + 1


def get_OM(cf_val, gas_or_coal, sw, vom_or_fom):
    """Return VOM or FOM multiplier based on capacity factor.
    Uses linear slope from reference CF to min CF, with switch-defined endpoint values.
    """
    adj_bool = float(sw.GSw_CF_Heatrate_adj)
    if adj_bool == 0:
        return 1.0
    if gas_or_coal == 'gas':
        ref_cf = 0.51
        if vom_or_fom == 'vom':
            sl = (1 - float(sw.GSw_CP_vom)) / (ref_cf - 0.06)
        else:
            sl = (1 - float(sw.GSw_CP_fom)) / (ref_cf - 0.06)
        mod = 1 + sl * (cf_val - ref_cf)
    elif gas_or_coal == 'coal':
        ref_cf = 0.43
        if vom_or_fom == 'vom':
            sl = (1 - float(sw.GSw_CP_vom)) / (ref_cf - 0.06)
        else:
            sl = (1 - float(sw.GSw_CP_fom)) / (ref_cf - 0.06)
        mod = 1 + sl * (cf_val - ref_cf)
    else:
        mod = 1.0
    return (mod - 1) * float(sw.GSw_HR_AdjStep) + 1


def _compute_adjustment(GEN_data_file, yearin, year_out, hierarchies,
                        iteration, sw, adj_col, adj_func, adj_func_kwargs):
    """Shared logic for computing CF-based adjustments (HR, VOM, FOM)."""
    gdx_filename = os.path.join(GEN_data_file, f'GEN_data_{yearin}.gdx')
    gdx_data = gdxpds.to_dataframes(gdx_filename)
    GEN = gdx_data['GEN_Annual']
    CAP = gdx_data['CAP']
    base_mask = gdx_data['heat_rate_init']
    base = pd.merge(left=base_mask, right=hierarchies, on='r')
    base[adj_col] = 1.0

    adj_bool = float(sw.GSw_CF_Heatrate_adj)
    if adj_bool == 0:
        base = base[['i', 'v', 'r', adj_col]]
        return base

    GEN = pd.merge(left=GEN, right=hierarchies, on='r')
    CAP = pd.merge(left=CAP, right=hierarchies, on='r')
    prev_yr = GEN.t.max()

    gas_cc = ['Gas-CC']
    coals = [
        'coal-CCS_mod', 'coal-CCS_max', 'coal-CCS-F1', 'coal-CCS-F2', 'coal-CCS-F3',
        'Coal-IGCC', 'coal-new', 'CoalOldScr', 'CoalOldUns', 'CofireNew',
        'coal-ccs_mod_upgrade', 'coal-ccs_max_upgrade', 'coal-ccs_mod',
        'coal-ccs_max', 'coal-ccs-nsp', 'coal-ccs-flex',
    ]

    hrs = 8784 if int(prev_yr) in list(range(2000, 2054, 4)) else 8760

    for reg in ['country', 'transreg', 'r']:
        for tech_label, tech_list in [('gas', gas_cc), ('coal', coals)]:
            temp = pd.merge(
                left=GEN.loc[(GEN.i.isin(tech_list)) & (GEN.t == prev_yr)],
                right=CAP.loc[(CAP.i.isin(tech_list)) & (CAP.t == prev_yr)],
                on=['i', 'v', reg],
            ).fillna(0)

            if temp.empty:
                continue

            temp['Annual_CF'] = temp['Value'] / (temp['Level'] * hrs)
            temp['Annual_CF'] = temp['Annual_CF'].clip(lower=0, upper=1)
            temp[adj_col] = [
                adj_func(cf, tech_label, **adj_func_kwargs)
                for cf in temp['Annual_CF']
            ]

            for r in temp[reg].unique():
                for v in temp.v.unique():
                    val = temp.loc[
                        (temp[reg] == r) & (temp.i.isin(tech_list)) & (temp.v == v),
                        adj_col,
                    ].mean()
                    if val > 0:
                        base.loc[
                            (base[reg] == r) & base.i.isin(tech_list) & (base.v == v),
                            adj_col,
                        ] = val

    base = base[['i', 'v', 'r', adj_col]].drop_duplicates()
    return base


def calc_HR_penalty(GEN_data_file, yearin, year_out, hierarchies, iteration, sw):
    """Compute CF-based heat rate multipliers."""
    base = _compute_adjustment(
        GEN_data_file, yearin, year_out, hierarchies, iteration, sw,
        adj_col='HR_pct',
        adj_func=get_hr,
        adj_func_kwargs={'sw': sw},
    )
    data = {'heatrate_cf_adj': base}
    gdxpds.to_gdx(data, os.path.join(GEN_data_file, f'heatrate_cf_adj{year_out}.gdx'))

    # Also save with CAP for convergence checking
    gdx_filename = os.path.join(GEN_data_file, f'GEN_data_{yearin}.gdx')
    CAP = gdxpds.to_dataframes(gdx_filename)['CAP']
    base_larger = pd.merge(left=base, right=CAP.loc[CAP.t == CAP.t.max()], on=['i', 'v', 'r'], how='left')
    base_larger['Level'] = base_larger['Level'].fillna(0)
    base_larger = base_larger[['i', 'v', 'r', 'HR_pct', 'Level']]
    base_larger.to_csv(
        os.path.join(GEN_data_file, f'heatrate_cf_adj_{year_out}_{iteration}.csv'),
        index=False,
    )
    return base_larger


def calc_OM_penalty(GEN_data_file, yearin, year_out, hierarchies, iteration, sw, vom_or_fom):
    """Compute CF-based VOM or FOM multipliers."""
    base = _compute_adjustment(
        GEN_data_file, yearin, year_out, hierarchies, iteration, sw,
        adj_col='OM_pct',
        adj_func=get_OM,
        adj_func_kwargs={'sw': sw, 'vom_or_fom': vom_or_fom},
    )
    data = {f'{vom_or_fom}_cf_adj': base}
    gdxpds.to_gdx(data, os.path.join(GEN_data_file, f'{vom_or_fom}_cf_adj{year_out}.gdx'))
    base.to_csv(
        os.path.join(GEN_data_file, f'{vom_or_fom}_cf_adj_{year_out}_{iteration}.csv'),
        index=False,
    )
    return base


#%% MAIN ENTRY POINT

def heatrate_main(year, casepath, iteration):
    """Compute and write CF-based heat rate, VOM, and FOM adjustments.

    Called by solve.py after each GAMS solve. Returns (hr_table, vom_table, fom_table)
    for convergence checking.
    """
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(casepath, 'gamslog.txt'),
    )
    print(f'Starting heatRate_cf_adjustment.py for {year}, iteration {iteration}')

    sw = reeds.io.get_switches(casepath)
    yearset = pd.read_csv(
        os.path.join(casepath, 'inputs_case', 'modeledyears.csv')
    ).columns.astype(int).values

    if year == min(yearset):
        most_recent_year = year
    elif iteration > 0:
        most_recent_year = year
    else:
        most_recent_year = max(yearset[yearset < year])

    hierarchy = pd.read_csv(
        os.path.join(casepath, 'inputs_case', 'hierarchy.csv')
    ).rename(columns={'*r': 'r'})

    GEN_data_file = os.path.join(casepath, 'outputs', 'heatRateData')
    os.makedirs(GEN_data_file, exist_ok=True)

    output_table = calc_HR_penalty(
        GEN_data_file, most_recent_year, year, hierarchy, iteration, sw,
    )
    vom = calc_OM_penalty(
        GEN_data_file, most_recent_year, year, hierarchy, iteration, sw, 'vom',
    )
    fom = calc_OM_penalty(
        GEN_data_file, most_recent_year, year, hierarchy, iteration, sw, 'fom',
    )

    print(f'Finished heatRate_cf_adjustment.py for {year}, iteration {iteration}')
    return output_table, vom, fom
