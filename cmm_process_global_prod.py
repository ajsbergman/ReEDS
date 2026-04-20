
#-------------------------------------------------------------------
# Packages
#-------------------------------------------------------------------

import pandas as pd
import numpy as np
import os
import re

#-------------------------------------------------------------------
# Directories
#-------------------------------------------------------------------
                                                                                
workdir = os.path.dirname(os.path.abspath(__file__))

#-------------------------------------------------------------------
# Import Data
#-------------------------------------------------------------------

df = pd.read_csv(os.path.join(workdir, 'cmm_global_mat_prod_raw.csv'))
price_df = pd.read_csv(os.path.join(workdir, 'cmm_global_mat_price_raw.csv'))
deflator_df = pd.read_csv(os.path.join(workdir, 'inputs', 'financials', 'deflator.csv'))


# PRODUCTION DATA
# keep relevant columns

df = df.iloc[:, 0:5]
new_cols = ['* mat','mat_ctry','value','type','sc_pt']
df.columns = new_cols

# trim whitespace and clean up values
df['* mat'] = df['* mat'].str.strip()
df['mat_ctry'] = df['mat_ctry'].str.strip()
df['type'] = df['type'].str.strip()
df['sc_pt'] = df['sc_pt'].str.strip()

# filter to production data for now, and keep only relevant columns
df = df[df['type'] == 'Production']
new_cols = ['* mat','mat_ctry','production','type','sc_pt']
df.columns = new_cols

# clean up value column
df['production'].unique() 
df['production'] = pd.to_numeric(df['production'], errors='coerce').fillna(0)

# clean up country names
df['mat_ctry'].unique()
df['mat_ctry'] = df['mat_ctry'].replace('Other countries','Other') 
df['mat_ctry'] = df['mat_ctry'].replace('United States','USA') 
df['mat_ctry'] = df['mat_ctry'].replace('Republic of Korea','South_Korea') 
df['mat_ctry'] = df['mat_ctry'].replace('Côte d’Ivoire','Cote_d_Ivoire') 
df['mat_ctry'] = df['mat_ctry'].replace('Congo(Kinshasa)','Congo') 
df['mat_ctry'] = df['mat_ctry'].replace('United Arab Emirates','UAE') 
df['mat_ctry'] = df['mat_ctry'].replace('China and Burma','China') 
df['mat_ctry'] = df['mat_ctry'].str.replace(r'\s+', '_', regex=True)

# ensure not double counting production at multiple points in supply chain  
df['* mat'].unique()
# Magnesium compound production is magnesite at mine site. 
df['* mat'] = df['* mat'].replace('Magnesium Compounds','Magnesium')
df = df[df['* mat'] != 'Magnesium Metal']
# filter out rare earths
df = df[df['* mat'] != 'Rare Earths']
# Titanium concentrates are ilmenite and Rutile at mine site. Titanium dioxide is at refinery stage. 
df['* mat'] = df['* mat'].replace('Titanium Mineral Concentrates','Titanium')
df = df[df['* mat'] != 'Titanium and Titanium Dioxide']
# Copper and Hafnium keep only mine production
df = df[~((df['* mat'] == 'Copper') & (df['sc_pt'] == 'Refinery'))]
df = df[~((df['* mat'] == 'Hafnium') & (df['sc_pt'] == 'Refinery'))]

# removing duplicate production values
dup_cols = ['* mat','mat_ctry']

# identify duplicates and separate from non-duplicates
is_duplicate = df.duplicated(subset=dup_cols, keep=False)
df_no_duplicates = df[~is_duplicate]
df_duplicates = df[is_duplicate]

# create function for processing duplicate data
def process_duplicates(group):
    # Get the material name for this group (it's the same for all rows in the group)
    material_name = group['* mat'].iloc[0]

    # Rule 1: If the material is 'Silicon', sum the values
    # because the two types of silicon are separate products
    if material_name == 'Silicon':
        total_production = round(group['production'].sum(), 2)
        result_row = group.iloc[[0]].copy()
        result_row['production'] = total_production
        result_row['sc_pt'] = 'Aggregated Silicon'
        return result_row

    # Rule 3: Otherwise (fallback for all other materials), keep the 'Mine' row
    # because mine vs refinery are different steps in supply chain
    else:
        return None # Or handle as needed if no 'Mine' row exists

