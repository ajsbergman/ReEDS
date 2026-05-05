#%% ===========================================================================
### --- IMPORTS ---
### ===========================================================================

import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import os
import sys
import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
import reeds
tic = datetime.datetime.now()

#%% Parse arguments
parser = argparse.ArgumentParser(description="Format and write climate inputs")
parser.add_argument('reeds_path', help='ReEDS directory')
parser.add_argument('inputs_case', help='output directory (inputs_case)')

args = parser.parse_args()
reeds_path = args.reeds_path
inputs_case = args.inputs_case

# #%% Settings for testing ###
# reeds_path = reeds.io.reeds_path
# inputs_case = str(Path(reeds_path,'runs','v20260420_transcostM0_Pacific','inputs_case'))


#%%#################
### FIXED INPUTS ###
decimals = 5
input_dollar_year = pd.read_csv(
    Path(reeds_path, 'inputs', 'transmission', 'dollaryear.csv'), index_col=0,
).squeeze(1)


#%% ===========================================================================
### --- FUNCTIONS ---
### ===========================================================================
def get_trancap_init(case, networksource='NARIS2024', level='r'):
    """
    AC capacity is defined for each direction and calculated using the scripts at
    https://github.nrel.gov/ReEDS/TSC
    """
    sw = reeds.io.get_switches(case)
    trancap_init_ac = (
        reeds.inputs.get_itls(case, level=level, GSw_ZoneSet=sw.GSw_ZoneSet)
        [['r', 'rr', 'MW_forward', 'MW_reverse']]
        .assign(trtype='AC')
    )
    ### DEPRECATED: p19 is islanded with NARIS transmission data, so connect it manually
    if (
        (networksource == 'NARIS2024')
        and (level != 'transgrp')
        and ('p19' in valid_regions['r'])
        and ('p20' in valid_regions['r'])
    ):
        trancap_init_ac = pd.concat([
            trancap_init_ac,
            pd.Series({
                'r':'p19',
                'rr':'p20',
                'MW_forward':0.001,
                'MW_reverse':0.001,
                'trtype':'AC',
            }).to_frame().T
        ], ignore_index=True)

    ### DC
    if level == 'r':
        ## transgrp capacity is only defined for AC
        hvdc = (
            reeds.inputs.map_hvdc_lines_to_interfaces(case, filename='hvdc_lines.csv')
            .reset_index()
        )
        b2b = reeds.inputs.get_b2b(case).assign(trtype='B2B')
        ## DC capacity is only defined in one direction,
        ## so duplicate it for the opposite direction
        trancap_init_nonac_undup = pd.concat([hvdc, b2b])[['r', 'rr', 'trtype', 'MW']]
        trancap_init_nonac = pd.concat([
            trancap_init_nonac_undup,
            trancap_init_nonac_undup.rename(columns={'r':'rr', 'rr':'r'})
        ], axis=0)
    else:
        trancap_init_nonac = pd.DataFrame(columns=['r', 'rr', 'trtype', 'MW'])

    ### Initial trading limit, using contingency levels specified by contingency level
    ### (but assuming full capacity of DC is available for both energy and capcity)
    dfout = (
        pd.concat(
            [
                ## AC
                pd.concat([
                    ## Forward direction
                    (trancap_init_ac[['r', 'rr', 'trtype', 'MW_forward']]
                    .rename(columns={'MW_forward':'MW'})),
                    ## Reverse direction
                    (trancap_init_ac[['r', 'rr', 'trtype', 'MW_reverse']]
                    .rename(columns={'r':'rr', 'rr':'r', 'MW_reverse':'MW'}))
                ], axis=0),
                ## DC
                trancap_init_nonac[['r', 'rr', 'trtype', 'MW']]
            ],
            axis=0
        )
        ## Drop entries with zero capacity
        .replace(0.,np.nan).dropna()
        .groupby(['r', 'rr', 'trtype']).sum().reset_index()
    )
    dfout = dfout.loc[
        dfout['r'].isin(valid_regions[level])
        & dfout['rr'].isin(valid_regions[level])
    ].copy()
    
    ## Get alias for level (e.g. rr, transgrpp)
    levell = level + level[-1]
    return dfout.rename(columns={'r':level, 'rr':levell})


