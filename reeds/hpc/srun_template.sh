#!/bin/bash
#SBATCH --account=finitoreeds
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=kavery@nlr.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=246000        # RAM in MB; up to 246000 for normal or 2000000 for bigmem on kestrel
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost