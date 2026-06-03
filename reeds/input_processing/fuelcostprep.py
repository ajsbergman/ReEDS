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


def calculate_region_aggregion_population_weights(
    inputs_case: str,
    region_level: str,
    aggregion_level: str,
) -> pd.Series:
    """
    For a given region level and aggregated region (aggregion)
    level, calculate each region's share of its corresponding
    aggregion's total population.
    
    
    Args:
        inputs_case: Path to the inputs case directory.
        region_level: Region level (example: 'state')
        aggregion_level: Aggregated region level
            (example: 'cendiv')

    Returns:
        pd.Series
    """
    # Get county populations
    county_populations = reeds.io.get_county_populations()
    county_populations = county_populations.rename(
        columns={'value': 'population'}
    )

    # Get county-to-region mapping
    county2zone = reeds.io.get_county2zone(
        os.path.dirname(inputs_case),
        as_map=False
    )
    county2zone['FIPS'] = (
        'p' + county2zone['FIPS'].astype(str).str.zfill(5)
    )
    state_groups = reeds.io.get_state_groups()
    county2zone = county2zone.merge(
        state_groups,
        left_on='st',
        right_on='state'
    )
    county_region_map = county2zone.set_index('FIPS')[region_level]

    # Calculate regional populations
    county_populations[region_level] = (
        county_populations['FIPS'].map(county_region_map)
    )
    region_populations = (
        county_populations.groupby(region_level, as_index=False)
        ['population']
        .sum()
    )

    # Calculate each region's percentage of aggregion population
    region2aggregion = dict(zip(
        county2zone[region_level],
        county2zone[aggregion_level]
    ))
    region_populations[aggregion_level] = (
        region_populations['state'].map(region2aggregion)
    )
    region_populations['weight'] = (
        region_populations['population']
        / (
            region_populations.groupby(aggregion_level)
            ['population']
            .transform('sum')
        )
    )
    region_aggregion_weights = (
        region_populations.set_index(region_level)['weight']
    )

    return region_aggregion_weights