def get_firm_import_limit(inputs_case):
    """Limits on PRMTRADE across nercr boundaries"""
    sw = reeds.io.get_switches(inputs_case)
    if not int(sw.GSw_PRM_NetImportLimit):
        ## No limit
        firm_import_limit = pd.DataFrame(columns=['*nercr','t','fraction']).set_index(['*nercr','t'])
    else:
        limits = pd.Series(
            {int(i.split('_')[0]): i.split('_')[1] for i in sw.GSw_PRM_NetImportLimitScen.split('/')}
        )

        solveyears = pd.read_csv(
            os.path.join(inputs_case,'modeledyears.csv')
        ).columns.astype(int).tolist()
        startyear = min(solveyears)
        endyear = max(solveyears)
        allyears = range(startyear, max(endyear, limits.index.max())+1)

        ## calculate the historical net_firm_import fraction for each region and drop negative values
        peak_net_imports = pd.read_csv(
            os.path.join(inputs_case,'peak_net_imports.csv'),
            index_col=['nercr']
        )
        net_firm_import_frac = (
            peak_net_imports.MW / peak_net_imports.MW_TotalDemand
        ).clip(lower=0)
        nercrs = net_firm_import_frac.index

        _dfout = {}
        for key, val in limits.items():
            ## If 'hist' is in GSw_PRM_NetImportLimitScen,
            ## all years up until that year use the historical regional max
            if val == 'hist':
                for y in range(startyear, key+1):
                    _dfout[y] = net_firm_import_frac
            ## If 'histmax', all prior years use the historical max across all regions
            elif val == 'histmax':
                for y in range(startyear, key+1):
                    _dfout[y] = net_firm_import_frac.clip(lower=net_firm_import_frac.max())
            else:
                ## Input values are percentages so convert to fractions
                _dfout[key] = pd.Series(index=nercrs, data=float(val) / 100)

        firm_import_limit = (
            pd.concat(_dfout, names=('t',)).unstack('nercr')
            ## Linear interpolation between values; flat projections before and after
            .reindex(allyears).interpolate('linear').bfill().ffill()
            .loc[solveyears]
            .unstack('t').rename('fraction').rename_axis(['*nercr','t'])
        )

    return firm_import_limit


def convert_to_tsc(interface_params, dollar_year=2004):
    transmission_cost_ac = interface_params.loc[
        interface_params.trtype=='AC',
        ['r', 'rr', f'USD{dollar_year}perMW']
    ].copy()
    transmission_cost_ac = (
        transmission_cost_ac
        .rename(columns={f'USD{dollar_year}perMW':f'USD{dollar_year}perMW_forward'})
        .assign(**{f'USD{dollar_year}perMW_reverse':transmission_cost_ac[f'USD{dollar_year}perMW']})
        .assign(tscbin='t0')
        .assign(**{f'binwidth_USD{dollar_year}':1e12})
        .rename(columns={})
        [[
            'r', 'rr', 'tscbin', f'binwidth_USD{dollar_year}',
            f'USD{dollar_year}perMW_forward', f'USD{dollar_year}perMW_reverse',
        ]]
    )
    _test = transmission_cost_ac.r < transmission_cost_ac.rr
    if not _test.all():
        print(transmission_cost_ac.loc[~_test])
        raise ValueError('Region must be lexicographically sorted so r < rr')
    return transmission_cost_ac


def calculate_adjacent_routes(dfzones):
    routes_adjacent = dfzones.copy()
    routes_adjacent['r_adj'] = routes_adjacent.apply(
        axis=1,
        func=lambda x: (
            routes_adjacent.loc[(
                routes_adjacent.touches(x['geometry'])
                | routes_adjacent.overlaps(x['geometry'])
            )]
            .index
            .values
            .tolist()
        )
    )
    # Reformat so that each row represents a pair of regions
    routes_adjacent = (
        routes_adjacent.drop(columns='geometry')
        .explode('r_adj')
        .reset_index(names=['r'])
        .rename(columns={'r': '*r', 'r_adj': 'rr'})
        [['*r', 'rr']]
        .dropna()
    )

    return routes_adjacent


