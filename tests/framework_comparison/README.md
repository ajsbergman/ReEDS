# ReEDS LP Framework Comparison

Benchmarks Python LP modeling frameworks on a ReEDS-representative linear program.
Compute work runs through Torc Slurm allocations on Kestrel — not direct `sbatch`
jobs or login-node solves.

## Problem structure

Simplified single-vintage capacity-expansion LP with the same indexing and
constraint patterns as `reeds/core/setup/c_model.gms`.

| Element | Description |
| --- | --- |
| Variables | `GEN[i,r,h,t]`, `CAP[i,r,t]`, `INV[i,r,t]`, `FLOW[r,rr,h,t]`, `RAMPUP[i,r,h,t]`, `CHARGE[i,r,h,t]`, `SOC[i,r,h,t]` |
| `eq_cap_accum` | Capacity accumulation across years |
| `eq_cap_limit` | Generation ≤ region-specific CF × capacity |
| `eq_mingen` | Minimum hourly dispatch fraction |
| `eq_supply_demand` | Energy balance with transmission and storage charging |
| `eq_reserve_margin` | Planning reserve requirement |
| `eq_transmission_limit` | Corridor flow limits |
| `eq_emit_cap` | Annual CO₂ cap |
| `eq_ramping` | RAMPUP slack ≥ hour-to-hour increase in dispatch |
| `eq_min_cf` | Minimum annual capacity factor for dispatchable techs |
| `eq_soc` / `eq_soc_cap` / `eq_charge_cap` | Battery storage state-of-charge |

## Problem sizes

| Size | Regions | Techs | Hours | Years | Approx. variables |
| --- | ---: | ---: | ---: | ---: | ---: |
| small | 5 | 4 | 24 | 2 | 15 K |
| medium | 20 | 5 | 100 | 2 | 200 K |
| large | 60 | 7 | 400 | 2 | 3 M |
| xlarge | 120 | 8 | 800 | 2 | 25 M |

## File layout

| File | Purpose |
| --- | --- |
| `data_generator.py` | Single source of truth for benchmark parameters and problem sizes |
| `run_framework.py` | CLI adapter: one job = one invocation → JSON result |
| `solve_arco.py` | Arco implementation |
| `solve_gams.py` | GAMS subprocess implementation |
| `solve_gamspy.py` | GAMSPy implementation |
| `solve_linopy.py` | Linopy implementation |
| `solve_pyomo.py` | Pyomo implementation |
| `solve_pyoptinterface.py` | PyOptInterface implementation |
| `run_gams.sh` | Thin GAMS subprocess wrapper called by `solve_gams.py` |
| `setup_env_local.sh` | Local env setup (uv sync + optional Arco wheel) |
| `setup_env_hpc.sh` | Kestrel HPC pre-job setup (modules + venv + Arco wheel + env exports) |
| `torc_local.yaml` | Torc workflow for local development runs (no Slurm) |
| `torc_kestrel.yaml` | Torc/Slurm workflow for canonical Kestrel benchmarks |
| `pull_results.sh` | Pull JSON results from a Torc run and emit CSV (local or remote SSH) |
| `create_comparison_benchmark_table.py` | Convert CSV results to a markdown table |

## Default benchmark matrix

Both `torc_local.yaml` and `torc_kestrel.yaml` run **small** and **medium**
sizes for:

| Framework | Module | Default solver |
| --- | --- | --- |
| Linopy | `solve_linopy.py` | HiGHS |
| Pyomo | `solve_pyomo.py` | HiGHS |
| Arco | `solve_arco.py` | HiGHS |
| GAMS | `solve_gams.py` | HiGHS (via GAMS) |

Xpress, CPLEX, GAMSPy, and PyOptInterface are not in the default matrix.
Add them when the required site access and licenses are confirmed.

---

## Quick-start: local smoke-test

```bash
# 1. Set up the Python environment
./tests/framework_comparison/setup_env_local.sh

# 2. Run a single framework/size directly
python tests/framework_comparison/run_framework.py \
  --module solve_linopy --solver highs --size small

# 3. Or run the full local Torc matrix (no Slurm)
torc workflow create tests/framework_comparison/torc_local.yaml
torc workflow run <workflow-id>
```

### Change the solver
```bash
BENCHMARK_SOLVER=scip torc workflow create tests/framework_comparison/torc_local.yaml
```

### Pull and display results
```bash
./tests/framework_comparison/pull_results.sh \
  --run-dir /path/to/torc-runs/framework-matrix-<id> > /tmp/results.csv

python tests/framework_comparison/create_comparison_benchmark_table.py /tmp/results.csv
```

---

## Kestrel HPC workflow

### Prerequisites

- Torc client: `/scratch/psanchez/torc/0.30.3/torc`
- Torc API: `http://torc.hpc.nrel.gov:8080/torc-service/v1`
- Kestrel modules: `gams/51.3.0 conda/2024.06.1`
- Optional Arco prefix: `/scratch/psanchez/arco/latest`

### Deploy and run

```bash
SHA=$(git rev-parse HEAD)
RUN_ID=framework-matrix-$(date +%Y%m%d-%H%M%S)

/path/to/deploy-git-torc-slurm.sh \
  --host psanchez@kestrel.hpc.nrel.gov \
  --remote-git-dir /scratch/psanchez/git/ReEDS.git \
  --sha "$SHA" \
  --run-id "$RUN_ID" \
  --workflow tests/framework_comparison/torc_kestrel.yaml \
  --torc-api-url http://torc.hpc.nrel.gov:8080/torc-service/v1 \
  --modules 'gams/51.3.0 conda/2024.06.1' \
  --remote-torc-bin /scratch/psanchez/torc/0.30.3/torc
```

### Monitor

```bash
export TORC_API_URL=http://torc.hpc.nrel.gov:8080/torc-service/v1
torc status <workflow-id>
torc results list <workflow-id>
```

### Pull results from Kestrel

```bash
./tests/framework_comparison/pull_results.sh \
  --host psanchez@kestrel.hpc.nrel.gov > /tmp/results.csv

python tests/framework_comparison/create_comparison_benchmark_table.py /tmp/results.csv
```

### Inspect individual JSON results on Kestrel

```bash
ssh psanchez@kestrel.hpc.nrel.gov \
  'find /scratch/psanchez/torc-runs/<run-id>/src/tests/framework_comparison/torc_output_matrix/framework_results \
    -name "*.json" -maxdepth 1 -print -exec cat {} \;'
```

---

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `BENCHMARK_SOLVER` | Solver used by all jobs in a workflow | `highs` |
| `FRAMEWORK_MODULES` | Space- or comma-separated Lmod modules (HPC) | `gams/51.3.0 conda/2024.06.1` |
| `FRAMEWORK_COMPARISON_ARCO_PREFIX` | Prefix with `wheels/` and `scip/lib/` | `/scratch/$USER/arco/latest` |
| `GAMS_EXE` | Explicit GAMS executable path | discovered from `PATH` |
| `TORC_API_URL` | Torc API endpoint | Kestrel Torc URL |
| `TORC_RUNS_BASE` | Local/remote Torc runs directory | `/scratch/$USER/torc-runs` |

## Notes

- **Torc job return code 0** only means the adapter wrote its JSON result.
  Always inspect `error` fields in per-case JSON files for pass/fail.
- **Login-node runs**: only for lightweight status/file checks.
  All benchmark solves must go through Torc/Slurm.
- **Solver override**: set `BENCHMARK_SOLVER` before workflow creation or
  pass `--env BENCHMARK_SOLVER=<solver>` to the deploy script.
