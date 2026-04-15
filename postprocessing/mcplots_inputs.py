#%%### Imports
import os
import sys
import cmocean
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patheffects as pe

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import reeds

reeds.plots.plotparams()


#%%### Inputs
if sys.platform == 'darwin':
    projpath = os.path.expanduser('~/Projects/Uncertainty')
    runspath = os.path.join(projpath, 'runs', '20250829')
else:
    projpath = '/projects/uncertainty'
    runspath = os.path.join(reeds.io.reeds_path, 'runs')

savepath = os.path.join(projpath,'figures','intro')
os.makedirs(savepath, exist_ok=True)

cases = {
    'low': os.path.join(runspath, 'v20251117_mcK0_intro_Low'),
    'mid': os.path.join(runspath, 'v20251117_mcK0_intro_Mid'),
    'high': os.path.join(runspath, 'v20251117_mcK0_intro_High'),
}

#%%### Functions
def pert(low, mid, high, samples=1, lamb=4):
    """https://stackoverflow.com/questions/68476485/random-values-from-a-pert-distribution-in-python"""
    r = high - low
    alpha = 1 + lamb * (mid - low) / r
    beta = 1 + lamb * (high - mid) / r
    return low + np.random.beta(alpha, beta, size=samples) * r


def triangular(low, mid, high, samples=1):
    """https://numpy.org/doc/stable/reference/random/generated/numpy.random.triangular.html"""
    return np.random.triangular(left=low, mode=mid, right=high, size=samples)


def dirichlet(low, mid, high, probs=[1, 1, 1], samples=1):
    dist = np.random.dirichlet(probs, size=samples)
    return (dist * np.array([low, mid, high])).sum(axis=1)


def dirichlet_lohi(low, high, probs=[1, 1], samples=1):
    dist = np.random.dirichlet(probs, size=samples)
    return (dist * np.array([low, high])).sum(axis=1)


def discrete(low, mid, high, probs=[1, 1, 1], samples=1):
    return np.random.choice([low, mid, high], p=np.array(probs)/sum(probs), size=samples)


#%%### Shared inputs
dfmap = reeds.io.get_dfmap()
hierarchy = reeds.io.get_hierarchy()
inflatable = reeds.io.get_inflatable()
inflator = inflatable[2004,2024]


#%%### Methods overview: Distributions
#%% Compare triangular and flat samples to distributions
np.random.seed(137)
numsamples = 200
samples = range(numsamples)
low = 0
mid = 0.7
high = 1
bins = 21

dfsamples = pd.DataFrame({
    'flat': dirichlet_lohi(low, high, probs=[1, 1], samples=numsamples),
    'triangular': dirichlet(low, mid, high, probs=[1, 1, 1], samples=numsamples),
}, index=samples)

## Plot it
nrows = 1
ncols = 2
plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(3, 1.5), sharex=False, sharey=True,
    gridspec_kw={'wspace':0.4}
)
### Distribution
ax[0].fill_between(
    [low, high], [1, 1], [0, 0], alpha=0.5, color='C0', lw=0,
    label='Distribution',
)
ax[1].fill_between([low, mid, high], [0, 2, 0], [0, 0, 0], alpha=0.5, color='C0', lw=0)
### Samples
for col, key in enumerate(['flat', 'triangular']):
    dfsamples[key].plot.hist(
        ax=ax[col], bins=bins, alpha=0.5, density=True, color='C1',
        label=f'Samples ({numsamples})',
    )
    ax[col].set_xlim(low, high)
    ax[col].set_title(key.title(), weight='bold')
### Formatting
ax[0].set_xticks([low, high])
ax[0].set_xticklabels(
    ['low', 'high'], rotation=45, rotation_mode='anchor', ha='right', va='center')
ax[1].set_xticks([low, mid, high])
ax[1].set_xticklabels(
    ['low', 'mid', 'high'], rotation=45, rotation_mode='anchor', ha='right', va='center')
ax[0].set_yticklabels([])
ax[0].legend(
    loc='upper left', bbox_to_anchor=(-0.05, 1.05),
    frameon=False,
    handletextpad=0.3, handlelength=0.7,
)
reeds.plots.despine(ax)
plt.savefig(os.path.join(savepath, f'distributions-flat,triangular-{numsamples}samples.png'))
plt.show()