def calculate_co2_storage_routes(dfzones, co2_storage_sites):
    # Determine the storage sites that are within 200 miles
    # of each region's transmission endpoint
    region_centroids = (
        gpd.GeoDataFrame(
            dfzones[['x', 'y']],
            geometry=gpd.points_from_xy(dfzones.x, dfzones.y),
            crs=dfzones.crs
        )
        [['geometry']]
        .rename_axis(index='*r')
        .reset_index()
    )
    region_centroids['cs'] = region_centroids.apply(
        axis=1,
        func=lambda x: (
            co2_storage_sites.loc[(
                co2_storage_sites.distance(x['geometry']) / 1609.34 <= 200
            )]
            ['cs']
            .tolist()
        )
    )

    # Calculate the lengths of the spurlines between regions and storage sites,
    # excluding routes not completely within the U.S.
    routes_cs = (
        region_centroids.explode('cs')
        .merge(
            co2_storage_sites[['cs', 'geometry']],
            on='cs',
            suffixes=('_region', '_site')
        )
        .assign(
            geometry=lambda x: (
                gpd.GeoSeries(x['geometry_region'])
                .shortest_line(gpd.GeoSeries(x['geometry_site']))
            )
        )
        [['*r', 'cs', 'geometry']]
    )
    routes_cs = gpd.GeoDataFrame(routes_cs, geometry='geometry', crs=dfzones.crs)
    routes_cs = routes_cs.loc[(
        routes_cs.within(
            reeds.io.get_dfmap(levels=['country'])['country'].loc['USA','geometry']
        )
        | (routes_cs.length == 0)
    )]
    routes_cs['distance_m'] = routes_cs.length
    routes_cs['miles'] = (routes_cs['distance_m'] / 1609.34).round(2)

    return routes_cs


#%% ===========================================================================
### --- PROCEDURE ---
### ===========================================================================

#%% Set up logger
log = reeds.log.makelog(
    scriptname=__file__,
    logpath=os.path.join(inputs_case,'..','gamslog.txt'),
)
print('Starting transmission.py', flush=True)


#%% Inputs from switches
sw = reeds.io.get_switches(inputs_case)

## networksource must end in a 4-digit year indicating the year represented by the network
trans_init_year = int(sw.GSw_TransNetworkSource[-4:])

valid_regions = {}
for level in ['r','itlgrp','transgrp']:
    valid_regions[level] = pd.read_csv(
        os.path.join(inputs_case, f'val_{level}.csv'), header=None).squeeze(1).tolist()


#%% Limits on PRMTRADE across nercr boundaries
firm_import_limit = get_firm_import_limit(inputs_case)
firm_import_limit.to_csv(os.path.join(inputs_case, 'firm_import_limit.csv'))


#%% Load the transmission scalars
case = Path(inputs_case).parent
scalars = reeds.io.get_scalars(inputs_case)
### Put some in dicts for easier access
## B2B converters are AC-AC/DC-DC/AC-AC, so use AC per-mile losses
trtypes = {'AC':'ac', 'B2B':'ac', 'LCC':'dc', 'VSC':'dc'}
tranloss_permile = {
    trtype: scalars[f'tranloss_permile_{polarity}'] for trtype, polarity in trtypes.items()
}
tranloss_fixed = {
    'AC': 1 - scalars['converter_efficiency_ac'],
    'B2B': 1 - scalars['converter_efficiency_lcc'],
    'LCC': 1 - scalars['converter_efficiency_lcc'],
    'VSC': 1 - scalars['converter_efficiency_vsc'],
}


#%% Get single-link distances and losses
interface_params = reeds.inputs.get_distances(case)
interface_params['r_rr'] = interface_params.r + '_' + interface_params.rr

## Calculate $/MW
_line_params = {
    polarity: pd.read_csv(
        Path(reeds_path, 'inputs', 'transmission', f'conductor_{polarity}.csv'),
        index_col='voltage_kv',
    )
    for polarity in ['ac', 'dc']
}
_line_params['ac']['MW'] = _line_params['ac']['MVA'] * scalars['power_factor_ac']
line_params = pd.concat(_line_params, names=('polarity','voltage')).MW
interface_params = interface_params.merge(line_params, on=['polarity','voltage'], how='left')

## Convert to output dollaryear
inflatable = reeds.io.get_inflatable()
deflator = inflatable[input_dollar_year['transmission_cost_distance.csv'], int(sw.dollar_year)]
interface_params[f'USD{sw.dollar_year}perMW'] = (
    interface_params['cost_MUSD'] * 1e6
    / interface_params['MW']
    * deflator
)
interface_params[f'USD{sw.dollar_year}perMWmile'] = (
    interface_params[f'USD{sw.dollar_year}perMW']
    / interface_params['length_miles']
)
interface_params[f'USD{sw.dollar_year}perMile'] = (
    interface_params['cost_MUSD'] * 1e6 / interface_params['length_miles']
)

