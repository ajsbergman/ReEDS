#%% Imports
import yaml
import pandas as pd
from pathlib import Path

#%% Convert from csv to yaml
dfin = pd.read_csv(
    Path('inputs','tech-subset-table.csv'),
    index_col=0,
)
dictout = dfin.stack().reset_index().groupby('level_0').level_1.agg(list).to_dict()
fpath = Path('inputs','tech-subset-table.yaml')
with open(fpath, 'w') as f:
    yaml.dump(dictout, f)
