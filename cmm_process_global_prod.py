
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

# keep relevant columns

df = df.iloc[:, 0:5]
new_cols = ['* mat','mat_ctry','value','type','spec']
df.columns = new_cols

# trim whitespace and clean up values
df['* mat'] = df['* mat'].str.strip()
df['mat_ctry'] = df['mat_ctry'].str.strip()
df['type'] = df['type'].str.strip()
df['spec'] = df['spec'].str.strip()

# filter to production data for now, and keep only relevant columns
df = df[df['type'] == 'Production']
new_cols = ['* mat','mat_ctry','production','type','spec']
df.columns = new_cols

# clean up value column
df['production'].unique()
df['production'] = df['production'].replace('W', 0.00) 
df['production'] = df['production'].replace('15,000-20,000', 15000.00) 
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

# clean up material names
df['* mat'].unique()
df['* mat'] = df['* mat'].replace('Magnesium Compounds','Magnesium')
df['* mat'] = df['* mat'].replace('Magnesium Metal','Magnesium')
df['* mat'] = df['* mat'].replace('Titanium and Titanium Dioxide','Titanium')
df['* mat'] = df['* mat'].replace('Zirconium mineral concentrates','Zirconium')

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

    # Rule 1: If the material is 'Magnesium', sum the values, 
    # because magnesium metal and magnesium compounds are two separate production
    if material_name == 'Magnesium':
        total_production = round(group['production'].sum(), 2)
        result_row = group.iloc[[0]].copy()
        result_row['production'] = total_production
        result_row['spec'] = 'Aggregated Magnesium'
        return result_row

    # Rule 2: If the material is 'Silicon', sum the values
    # because the two types of silicon are separate products
    elif material_name == 'Silicon':
        total_production = round(group['production'].sum(), 2)
        result_row = group.iloc[[0]].copy()
        result_row['production'] = total_production
        result_row['spec'] = 'Aggregated Silicon'
        return result_row

    # Rule 3: Otherwise (fallback for all other materials), keep the 'Mine' row
    # because mine vs refinery are different steps in supply chain
    else:
        mine_row = group[group['spec'] == 'Mine']
        if not mine_row.empty:
            return mine_row
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


# filter out rare earths for now
df = df[df['* mat'] != 'Rare Earths']

df.to_csv(os.path.join(workdir, 'cmm_global_mat_prod.csv'), index=False)

# make set of countries for which we have production data
countries_array = df['mat_ctry'].unique()
countries = pd.DataFrame(countries_array, columns=['* mat_ctry'])
caption = "* set of countries for which we have materials production data"
caption_df = pd.DataFrame([caption], columns=['* mat_ctry'])
countries = pd.concat([caption_df, countries], ignore_index=True)

countries.to_csv(os.path.join(workdir, 'cmm_countries.csv'), index=False)

# make set of countries for analysis domestic + allied analysis 
# list of free trade countries from here: https://ustr.gov/trade-agreements/free-trade-agreements
free_trade = np.array(['Australia','Bahrain','Canada','Chile','Colombia','Costa_Rica','Dominican_Republic','El_Salvador','Guatemala','Honduras','Israel','Japan','Jordan','South_Korea','Mexico','Morocco','Nicaragua','Oman','Panama','Peru','Singapore'])
allies = np.intersect1d(countries_array, free_trade)
allies = pd.DataFrame(allies,columns=['* allies'])
caption = "* allied countries with material inputs for power"
caption_df = pd.DataFrame([caption],columns=['* allies'])
allies = pd.concat([caption_df, allies], ignore_index=True)

allies.to_csv(os.path.join(workdir, 'cmm_allies.csv'), index=False)