## Apply the distance multiplier
interface_params['miles'] = interface_params['length_miles'] * float(sw.GSw_TransSquiggliness)

## Make sure there are no duplicates
if interface_params[['r','rr','polarity']].duplicated().sum():
    print(
        interface_params.loc[
            interface_params[['r','rr','polarity']].duplicated(keep=False)
        ].sort_values(['r','rr','polarity'])
    )
    raise Exception('Duplicate entries in transmission_distance.csv')

### Calculate losses
def getloss(row):
    """
    Fixed losses are entered as per-endpoint values (e.g. for each AC/DC converter station
    on a LCC DC line). There are two endpoints per line, so multiply fixed losses by 2.
    Note that this approach only applies for LCC DC lines; VSC AC/DC losses are applied later.
    """
    return row.miles * tranloss_permile[row.trtype] + tranloss_fixed[row.trtype] * 2

interface_params = pd.concat({
    trtype: interface_params.loc[interface_params.polarity == polarity]
    for trtype, polarity in trtypes.items()
}, names=('trtype', 'drop')).reset_index().drop(columns=['drop'])
interface_params['loss'] = interface_params.apply(lambda row: getloss(row), axis=1)


#%% Include distances for existing lines
transmission_distance = interface_params.miles.copy()

#%% Write the line-specific transmission FOM costs [$/MW/year]
trans_fom_region_mult = int(scalars['trans_fom_region_mult'])
trans_fom_frac = scalars['trans_fom_frac']

### For simplicity we just take the unweighted average greenfield $/MWmile cost
### across all interfaces.
### Future work should identify a better assumption.
transfom_USDperMWmileyear = (
    interface_params.groupby('trtype')[f'USD{sw.dollar_year}perMWmile'].mean()
    * trans_fom_frac
)

### Multiply $/MW/mile/year by distance [miles] to get $/MW/year for ALL lines
transmission_line_fom = interface_params.copy()
transmission_line_fom['USDperMWyear'] = transmission_line_fom.apply(
    lambda row: transfom_USDperMWmileyear[row.trtype] * row.miles,
    axis=1
)
transmission_line_fom = transmission_line_fom.set_index(['r','rr','trtype']).USDperMWyear


#%%### Write files for ReEDS (adding * to make GAMS read column names as comment)
### transmission_distance
transmission_distance.round(3).reset_index().rename(columns={'r':'*r'}).to_csv(
    os.path.join(inputs_case,'transmission_miles.csv'), index=False)

### tranloss
tranloss = interface_params['loss'].reset_index()
tranloss.round(decimals).rename(columns={'r':'*r'}).to_csv(
    os.path.join(inputs_case,'tranloss.csv'), index=False, header=True)

### transmission_line_fom
transmission_line_fom.round(2).rename_axis(('*r','rr','trtype')).to_csv(
    os.path.join(inputs_case,'transmission_line_fom.csv'))

#%% Write the initial capacities
trancap_init = {}
for captype, level in [
    ('energy', 'r'),
    ('transgroup', 'transgrp'),
]:
    trancap_init[captype] = get_trancap_init(
        case=case, networksource=sw.GSw_TransNetworkSource, level=level)
    ### TEMPORARY 20260402: Drop county interfaces with no distance/cost
    if (level == 'r') and (sw.GSw_RegionResolution in ['county', 'mixed']):
        indices = ['r', 'rr', 'trtype']
        drop = (
            trancap_init[captype]
            .merge(transmission_line_fom.reset_index(), on=indices, how='left')
        )
        drop = list(drop.loc[drop.USDperMWyear.isnull(), indices].itertuples(index=False))
        trancap_init[captype] = trancap_init[captype].set_index(indices).drop(drop).reset_index()
    trancap_init[captype].rename(columns={level:'*'+level}).round(3).to_csv(
        os.path.join(inputs_case,f'trancap_init_{captype}.csv'),
        index=False,
    )