#%% Maps showing samples with/without geographic correlation
np.random.seed(314)
numsamples = 4
level = 'st'
df = dfmap[level].copy()
dfplot = {'country': df.copy(), level: df.copy()}
for i in range(numsamples):
    dfplot['country'][f'sample{i}'] = np.random.uniform(low=0, high=1)
    dfplot[level][f'sample{i}'] = np.random.uniform(low=0, high=1, size=len(df))

## Plot it
nrows = 2
ncols = numsamples
scale = 0.7
cmap = plt.cm.RdBu_r
plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(ncols*scale, nrows*scale*0.8), sharex=True, sharey=True,
    gridspec_kw={'hspace':-0.05, 'wspace':-0.05},
)
for row, key in enumerate(['country', level]):
    for col, sample in enumerate([f'sample{i}' for i in range(numsamples)]):
        _ax = ax[row,col]
        dfplot[key].plot(
            ax=_ax, column=sample, cmap=cmap, vmin=0, vmax=1,
        )
        dfmap['country'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.3)
        _ax.axis('off')
## Formatting
cax, hax, cbar = reeds.plots.addcolorbarhist(
    f=f, ax0=ax[0,-1], data=dfplot['country']['sample0'],
    vmin=0, vmax=1, cmap=cmap,
    histratio=0.01, histcolor='w',
    cbarheight=2, cbarwidth=0.1, cbarbottom=-1.025,
)
cax.set_yticks([0,1])
cax.set_yticklabels(['low','high'])
cax.yaxis.set_label_position('right')
cax.yaxis.tick_right()

for row, label in enumerate(['Country', 'State']):
    ax[row,0].annotate(
        label, (-0.05, 0.5), xycoords='axes fraction',
        weight='bold', fontsize='large', ha='right', va='center',
    )
plt.savefig(os.path.join(savepath, f'distributions-country,state-{numsamples}samples.png'))
plt.show()


#%%### State demand
loadscens = {
    'low': 'EER_Baseline_AEO2023',
    'mid': 'EER_IRAlow',
    'high': 'EER_100by2050',
}
scalars = reeds.io.get_scalars()
dictload = {
    key: reeds.io.read_file(
        os.path.join(reeds.io.reeds_path, 'inputs', 'load', f'{val}_load_hourly.h5')
    ).groupby('year').mean() / (1 - scalars['distloss'])
    for key, val in loadscens.items()
}

#%%
dfload = pd.concat(dictload, names=('loadscen',))
dfload.columns = dfload.columns.map(hierarchy.st)
dfload = dfload.groupby(axis=1, level=0).sum() / 1e3

#%%
state_subplot_layout = 'r6c11'
state_subplots = (
    pd.read_csv(
        os.path.join(reeds.io.reeds_path, 'postprocessing', 'plots', 'state_subplots.csv'),
        index_col=[0,1], header=0,
    )
    .loc[state_subplot_layout]
    .stack().rename_axis(['row','col']).rename('state').reset_index().set_index('state')
    .astype({'row':int, 'col':int})
)
state_subplots['ax'] = state_subplots[['row','col']].apply(lambda row: tuple(row), axis=1)

#%% Plot it
nrows = state_subplots['row'].max() + 1
ncols = state_subplots['col'].max() + 1
scale = 0.78
states = sorted(state_subplots.index.tolist())
rs = hierarchy.index.values
years = list(range(2025,2051,5))
color = 'C3'
alpha = 0.25
fontsize = 12

plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(ncols*scale, nrows*scale),
    sharex=False,
    # gridspec_kw={'wspace':0.3},
)
for state in states:
    _ax = ax[state_subplots.loc[state,'ax']]
    df = dfload[state].unstack('loadscen').loc[years]
    _ax.fill_between(
        years, df['high'], df['low'],
        color=color, alpha=alpha, lw=0,
    )
    _ax.plot(years, df['mid'], color=color)
    ## Formatting
    _ax.set_ylim(0)
    _ax.set_yticks([])
    _ax.annotate(
        state,
        (0.05, 0.95), xycoords='axes fraction', ha='left', va='top',
        color='k', fontsize=fontsize,
        path_effects=[pe.withStroke(linewidth=3.0, foreground='w', alpha=0.9)],
        zorder=1e6,
    )
    val = df.loc[min(years), 'mid']
    decimals = 1 if val < 10 else 0
    _ax.annotate(
        f"{val:.{decimals}f}",
        (min(years), val),
        xytext=(12,-5), textcoords='offset points',
        ha='left', va='top', fontsize=fontsize, color='k',
        # arrowprops={'headwidth':2, 'headlength':2, 'color':'k'},
        arrowprops={'arrowstyle':'-|>', 'color':'k', 'shrinkA':0, 'mutation_scale':10},
    )
    if state != 'TX':
        _ax.set_xticklabels([])