def calculate_historical_daily_state_degree_days(
    inputs_case: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate daily historical heating and cooling degree days for each state
    and each weather year (based on the GSw_HourlyWeatherYears switch) using
    hourly state-level temperature data.

    Args:
        inputs_case: Path to the inputs case directory.

    Returns:
        (pd.DataFrame, pd.DataFrame)
    """
    # Get hourly state-level temperatures for the given weather year(s)
    sw = reeds.io.get_switches(inputs_case)
    weather_years = [int(y) for y in sw.GSw_HourlyWeatherYears.split('_')]
    temp_hourly = reeds.io.get_temperatures(inputs_case, subset_years=False)
    temp_hourly = temp_hourly.loc[temp_hourly.index.year.isin(weather_years)]

    # Get baseline temperature for calculating degree days
    scalars = reeds.io.get_scalars(inputs_case)
    base_temp = scalars['degree_days_base_temperature']

    # Calculate each state's average temperature for each day
    temp_daily = temp_hourly.resample('D').agg(['min', 'max'])
    avg_temp_daily = (
        temp_daily.xs('min', axis=1, level=1)
        + temp_daily.xs('max', axis=1, level=1)
    ) / 2

    # Take differences between baseline and average temperatures
    hdd_daily = (base_temp - avg_temp_daily).clip(lower=0)
    cdd_daily = (avg_temp_daily - base_temp).clip(lower=0)

    return hdd_daily, cdd_daily

def aggregate_state_degree_days_to_gasreg(
    state_degree_days: pd.DataFrame,
    state_weights: pd.Series,
    st2gasreg: dict[str, str]
) -> pd.DataFrame:
    """
    Aggregate state-level degree days to the gasreg level via
    population-weighted average.

    Args:
        historical_daily_state_degree_days: Daily historical
            state-level degree days.
        state_weights: The percentage of each state's share of
            gasreg population.
        st2gasreg: State-to-gasreg mapping.

    Returns:
        pd.DataFrame
    """
    gasreg_degree_days = (
        (state_degree_days * state_weights)
        .transpose()
        .rename(st2gasreg)
        .groupby(level=0)
        .sum()
        .transpose()
    )
    return gasreg_degree_days

def rescale_historical_daily_degree_days_to_projected_annuals(
    historical_daily_degree_days: pd.DataFrame,
    projected_annual_degree_days: pd.DataFrame
) -> pd.DataFrame:
    """
    Rescale daily, historical degree days so that they match
    annual degree day projections. This is used to estimate
    daily degree day projections for model solve years.

    Args:
        historical_daily_degree_days: Daily historical degree days.
        projected_annual_degree_days: Annual degree day projections.

    Returns:
        pd.DataFrame
    """
    # Normalize the daily degree day profile annually to get daily
    # shapes for each historical year
    historical_degree_day_shapes = (
        historical_daily_degree_days.div(
            historical_daily_degree_days.groupby(
                historical_daily_degree_days.index.year
            )
            .transform('sum')
        )
        .reset_index()
    )

    # Combine the historical daily normalized values and projected
    # annual degree day magnitudes via cartesian product to line
    # them up row-by-row for each region
    projected_daily_degree_days = (
        pd.merge(
            historical_degree_day_shapes,
            projected_annual_degree_days,
            how='cross',
            suffixes=('_shape', '_magnitude')
        )
        .set_index(['t', 'timestamp'])
        .rename_axis(['year', 'datetime'])
        .sort_index()
    )

    # For each region, multiply the daily normalized value by the
    # annual projection to calculate a degree day projection for
    # each day
    regions = (
        projected_annual_degree_days
        .drop(columns='t')
        .columns
        .tolist()
    )
    for region in regions:
        projected_daily_degree_days[region] = (
            projected_daily_degree_days[f"{region}_shape"]
            * projected_daily_degree_days[f"{region}_magnitude"]
        )
        projected_daily_degree_days = (
            projected_daily_degree_days.drop(
                columns=[f"{region}_shape", f"{region}_magnitude"]
            )
        )
    
    return projected_daily_degree_days

def calculate_daily_gasreg_degree_days(
    reeds_path: str,
    inputs_case: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate daily gasreg-level heating and cooling degree days.
    This is done by calculating historical daily state-level degree
    days for the given weather year(s), aggregating them to the
    gasreg level via population-weighted average, and then rescaling
    the historical daily degree days to match projected annual
    degree days (corresponding to model solve years) for each gasreg.

    Args:
        reeds_path: Path to ReEDS directory.
        inputs_case: Path to the inputs case directory.

    Returns:
        (pd.DataFrame, pd.DataFrame)
    """
    # Get state-to-gasreg mapping
    state_groups = reeds.io.get_state_groups
    st2gasreg = state_groups.set_index('st')['gasreg']

    # Calculate population-based state-gasreg weights for
    # calculating population-weighted gasreg-level degree days
    state_gasreg_weights = calculate_region_aggregion_population_weights(
        inputs_case,
        region_level='state',
        aggregion_level='gasreg'
    )

    # Calculate historical state-level daily HDDs and CDDs
    historical_hdd_daily_st, historical_cdd_daily_st = (
        calculate_historical_daily_state_degree_days(inputs_case)
    )

    # Aggregate historical daily state-level degree days to
    # the gasreg level via population-weighted average
    historical_hdd_daily_gasreg = (
        aggregate_state_degree_days_to_gasreg(
            historical_hdd_daily_st,
            state_gasreg_weights,
            st2gasreg
        )
    )
    historical_cdd_daily_gasreg = (
        aggregate_state_degree_days_to_gasreg(
            historical_cdd_daily_st,
            state_gasreg_weights,
            st2gasreg
        )
    )

    # Get gasreg-level annual HDD/CDD projections
    # for the model solve years
    solveyears = reeds.io.get_years(os.path.dirname(inputs_case))
    annual_degree_days_gasreg = pd.read_csv(
        os.path.join(inputs_case, 'gasreg_degree_days.csv')
    )
    annual_degree_days_gasreg = (
        annual_degree_days_gasreg
        .loc[annual_degree_days_gasreg['t'].isin(solveyears)]
    )
    annual_hdd_gasreg = (
        annual_degree_days_gasreg
        .loc[annual_degree_days_gasreg.ddtype == 'HDD']
        .drop(columns='ddtype')
    )
    annual_cdd_gasreg = (
        annual_degree_days_gasreg
        .loc[annual_degree_days_gasreg.ddtype == 'CDD']
        .drop(columns='ddtype')
    )

    # Apply annual HDD/CDD projections to historical daily degree day shapes to
    # estimate daily gasreg-level HDD/CDD projections for each model solve year
    hdd_daily_gasreg = (
        rescale_historical_daily_degree_days_to_projected_annuals(
            historical_hdd_daily_gasreg,
            annual_hdd_gasreg
        )
    )
    cdd_daily_gasreg = (
        rescale_historical_daily_degree_days_to_projected_annuals(
            historical_cdd_daily_gasreg,
            annual_cdd_gasreg
        )
    )

    return hdd_daily_gasreg, cdd_daily_gasreg

def calculate_daily_gasprice_multipliers(
    reeds_path: str,
    inputs_case: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Calculate daily gas price multipliers at the r and cendiv levels.
    This is done by first calculating daily, gasreg-level heating and cooling
    degree days, where the daily degree day shapes correspond to temperature
    patterns of the given weather year(s) and annual degree day totals
    correspond to projections for the model solve years. Then, degree
    day-price multiplier regression parameters are applied to derive
    gasreg-level price multipliers. To derive r-level multipliers, the
    gasreg-level multipliers are copied to their constituent zones. To
    derive cendiv-level multipliers, gasreg-level multipliers are
    aggregated via population-weighted average. 

    Args:
        reeds_path: Path to ReEDS directory.
        inputs_case: Path to the inputs case directory.

    Returns:
        (pd.DataFrame, pd.DataFrame)
    """
    # Get degree day-price multiplier regression parameters. These
    # parameters represent a regression model where heating and
    # cooling degree days were regressed on the log of the multiplicative
    # difference between daily gas prices and the annual price for each
    # gasreg with monthly fixed effects.
    regression_params = pd.read_csv(
        os.path.join(
            inputs_case,
            'gasreg_degree_day_price_mult_regression_parameters.csv'
        ),
        index_col='param'
    )

    # Calculate daily gasreg-level HDDs and CDDs
    hdd_daily_gasreg, cdd_daily_gasreg = (
        calculate_daily_gasreg_degree_days(
            reeds_path,
            inputs_case,
        )
    )

    # Apply regression parameters to daily HDD/CDDs
    # to get daily gasreg-level price multipliers
    year_datetime_index = hdd_daily_gasreg.index
    df_out = pd.DataFrame(index=year_datetime_index)
    for gasreg in regression_params.columns:
        beta_cdd = regression_params.loc['beta_CDD', gasreg]
        beta_hdd = regression_params.loc['beta_HDD', gasreg]
        alpha = regression_params.loc['alpha', gasreg]
        month_effects_map = (
            regression_params
            .loc[regression_params.index.str.contains('alpha_')]
            [gasreg]
        )
        month_effects_map.index = month_effects_map.index.str.removeprefix('alpha_')
        month_effects = (
            year_datetime_index
            .get_level_values('datetime')
            .strftime('%b')
            .str
            .upper()
            .map(month_effects_map)
        )
        # Applying the regression parameters gives the log of the
        # daily multiplicative difference from the annual average
        # price, so exponentiate to get daily price multipliers.
        gasreg_price_log_mult_diffs = (
            alpha
            + beta_cdd * cdd_daily_gasreg[gasreg]
            + beta_hdd * hdd_daily_gasreg[gasreg]
            + month_effects.values
        )
        gasreg_price_multipliers = np.exp(gasreg_price_log_mult_diffs)
        # Divide each multiplier by the annual average of the multipliers
        # to ensure a mean of 1 (so that the year-round average gas price
        # doesn't change). 
        gasreg_price_multipliers = gasreg_price_multipliers.div(
            gasreg_price_multipliers.groupby(level=0).mean()
        )
        df_out[gasreg] = gasreg_price_multipliers

    # Get hierarchy
    hierarchy = reeds.io.get_hierarchy(os.path.dirname(inputs_case))

    # Create one set of multipliers at the r hierarchy level
    # by copying the gasreg-level multipliers to their constitutent zones
    df_out_r = pd.DataFrame(data={
        r: df_out[gasreg] for r, gasreg in hierarchy['gasreg'].items()
    })

    breakpoint()

    # Create another set of multipliers for census divisions by aggregating
    # the gasreg-level multipliers via population-weighted average
    gasreg_cendiv_weights = calculate_region_aggregion_population_weights(
        inputs_case,
        region_level='gasreg',
        aggregion_level='cendiv'
    )
    gasreg_cendiv_map = dict(zip(hierarchy['gasreg'], hierarchy['cendiv']))
    df_out_cendiv = (
        df_out.mul(gasreg_cendiv_weights, level=0)
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
daily_gasprice_multipliers_r, daily_gasprice_multipliers_cendiv = (
    calculate_daily_gasprice_multipliers(reeds_path, inputs_case)
)


#%%###################
### Data Write-Out ###
######################

fuel.to_csv(os.path.join(inputs_case,'fprice.csv'),index=False)
ngprice_cendiv.to_csv(os.path.join(inputs_case,'gasprice_ref.csv'))
reeds.io.write_profile_to_h5(
    daily_gasprice_multipliers_r,
    'daily_gasprice_multipliers_r.h5',
    inputs_case
)
reeds.io.write_profile_to_h5(
    daily_gasprice_multipliers_cendiv,
    'daily_gasprice_multipliers_cendiv.h5',
    inputs_case
)

ngdemand.to_csv(os.path.join(inputs_case,'ng_demand_elec.csv'))
ngtotdemand.to_csv(os.path.join(inputs_case,'ng_demand_tot.csv'))
alpha.to_csv(os.path.join(inputs_case,'alpha.csv'))

reeds.log.toc(tic=tic, year=0, process='input_processing/fuelcostprep.py', 
    path=os.path.join(inputs_case,'..'))

print('Finished fuelcostprep.py')
