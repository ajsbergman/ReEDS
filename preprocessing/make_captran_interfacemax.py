#%% Imports
import os
import numpy as np
import pandas as pd
import argparse

reeds_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#%% Argument inputs
parser = argparse.ArgumentParser(
    description=(
        'Write single-interface transmission limits based on existing ReEDS case.\n'
        'Output is written to\n'
        'inputs/transmission/captran_interfacemax_{case}_d{delay}_f{fraction}.csv\n'
        'where `delay` is the years by which transmission capacity is delayed and\n'
        '`fraction` is a float by which the transmission capacity is multiplied.'
    ),
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    'case', type=str, help='Path to ReEDS run to draw interface limits from',
)
parser.add_argument(
    '--delay', '-d', type=int, default=0,
    help='Years by which to delay transmission capacities from ReEDS case',
)
parser.add_argument(
    '--fraction', '-f', type=float, default=1.0,
    help='Fraction by which to multiply transmission capacities from ReEDS case',
)
args = parser.parse_args()
case = args.case
delay = args.delay
fraction = args.fraction

# #%% Inputs for debugging
# case = (
#     '/Volumes/ReEDS/FY22-NTP/Candidates/Archive/ReEDSruns/'
#     '20230910/v20230910_ntpH0_AC_DemMd_90by2035EP__core'
# )
# delay = 5
# fraction = 1.0

#%%### Procedure
### Load transmission capacity from ReEDS case
dfin_transcap = pd.read_csv(
    os.path.join(case,'outputs','tran_cap_energy.csv'),
)
dfout_transcap = dfin_transcap.copy()
yearmin = dfin_transcap.t.min()
yearmax = dfin_transcap.t.max()
### Delay if necessary
if delay:
    dfout_transcap.t += delay
    ## Broadcast the delayed-start-year capacity back to the actual start year
    dfout_transcap = pd.concat([
        dfout_transcap.loc[dfout_transcap.t == yearmin + delay].assign(t=yearmin),
        dfout_transcap.loc[dfout_transcap.t <= yearmax],
    ], axis=0, ignore_index=True)
### Multiply additions by fraction if necessary
if fraction != 1:
    ## Get additions
    dfwide = (
        dfout_transcap
        .pivot(index='t', columns=['r','rr','trtype'], values='Value')
        .fillna(0)
    )
    dfout_transinv = dfwide.diff(1).fillna(0) * fraction
    dfout_transcap = (
        dfwide.loc[yearmin].fillna(0).add(dfout_transinv.cumsum(), fill_value=0)
        .stack(['r','rr','trtype'])
        .replace(0,np.nan).dropna()
        .rename('Value').reset_index()[['r','rr','trtype','t','Value']]
    )

# #%% Take a look
# import matplotlib.pyplot as plt
# plt.close()
# f,ax = plt.subplots()
# ax.plot(
#     sorted(dfin_transcap.t.unique()),
#     dfin_transcap.groupby('t').Value.sum().values,
#     marker='o', markerfacecolor='none', label='input',
# )
# ax.plot(
#     sorted(dfout_transcap.t.unique()),
#     dfout_transcap.groupby('t').Value.sum().values,
#     marker='s', markerfacecolor='none', label='output',
# )
# ax.legend()
# plt.show()

#%% Write it
fracname = '1' if fraction == 1 else f'{fraction:.2f}'
savename = f'captran_interfacemax_{os.path.basename(case)}_d{delay}_f{fracname}.csv'
dfout_transcap.round(3).to_csv(
    os.path.join(reeds_path, 'inputs', 'transmission', savename),
    index=False,
)
print(savename)