## Turn off unused axes
subplots_used = state_subplots['ax'].tolist()
for row in range(nrows):
    for col in range(ncols):
        if (row,col) not in subplots_used:
            ax[row,col].axis('off')
ax[state_subplots.loc['OR','ax']].set_ylabel('Mean demand [GW]')
reeds.plots.despine(ax)
plt.savefig(os.path.join(savepath, 'demand_annual-state-low,mid,high.png'))
plt.show()


#%%### Capacity cost trajectories
# plantchar_battery,,battery_ATB_2024_conservative,battery_ATB_2024_moderate,battery_ATB_2024_advanced
# plantchar_coal_ccs,,coal-ccs_ATB_2024_conservative,coal-ccs_ATB_2024_moderate,coal-ccs_ATB_2024_advanced
# plantchar_gas_ccs,,gas-ccs_ATB_2024_conservative,gas-ccs_ATB_2024_moderate,gas-ccs_ATB_2024_advanced
# plantchar_geo,,geo_ATB_2024_conservative,geo_ATB_2024_moderate,geo_ATB_2024_advanced
# plantchar_nuclear_smr,,nuclear-smr_ATB_2024_conservative,nuclear-smr_ATB_2024_moderate,nuclear-smr_ATB_2024_advanced
# plantchar_nuclear,,nuclear_ATB_2024_conservative,nuclear_ATB_2024_moderate,nuclear_ATB_2024_advanced
# plantchar_ofswind,,ofs-wind_ATB_2024_conservative,ofs-wind_ATB_2024_moderate,ofs-wind_ATB_2024_advanced
# plantchar_onswind,,ons-wind_ATB_2024_conservative,ons-wind_ATB_2024_moderate,ons-wind_ATB_2024_advanced
# plantchar_upv,,upv_ATB_2024_conservative,upv_ATB_2024_moderate,upv_ATB_2024_advanced

## TODO: Include $/kWh cost for batteries and show a specific duration (4 hours)

dictin_cap_cost = {
    key: pd.read_csv(
        os.path.join(case, 'inputs_case', 'plantcharout.csv'),
        index_col=['variable','*i','t'],
    ).loc['capcost'].value.unstack('*i').rename_axis('i', axis=1) * inflator / 1e3
    for key, case in cases.items()
}
dfin_cap_cost = pd.concat(dictin_cap_cost, names=('scen',))
dfin_cap_cost.columns = dfin_cap_cost.columns.str.lower()
print(dfin_cap_cost.columns.str.strip('_0123456789').sort_values().unique())

dictin_cap_cost_energy = {
    key: (
        pd.read_csv(
            os.path.join(case, 'inputs_case', 'plantcharout.csv'),
            index_col=['variable','*i','t'],
        )
        .loc['capcost_energy']
        .value
        .replace(0, np.nan).dropna()
        .unstack('*i').rename_axis('i', axis=1)
        * inflator / 1e3
    )
    for key, case in cases.items()
}
dfin_cap_cost_energy = pd.concat(dictin_cap_cost_energy, names=('scen',))
dfin_cap_cost_energy.columns = dfin_cap_cost_energy.columns.str.lower()
print(dfin_cap_cost_energy.columns.str.strip('_0123456789').sort_values().unique())


#%% Plot it
battery_duration = 4
techs = {
    'PV': {'techlist': ['upv_3']},
    'Wind (land)': {'techlist': ['wind-ons_3']},
    f'Battery ({battery_duration} hr)': {'techlist': ['battery_li']},
    'Gas CCS': {'techlist': ['gas-cc-ccs_mod']},
    'Wind (offshore)': {'techlist': ['wind-ofs_3', 'wind-ofs_7'], 'techlabels': ['Fixed', 'Floating']},
    'Coal CCS': {'techlist': ['coal-ccs_mod']},
    'Nuclear': {'techlist': ['nuclear', 'nuclear-smr'], 'techlabels': ['Large', 'Small']},
    'Geothermal': {'techlist': ['geohydro_allkm_8', 'egs_allkm_3'], 'techlabels': ['Hydrothermal', 'Deep EGS']},
}
colors = ['C2', 'C6']
# dfin_cap_cost[[i for sublist in techs.values() for i in sublist]]

