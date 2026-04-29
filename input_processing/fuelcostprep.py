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
import h5py
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

def get_degree_days(case, base_temp_c=18.3333333333, hourly_formula=False):
    """
    Return daily HDD/CDD by gasreg for the modeled years in this case,
    using temperature shapes from GSw_HourlyWeatherYears and annual totals
    from gasreg_hdd.csv / gasreg_cdd.csv.
    """
    case = reeds.io.standardize_case(case)
    inputs_case = os.path.join(case, 'inputs_case')
    sw = reeds.io.get_switches(case)

    # modeled years for outputs
    model_years = reeds.io.get_years(case)
    model_years = np.array([y for y in model_years if y <= int(sw.endyear)], dtype=int)

    # weather years for temperature shapes
    weather_years = np.array(
        [int(y) for y in str(sw.GSw_HourlyWeatherYears).split('_') if str(y).strip()],
        dtype=int,
    )

    # annual gasreg totals (read from inputs_case to pick up forecasted values)
    ddh = pd.read_csv(
        os.path.join(inputs_case, 'gasreg_hdd.csv'),
        index_col=0,
    )
    ddc = pd.read_csv(
        os.path.join(inputs_case, 'gasreg_cdd.csv'),
        index_col=0,
    )
    ddh.index = ddh.index.astype(int)
    ddc.index = ddc.index.astype(int)

    ddh = ddh.loc[ddh.index.intersection(model_years)].copy()
    ddc = ddc.loc[ddc.index.intersection(model_years)].copy()

    # state -> gasreg mapping
    state_groups = pd.read_csv(
        os.path.join(reeds_path, 'inputs', 'zones', 'state_groups.csv')
    )
    st2gasreg = state_groups.set_index('st')['gasreg']

    # valid states in this case
    val_st = (
        pd.read_csv(os.path.join(inputs_case, 'val_st.csv'), header=None)
        .squeeze(1)
        .astype(str)
        .values
    )
    valid_states = [s for s in val_st if s in st2gasreg.index]

    # state population
    pop = pd.read_csv(
        os.path.join(reeds_path, 'inputs', 'disaggregation', 'county_population.csv'),
        dtype={'FIPS': str},
    ).rename(columns={'value': 'population'})

    county_state = pd.read_csv(
        os.path.join(reeds_path, 'inputs', 'zones', 'county_state.csv'),
        dtype={'FIPS': str, 'state': str},
    )
    county_state['FIPS'] = 'p' + county_state['FIPS'].str.zfill(5)

    pop_state = (
        pop.merge(county_state[['FIPS', 'state']], on='FIPS', how='left')
        .rename(columns={'state': 'st'})
        .dropna(subset=['st'])
        .groupby('st', as_index=True)['population']
        .sum()
        .rename_axis('st')
        .rename('population')
        .to_frame()
    )

    pop_state = pop_state.loc[pop_state.index.intersection(valid_states)].copy()
    pop_state['gasreg'] = pop_state.index.map(st2gasreg)

    active_gasregs = sorted(pop_state['gasreg'].dropna().unique())

    pop_state['weight'] = (
        pop_state['population']
        / pop_state.groupby('gasreg')['population'].transform('sum')
    )

    # read temperature file using one extra year on each side
    h5path = os.path.join(
        reeds.io.reeds_path, 'inputs', 'profiles_temperature', 'temperature_state.h5'
    )

    read_years = range(weather_years.min() - 1, weather_years.max() + 2)

    temp_dict = {}
    with h5py.File(h5path, 'r') as f:
        cols = pd.Series(f['columns']).map(lambda x: x.decode()).tolist()

        for year in read_years:
            if str(year) not in f:
                continue

            timeindex = pd.to_datetime(
                pd.Series(f[f'index_{year}'][:]).str.decode('utf-8')
            )

            temp_dict[year] = pd.DataFrame(
                index=timeindex,
                columns=cols,
                data=f[str(year)][:]
            )

    temp = (
        pd.concat(temp_dict, names=['weather_year', 'timestamp'])
        .rename_axis(columns='st')
        .round(0)
        .astype(float)
        .reset_index('weather_year', drop=True)
        .tz_localize('UTC')
        .tz_convert('Etc/GMT+6')
    )

    # subset to selected weather years after timezone conversion
    temp = temp.loc[temp.index.year.isin(weather_years)].copy()


    # keep valid states only
    temp = temp[[c for c in temp.columns if c in valid_states]].copy()

    if hourly_formula:
        hdd = (base_temp_c - temp).clip(lower=0)
        cdd = (temp - base_temp_c).clip(lower=0)

        hdd_daily_st = hdd.resample('D').sum()
        cdd_daily_st = cdd.resample('D').sum()
    else:
        temp_daily_st = temp.resample('D').agg(['min', 'max'])

        tavg_daily_st = (
            temp_daily_st.xs('min', axis=1, level=1)
            + temp_daily_st.xs('max', axis=1, level=1)
        ) / 2

        hdd_daily_st = (base_temp_c - tavg_daily_st).clip(lower=0)
        cdd_daily_st = (tavg_daily_st - base_temp_c).clip(lower=0)

    # weighted aggregation to gasreg
    state_weights = pop_state['weight'].to_dict()
    state_gasreg = pop_state['gasreg'].to_dict()

    hdd_daily_reg = pd.concat(
        {
            st: hdd_daily_st[st] * state_weights[st]
            for st in hdd_daily_st.columns
            if st in state_weights
        },
        axis=1,
    )
    hdd_daily_reg.columns = [state_gasreg[st] for st in hdd_daily_reg.columns]
    hdd_daily_reg = hdd_daily_reg.groupby(level=0, axis=1).sum()
    hdd_daily_reg = hdd_daily_reg[[c for c in hdd_daily_reg.columns if c in active_gasregs]]

    cdd_daily_reg = pd.concat(
        {
            st: cdd_daily_st[st] * state_weights[st]
            for st in cdd_daily_st.columns
            if st in state_weights
        },
        axis=1,
    )
    cdd_daily_reg.columns = [state_gasreg[st] for st in cdd_daily_reg.columns]
    cdd_daily_reg = cdd_daily_reg.groupby(level=0, axis=1).sum()
    cdd_daily_reg = cdd_daily_reg[[c for c in cdd_daily_reg.columns if c in active_gasregs]]

    # normalize daily shapes within each weather year
    hdd_shape = hdd_daily_reg.div(
        hdd_daily_reg.groupby(hdd_daily_reg.index.year).transform('sum')
    )
    cdd_shape = cdd_daily_reg.div(
        cdd_daily_reg.groupby(cdd_daily_reg.index.year).transform('sum')
    )

    hdd_shape['month'] = hdd_shape.index.month
    hdd_shape['day'] = hdd_shape.index.day
    cdd_shape['month'] = cdd_shape.index.month
    cdd_shape['day'] = cdd_shape.index.day

    hdd_md = hdd_shape.groupby(['month', 'day'])[active_gasregs].mean()
    cdd_md = cdd_shape.groupby(['month', 'day'])[active_gasregs].mean()

    # expand to model years and scale to annual gasreg totals
    out = []

    for t in model_years:
        idx = pd.date_range(f'{t}-01-01', f'{t}-12-31', freq='D')

        # only needed if model year is leap year, exclude dec 31st and keep Feb 29th
        if len(idx) > 365:
            idx = idx[~((idx.month == 12) & (idx.day == 31))]
        # 365-day calendar excludes Feb 29
        else:
            #Make sure to exclude Feb 29 even if we don't expect it to be present
            idx = idx[~((idx.month == 2) & (idx.day == 29))]


        hdd_t = pd.DataFrame(index=idx, columns=active_gasregs, dtype=float)
        cdd_t = pd.DataFrame(index=idx, columns=active_gasregs, dtype=float)

        for dt in idx:
            key = (dt.month, dt.day)
            hdd_t.loc[dt] = hdd_md.loc[key].values
            cdd_t.loc[dt] = cdd_md.loc[key].values

        hdd_t = hdd_t.mul(ddh.loc[t, active_gasregs], axis=1)
        cdd_t = cdd_t.mul(ddc.loc[t, active_gasregs], axis=1)

        hdd_t['t'] = t
        cdd_t['t'] = t
        hdd_t['ddtype'] = 'hdd'
        cdd_t['ddtype'] = 'cdd'

        out.append(hdd_t.reset_index().rename(columns={'index': 'date'}))
        out.append(cdd_t.reset_index().rename(columns={'index': 'date'}))

    daily_dds = pd.concat(out, ignore_index=True)
    return daily_dds

# Regression parameters for calculating natural gas price differences across regions based on degree days
params = pd.read_csv(os.path.join(reeds_path,'inputs', 'fuelprices', 'temperature_price_regression_parameters.csv'), index_col='param')

# Daily degree days by price region
daily_dd = get_degree_days(inputs_case, hourly_formula=False)

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

out_year = hdd['t'].where(hdd['t'].notna(), cdd['t'])
if out_year.isna().any():
    raise ValueError('Missing weather year for one or more natural gas price diff dates')

out_datetime = out.index
if out_datetime.tz is None:
    out_datetime = out_datetime.tz_localize('Etc/GMT+6')

out = out.astype(np.float32)
out.index = pd.MultiIndex.from_arrays(
    [out_year.astype(np.int32), out_datetime],
    names=['year', 'datetime'],
)
out = out.sort_index()
reeds.io.write_profile_to_h5(out, 'natgas_price_diffs.h5', inputs_case)


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
