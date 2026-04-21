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

reeds_path = os.path.expanduser('~/Documents/Github/ReEDS/public_ReEDS/ReEDS')
sys.path.append(reeds_path)

rev_file = pd.read_csv(os.path.join(reeds_path,'inputs/supply_curve/rev_paths.csv'))

# technologies to prepare supply curve data for, egs is included in the supply curve file 
tech_list = ['upv','wind-ons','wind-ofs'] 

# for offshore wind
sub_tech_list = ['fixed','floating']

#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

# Load a supply-curve CSV for `tech` and `access_type`, compute class ranges,
# and return a DataFrame with class id, min/max of the selected metric, and
# the access case.
def prep_supply_curve(tech, access_type, subtech):

    rev_file_part = rev_file[(rev_file['tech'] == tech) & (rev_file['access_case'] == access_type)]
    class_def = 'capacity_factor_ac'
    class_def_name = 'reV_cf_ac'

    # Load the supply curve raw file produced by reV
    df = pd.read_csv(os.path.join(
        remotepath,rev_file_part['sc_path'].iloc[0],
        f"{tech}_{rev_file_part['access_case'].iloc[0]}_ba","results",
        f"{tech}_supply_curve_raw.csv" ),
        on_bad_lines='skip',low_memory=False)

    # Aggregate min/max by class and attach access_case
    if tech == 'wind-ofs':
        df_sub = df[df['technology']==subtech]
        summary_df = df_sub.groupby('class')[class_def].agg(['min', 'max']).reset_index()
        summary_df['subtech'] = subtech
        summary_df['access_case'] = access_type
        summary_df.columns = ['class', f'min_{class_def_name}', f'max_{class_def_name}', 'subtech', 'access_case']
    else:
        summary_df = df.groupby('class')[class_def].agg(['min', 'max']).reset_index()
        summary_df['access_case'] = access_type
        summary_df.columns = ['class', f'min_{class_def_name}', f'max_{class_def_name}', 'access_case']
    
    # Only use max capacity factors as class cut offs to avoid gaps
    summary_df = summary_df.sort_values(by=['class',f'min_{class_def_name}'])
    for c in summary_df['class'].unique().tolist():
        if c > min(summary_df['class'].unique().tolist()):
            summary_df.loc[summary_df['class']==c,f'min_{class_def_name}'] = summary_df.loc[summary_df['class']==c-1][f'max_{class_def_name}'].iloc[0]

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
        if tech == 'wind-ofs':
            all_supply_curve_sub_dfs = []
            for subtech in sub_tech_list:
                supply_curve_sub_df = prep_supply_curve(tech, access_type, subtech)
                all_supply_curve_sub_dfs.append(supply_curve_sub_df)
            supply_curve_df = pd.concat(all_supply_curve_sub_dfs, ignore_index=True)    
        else:
            supply_curve_df = prep_supply_curve(tech, access_type, subtech='')
        
        all_supply_curve_dfs.append(supply_curve_df)
    df = pd.concat(all_supply_curve_dfs, ignore_index=True)

    df.to_csv(os.path.join(reeds_path,'inputs','capacity_exogenous',tech+'_classification.csv'),index=False)

