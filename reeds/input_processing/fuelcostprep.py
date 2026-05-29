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
import numpy as np
import os
import sys
import argparse
import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
import reeds

def calculate_state_weights(
    inputs_case,
    st2gasreg
):
    ## Calculate state population to calculate
    ## population-weighted degree days
    # Get county populations
    county_populations = reeds.io.get_county_populations()
    county_populations = county_populations.rename(
        columns={'value': 'population'}
    )
    # Get county-state map
    county2zone = reeds.io.get_county2zone(
        os.path.dirname(inputs_case),
        as_map=False
    )
    county2zone['FIPS'] = (
        'p' + county2zone['FIPS'].astype(str).str.zfill(5)
    )
    county_state_map = county2zone.set_index('FIPS')['state']
    # Calculate state populations
    county_populations['state'] = (
        county_populations['FIPS'].map(county_state_map)
    )
    state_populations = (
        county_populations.groupby('state', as_index=False)
        ['population']
        .sum()
    )
    # Calculate state weights
    state_populations['gasreg'] = (
        state_populations['state'].map(st2gasreg)
    )
    state_populations['weight'] = (
        state_populations['population']
        / (
            state_populations.groupby('gasreg')
            ['population']
            .transform('sum')
        )
    )
    state_weights = (
        state_populations.set_index('state')['weight']
    )

    return state_weights

def calculate_historical_daily_state_degree_days(inputs_case):
    # Get hourly state-level temperatures
    sw = reeds.io.get_switches(inputs_case)
    weather_years = [int(y) for y in sw.GSw_HourlyWeatherYears.split('_')]
    temp_hourly = reeds.io.get_temperatures(inputs_case, subset_years=False)
    temp_hourly = temp_hourly.loc[temp_hourly.index.year.isin(weather_years)]

    # Get baseline temperature
    scalars = reeds.io.get_scalars(inputs_case)
    base_temp = scalars['degree_days_base_temperature']

    # Calculate state-level, daily heating and cooling degree days
    temp_daily = temp_hourly.resample('D').agg(['min', 'max'])
    avg_temp_daily = (
        temp_daily.xs('min', axis=1, level=1)
        + temp_daily.xs('max', axis=1, level=1)
    ) / 2
    hdd_daily = (base_temp - avg_temp_daily).clip(lower=0)
    cdd_daily = (avg_temp_daily - base_temp).clip(lower=0)

    return hdd_daily, cdd_daily

def calculate_historical_daily_gasreg_popweighted_degree_days(
    historical_daily_state_degree_days,
    state_weights,
    st2gasreg
):
    historical_daily_gasreg_popweighted_degree_days = (
        (historical_daily_state_degree_days * state_weights)
        .transpose()
        .rename(st2gasreg)
        .groupby(level=0)
        .sum()
        .transpose()
    )
    return historical_daily_gasreg_popweighted_degree_days

def calculate_projected_daily_gasreg_popweighted_degree_days(
    historical_daily_gasreg_popweighted_degree_days,
    annual_gasreg_degree_day_projections
):
    # Apply historical degree day shapes to annual projections
    historical_gasreg_popweighted_degree_day_shapes = (
        historical_daily_gasreg_popweighted_degree_days.div(
            historical_daily_gasreg_popweighted_degree_days.groupby(
                historical_daily_gasreg_popweighted_degree_days.index.year
            )
            .transform('sum')
        )
        .reset_index()
    )
    daily_gasreg_popweighted_degree_days = (
        pd.merge(
            historical_gasreg_popweighted_degree_day_shapes,
            annual_gasreg_degree_day_projections,
            how='cross',
            suffixes=('_shape', '_magnitude')
        )
        .set_index(['t', 'timestamp'])
        .rename_axis(['year', 'datetime'])
        .sort_index()
    )
    gasregs = (
        annual_gasreg_degree_day_projections
        .drop(columns='t')
        .columns
        .tolist()
    )
    for gasreg in gasregs:
        daily_gasreg_popweighted_degree_days[gasreg] = (
            daily_gasreg_popweighted_degree_days[f"{gasreg}_shape"]
            * daily_gasreg_popweighted_degree_days[f"{gasreg}_magnitude"]
        )
        daily_gasreg_popweighted_degree_days = (
            daily_gasreg_popweighted_degree_days.drop(
                columns=[f"{gasreg}_shape", f"{gasreg}_magnitude"]
            )
        )
    
    return daily_gasreg_popweighted_degree_days