trancap_init['energy'].rename(columns={'r':'*r'}).round(3).to_csv(
    os.path.join(inputs_case,'trancap_init_prm.csv'),
    index=False,
)
### TEMPORARY 20260402: Skip itlgrp functionality until we fix it
# ### Also write itlgrp capacity
# trancap_itlgrp = trancap_init['energy'].copy()
# ## Map counties to itlgrp's
# hierarchy_itlgrp = pd.read_csv(os.path.join(inputs_case, 'hierarchy_itlgrp.csv'))
# itl_d = dict(zip(hierarchy_itlgrp['*r'], hierarchy_itlgrp['itlgrp']))
# for r in ['r', 'rr']:
#     trancap_itlgrp[r] = trancap_itlgrp[r].map(lambda x: itl_d.get(x,x))
# trancap_itlgrp.rename(columns={'r':'*itlgrp', 'rr':'itlgrpp'}).round(3).to_csv(
#     os.path.join(inputs_case, 'trancap_init_itlgrp.csv'),
#     index=False,
# )


#%%### Future transmission capacity
## note that '0' is used as a filler value in the t column for firstyear_trans, which is defined
## in inputs/scalars.csv. So we replace it whenever we load a transmission_capacity_future file.
planned_capacity = reeds.inputs.map_hvdc_lines_to_interfaces(
    case=case, filename='planned_lines-baseline.csv',
)
if sw.GSw_TransScen != 'none':
    planned_capacity = pd.concat([
        planned_capacity,
        reeds.inputs.map_hvdc_lines_to_interfaces(
            case=case, filename=f'planned_lines-{sw.GSw_TransScen}.csv',
        )
    ])

trancap_fut = (
    planned_capacity.reset_index()
    .rename(columns={'year_online':'t', 'certain':'status'})
    .astype({'t':int})
    .replace({
        't': {0: int(scalars['firstyear_trans_longterm'])},
        'status': {0:'possible', 1:'certain'}
    })
    [['r', 'rr', 'status', 'trtype', 't', 'MW']]
)

trancap_fut.rename(columns={'r':'*r'}).astype({'t':int}).round(3).to_csv(
    os.path.join(inputs_case,'trancap_fut.csv'), index=False)


#%%### Transmission upgrade supply curve
if sw.GSw_TransUpgradeMethod == 'greenfield':
    transmission_cost_ac = convert_to_tsc(interface_params, sw.dollar_year)
else:
    fpath = Path(
        reeds.io.reeds_path, 'inputs', 'transmission',
        f'transmission_cost_ac_{sw.GSw_TransUpgradeMethod}_{sw.GSw_ZoneSet}.h5'
    )
    transmission_cost_ac = reeds.io.read_file(fpath).reset_index()
    for col in ['r', 'rr', 'tscbin']:
        transmission_cost_ac[col] = transmission_cost_ac[col].str.decode('utf-8')
### Interfaces are always defined with the zones sorted in lexicographic order
reverse_interfaces = transmission_cost_ac.loc[
    transmission_cost_ac.apply(lambda row: row.r > row.rr, axis=1)
]
for i, row in reverse_interfaces.iterrows():
    transmission_cost_ac.loc[i, ['r', 'rr']] = transmission_cost_ac.loc[i, ['rr', 'r']].values
    transmission_cost_ac.loc[i, ['USD2004perMW_forward', 'USD2004perMW_reverse']] = (
        transmission_cost_ac.loc[i, ['USD2004perMW_reverse', 'USD2004perMW_forward']].values
    )

_test = transmission_cost_ac.apply(lambda row: row.r < row.rr, axis=1)
if not _test.all():
    print(transmission_cost_ac.loc[~_test])
    err = (
        "Must have r < rr in AC transmission cost inputs but the interfaces "
        "listed above are out of order"
    )
    raise ValueError(err)

labels = {
    'binwidth_USD2004': 'binwidth',
    'USD2004perMW_forward': 'forward',
    'USD2004perMW_reverse': 'reverse',
}
for col, label in labels.items():
    transmission_cost_ac[['r','rr','tscbin',col]].rename(columns={'r':'*r'}).round(2).to_csv(
        os.path.join(inputs_case, f'tsc_{label}.csv'),
        index=False,
    )
transmission_cost_ac.tscbin.drop_duplicates().to_csv(
    os.path.join(inputs_case, 'tscbin.csv'),
    index=False,
    header=False,
)


