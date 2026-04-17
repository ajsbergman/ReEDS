#!/bin/bash
#SBATCH --account=finitoreeds
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=kavery@nrel.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=240000        # RAM in MB; up to 256000 for normal or 2000000 for bigmem on kestrel#
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost

source /nopt/nrel/apps/env.sh
module load anaconda3
module use /nopt/nrel/apps/software/gams/modulefiles
module load gams

conda deactivate
conda activate reeds2

# Access the current directory
# cd /projects/finitoreeds/kpitman/ReEDS-2.0/postprocessing/bokehpivot

python run_report_materials_kp.py