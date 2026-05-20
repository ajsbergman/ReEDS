# AGENTS.md - Guidance for AI Coding Assistants

This file gives AI coding tools the minimum repo-specific guidance needed to
make safe, useful changes in ReEDS. Keep it short and operational. If guidance
needs extended explanation, move it to
[`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md)
and link to it.

For files in nested folders that contain their own `AGENTS.md`, the nearer file
takes precedence for that subtree.

If this file conflicts with explicit user instructions or
[`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md),
those sources win.

---

## 1. Core rules

- Prefer the smallest patch that solves the request.
- Do not make "while I'm here" refactors, renames, reformatting passes, or
  speculative abstractions.
- Read the file you will edit and at least one nearby caller, consumer, or
  owning file before changing behavior.
- Reuse existing helpers in the `reeds/` package before adding new utilities.
- Do not add dependencies or change [`environment.yml`](environment.yml) or
  [`Project.toml`](Project.toml) without explicit approval.
- Do not use destructive git operations, force-push, rewrite published history,
  or modify CI secrets unless explicitly instructed.
- Do not claim behavior or test outcomes you did not verify.
- If a point is unclear, verify it from the repo instead of guessing.

Ask the human before proceeding if:

- the meaning of a switch, parameter, or canonical file is ambiguous;
- the change would alter default-case results and that was not requested;
- the fix appears to require large data edits, CI changes, new dependencies,
  or updates in ReEDS_Input_Processing / Zenodo;
- the request appears to conflict with
  [`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md).

When asking, present concrete options and a recommendation.

---

## 2. Repo-specific risk areas

- [`runreeds.py`](runreeds.py) is interactive by default. Agents should pass
  `-b <batch>` and `-c <suffix>` and usually `-s <case>` and/or `-f`.
- [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
  is the gatekeeper for files copied into `inputs_case/`. After `copy_files.py`
  runs, downstream steps read from `inputs_case/`, not directly from `inputs/`.
- If you add, remove, or rename a GAMS-read CSV, usually update both
  [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
  and [`inputs/userinput/futurefiles.csv`](inputs/userinput/futurefiles.csv).
  New scalar inputs belong in [`inputs/scalars.csv`](inputs/scalars.csv)
  rather than hard-coded values.
- Inputs used in [`reeds/core/setup/d_objective.gms`](reeds/core/setup/d_objective.gms)
  should also appear in
  [`tests/objective_function_params.yaml`](tests/objective_function_params.yaml)
  when feasible so input checks can validate them.
- Reported parameters are coupled across
  [`reeds/core/terminus/report_params.csv`](reeds/core/terminus/report_params.csv),
  [`reeds/core/terminus/report.gms`](reeds/core/terminus/report.gms), and any
  downstream postprocessing that reads them.
- [`reeds/resource_adequacy/`](reeds/resource_adequacy) is part of the solve
  workflow between years, not just postprocessing. Changes there can change
  model results.
- Costs loaded in [`reeds/core/setup/b_inputs.gms`](reeds/core/setup/b_inputs.gms)
  must already be in 2004$. Use
  [`inputs/financials/deflator.csv`](inputs/financials/deflator.csv) rather
  than hard-coded conversions.
- In Python, prefer `pathlib.Path`, use absolute paths where practical, and do
  not change the working directory in preprocessing scripts.
- Use ReEDS set names in data columns where practical, and add unit suffixes
  to new data columns such as `capcost_usd.per.kw`.

Before making a non-trivial change, check whether it can affect:

- switch-gated behavior in [`cases.csv`](cases.csv) and related case files;
- reporting or postprocessing outputs;
- resource adequacy feedback into later solve years;
- default-case results, runtime, or input-copy behavior.

---

## 3. Documentation and change summaries

Documentation is part of the change.

- If you change model behavior, switches, inputs, outputs, setup, or
  postprocessing behavior, update the relevant docs in [`docs/source/`](docs/source).
- If you add or rename a switch, update [`cases.csv`](cases.csv) and
  [`docs/source/user_guide.md`](docs/source/user_guide.md).
- If you add or rename an input file, update
  [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
  and the relevant `inputs/*/README.md` if one exists.
- If you change sourced data, regenerate [`docs/sources.csv`](docs/sources.csv)
  and [`docs/sources_documentation.md`](docs/sources_documentation.md) using
  [`docs/source/documentation_tools/`](docs/source/documentation_tools).
- Do not hand-edit [`docs/source/references.bib`](docs/source/references.bib)
  unless explicitly asked.

In a PR description or handoff summary, state:

- what changed and why;
- which switches, scenarios, or outputs could be affected;
- whether the default case is expected to change;
- which docs were updated;
- which test tier is required.

If opening a PR, the author must disclose LLM usage in the PR template and be
able to defend every change.

---

## 4. Testing expectations

Always run lightweight local checks that fit the change, at minimum `pytest`
from the repo root for code changes. Treat it as a smoke test, not a model
correctness test. Run `ruff check` for Python edits, but do not auto-format
existing files.

Use this test floor for model-facing work:

- Postprocessing or cosmetic-only change: rerun the affected postprocessing on
  an existing run; no model rerun required.
- Code change not expected to affect default-case results: run the Pacific test
  case from [`cases_test.csv`](cases_test.csv) and generate a comparison report.
- Anything likely to affect results: run `USA_defaults` (or `Mid_Case`) plus
  `USA_decarb` from [`cases_test.csv`](cases_test.csv) and compare results with
  [`postprocessing/compare_cases.py`](postprocessing/compare_cases.py).

Call out the required test tier explicitly if you cannot run it yourself.

---

## 5. Fast inner loop from `call_*`

If a completed run already exists, re-running one step from its `call_{case}`
script is often the fastest way to validate a single-file or single-stage
change.

Use this approach when:

- one file or one pipeline stage changed;
- you want a quick compile or output diff before a full rerun.

Do not rely on it when:

- the change crosses pipeline stages;
- the change affects resource adequacy feedbacks;
- the existing run does not exercise the relevant switch settings.

Important gotcha: run directories contain a frozen copy of `reeds/`, and the
`call_*` script uses that copy. If you edit a source file in the repo, reusing
`call_*` without updating the frozen copy can produce no diff. Either copy the
edited file into the run directory or invoke the source path directly with the
same arguments.

When using this fast loop, report the command you re-ran, the outputs that
changed, and whether the deltas match the intended behavior. This complements,
but does not replace, the test tiers above.

---

## 6. High-value paths

- [`runreeds.py`](runreeds.py)
- [`cases.csv`](cases.csv) and other `cases_*.csv`
- [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
- [`inputs/scalars.csv`](inputs/scalars.csv)
- [`reeds/core/setup/`](reeds/core/setup)
- [`reeds/core/terminus/`](reeds/core/terminus)
- [`reeds/resource_adequacy/`](reeds/resource_adequacy)
- [`docs/source/`](docs/source)
- [`tests/`](tests)
- `runs/<batch_case>/call_*`

---

## 7. Useful commands

```bash
conda activate reeds2
pytest
ruff check
cd docs && make html
python runreeds.py -h
python runreeds.py -b v20260101_dev -c test -s Pacific
python reeds/remote.py
```

When in doubt, prefer the smallest correct change, document impact clearly,
and ask before making a change that could affect default results.