#%% DC and B2B per-mile costs use greenfield assumptions
costcol = f'USD{sw.dollar_year}perMW'
transmission_cost_nonac = interface_params.loc[
    interface_params.trtype != 'AC',
    ['r', 'rr', 'trtype', costcol]
]

transmission_cost_nonac.rename(columns={'r':'*r'}).round(2).to_csv(
    os.path.join(inputs_case, 'transmission_cost_nonac.csv'),
    index=False,
)


#%%### Hurdle rates
hurdle_levels = [1, 2]
cost_hurdle_intra = (
    pd.read_csv(os.path.join(inputs_case, 'cost_hurdle_intra.csv'))
    .rename(columns={'t':'*t'}).set_index('*t').round(3)
)
cost_hurdle_rate = {
    i: (
        cost_hurdle_intra[sw[f'GSw_TransHurdleLevel{i}']] if int(sw.GSw_TransHurdleRate)
        else pd.Series(name='region').rename_axis('*t')
    )
    for i in hurdle_levels
}
for i in hurdle_levels:
    cost_hurdle_rate[i].to_csv(os.path.join(inputs_case, f'cost_hurdle_rate{i}.csv'))


#%%### H2 pipeline cost multipliers
# Calculate H2 pipeline cost multipliers by dividing the [$/mile] cost of DC transmission
# between each pair of regions by the minimum interface [$/mile] cost for DC transmission
# and subtracting 1 to get a fractional adder (which is then added to 1 in b_inputs.gms)
fpath = os.path.join(inputs_case, 'pipeline_cost_mult.csv')
if len(transmission_cost_nonac):
    dc_cost_permile = (
        interface_params.loc[interface_params.trtype=='VSC']
        .set_index(['r','rr'])[f'USD{sw.dollar_year}perMile']
    )
    pipeline_cost_mult = dc_cost_permile.rename('multiplier') / dc_cost_permile.min() - 1

    pipeline_cost_mult.reset_index().rename(columns={'r':'*r'}).round(3).to_csv(
        fpath,
        index=False,
    )
else:
    pd.DataFrame(columns=['*r','rr','multiplier']).to_csv(fpath, index=False)


#%%### Adjacent regions
# Get model regions
dfzones = reeds.io.get_dfmap(
    os.path.dirname(inputs_case),
    levels=['r'],
    exclude_water_areas=True
)['r']
# Determine which pairs of model regions are adjacent to each other
routes_adjacent = calculate_adjacent_routes(dfzones)
routes_adjacent.to_csv(
    os.path.join(inputs_case,'routes_adjacent.csv'),
    index=False
)

#%%### CO2 storage sites
# Determine spurline routes from model regions to carbon storage sites
co2_storage_sites = reeds.io.get_co2_storage_sites()
routes_cs = calculate_co2_storage_routes(dfzones, co2_storage_sites)
routes_cs[['*r', 'cs']].to_csv(
    os.path.join(inputs_case, 'r_cs.csv'), index=False
)
routes_cs[['*r', 'cs', 'miles']].to_csv(
    os.path.join(inputs_case,'r_cs_distance_mi.csv'),
    index=False
)

# Determine sites that have valid routes to model regions
val_cs = pd.Series(routes_cs['cs'].unique())
val_cs.to_csv(os.path.join(inputs_case, 'val_cs.csv'), header=False, index=False)

# Subset CO2 site characteristics data to valid sites
co2_site_char = pd.read_csv(os.path.join(inputs_case, 'co2_site_char.csv'))
co2_site_char = co2_site_char.loc[co2_site_char['cs'].isin(val_cs)]
co2_site_char.to_csv(os.path.join(inputs_case, 'co2_site_char.csv'), index=False)

# Create WKT file of region-to-site spurlines
r_cs_spurlines = (
    routes_cs.loc[routes_cs['distance_m'] > 0]
    .rename(columns={'*r': 'ba_str', 'cs': 'FmnID'})
    .to_crs('EPSG:4326')
    .assign(WKT=lambda x: x['geometry'].to_wkt())
    [['ba_str', 'FmnID', 'distance_m', 'WKT']]
)
r_cs_spurlines.to_csv(
    os.path.join(inputs_case,'ctus_r_cs_spurlines_200mi.csv'),
    index=False
)


#%% Finish the timer
reeds.log.toc(tic=tic, year=0, process='input_processing/transmission.py',
    path=os.path.join(inputs_case,'..'))
print('Finished transmission.py', flush=True)