nrows, ncols, coords = reeds.plots.get_coordinates(techs, nrows=1)
years = range(2025,2051,5)
xmin, xmax = min(years), max(years)
alpha = 0.4

plt.close()
f,ax = plt.subplots(nrows, ncols, figsize=(5, 4), sharex=False, sharey=True)
for label in techs:
    techlist = techs[label]['techlist']
    techlabels = techs[label].get('techlabels', [])
    _ax = ax[coords[label]]
    for i, tech in enumerate(techlist):
        df = pd.concat({scen: dfin_cap_cost.loc[scen].loc[years, tech] for scen in cases}, axis=1)
        if tech == 'battery_li':
            df_energy = pd.concat({scen: dfin_cap_cost_energy.loc[scen].loc[years, tech] for scen in cases}, axis=1)
            df += battery_duration * df_energy
        # if label == 'Nuclear':
        #     df = df.loc[2030:]
        _ax.fill_between(
            df.index, df['high'], df['low'],
            alpha=alpha, color=colors[i], lw=0,
            zorder=-i,
        )
        _ax.plot(
            df.index, df['mid'], color=colors[i], zorder=-i,
            label=(techlabels[i] if len(techlabels) else '_nolabel'),
        )
        _ax.set_xticks([xmin, xmax])
        _ax.set_xticklabels([xmin, xmax] if label == list(techs.keys())[0] else [])
        # _ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))
        if len(techlabels):
            lh, ll = _ax.get_legend_handles_labels()
            leg = _ax.legend(
                lh[::-1], ll[::-1],
                loc='upper left', bbox_to_anchor=(-0.3, -0.01), frameon=False,
                handletextpad=0.2, handlelength=0.6,
            )
            for legobj in leg.legend_handles:
                legobj.set_linewidth(6.5)
                legobj.set_solid_capstyle('butt')
        print(f"{tech}: {df['mid'].iloc[0]:.0f}")
    _ax.set_title(label, rotation=45, rotation_mode='anchor', ha='left', x=0.2)
## Formatting
reeds.plots.despine(ax)
_ax = ax[coords[list(techs.keys())[0]]]
_ax.set_ylabel('Capacity cost [$/kW]')
_ax.set_ylim(0)
_ax.yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
# _ax.set_xticks([2025, 2050])
# _ax.set_xticklabels([2025, 2050], rotation=45, rotation_mode='anchor', ha='right')
# _ax.tick_params(axis='x', rotation=90)
plt.draw()
reeds.plots.shorten_years(_ax, start_shortening_in=2026)
plt.savefig(os.path.join(savepath, 'capcost-low,mid,high.png'))
plt.show()


#%%### Gas price
dictin_gasprice = {
    scen: (
        pd.read_csv(os.path.join(case, 'inputs_case', 'fprice.csv'))
        .pivot(index='t', columns='r', values='naturalgas')
    ) * inflator
    for scen, case in cases.items()
}
dfin_gasprice = pd.concat(dictin_gasprice, axis=0, names=('scen',))
dfin_gasprice.columns = dfin_gasprice.columns.map(hierarchy.cendiv)
dfgas = dfin_gasprice.groupby(axis=1, level='r').mean()

#%%
nrows = 2
regions = dfmap['cendiv'].bounds.sort_values('minx').index.values
ncols = len(regions)
years = range(2025,2051,1)
xmin, xmax = min(years), max(years)
alpha = 0.4
color = 'C4'
ymin = 0
ymax = dfgas.xs(2050,0,'t').max().max()

