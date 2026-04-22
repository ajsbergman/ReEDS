#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================
import os
import sys
import datetime
import numpy as np
import pandas as pd
import geopandas as gpd
import argparse

# Local Imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..','input_processing')))
from copy_files import get_regions_and_agglevel


#%% ===========================================================================
### --- General Read Functions---
### ===========================================================================
def main(reeds_path, casedir, inputs_case):

    sw = reeds.io.get_switches(casedir)
    crs = 'EPSG:5070'
    
    print('Processing generator database:')
    df = pd.read_csv(os.path.join(reeds_path,'inputs','capacity_exogenous','ReEDS_generator_database_final_'+sw.unitdata+'.csv'), low_memory=False)
    
    regions_and_agglevel = get_regions_and_agglevel(reeds_path, inputs_case)

    fips_ba_map = regions_and_agglevel['ba_county'].dropna().set_index('county')['ba']
    df['reeds_ba'] = df['FIPS'].map(fips_ba_map)
    df = df.dropna(subset=["reeds_ba"])
    ## If using offshore zones, map offshore wind units from land to offshore zones
    if int(sw.GSw_OffshoreZones):
        df = reeds.spatial.assign_to_offshore_zones(df)
    num_units_missing_bas = len(df.loc[df.reeds_ba.isna()])
    if num_units_missing_bas > 0:
        raise ValueError(
            f"{num_units_missing_bas} units were not mapped to any BAs."
        )
    
    gdf = reeds.plots.df2gdf(
        df,
        lat='T_LONG',
        lon='T_LAT',
        crs=crs)
    
    # Assign sc_point_gids to units based on distance
    # Read land data
    ilpath = os.path.join(reeds_path,'inputs','supply_curve','interconnection_land.h5')
    land_df = reeds.io.read_h5_groups(ilpath)
    land_df['sc_point_gid'] = land_df.index
    land_df = land_df[['sc_point_gid','latitude','longitude']]

    land_gdf = reeds.plots.df2gdf(
        land_df,
        lat='latitude',
        lon='longitude',
        crs=crs)

    # 
    gdf = gpd.sjoin_nearest(gdf, land_gdf, distance_col='distance', how='left')

    # Merge unit database with VRE supply curves to assign AC capacity factors to VRE units
    # and mean resource temp for geothermal units
    gdf = gdf[['sc_point_gid'] + df.columns.to_list()]
    gdf['temp_id'] = gdf.index

    df_rev_list = []
    tech_match = {'upv': ['upv','dupv','pvb_pv','csp-wp','csp-ns'],
                  'wind-ons': ["wind-ons"], 
                  'wind-ofs': ["wind-ofs"],
                  'geohydro': ['geohydro_allkm', 'geothermal'],
                  'egs':['egs']}
    for tech in ['upv','wind-ons','wind-ofs','geohydro']:
        tech_sub = tech_match[tech]
        df_rev = gdf[gdf.tech.isin(tech_sub)]
        if len(df_rev) > 0:
            df_rev['sc_point_gid'] = df_rev['sc_point_gid'].fillna(0).astype(np.int64)
            if (tech == 'geohydro') or (tech == 'egs'):
                geo_tech = 'egs'            # Using 'egs' for geohydro for now since there are issues with geohydro supply curves
                supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_'+geo_tech+'-'+'reference'+'.csv'))
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','mean_resource_temp']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'mean_resource_temp':'reV_mean_resource_temp'})
                df_rev['reV_capacity_factor_ac'] = np.nan
            else:
                supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_'+tech+'-'+'open'+'.csv'))
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','cf']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'cf':'reV_capacity_factor_ac'})
                df_rev['reV_mean_resource_temp'] = np.nan
            df_rev_list = df_rev_list + [df_rev]
        
    df_rev = pd.concat(df_rev_list, ignore_index=False, sort=False)
    df = gdf.merge(df_rev[['temp_id','reV_capacity_factor_ac']],
                    on = 'temp_id',how = 'left').drop('temp_id', axis=1)  
    
    df.to_csv(os.path.join(inputs_case,'unitdata.csv'))

if __name__ == '__main__':
    ### Time the operation of this script
    tic = datetime.datetime.now()
    
    ### Parse arguments
    parser = argparse.ArgumentParser(description="""This file processes NEMS unitdata""")
    parser.add_argument("reeds_path", help="ReEDS directory")
    parser.add_argument("inputs_case", help="path to runs/{case}/inputs_case")

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case
    #casedir = args.casedir
    
    # for testing
    # reeds_path = os.path.expanduser('~/Documents/GitHub/ReEDS/public_ReEDS/ReEDS')
    casedir = os.path.join(reeds_path,'runs','test_github_MA_county_CC')
    # inputs_case = os.path.join(reeds_path,'runs','test_github_MA_county_CC','inputs_case')

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting generate_unitdata.py')
    main(reeds_path, casedir, inputs_case)
