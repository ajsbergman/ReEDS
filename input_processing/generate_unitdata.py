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
def main(reeds_path, casepath, inputs_case):

    sw = reeds.io.get_switches(casepath)
    crs = 'EPSG:5070'
    
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
        lat='T_LAT',
        lon='T_LONG',
        crs=crs)
    
    gdf['temp_id'] = gdf.index

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


    df_rev_list = []
    tech_match = {'upv': ['upv','dupv','pvb_pv','csp-wp','csp-ns'],
                  'wind-ons': ["wind-ons"], 
                  'wind-ofs': ["wind-ofs"],
                  'geohydro': ['geohydro_allkm', 'geothermal'],
                  'egs':['egs']}
    for tech in ['upv','wind-ons','wind-ofs','geohydro']:
        print(f'Assigning {tech} classes')

        # Only consider the sc_point_pids that are in supply curves:
        if (tech == 'geohydro') or (tech == 'egs'):
            geo_tech = 'egs'
            supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_'+geo_tech+'-'+'reference'+'.csv'))
        else:
            supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve','supplycurve_'+tech+'-'+'open'+'.csv'))    
        
        land_filtered_pdf = land_gdf[land_gdf['sc_point_gid'].isin(supply_curve['sc_point_gid'].to_list())]
        gdf_joined = gpd.sjoin_nearest(gdf, land_filtered_pdf, distance_col='distance', how='left')

        # Merge unit database with VRE supply curves to assign AC capacity factors to VRE units
        # and mean resource temp for geothermal units
        gdf_joined = gdf_joined[['sc_point_gid'] + df.columns.to_list() + ['temp_id']]

        tech_sub = tech_match[tech]
        df_rev = gdf_joined[gdf_joined.tech.isin(tech_sub)]
        if len(df_rev) > 0:
            df_rev.loc[:, ['sc_point_gid']] = df_rev.loc[:, ['sc_point_gid']].fillna(0).astype(np.int64)
            if (tech == 'geohydro') or (tech == 'egs'):
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','mean_resource_temp']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'mean_resource_temp':'reV_mean_resource_temp'})
            else:
                df_rev = df_rev.merge(supply_curve[['sc_point_gid','cf']],
                                        on='sc_point_gid',
                                        how='left').rename(columns={'cf':'reV_capacity_factor_ac'})
            df_rev_list = df_rev_list + [df_rev]
        
    df_rev = pd.concat(df_rev_list, ignore_index=False, sort=False)
    df = gdf.merge(df_rev[['sc_point_gid','temp_id','reV_capacity_factor_ac','reV_mean_resource_temp']],
                    on = 'temp_id',how = 'left') 
    
    # Rearrange column orders
    cols = df_rev.columns.to_list()
    df = df[cols]

    df.to_csv(os.path.join(inputs_case,'unitdata.csv'),index=False)

if __name__ == '__main__':
    ### Time the operation of this script
    tic = datetime.datetime.now()
    
    ### Parse arguments
    parser = argparse.ArgumentParser(description="""This file processes NEMS unitdata""")
    parser.add_argument('reeds_path', help="ReEDS directory")
    parser.add_argument('inputs_case', help="path to runs/{case}/inputs_case")

    args = parser.parse_args()
    reeds_path = args.reeds_path
    inputs_case = args.inputs_case
    
    # for testing
    # reeds_path = os.path.expanduser('~/Documents/GitHub/ReEDS/public_ReEDS/ReEDS')
    # inputs_case = os.path.join(reeds_path,'runs','test_Pacific','inputs_case')

    casepath = os.path.dirname(inputs_case)

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting generate_unitdata.py')
    main(reeds_path, casepath, inputs_case)
    print('Complete processsing generate_unitdata.py')
