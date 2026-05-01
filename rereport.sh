#!/bin/bash
#SBATCH --account=finitoreeds
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mail-user=kavery@nrel.gov
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mem=240000        # RAM in MB; up to 256000 for normal or 2000000 for bigmem on kestrel#
#SBATCH --output=logs/rereport_%j.out
# add >>> #SBATCH --qos=high <<< above for quicker launch at double AU cost

set -eo pipefail

folder="$1"

cd "$folder"

. $HOME/.bashrc 
module purge 
source /nopt/nrel/apps/env.sh 
module load anaconda3 
module use /nopt/nrel/apps/software/gams/modulefiles 
module load gams 
conda deactivate 
conda activate reeds2 
export R_LIBS_USER="$HOME/rlib" 

target_script="$(basename "$(find "$folder" -maxdepth 1 -type f -name 'call_*.sh' | head -n 1)")"
marker="# Output processing"

tmp_script="$(mktemp)"
trap 'rm -f "$tmp_script"' EXIT

awk -v marker="$marker" '
  found { print }
  $0 == marker { found = 1 }
' "$target_script" > "$tmp_script"

bash "$tmp_script"