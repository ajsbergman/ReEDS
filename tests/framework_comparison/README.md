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

## Latest Kestrel full-matrix pull (workflow 964)

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

## Kestrel partial successful table (workflow 971)

Built from `run_complete` events for jobs that finished successfully in workflow `971`.

Artifacts:
- `tests/framework_comparison/results/benchmark_wf971_partial.csv`
- `tests/framework_comparison/results/benchmark_wf971_partial_comparison.csv`
- `tests/framework_comparison/results/benchmark_wf971_partial_comparison.md`

> [!NOTE]
> Some fast jobs in workflow 971 reported `peak_mb=0` from Torc due to runner allocation sharing/sampling. Re-run the workflow with `torc submit --max-parallel-jobs 1 ...` to improve per-job memory attribution before publishing final memory comparisons.

| framework | size | status | build_s | solve_s | total_s | objective |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| gams-cplex | large | ok | 24.233 | 103.361 | 127.594 | 259111953154.042 |
| arco-highs | medium | ok | 0.174 | 7.505 | 7.678 | 15385579143.525 |
| arco-xpress | medium | ok | 0.182 | 8.594 | 8.776 | 15385579143.526 |
| gams-cplex | medium | ok | 1.346 | 1.180 | 2.526 | 15385579143.525 |
| linopy-highs | medium | ok | 0.245 | 7.947 | 8.192 | 15385579143.525 |
| linopy-xpress | medium | ok | 0.230 | 13.957 | 14.187 | 15385579143.525 |
| pyomo-highs | medium | ok | 0.582 | 9.632 | 10.213 | 15385579143.525 |
| pyomo-xpress | medium | ok | 0.579 | 13.215 | 13.794 | 15385579143.525 |
| pyoptinterface-xpress | medium | ok | 0.410 | 10.984 | 11.395 | 15385579143.525 |
| arco-highs | small | ok | 0.035 | 0.186 | 0.221 | 1041838761.547 |
| arco-xpress | small | ok | 0.036 | 0.525 | 0.561 | 1041838761.547 |
| gams-cplex | small | ok | 0.209 | 0.048 | 0.257 | 1041838761.547 |
| linopy-highs | small | ok | 0.234 | 0.352 | 0.586 | 1041838761.547 |
| linopy-xpress | small | ok | 0.263 | 6.745 | 7.008 | 1041838761.547 |
| pyomo-highs | small | ok | 0.042 | 0.184 | 0.226 | 1041838761.547 |
| pyomo-xpress | small | ok | 0.051 | 2.156 | 2.207 | 1041838761.547 |
| pyoptinterface-highs | small | ok | 0.137 | 0.440 | 0.577 | 1041838761.547 |
| pyoptinterface-xpress | small | ok | 0.142 | 0.076 | 0.218 | 1041838761.547 |

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
