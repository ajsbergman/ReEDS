'''
The purpose of this script is to write out fuel costs for the following fuels at 
census division level:
    - coal
    - uranium
    - H2 (for H2-CT/CC tech)
    - natural gas
Additionally, this script also writes out natural gas demand (total NG demand as 
well as NG demand for electricity generation) and natural gas alphas
'''
#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================

import pandas as pd
import os
import sys
import argparse
import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds
# Time the operation of this script
tic = datetime.datetime.now()

#%% Parse arguments
parser = argparse.ArgumentParser(description="""This file organizes fuel cost data by techonology""")

parser.add_argument("reeds_path", help='ReEDS-2.0 directory')
parser.add_argument("inputs_case", help='ReEDS-2.0/runs/{case}/inputs_case directory')

args = parser.parse_args()
reeds_path = args.reeds_path
inputs_case = args.inputs_case

# #%% Settings for testing
# reeds_path = 'd:\\Danny_ReEDS\\ReEDS-2.0'
# reeds_path = os.getcwd()
# inputs_case = os.path.join('runs','nd5_ND','inputs_case')

#%% Set up logger
log = reeds.log.makelog(
    scriptname=__file__,
    logpath=os.path.join(inputs_case,'..','gamslog.txt'),
)
print("Starting fuelcostprep.py")

#%% Inputs from switches
sw = reeds.io.get_switches(inputs_case)

# Load valid regions
val_r = pd.read_csv(
    os.path.join(inputs_case, 'val_r.csv'), header=None).squeeze(1).tolist()
val_cendiv = pd.read_csv(
    os.path.join(inputs_case, 'val_cendiv.csv'), header=None).squeeze(1).tolist()

r_cendiv = pd.read_csv(os.path.join(inputs_case,"r_cendiv.csv"))

dollaryear = pd.read_csv(os.path.join(inputs_case, "dollaryear_fuel.csv"))
deflator = pd.read_csv(os.path.join(inputs_case,'deflator.csv'))
deflator.columns = ["Dollar.Year","Deflator"]
dollaryear = dollaryear.merge(deflator,on="Dollar.Year",how="left")

#%% ===========================================================================
### --- PROCEDURE: FUEL PRICE CALCULATIONS ---
### ===========================================================================

####################
#    -- Coal --    #
####################
coal = pd.read_csv(os.path.join(inputs_case, 'coal_price.csv'))
coal = coal.melt(id_vars = ['year']).rename(columns={'variable':'cendiv'})
coal = coal.loc[coal['cendiv'].isin(val_cendiv)]

# Adjust prices to 2004$
deflate = dollaryear.loc[dollaryear['Scenario'] == sw.coalscen,'Deflator'].values[0]
coal.loc[:,'value'] = coal['value'] * deflate

coal = coal.merge(r_cendiv,on='cendiv',how='left')
coal = coal.drop('cendiv', axis=1)
coal = coal[['year','r','value']].rename(columns={'year':'t','value':'coal'})
coal.coal = coal.coal.round(6)

#######################
#    -- Uranium --    #
#######################
uranium = pd.read_csv(os.path.join(inputs_case, 'uranium_price.csv'))

# Adjust prices to 2004$
deflate = dollaryear.loc[dollaryear['Scenario'] == sw.uraniumscen,'Deflator'].values[0]
uranium.loc[:,'cost'] = uranium['cost'] * deflate
uranium = pd.concat([uranium.assign(r=i) for i in val_r], ignore_index=True)
uranium = uranium[['year','r','cost']].rename(columns={'year':'t','cost':'uranium'})
uranium.uranium = uranium.uranium.round(6)

#############################
#    -- H2-Combustion --    #
#############################
# note that these fuel inputs are not used when H2 production is run endogenously in ReEDS (GSw_H2 > 0)
h2fuel = pd.read_csv(os.path.join(inputs_case, 'hydrogen_price.csv'), index_col='year')

#Adjust prices to 2004$
deflate = dollaryear.loc[dollaryear['Scenario'] == sw.h2combustionfuelscen,'Deflator'].squeeze()
h2fuel['cost'] = h2fuel['cost'] * deflate
# Reshape from [:,[t,cost]] to [:,[t,r,cost]]
h2fuel = (
    pd.concat({r:h2fuel for r in val_r}, axis=0, names=['r'])
    .reset_index().rename(columns={'year':'t','cost':'h2fuel'})
    [['t','r','h2fuel']]
    .round(6)
)

###########################
#    -- Natural Gas --    #
###########################

ngprice = pd.read_csv(os.path.join(inputs_case,'natgas_price_cendiv.csv'))
ngprice = ngprice.melt(id_vars=['year']).rename(columns={'variable':'cendiv'})
ngprice = ngprice.loc[ngprice['cendiv'].isin(val_cendiv)]

