# AGENTS.md — ReEDS quick guide for LLM coding agents

This file is the **day-to-day operating guide** for LLM coding agents (for example Claude, Codex, and ChatGPT) working in ReEDS.
For files in nested folders that contain their own AGENTS.md, the nearer file takes precedence.
It is the primary source of truth for agent instructions in this repository root.

**This is the repository equivalent of `CLAUDE.md`** (kept here as `AGENTS.md` for broader agent tooling compatibility).

If anything here conflicts with:

1. explicit user instructions, or
2. a closer/nested `AGENTS.md` for the edited path, or
3. [`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md),

then that higher-priority source wins.

## 0) Keep this file lean

- Treat this file as a **quick operating contract**, not full documentation.
- No required schema; plain Markdown is enough.
- Keep it short (target: ~200 lines; if it grows much beyond that, move detail out).
- Keep only: non-negotiables, checklists, and ReEDS-specific gotchas that change agent behavior.
- Move deep tutorials/reference material to [`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md) and link to it.
- Prefer short, imperative bullets with concrete actions/commands over prose.
- If guidance is team- or folder-specific, put it in a closer nested `AGENTS.md` instead of expanding this root file.
- Keep this document current as a living guide.
- Do not add generic coding advice that is not ReEDS-specific.

---

## 1) What matters most (read first)

ReEDS is a large, mixed-language, production research model (GAMS + Python + Julia).
Small edits can have large downstream effects.

### Non-negotiables

- Make the **smallest correct change**.
- No drive-by refactors, renames, formatting, or speculative abstractions.
- Ask the human when intent is unclear.
- Do not claim behavior/test outcomes you did not verify.
- Do not run destructive git/file operations without explicit approval.

---

## 2) Daily workflow checklist (default)

For any non-trivial change:

1. Restate the request and scope before editing broadly.
2. Read the target file and at least one caller/consumer.
3. Check switch interactions (`GSw_*`, `Sw_*`) in touched logic.
4. Implement minimal patch.
5. Update required docs/registries in the same change.
6. Run relevant checks (at least `pytest` smoke test when feasible).
7. Summarize impact: files changed, affected switches/scenarios, expected default-case effect, recommended test tier.

---

## 3) High-impact gotchas unique to ReEDS

### 3.1 Input pipeline contract

If you add/rename/remove a model input CSV:

- Update [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv)
- Update [`inputs/userinput/futurefiles.csv`](inputs/userinput/futurefiles.csv) for forward projection
- Update relevant input-folder README (if present)

If you add a scalar, use [`inputs/scalars.csv`](inputs/scalars.csv) (do not hard-code).

### 3.2 GAMS/report coupling

Changes to reported parameters usually require coordinated updates across:

- [`reeds/core/terminus/report_params.csv`](reeds/core/terminus/report_params.csv)
- [`reeds/core/terminus/report.gms`](reeds/core/terminus/report.gms)
- downstream postprocessing that reads those outputs

Inputs used in objective logic should stay aligned with:

- [`reeds/core/setup/d_objective.gms`](reeds/core/setup/d_objective.gms)
- [`tests/objective_function_params.yaml`](tests/objective_function_params.yaml)

### 3.3 Cost units and dollar year

- Costs loaded into `b_inputs.gms` should be in **2004$**.
- Use [`inputs/financials/deflator.csv`](inputs/financials/deflator.csv) in preprocessing.
- Add unit suffixes in new columns (e.g., `capcost_usd.per.kw`).

### 3.4 Default-case neutrality

If change is not expected to alter default outputs, state that explicitly.

---

## 4) Required docs sync

When behavior/switch/input/output changes, update docs in same PR.

Primary targets:

- [`docs/source/model_documentation.md`](docs/source/model_documentation.md)
- [`docs/source/user_guide.md`](docs/source/user_guide.md)
- [`docs/source/faq.md`](docs/source/faq.md)
- [`docs/source/postprocessing_tools.md`](docs/source/postprocessing_tools.md)
- [`docs/source/setup.md`](docs/source/setup.md)