# run function and combine non-duplicate and processed duplicate data
processed_duplicates = df_duplicates.groupby(dup_cols).apply(process_duplicates)
processed_duplicates = processed_duplicates.reset_index(drop=True)
df = pd.concat([df_no_duplicates, processed_duplicates], ignore_index=True)
# double check no more duplicates
is_duplicate = df.duplicated(subset=dup_cols, keep=False)
# select only relevant columns for model
df = df.iloc[:, 0:3]

df.to_csv(os.path.join(workdir, 'cmm_global_mat_prod.csv'), index=False)

# make set of countries for which we have production data
countries_array = df['mat_ctry'].unique()
countries = pd.DataFrame(countries_array, columns=['* mat_ctry'])
caption = "* set of countries for which we have materials production data"
caption_df = pd.DataFrame([caption], columns=['* mat_ctry'])
countries = pd.concat([caption_df, countries], ignore_index=True)

countries.to_csv(os.path.join(workdir, 'cmm_countries.csv'), index=False)


# deprecated - remove once confirmed not needed for analysis
# make set of countries for analysis domestic + allied analysis 
# list of free trade countries from here: https://ustr.gov/trade-agreements/free-trade-agreements
free_trade = np.array(['Australia','Bahrain','Canada','Chile','Colombia','Costa_Rica','Dominican_Republic','El_Salvador','Guatemala','Honduras','Israel','Japan','Jordan','South_Korea','Mexico','Morocco','Nicaragua','Oman','Panama','Peru','Singapore'])
allies = np.intersect1d(countries_array, free_trade)
allies = pd.DataFrame(allies,columns=['* allies'])
caption = "* allied countries with material inputs for power"
caption_df = pd.DataFrame([caption],columns=['* allies'])
allies = pd.concat([caption_df, allies], ignore_index=True)

allies.to_csv(os.path.join(workdir, 'cmm_allies.csv'), index=False)


# PRICE DATA

new_cols = ['year','deflator']
deflator_df.columns = new_cols
deflator_df.loc[len(deflator_df)] = {'year': 2025, 'deflator': 0.586666667} # calculated from https://www.minneapolisfed.org/about-us/monetary-policy/inflation-calculator/consumer-price-index-1800-
deflator_df.loc[len(deflator_df)] = {'year': 2026, 'deflator': 0.586666667} # using 2025 because pulled in Q1 of 2026

price_df = pd.merge(
    price_df,
    deflator_df,
    how='left',
    left_on='year_source', # Key in the left DataFrame
    right_on='year'      # Key in the right DataFrame
)

price_df['price_per_tonne_2004'] = price_df['price_per_tonne'] * price_df['deflator']

price_df['price_per_tonne_2004'] = price_df['price_per_tonne_2004'].round(2)

price_df = price_df[['Material','Product','Type','price_per_tonne_2004']]
price_df['Material'] = price_df['Material'].str.strip()


# remove prices not needed 
#keep only metal chromium
price_df = price_df[~((price_df['Material'] == 'Chromium') & (price_df['Product'] == 'ore'))]
price_df = price_df[~((price_df['Material'] == 'Chromium') & (price_df['Product'] == 'alloy'))]
# keep only refined gallium
price_df = price_df[~((price_df['Material'] == 'Gallium') & (price_df['price_per_tonne_2004'] == '132612.07'))]
# keep only magnesium metal 
price_df = price_df[~((price_df['Material'] == 'Magnesium') & (price_df['Product'] == 'chemical compound'))]
# keep only titanium metal
price_df = price_df[~((price_df['Material'] == 'Titanium') & (price_df['Product'] == 'chemical compound'))]
price_df = price_df[~((price_df['Material'] == 'Titanium') & (price_df['Product'] == 'mineral concentrate'))]
# keep only yttrium metal 
price_df = price_df[~((price_df['Material'] == 'Yttrium') & (price_df['Product'] == 'chemical compound'))]
# keep only zinc metal
price_df = price_df[~((price_df['Material'] == 'Zirconium') & (price_df['Product'] == 'ore'))]

# take average by material type
price_df = price_df.groupby(['Material'], as_index=False)['price_per_tonne_2004'].mean().round(2)
new_cols = ['* mat','price']
price_df.columns = new_cols

price_df.to_csv(os.path.join(workdir, 'cmm_global_mat_price.csv'), index=False)