plt.close()
f,ax = plt.subplots(
    nrows, ncols, figsize=(6, 1.7),
    gridspec_kw={'height_ratios':[0.25, 1], 'hspace':0},
)
for col, region in enumerate(regions):
    ## Top map
    dfmap['cendiv'].loc[[region]].plot(ax=ax[0,col], facecolor='k', edgecolor='none', zorder=1e7)
    ax[0,col].set_xlim(*ax[0,col].get_xlim())
    ax[0,col].set_ylim(*ax[0,col].get_ylim())
    # dfmap['st'].plot(ax=ax[0,col], facecolor='0.99', edgecolor='k', lw=0.2, zorder=1e6)
    dfmap['st'].plot(ax=ax[0,col], facecolor='none', edgecolor='w', lw=0.2, zorder=1e7)
    # dfmap['country'].plot(ax=ax[0,col], facecolor='none', edgecolor='k', lw=0.5, zorder=1e8)
    ## Prices
    df = dfgas[region].unstack('scen').loc[years]
    ax[1,col].fill_between(df.index, df['high'], df['low'], color=color, alpha=alpha, lw=0)
    ax[1,col].plot(df.index, df['mid'],  color=color)
    ## Formatting
    ax[1,col].set_ylim(ymin, ymax)
    ax[1,col].yaxis.set_major_locator(mpl.ticker.MultipleLocator(2))
    ax[1,col].yaxis.set_minor_locator(mpl.ticker.AutoMinorLocator(2))
    ax[0,col].axis('off')
    reeds.plots.despine(ax[1,col])
    if col >= 1:
        ax[1,col].set_yticklabels([])
        ax[1,col].set_xticklabels([])
ax[1,0].set_ylabel('Gas price\n[$/MMBtu]')
# ax[1,0].set_xticks([xmin, xmax])
# ax[1,0].set_xticklabels([xmin, xmax], rotation=45, ha='right', rotation_mode='anchor')
plt.draw()
reeds.plots.shorten_years(ax[1,0], start_shortening_in=2026)
plt.savefig(os.path.join(savepath, 'gasprice-cendiv-low,mid,high.png'))
plt.show()



#%%### RE availability
sitemap = reeds.io.get_sitemap()
sitemap.geometry = sitemap.buffer(11530/2, cap_style='square')

#%%
techs = ['upv', 'wind-ons']
scens = ['limited', 'reference', 'open']
dictin_sc = {}
for tech in techs:
    dictin_sc[tech] = pd.concat({
        scen: pd.read_csv(
            os.path.join(
                reeds.io.reeds_path, 'inputs', 'supply_curve',
                f'{tech}_supply_curve-{scen}_ba.csv'
            )
        )
        for scen in scens
    }, names=(['scen','drop']))
dfsc = (
    pd.concat(dictin_sc, names=('tech',))
    .reset_index(level='drop', drop=True)
    .reset_index()
)
dfsc = sitemap.merge(dfsc, on='sc_point_gid').set_index(['tech','scen','sc_point_gid'])


#%%
scale = 2
nrows, ncols = 1, len(scens)
cmap = cmocean.cm.rain
vmin = 0
labels = {'limited':'Low', 'reference':'Mid', 'open':'High', 'upv':'PV', 'wind-ons':'wind'}
for tech in techs:
    # vmax = dfsc.loc[tech].capacity.max()
    vmax = dfsc.loc[tech].capacity.describe([0.999])['99.9%']
    plt.close()
    f,ax = plt.subplots(
        nrows, ncols, figsize=(ncols*scale, nrows*scale*0.7),
        gridspec_kw={'wspace':0}, dpi=300,
    )
    for col, scen in enumerate(scens):
        _ax = ax[col]
        dfmap['st'].plot(ax=_ax, facecolor='none', edgecolor='C7', lw=0.1, zorder=1e6)
        dfmap['country'].plot(ax=_ax, facecolor='none', edgecolor='k', lw=0.25, zorder=1e7)
        df = dfsc.loc[tech].loc[scen]
        df.plot(ax=_ax, column='capacity', cmap=cmap, vmin=vmin, vmax=vmax)
        reeds.plots.addcolorbarhist(
            f, _ax, df['capacity'].values, cmap=cmap, vmin=vmin, vmax=vmax,
            orientation='horizontal', cbarheight=0.8, histratio=1.5, cbarwidth=0.05,
            cbarbottom=-0.1,
            title=(f'Available {labels[tech]} capacity [MW]' if col == 1 else None),
            labelpad=3.5,
            nbins={'upv':101, 'wind-ons':int(vmax//6)}[tech],
        )
        _ax.set_title(labels[scen], y=0.9)
        _ax.axis('off')
    plt.savefig(os.path.join(savepath, f"supplycurve_MW-{tech.replace('-','')}-low,mid,high.png"))
    plt.show()
