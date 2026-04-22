#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import datetime
import numpy as np
import pandas as pd
import argparse
import shutil
import yaml
import json
import h5py
from pathlib import Path
# Local Imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds


#%% ===========================================================================
### --- General Read Functions---
### ===========================================================================
def main(reeds_path, inputs_case):
    print('Processing generator database:')
    df = pd.read_csv(os.path.join(inputs_case,'unitdata.csv'), low_memory=False)
    
    # Assign sc_point_gids to units based on distance
    # Read land data
    ilpath = os.path.join(reeds_path,'inputs','supply_curve','interconnection_land.h5')
    land_df = reeds.io.read_h5_groups(ilpath)

    # Merge unit database with VRE supply curves to assign AC capacity factors to VRE units
    df['temp_id'] = df.index

    df_rev_list = []
    tech_match = {"upv": ["upv","dupv","pvb_pv","csp-wp","csp-ns"],
                    "wind-ons": ["wind-ons"], 
                    "wind-ofs": ["wind-ofs"]}
    for tech in ['upv','wind-ons','wind-ofs']:
        tech_sub = tech_match[tech]
        df_rev = df[df.tech.isin(tech_sub)]
        if len(df_rev) > 0:
            df_rev['sc_point_gid'] = df_rev['sc_point_gid'].fillna(0).astype(np.int64)
            supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_'+tech+'-'+'open'+'.csv'))
            df_rev = df_rev.merge(supply_curve[['sc_point_gid','cf']],
                                    on='sc_point_gid',
                                    how='left').rename(columns={'cf':'reV_capacity_factor_ac'})
            df_rev_list = df_rev_list + [df_rev]
        
    df_rev = pd.concat(df_rev_list, ignore_index=False, sort=False)
    df = df.merge(df_rev[['temp_id','reV_capacity_factor_ac']],
                    on = 'temp_id',how = 'left').drop('temp_id', axis=1)  

if __name__ == '__main__':
    ### Time the operation of this script
    tic = datetime.datetime.now()
    
    ### Parse arguments
    parser = argparse.ArgumentParser(description="""This file processes NEMS unitdata""")
    parser.add_argument("reeds_path", help="ReEDS directory")
    parser.add_argument("inputs_case", help="path to runs/{case}/inputs_case")

    #args = parser.parse_args()
    #reeds_path = args.reeds_path
    #inputs_case = args.inputs_case
    
    # for testing
    reeds_path = os.path.expanduser('~/Documents/GitHub/ReEDS/public_ReEDS/ReEDS')
    inputs_case = os.path.join(reeds_path,'runs','test_github_MA_county_CC','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting generate_unitdata.py')
    main(reeds_path, inputs_case)
