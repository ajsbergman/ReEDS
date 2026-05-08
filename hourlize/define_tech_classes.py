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

# technologies to prepare supply curve data for
tech_list = ['upv','wind-ons','wind-ofs'] 

# for offshore wind
sub_tech_list = ['fixed','floating']


def main(rev_file):
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

        df.to_csv(os.path.join(reeds_path,'inputs','capacity_exogenous','classification_'+tech+'.csv'),index=False)

    ## One-off modification to supplycurve_egs/geohydro-reference.csv to add resource temp column
    # Can remove the next time running hourlize
    for tech in ['geohydro','egs']:
        rev_file = pd.read_csv(os.path.join(reeds_path,'inputs/supply_curve/rev_paths.csv'))
        rev_file_part_geo=rev_file[(rev_file['tech'] == tech) & (rev_file['access_case'] == 'reference')]
        # Load the supply curve file for geothermal
        df = pd.read_csv(os.path.join(remotepath,rev_file_part_geo['sc_path'].iloc[0],
                                        f"{tech}_{rev_file_part_geo['access_case'].iloc[0]}_ba","results",
                                        f"{tech}_supply_curve_raw.csv" ))

        # Select relevant columns and convert longitude to negative if needed
        df['longitude'] = df['longitude'].abs() * -1  # Convert longitude to negative if needed
        # resource temp to geothermal supply curves in ReEDS
        if tech == 'geohydro':
            geo_sc = df[['sc_point_gid','class','capacity','capital_adder_per_mw','mean_cf','mean_resource_temp']].copy()
            geo_sc = geo_sc.rename(columns={'mean_cf':'cf'})
        elif tech == 'egs':
            df_sc = df[['sc_point_gid','class','capacity','capital_adder_per_mw','capacity_factor_ac','mean_resource_temp']].copy()
            df_sc = df_sc.rename(columns={'capacity_factor_ac':'cf'})
            geo_sc = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_egs-reference.csv'))
            geo_sc = geo_sc.merge(df_sc, on='sc_point_gid', how='left', indicator=True)
            geo_sc = geo_sc.rename(columns={'class_x':'class','cf_x':'cf','capacity_x':'capacity',
                                            'capital_adder_per_mw_x':'capital_adder_per_mw',
                                            'mean_resource_temp_x':'mean_resource_temp'})
            geo_sc = geo_sc[df_sc.columns.to_list()]
        
        # Round mean resource temp to 0 decimal (as int)
        geo_sc['mean_resource_temp'] = round(geo_sc['mean_resource_temp'])
        geo_sc.to_csv(os.path.join(reeds_path,'inputs', 'supply_curve','supplycurve_'+tech+'-reference.csv'),index=False)

#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================

# Load a supply-curve CSV for `tech` and `access_type`, compute class ranges,
# and return a DataFrame with class id, min/max of the selected metric, and
# the access case.
def prep_supply_curve(tech, access_type, subtech):
    class_def_name = 'reV_cf_ac'

    # Load the supply curve raw file produced by reV
    df = pd.read_csv(os.path.join(
        reeds_path,'inputs','supply_curve',
        'supplycurve_'+tech+'-'+access_type+'.csv'))

    # Aggregate min/max by class and attach access_case
    if tech == 'wind-ofs':
        df['subtech'] = 'fixed'
        df.loc[df['class']>=6,'subtech'] = 'floating'
        df_sub = df[df['subtech']==subtech]
        summary_df = df_sub.groupby('class')['cf'].agg(['min', 'max']).reset_index()
        summary_df['subtech'] = subtech
        summary_df['access_case'] = access_type
        summary_df.columns = ['class', f'min_{class_def_name}', f'max_{class_def_name}', 'subtech', 'access_case']
    else:
        summary_df = df.groupby('class')['cf'].agg(['min', 'max']).reset_index()
        summary_df['access_case'] = access_type
        summary_df.columns = ['class', f'min_{class_def_name}', f'max_{class_def_name}', 'access_case']
    
    # Only use max capacity factors as class cut offs to avoid gaps
    summary_df = summary_df.sort_values(by=['class',f'min_{class_def_name}'])
    for c in summary_df['class'].unique().tolist():
        if c > min(summary_df['class'].unique().tolist()):
            summary_df.loc[summary_df['class']==c,
                           f'min_{class_def_name}'] = summary_df.loc[summary_df['class']==c-1][f'max_{class_def_name}'].iloc[0]

    # Round values to 4 decimal places
    summary_df[f'min_{class_def_name}'] = summary_df[f'min_{class_def_name}'].round(4)
    summary_df[f'max_{class_def_name}'] = summary_df[f'max_{class_def_name}'].round(4)

    return summary_df

main(rev_file)
