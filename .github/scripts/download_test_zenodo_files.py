import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import reeds.remote

# only download files needed for test scenarios
required_files = [
    'cf_distpv_county.h5',
    'cf_upv_limited.h5',
    'cf_wind-ofs_limited.h5',
    'cf_wind-ons_limited.h5',
    'demand_EER2025_IRAlow.h5',
    'demand_historic.h5',
]

reeds.remote.download_remote_files(only=required_files)