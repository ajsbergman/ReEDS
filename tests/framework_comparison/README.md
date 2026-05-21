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

## Earlier Kestrel full-matrix pull (workflow 964)

Pulled with:

```bash
./tests/framework_comparison/pull_results.sh --host psanchez@kestrel.hpc.nrel.gov \
  > tests/framework_comparison/results/benchmark_wf964.csv
```

Artifact:
- `tests/framework_comparison/results/benchmark_wf964.csv` (36 cases + header)

Summary from JSON adapter results:

| Metric | Value |
| --- | ---: |
| Workflow ID | 964 |
| Cases | 36 |
| Adapter status `ok` | 0 |
| Adapter status `failed` | 36 |
| Common error signature | `Traceback ... run_framework.py line 302` |

Notes:
- Torc job status is `completed` for all 36 jobs, but adapter JSONs report failures.
- Per the project contract, treat JSON `error` field as benchmark pass/fail source of truth.

## Simple HPC run (Kestrel)

Ensure Torc CLI and `TORC_API_URL` are configured in your environment, then run:

```bash
# 1) Generate Slurm workflow
torc slurm generate --account <account> --overwrite \
  -o tests/framework_comparison/torc_kestrel_full_matrix_slurm.yaml \
  tests/framework_comparison/torc_kestrel_full_matrix.yaml

# 2) Submit (use max-parallel-jobs=1 for better per-job memory attribution)
torc submit --max-parallel-jobs 1 \
  -o <torc-output-dir> \
  tests/framework_comparison/torc_kestrel_full_matrix_slurm.yaml

# 3) Monitor
torc status <workflow-id>
```

## Kestrel completed benchmark table (workflow 973)

Built from workflow `973` rows where Torc status is `Completed` and the adapter JSON has no `error`.

Pulled with:

```bash
./tests/framework_comparison/pull_results.sh --host psanchez@kestrel.hpc.nrel.gov \
  > tests/framework_comparison/results/benchmark_20260520_101751_kestrel.csv
```

Workflow summary:

| Metric | Value |
| --- | ---: |
| Workflow ID | 973 |
| Torc results | 36 |
| Torc `Completed` | 23 |
| Torc `Failed` | 1 |
| Torc `Terminated` | 12 |
| Rows shown below | 23 |

> [!NOTE]
> `peak_mb=0` means Torc did not attribute a non-zero memory sample for that fast job in this run.

Retry notes:

- Workflow `977` retried the 12 timeout-terminated workflow `973` jobs with an
  8h48m Slurm allocation, but all 12 were terminated again when Torc reached
  the allocation timeout window.
- Workflow `986` reruns the same retry set using Kestrel's max partition
  walltime. It was generated with
  `torc slurm generate --profile kestrel --walltime-strategy max-partition-time`,
  producing `walltime: 2-00:00:00`, then submitted with `--max-parallel-jobs 1`.
- Latest check of workflow `986`: 2 active Slurm allocations, 10 jobs still
  ready, 2 jobs running, and no completed Torc results yet. Until workflow
  `986` emits JSON result files, the table below remains the latest completed
  benchmark result set.

| framework | size | status | build_s | solve_s | total_s | peak_mb | objective |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| arco-highs | small | ok | 0.182 | 0.782 | 1.032 | 0.000 | 1041838761.547 |
| arco-xpress | small | ok | 0.035 | 0.621 | 0.727 | 0.000 | 1041838761.547 |
| gams-cplex | small | ok | 0.195 | 0.045 | 0.455 | 0.000 | 1041838761.547 |
| linopy-highs | small | ok | 0.233 | 1.514 | 7.716 | 138.100 | 1041838761.547 |
| linopy-xpress | small | ok | 0.372 | 12.000 | 15.052 | 577.100 | 1041838761.547 |
| pyomo-highs | small | ok | 0.044 | 0.252 | 0.904 | 0.000 | 1041838761.547 |
| pyomo-xpress | small | ok | 0.043 | 3.012 | 3.662 | 155.100 | 1041838761.547 |
| pyoptinterface-highs | small | ok | 0.207 | 0.519 | 1.173 | 31.900 | 1041838761.547 |
| pyoptinterface-xpress | small | ok | 0.230 | 0.102 | 0.612 | 0.000 | 1041838761.547 |
| arco-highs | medium | ok | 0.302 | 7.165 | 7.543 | 255.900 | 15385579143.525 |
| arco-xpress | medium | ok | 0.178 | 9.188 | 9.446 | 187.800 | 15385579143.526 |
| gams-cplex | medium | ok | 1.379 | 1.051 | 2.675 | 0.000 | 15385579143.525 |
| linopy-highs | medium | ok | 0.243 | 8.607 | 14.687 | 190.800 | 15385579143.525 |
| linopy-xpress | medium | ok | 0.379 | 22.029 | 25.002 | 1290.240 | 15385579143.525 |
| pyomo-highs | medium | ok | 0.584 | 9.299 | 10.538 | 359.800 | 15385579143.525 |
| pyomo-xpress | medium | ok | 0.588 | 13.541 | 14.763 | 380.200 | 15385579143.525 |
| pyoptinterface-highs | medium | ok | 0.266 | 8.710 | 9.204 | 1075.200 | 15385579143.525 |
| pyoptinterface-xpress | medium | ok | 0.400 | 10.076 | 10.688 | 181.300 | 15385579143.525 |
| arco-highs | large | ok | 4.060 | 3951.595 | 3956.053 | 2160.640 | 259111953154.049 |
| gams-cplex | large | ok | 22.994 | 90.196 | 113.799 | 5201.920 | 259111953154.042 |
| linopy-highs | large | ok | 0.558 | 3600.725 | 3608.375 | 2816.000 | 259111953154.019 |
| pyomo-highs | large | ok | 10.901 | 3642.356 | 3654.320 | 3635.200 | 259111953154.027 |
| gams-cplex | xlarge | ok | 104.153 | 2094.032 | 2200.584 | 19148.800 | 1213777350852.881 |

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
| `GAMS_LICENSE_FILE` | Path to GAMS/CPLEX license file used by `gams ... license=...` | unset |
| `TORC_RUNS_BASE` | Local/remote Torc runs directory | `/scratch/$USER/torc-runs` |

## Notes

- **Torc job return code 0** only means the adapter wrote its JSON result.
  Always inspect `error` fields in per-case JSON files for pass/fail.
- **Login-node runs**: only for lightweight status/file checks.
  All benchmark solves must go through Torc/Slurm.
- **Solver override**: set `BENCHMARK_SOLVER` before workflow creation or
  pass `--env BENCHMARK_SOLVER=<solver>` to the deploy script.

## Debugging learnings (May 2026)

- Keep `invocation_script` env-only and finish with `exec "$@"` in `setup_env_hpc.sh`.
- Use single-line `command:` entries in Torc YAML to avoid shell split issues.
- For Arco on Kestrel, install from `/scratch/$USER/arco/latest/wheels` with `--no-deps`.
- Pin `xpress==9.7.*` to match site license and use `pyoptinterface[highs]` so HiGHS is bundled.
- GAMS CPLEX requires passing a license path explicitly: runner now uses
  `gams ... license=<GAMS_LICENSE_FILE|GAMS_LICENSE>`.
