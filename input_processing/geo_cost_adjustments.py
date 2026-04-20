###########
"""
Preprocessing script to calculate cost adjustment multipliers for EGS based on differences in drilling costs at specific depths and plant cycle-related costs
"""

#%% IMPORTS
import os
import argparse
import pandas as pd
import numpy as np
import reeds
import traceback

#############
#%% FUNCTION DEFINITION

def main(inputs_case, plantchar_geo, tech_type=None, output_multipliers=True):
    tech_types = [tech_type] if tech_type else ['egs', 'geohydro']

    try:
        sw = reeds.io.get_switches(inputs_case)
        if int(sw.get('numbins_egs_depth', 1)) <= 1 and (tech_type is None or tech_type == 'egs'):
            if output_multipliers:
                print("numbins_egs_depth <= 1: writing zero-filled egs_cap_cost_mult.csv")
                # Create a minimal zero-filled DF with required columns
                zero_df = pd.DataFrame([{'*i': 'egs1_1', 'r': 'p1', 'value': 0.0}])
                out_file = os.path.join(inputs_case, f'{tech_type}_cap_cost_mult.csv' if tech_type else 'geo_cap_cost_mult.csv')
                zero_df.to_csv(out_file, index=False)
            return None
    except Exception:
        pass

    ## load drilling cost curves
    geo_cost_curves = pd.read_csv(os.path.join(inputs_case, 'geo_cost_curves.csv'))
    geo_cost_coeffs = geo_cost_curves[geo_cost_curves['scenario'] == plantchar_geo].iloc[0]
    c1, c2, c3 = geo_cost_coeffs['c1'], geo_cost_coeffs['c2'], geo_cost_coeffs['c3']

    ## load ATB reference data
    geo_atb_ref = pd.read_csv(os.path.join(inputs_case, 'geo_ATB_reference.csv'))
    ## placeholders for drilling cost as share of total capital cost
    drilling_percent = {1: 23, 2: 25, 3: 25, 4: 25, 5: 25, 6: 25, 7: 30, 8: 30, 9: 30, 10: 30, }

    ## function to calculate drilling cost adjustment based on depth
    def calc_drilling_cost(depth):
        return c1 * (depth**2) + c2 * depth + c3
    
    all_multipliers = []

    for tech in tech_types:
        depths_file = os.path.join(inputs_case, f'{tech}_rep_depths.csv')
        if not os.path.exists(depths_file):
            print(f"Warning: no file found for {tech}")
            continue
        depths_data = pd.read_csv(depths_file)

        # get reference depths
        tech_ref_data = geo_atb_ref[(geo_atb_ref['tech'] == tech) & (geo_atb_ref['geoscen'] == plantchar_geo)]
        if tech_ref_data.empty:
            print(f"Warning: no ATB reference data found for {tech} and ATB scenario: {plantchar_geo}")
            continue
        class_to_ref_depth = tech_ref_data.set_index('geo_class')['ref_depth'].to_dict()
        ## calculate cost multipliers for each depth record
        for _, row in depths_data.iterrows():
            class_val = row['class']
            if class_val not in class_to_ref_depth: ## fix for class 10 edge cases
                continue
            ref_depth = class_to_ref_depth[class_val]
            act_depth = row['rep_depth']
            
            ## calculate drilling cost ratio
            drilling_cost_ratio = calc_drilling_cost(act_depth) / calc_drilling_cost(ref_depth)
            
            ## calculate occ multiplier
            pct = drilling_percent.get(class_val, 50)  ## using 50% as default value if drilling percent value is not found
            occ_mult = 1 + (pct/100) * (drilling_cost_ratio - 1)

            ## plant_type (flash vs. binary) multiplier calculation
            binary_cost_conv = 1.0
            flash_fraction = row.get('flash_fraction', np.nan)
            if np.isnan(flash_fraction):
                plant_cost_mult = 1.0
            else:
                # for class <= 6 base is flash; for >6 base is binary (match original plantcostprep logic)
                if class_val <= 6:
                    plant_cost_mult = flash_fraction + (1 - flash_fraction) * binary_cost_conv
                else:
                    plant_cost_mult = flash_fraction / binary_cost_conv + (1 - flash_fraction)
            
            all_multipliers.append({
                'r': row['r'], 'tech': row['tech'], 'bin': row['bin'],
                'ref_depth': ref_depth, 'act_depth': act_depth,
                'occ_mult': round(occ_mult, 4), 'plant_cost_mult': round(plant_cost_mult, 6),
                'capacity': row.get('capacity', np.nan)
            })
    
    if not all_multipliers:
        return None
        
    cost_multipliers = pd.DataFrame(all_multipliers)

    ### write out and save for reference
    if output_multipliers:
        out_detailed = os.path.join(inputs_case, f'{tech_type}_cost_multipliers_detailed.csv' if tech_type else 'geo_cost_multipliers_detailed.csv')
        out_agg = os.path.join(inputs_case, f'{tech_type}_cost_multipliers.csv' if tech_type else 'geo_cost_multipliers.csv')
        cost_multipliers.to_csv(out_detailed, index=False)

    # aggregate to one occ_mult & plant_cost_mult per (r,tech) using capacity weights when available
    if 'capacity' in cost_multipliers.columns and cost_multipliers['capacity'].notnull().any():
        cost_multipliers['capacity'] = cost_multipliers['capacity'].fillna(0.0)
        agg_occ = (
            cost_multipliers
            .groupby(['r','tech'])
            .apply(lambda g: np.average(g['occ_mult'].astype(float), weights=g['capacity'].astype(float)) )
            .reset_index(name='occ_mult')
        )
        agg_plant = (
            cost_multipliers
            .groupby(['r','tech'])
            .apply(lambda g: np.average(g['plant_cost_mult'].astype(float), weights=g['capacity'].astype(float)) )
            .reset_index(name='plant_cost_mult')
        )
        agg = agg_occ.merge(agg_plant, on=['r','tech'])
    else:
        agg = cost_multipliers.groupby(['r','tech']).agg({
            'occ_mult': 'mean',
            'plant_cost_mult': 'mean'
        }).reset_index()

    # combine into a single total multiplier if you prefer
    agg['total_mult'] = (agg['occ_mult'].astype(float) * agg['plant_cost_mult'].astype(float))

    # write fractional diff values for egs_cost_cap_mult.csv
    agg['value'] = agg['total_mult'] - 1.0

    # write out aggregated file with both components and combined total
    if output_multipliers:
        cost_multipliers.to_csv(out_detailed, index=False)
        agg.to_csv(out_agg, index=False)

        # expand aggregated multipliers to county-level using county2zone.csv
        try:
            county_path = os.path.join(inputs_case, 'county2zone.csv')
            hierarchy_path = os.path.join(inputs_case, 'hierarchy.csv')
            
            if os.path.exists(county_path) and os.path.exists(hierarchy_path):
                # 1. Load county map (FIPS -> BA)
                county_df = pd.read_csv(county_path, dtype=str).fillna('')
                
                # Detect columns
                fips_col = next((c for c in county_df.columns if 'fips' in c.lower()), None)
                ba_col = next((c for c in county_df.columns if c.lower() in ['ba', 'rb', 'zone', 'p']), None)

                # 2. Load hierarchy to map BA -> Model Region (r)
                # hierarchy.csv typically has columns like [*r, ba, ...] or [r, ba, ...]
                # We need the mapping from the base 'ba' (p28) to the solved 'r' (z28)
                hier = pd.read_csv(hierarchy_path)
                # Standardize column names for mapping
                if '*r' in hier.columns: hier = hier.rename(columns={'*r': 'r'})
                
                # Create dictionary: ba -> r
                # If 'ba' column exists, use it. If not, assume 'r' is the lowest level or check hierarchy_original
                if 'ba' in hier.columns and 'r' in hier.columns:
                    ba_to_r = hier.set_index('ba')['r'].to_dict()
                else:
                    # if hierarchy doesn't have 'ba', try hierarchy_original for aggreg mapping
                    hier_org_path = os.path.join(inputs_case, 'hierarchy_original.csv')
                    if os.path.exists(hier_org_path):
                        hier_org = pd.read_csv(hier_org_path)
                        # In hierarchy_original, 'ba' is base, 'aggreg' is the aggregated zone (z28)
                        # If 'aggreg' column exists, map ba -> aggreg
                        # Note: For non-aggregated regions, 'aggreg' might be NaN or same as 'ba'.
                        # We need a map that covers ALL BAs.
                        if 'aggreg' in hier_org.columns:
                            # fillna in 'aggreg' with 'ba' values for regions that aren't aggregated
                            hier_org['aggreg'] = hier_org['aggreg'].fillna(hier_org['ba'])
                            ba_to_r = hier_org.set_index('ba')['aggreg'].to_dict()
                        else:
                            ba_to_r = {r: r for r in county_df[ba_col].unique()}
                    else:
                        ba_to_r = {r: r for r in county_df[ba_col].unique()}

                if fips_col and ba_col:
                    # 3. Map county BAs to Model Regions
                    # Create a new column 'r' in county_df representing the model region (z28, p1, etc.)
                    county_df['r'] = county_df[ba_col].map(ba_to_r)
                    
                    # Handle cases where mapping failed (e.g. if county2zone has BAs not in hierarchy)
                    # Fill NAs with the original BA code if map failed (fallback)
                    county_df['r'] = county_df['r'].fillna(county_df[ba_col])

                    # 4. Merge multipliers onto counties based on Model Region 'r'
                    # agg has columns ['r', 'tech', 'occ_mult', ...]
                    merged = county_df[['r', fips_col]].merge(agg, on='r', how='inner')
                    
                    # 5. Format output
                    # Rename FIPS to 'r' for the output file format (standard ReEDS spatial format)
                    merged = merged.rename(columns={fips_col: 'r'})
                    
                    out_county = os.path.join(inputs_case, f'{tech_type}_cost_multipliers_county.csv' if tech_type else 'geo_cost_multipliers_county.csv')
                    cols_to_write = [c for c in ['r','tech','occ_mult','plant_cost_mult','total_mult', 'value'] if c in merged.columns]
                    merged[cols_to_write].to_csv(out_county, index=False)
                    print(f"Wrote county-level aggregated multipliers to {out_county}")
                else:
                    print("Warning: could not detect FIPS/BA columns in county2zone.csv")
            else:
                print("Warning: county2zone.csv or hierarchy.csv not found")
        except Exception as ex:
            print(f"Warning: failed to create county-level multipliers: {ex}")
            traceback.print_exc()
    
    ret = agg.copy()
    # rename tech -> *i
    ret = ret.rename(columns={'tech': '*i'})
    # keep only requested columns in the exact order
    ret = ret[['*i', 'r', 'value']]

    # overwrite aggregated output file with the exact long format expected downstream
    out_agg_long = os.path.join(inputs_case, f'{tech_type}_cap_cost_mult.csv' if tech_type else 'geo_cap_cost_mult.csv')
    ret.to_csv(out_agg_long, index=False)

    return ret
