#!/bin/bash
#SBATCH --account=last10p
#SBATCH --time=4:00:00
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=yijin.li@nlr.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=246000    # RAM in MB; up to 246000 for normal or 2000000 for bigmem on kestrel
