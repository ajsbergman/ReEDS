#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import pandas as pd
import os
import sys

"""
Prepare and export supply-curve class definitions for ReEDS technologies.

This module reads reV supply-curve listed in `rev_paths.csv`, extracts
the regions class properties (e.g. capacity factor) for each technology and access case,
computes the min/max range per class for each `access_case' and writes per-technology 
classification CSVs to`inputs/capacity_exogenous/`.

Run this script after updates of reV supply curves to regenerate 
`{tech}_classification.csv` files.
"""

#%% ===========================================================================
### --- MAIN DATA ---
### ===========================================================================

if sys.platform == 'win32':
    remotepath = '/nrelnas01/ReEDS/Supply_Curve_Data'
elif sys.platform == 'darwin':
    remotepath = '/Volumes/ReEDS/Supply_Curve_Data'         #TODO: Move supply curves to zenodo

reeds_path = os.path.expanduser('~/Documents/Github/ReEDS/ReEDS-2.0/')
sys.path.append(reeds_path)

rev_file = pd.read_csv(os.path.join(reeds_path,'inputs/supply_curve/rev_paths.csv'))

tech_list = ['upv','wind-ons','wind-ofs'] # technologies to prepare supply curve data for, egs is included in the supply curve file 
access_type_list=['open','reference','limited'] # access type for each technology, geohydro and egs use reference, upv and wind use open


#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

#Load a supply-curve CSV for `tech` and `access_type`, compute class ranges,
#and return a DataFrame with class id, min/max of the selected metric, and
#the access case.
def prep_supply_curve(tech, access_type):

    rev_file_part = rev_file[(rev_file['tech'] == tech) & (rev_file['access_case'] == access_type)]
    class_def = 'capacity_factor_ac'
    class_def_name = 'reV_cf_ac'

    # Load the supply curve raw file produced by reV
    df = pd.read_csv(os.path.join(remotepath,rev_file_part['sc_path'].iloc[0],f"{tech}_{rev_file_part['access_case'].iloc[0]}_ba","results",f"{tech}_supply_curve_raw.csv" ),on_bad_lines='skip',low_memory=False)

    # Aggregate min/max by class and attach access_case
    summary_df = df.groupby('class')[class_def].agg(['min', 'max']).reset_index()
    summary_df['access_case'] = access_type
    summary_df.columns = ['class', f'min_{class_def_name}', f'max_{class_def_name}', 'access_case']

    # Round values to 4 decimal places
    summary_df[f'min_{class_def_name}'] = summary_df[f'min_{class_def_name}'].round(4)
    summary_df[f'max_{class_def_name}'] = summary_df[f'max_{class_def_name}'].round(4)

    return summary_df


 # %% ===========================================================================
for tech in tech_list:
    # Prepare the class capacity factor range for each technology
    print("Prepare class capacity factors for " + tech)
    all_supply_curve_dfs = []
    for access_type in rev_file[(rev_file['tech'] == tech)]['access_case'].unique():
        print(access_type)
        supply_curve_df = prep_supply_curve(tech, access_type)
        all_supply_curve_dfs.append(supply_curve_df)
    df = pd.concat(all_supply_curve_dfs, ignore_index=True)

    df.to_csv(os.path.join(reeds_path,'inputs','capacity_exogenous',tech+'_classification.csv'),index=False)

