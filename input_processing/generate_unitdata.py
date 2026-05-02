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
def prepare_data_for_mapping(crs, filepath):
    df = reeds.io.read_h5_groups(filepath)
    df['sc_point_gid'] = df.index
    df = df[['sc_point_gid','latitude','longitude']]

    gdf = reeds.plots.df2gdf(
        df,
        lat='latitude',
        lon='longitude',
        crs=crs)
    
    return gdf

# Function to merge NEMS unitdata with interconnection_land/offshore data by 
# mapping each unit in NEMS by lon/lat to its closest sc_point_gid
def assign_gids_to_unitdata(df, gdf, offland_gdf, land_gdf):
    # Technologies to map - pv, wind, and geothermal
    tech_match = {'upv': ['upv','dupv','pvb_pv','csp-wp','csp-ns'],
                  'wind-ons': ["wind-ons"], 
                  'wind-ofs': ["wind-ofs"],
                  'geohydro': ['geohydro_allkm', 'geothermal'],
                  'egs':['egs']}
    
    df_rev_list = []
    for tech in ['upv','wind-ons','wind-ofs','geohydro']:
        print(f'Assigning {tech} classes')
    
        # Read supply curves
        if (tech == 'geohydro') or (tech == 'egs'):
            geo_tech = 'egs'
            supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve',
                                                    'supplycurve_'+geo_tech+'-'+'reference'+'.csv'))
        else:
            supply_curve = pd.read_csv(os.path.join(reeds_path,'inputs','supply_curve',
                                                    'supplycurve_'+tech+'-'+'open'+'.csv'))    
        
        # Only consider the sc_point_pids that are in supply curves:
        # (to avoid unmatched units later)
        if tech == 'wind-ofs':
            sc_point_pid_pdf = offland_gdf[offland_gdf['sc_point_gid'].isin(supply_curve['sc_point_gid'].to_list())]
        else:
            sc_point_pid_pdf = land_gdf[land_gdf['sc_point_gid'].isin(supply_curve['sc_point_gid'].to_list())]
        gdf_joined = gpd.sjoin_nearest(gdf, sc_point_pid_pdf, distance_col='distance', how='left')

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
    return df_rev

#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================
def main(reeds_path, casepath, inputs_case):
    
    # Read in switch setting
    sw = reeds.io.get_switches(casepath)

    # Read raw NEMS database
    unitdata = pd.read_csv(
        os.path.join(
            reeds_path, 'inputs', 'capacity_exogenous',
            f'ReEDS_generator_database_final_{sw.unitdata}.csv'
            ),
            low_memory=False
            )
    
    # Filter and process raw NEMS database to defined model resolution
    regions_and_agglevel = get_regions_and_agglevel(reeds_path, inputs_case)

    fips_ba_map = regions_and_agglevel['ba_county'].dropna().set_index('county')['ba']
    unitdata['reeds_ba'] = unitdata['FIPS'].map(fips_ba_map)
    unitdata = unitdata.dropna(subset=["reeds_ba"])

    ## If using offshore zones, map offshore wind units from land to offshore zones
    if int(sw.GSw_OffshoreZones):
        unitdata = reeds.spatial.assign_to_offshore_zones(unitdata)
    num_units_missing_bas = len(unitdata.loc[unitdata.reeds_ba.isna()])
    if num_units_missing_bas > 0:
        raise ValueError(
            f"{num_units_missing_bas} units were not mapped to any BAs."
        )
    
    ## Assign sc_point_gids and pv, wind capacity factors, and geothermal resource temperature to NEMS unit
    # Using 'EPSG:5070' projection for nearest distance calculation
    crs = 'EPSG:5070'
    # Convert NEMS data base to geopandas dataframe by lon/lat
    gdf = reeds.plots.df2gdf(
        unitdata,
        lat='T_LAT',
        lon='T_LONG',
        crs=crs)
    gdf['temp_id'] = gdf.index

    # Assign sc_point_gids to units based on distance
    # Using interconnection_land.h5 for sc_point_gids - lon/lat mapping for pv, land-based wind, and geothermal
    ilpath = os.path.join(reeds_path,'inputs','supply_curve','interconnection_land.h5')
    land_gdf = prepare_data_for_mapping(crs,ilpath)
    # Using interconnection_offshore.h5 for sc_point_gids - lon/lat mapping for offshore wind
    iopath = os.path.join(reeds_path,'inputs','supply_curve','interconnection_offshore.h5')
    offland_gdf = prepare_data_for_mapping(crs,iopath)
    
    # Merge NEMS unitdata with interconnection_land/offshore data by 
    # mapping each unit in NEMS by lon/lat to its closest sc_point_gid  
    df_rev = assign_gids_to_unitdata(unitdata, gdf, offland_gdf, land_gdf)
        
    # Clean up merged data    
    if 'reV_mean_resource_temp' in df_rev.columns:
        unitdata = gdf.merge(df_rev[['sc_point_gid','temp_id',
                               'reV_capacity_factor_ac','reV_mean_resource_temp']],
                               on = 'temp_id',how = 'left') 
    else:
        unitdata = gdf.merge(df_rev[['sc_point_gid','temp_id',
                               'reV_capacity_factor_ac']],
                               on = 'temp_id',how = 'left') 
    
    # Rearrange column orders
    cols = df_rev.columns.to_list()
    unitdata = unitdata[cols].drop(columns=['temp_id'])
    
    # Save processed unitdata
    unitdata.to_csv(os.path.join(inputs_case,'unitdata.csv'),index=False)
    
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
    #reeds_path = os.path.expanduser('~/Documents/GitHub/ReEDS/public_ReEDS/ReEDS')
    #inputs_case = os.path.join(reeds_path,'runs','test_Pacific','inputs_case')

    casepath = os.path.dirname(inputs_case)

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(inputs_case,'..','gamslog.txt'),
    )
    print('Starting generate_unitdata.py')
    main(reeds_path, casepath, inputs_case)
    print('Complete processsing generate_unitdata.py')