Also:

- Switch add/rename: update `cases.csv` description + `user_guide.md`
- Input file add/rename: update `runfiles.csv` + input README
- Sourced data changes: regenerate [`docs/sources.csv`](docs/sources.csv) and [`docs/sources_documentation.md`](docs/sources_documentation.md)

---

## 5) Testing expectations (tell human what tier is needed)

`pytest` is a smoke test, not full model validation.

Recommended tiers:

- **Postprocessing/cosmetic only:** rerun relevant postprocessing against existing outputs.
- **No expected default-case result change:** run Pacific (`cases_test.csv`) + comparison report.
- **Most behavior changes:** run `USA_defaults` (or `Mid_Case`) **and** `USA_decarb` from `cases_test.csv`, then compare with `postprocessing/compare_cases.py`.

Always state which tier applies.

---

## 6) Fast inner loop (useful while iterating)

If a completed run exists in `runs/`, rerun only the impacted step from `call_*` for faster feedback.

Use when:

- single-file or single-stage changes.

Avoid as sole validation when:

- change crosses stages (preprocess ↔ GAMS ↔ report),
- change touches feedback loops (resource adequacy),
- required switches are not exercised by that existing run.

Important gotcha:

- `runreeds.py` copies `reeds/` into run folders. `call_*` may execute stale copied code unless you invoke updated source path or sync the edited file.

---

## 7) Run commands and execution notes

- `runreeds.py` is interactive by default.
- For non-interactive use, pass at least `-b <batch>` and `-c <suffix>` (often also `-s <case>` and/or `-f`).
- If a command runs longer than 5 minutes without useful progress, stop it, capture logs/output, and report before retrying.

Examples:

```bash
python runreeds.py -b v20260101_dev -c test
python runreeds.py -b v20260101_dev -c test -s Pacific
```

Quick checks:

```bash
pytest
ruff check
cd docs && make html
```

---

## 8) When to stop and ask the human

Ask before proceeding when:

- switch/parameter intent is ambiguous,
- multiple plausible canonical control points exist,
- default-case outputs may change unexpectedly,
- change requires dependencies/CI/env changes,
- fix appears to require external input repos/Zenodo,
- request conflicts with best-practices guidance,
- before adding a dependency, confirm maintained alternatives and necessity with the user unless the need is urgent.

Avoid leaving move/delete breadcrumb comments such as "moved to X" in code.

Treat `git status` and `git diff` as read-only context; do not assume uncommitted changes were made only by this agent.

When asking, provide 2–3 concrete options and recommend one.

---

## 9) High-value file map (minimal)

- [`runreeds.py`](runreeds.py): top-level launcher (interactive unless flags provided)
- [`cases.csv`](cases.csv), `cases_*.csv`: switches + scenarios
- [`reeds/input_processing/runfiles.csv`](reeds/input_processing/runfiles.csv): authoritative input file registry
- [`reeds/core/setup/b_inputs.gms`](reeds/core/setup/b_inputs.gms): input loading
- [`reeds/core/setup/a_createmodel.gms`](reeds/core/setup/a_createmodel.gms): compile entrypoint
- [`reeds/core/setup/d_objective.gms`](reeds/core/setup/d_objective.gms): objective inputs
- [`reeds/core/terminus/report_params.csv`](reeds/core/terminus/report_params.csv), [`reeds/core/terminus/report.gms`](reeds/core/terminus/report.gms): outputs/reporting
- [`reeds/resource_adequacy/`](reeds/resource_adequacy): between-year feedback calculations
- [`docs/source/developer_best_practices.md`](docs/source/developer_best_practices.md): canonical process and conventions

---

## 10) PR hygiene reminders

- Keep PRs small and single-topic.
- Use descriptive PR titles (used in release-note summaries).
- Disclose LLM usage in PR template.
- Never force-push published history or modify secrets without explicit instruction.

---

## 11) Final handoff discipline

- Always report commands run and outcomes (pass/fail/timeout).
- Note follow-up TODOs, assumptions, and risks before handoff.