def calculate_daily_gasreg_population_weighted_degree_days(
    reeds_path,
    inputs_case,
):
    # state -> gasreg mapping
    state_groups = pd.read_csv(
        os.path.join(reeds_path, 'inputs', 'zones', 'state_groups.csv')
    )
    st2gasreg = state_groups.set_index('st')['gasreg']
    # Get population-based state weights
    state_weights = calculate_state_weights(
        inputs_case,
        st2gasreg
    )
    # Get historical state-level daily HDD/CDDs
    historical_hdd_daily_st, historical_cdd_daily_st = (
        calculate_historical_daily_state_degree_days(inputs_case)
    )
    # Calculate historical gasreg-level population-weighted degree days
    historical_popweighted_hdd_daily_gasreg = (
        calculate_historical_daily_gasreg_popweighted_degree_days(
            historical_hdd_daily_st,
            state_weights,
            st2gasreg
        )
    )
    historical_popweighted_cdd_daily_gasreg = (
        calculate_historical_daily_gasreg_popweighted_degree_days(
            historical_cdd_daily_st,
            state_weights,
            st2gasreg
        )
    )
    # Get gasreg-level annual HDD/CDD projections and
    # subset to solve years only
    solveyears = reeds.io.get_years(os.path.dirname(inputs_case))
    gasreg_degree_days = pd.read_csv(
        os.path.join(inputs_case, 'gasreg_degree_days.csv')
    )
    gasreg_degree_days = (
        gasreg_degree_days.loc[gasreg_degree_days['t'].isin(solveyears)]
    )
    gasreg_hdd = (
        gasreg_degree_days.loc[gasreg_degree_days.ddtype == 'HDD']
        .drop(columns='ddtype')
    )
    gasreg_cdd = (
        gasreg_degree_days.loc[gasreg_degree_days.ddtype == 'CDD']
        .drop(columns='ddtype')
    )
    # Apply annual HDD/CDD projections to historical degree day shapes
    popweighted_hdd_daily_gasreg = (
        calculate_projected_daily_gasreg_popweighted_degree_days(
            historical_popweighted_hdd_daily_gasreg,
            gasreg_hdd
        )
    )
    popweighted_cdd_daily_gasreg = (
        calculate_projected_daily_gasreg_popweighted_degree_days(
            historical_popweighted_cdd_daily_gasreg,
            gasreg_cdd
        )
    )

    return popweighted_hdd_daily_gasreg, popweighted_cdd_daily_gasreg