# Adjust prices to 2004$
deflate = dollaryear.loc[dollaryear['Scenario'] == sw.ngscen,'Deflator'].values[0]
ngprice.loc[:,'value'] = ngprice['value'] * deflate

# Save Natural Gas prices by census region
ngprice_cendiv = ngprice.copy()
ngprice_cendiv = ngprice_cendiv.pivot_table(index='cendiv',columns='year',values='value')
ngprice_cendiv = ngprice_cendiv.round(6)

# Map census regions to model regions
ngprice = ngprice.merge(r_cendiv,on='cendiv',how='left')
ngprice = ngprice.drop('cendiv', axis=1)
ngprice = ngprice[['year','r','value']].rename(columns={'year':'t','value':'naturalgas'})
ngprice.naturalgas = ngprice.naturalgas.round(6)

# Combine all fuel data
fuel = coal.merge(uranium,on=['t','r'],how='left')
fuel = fuel.merge(ngprice,on=['t','r'],how='left')
fuel = fuel.merge(h2fuel,on=['t','r'],how='left')
fuel = fuel.sort_values(['t','r'])

#%%#################################### 
### Natural Gas Price Diffs ###

# Regression parameters for calculating natural gas price differences across regions based on degree days
params = pd.read_csv(os.path.join(reeds_path,'inputs', 'fuelprices', 'temperature_price_regression_parameters.csv'), index_col='param')

# Daily degree days by price region
daily_dd = reeds.io.get_degree_days(inputs_case, hourly_formula=False)

#apply the regional regression params to get daily multiplicative price differences from the annual price 
daily_dd['date'] = pd.to_datetime(daily_dd['date'])
daily_dd['month'] = daily_dd['date'].dt.month

regions = [c for c in daily_dd.columns if c not in ['date','t','ddtype','month']]

# split HDD / CDD
hdd = daily_dd[daily_dd['ddtype'] == 'hdd'].set_index('date')
cdd = daily_dd[daily_dd['ddtype'] == 'cdd'].set_index('date')

# align
hdd, cdd = hdd.align(cdd, join='outer', axis=0, fill_value=0)

out = pd.DataFrame(index=hdd.index)

for r in regions:
    beta_cdd = params.loc['beta_CDD', r]
    beta_hdd = params.loc['beta_HDD', r]
    alpha = params.loc['alpha', r]

    # monthly effects
    month_map = {
        i: params.loc[f'alpha_{m}', r]
        for i, m in enumerate(
            ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'],
            start=1
        )
    }

    #Align index of month effects with index of hdd/cdd
    month_effect = hdd.index.month.map(month_map)

    log_ret = (
        alpha
        + beta_cdd * cdd[r]
        + beta_hdd * hdd[r]
        + month_effect.values
    )

    out[r] = np.exp(log_ret)


#%%#################################### 
### Natural Gas Demand Calculations ###

# Natural Gas demand
ngdemand = pd.read_csv(os.path.join(inputs_case,'ng_demand_elec.csv'), index_col='year')
ngdemand = ngdemand[ngdemand.columns[ngdemand.columns.isin(val_cendiv)]]
ngdemand = ngdemand.transpose()
ngdemand = ngdemand.round(6)

# Total Natural Gas demand
ngtotdemand = pd.read_csv(os.path.join(inputs_case, 'ng_demand_tot.csv'), index_col='year')
ngtotdemand = ngtotdemand[ngtotdemand.columns[ngtotdemand.columns.isin(val_cendiv)]]
ngtotdemand = ngtotdemand.transpose()
ngtotdemand = ngtotdemand.round(6)

### Natural Gas Alphas (already in 2004$)
alpha = pd.read_csv(os.path.join(inputs_case, 'alpha.csv'), index_col='t')
alpha = alpha[alpha.columns[alpha.columns.isin(val_cendiv)]]
alpha = alpha.round(6)

#%%###################
### Data Write-Out ###
######################

fuel.to_csv(os.path.join(inputs_case,'fprice.csv'),index=False)
ngprice_cendiv.to_csv(os.path.join(inputs_case,'gasprice_ref.csv'))

ngdemand.to_csv(os.path.join(inputs_case,'ng_demand_elec.csv'))
ngtotdemand.to_csv(os.path.join(inputs_case,'ng_demand_tot.csv'))
alpha.to_csv(os.path.join(inputs_case,'alpha.csv'))

reeds.log.toc(tic=tic, year=0, process='input_processing/fuelcostprep.py', 
    path=os.path.join(inputs_case,'..'))

print('Finished fuelcostprep.py')
