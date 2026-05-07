#%% Imports
import gdxpds
import pandas as pd
from pathlib import Path


#%% Functions
def get_gams_results(case):
    print('Loading resultsgdx')
    dictin = gdxpds.to_dataframes(Path(case, 'outputs', 'results.gdx'))
    ## Set indices as multiindex
    valcols = ['Value','Level','Marginal','Lower','Upper','Scale']
    for key, df in dictin.items():
        indices = [i for i in df if i not in valcols]
        dictin[key] = df.set_index(indices).squeeze(1)
    print('Finished loading results.gdx')
    return dictin


def calc_iq(g):
    """Capacity above interconnection queue limit"""
    dfs = {}
    dfs['cap_above_limit'] = g['CAP_ABOVE_LIM'].Level
    return dfs


def calc_co2_stor(g):
    """CO2 capture, transport, and storage"""
    dfs = {}
    dfs['CO2_CAPTURED_out'] = g['CO2_CAPTURED'].Level
    dfs['CO2_CAPTURED_out_ann'] = (g['CO2_STORED'].Level * g['hours']).groupby(['r','t']).sum()
    return dfs


def combine_forward_reverse(df, value='Level'):
    """Combine forward (r < rr) and reverse (r > rr) into one +/- series"""
    r_indices = ['r', 'rr']
    other_indices = [i for i in df.index.names if i not in r_indices]
    forward = df.loc[
        df.index.get_level_values('r') < df.index.get_level_values('rr'),
        value,
    ]
    reverse = -df.loc[
        df.index.get_level_values('r') > df.index.get_level_values('rr'),
        value,
    ].rename_axis(['rr', 'r'] + other_indices).reorder_levels(['r', 'rr'] + other_indices)
    return pd.concat([forward, reverse]).groupby(['r', 'rr'] + other_indices).sum()


def calc_transmission(g):
    """Transmission capacity and flow"""
    dfs = {}
    dfs['tran_flow_rep'] = combine_forward_reverse(g['FLOW'])
    dfs['tran_flow_rep_ann'] = (dfs['tran_flow_rep'] * g['hours']).groupby(['r','rr','trtype','t']).sum()
    return dfs


def main(case):
    dictin = get_gams_results(case)
    dictout = {
        **calc_iq(dictin),
        **calc_co2_stor(dictin),
        **calc_transmission(dictin),
    }
    ## Drop zeros to reduce file size and match GAMS convention
    for key, df in dictout.items():
        _df = df.rename('Value').reset_index()
        dictout[key] = _df.loc[_df.Value != 0].copy()
    return dictout