def calculate_daily_gas_price_multipliers(reeds_path, inputs_case):
    # Get temperature-price regression parameters and daily
    # population-weighted degree days for each gasreg
    dd_gas_price_regression_params = pd.read_csv(
        os.path.join(
            inputs_case,
            'degree_day_gas_price_regression_parameters.csv'
        ),
        index_col='param'
    )
    popweighted_hdd_daily_gasreg, popweighted_cdd_daily_gasreg = (
        calculate_daily_gasreg_population_weighted_degree_days(
            reeds_path,
            inputs_case,
        )
    )
    # Apply regression parameters to get daily price multipliers
    df_out = pd.DataFrame(index=popweighted_hdd_daily_gasreg.index)
    for gasreg in dd_gas_price_regression_params.columns:
        beta_cdd = dd_gas_price_regression_params.loc['beta_CDD', gasreg]
        beta_hdd = dd_gas_price_regression_params.loc['beta_HDD', gasreg]
        alpha = dd_gas_price_regression_params.loc['alpha', gasreg]
        # monthly effects
        month_effects_map = (
            dd_gas_price_regression_params
            .loc[dd_gas_price_regression_params.index.str.contains('alpha_')]
            [gasreg]
        )
        month_effects_map.index = month_effects_map.index.str.removeprefix('alpha_')
        month_effects = (
            popweighted_hdd_daily_gasreg.index
            .get_level_values('datetime')
            .strftime('%b')
            .str
            .upper()
            .map(month_effects_map)
        )
        gasreg_price_log_returns = (
            alpha
            + beta_cdd * popweighted_cdd_daily_gasreg[gasreg]
            + beta_hdd * popweighted_hdd_daily_gasreg[gasreg]
            + month_effects.values
        )
        gasreg_price_multipliers = np.exp(gasreg_price_log_returns)
        gasreg_price_multipliers = gasreg_price_multipliers.div(
            gasreg_price_multipliers.groupby(level=0).mean()
        )
        df_out[gasreg] = gasreg_price_multipliers

    hierarchy = reeds.io.get_hierarchy(os.path.dirname(inputs_case))
    # Create one set of multipliers for model zones
    # (needed if GSw_GasCurve == 2)
    df_out_r = pd.DataFrame(data={
        r: df_out[gasreg] for r, gasreg in hierarchy['gasreg'].items()
    })
    # Create another set of multipliers for census divisions
    # (needed if GSw_GasCurve != 2)
    popweighted_dd_daily_gasreg = (
        popweighted_hdd_daily_gasreg + popweighted_cdd_daily_gasreg
    )
    annual_gasreg_dd = (
        popweighted_dd_daily_gasreg.groupby(
            popweighted_dd_daily_gasreg.index.get_level_values('year')
        )
        .sum()
    )
    gasreg_cendiv_map = dict(zip(hierarchy['gasreg'], hierarchy['cendiv']))
    annual_cendiv_dd = (
        annual_gasreg_dd.transpose()
        .assign(cendiv=gasreg_cendiv_map)
        .groupby('cendiv', as_index=False)
        .transform('sum')
        .transpose()
    )
    annual_gasreg_cendiv_weights = annual_gasreg_dd / annual_cendiv_dd
    df_out_cendiv = (
        df_out.mul(annual_gasreg_cendiv_weights, level=0)
        .transpose()
        .rename(gasreg_cendiv_map)
        .groupby(level=0)
        .sum()
        .transpose()
    )

    return df_out_r, df_out_cendiv

# Time the operation of this script
tic = datetime.datetime.now()

#%% Parse arguments
parser = argparse.ArgumentParser(description="""This file organizes fuel cost data by techonology""")

parser.add_argument("reeds_path", help='ReEDS directory')
parser.add_argument("inputs_case", help='ReEDS/runs/{case}/inputs_case directory')

args = parser.parse_args()
reeds_path = args.reeds_path
inputs_case = args.inputs_case

# #%% Settings for testing
# reeds_path = 'd:\\Danny_ReEDS\\ReEDS'
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
val_r = reeds.io.read_input(inputs_case, 'r').squeeze(1).tolist()
val_cendiv = reeds.io.read_input(inputs_case, 'cendiv').squeeze(1).tolist()

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

### Daily gas price multipliers
daily_gas_price_multipliers_r, daily_gas_price_multipliers_cendiv = (
    calculate_daily_gas_price_multipliers(reeds_path, inputs_case)
)


#%%###################
### Data Write-Out ###
######################

fuel.to_csv(os.path.join(inputs_case,'fprice.csv'),index=False)
ngprice_cendiv.to_csv(os.path.join(inputs_case,'gasprice_ref.csv'))
ngdemand.to_csv(os.path.join(inputs_case,'ng_demand_elec.csv'))
ngtotdemand.to_csv(os.path.join(inputs_case,'ng_demand_tot.csv'))
alpha.to_csv(os.path.join(inputs_case,'alpha.csv'))
reeds.io.write_profile_to_h5(
    daily_gas_price_multipliers_r,
    'daily_gas_price_multipliers_r.h5',
    inputs_case
)
reeds.io.write_profile_to_h5(
    daily_gas_price_multipliers_cendiv,
    'daily_gas_price_multipliers_cendiv.h5',
    inputs_case
)

reeds.log.toc(tic=tic, year=0, process='input_processing/fuelcostprep.py', 
    path=os.path.join(inputs_case,'..'))

print('Finished fuelcostprep.py')
