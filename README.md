# ReEDS: BAAJA permitting reform analysis (RFF)

This branch contains the version of the Regional Energy Deployment System (ReEDS) model used by Resources for the Future (RFF) for the issue brief
[Projected Effects of the Bipartisan American Affordability and Jobs Act on the Power Sector](https://www.rff.org/publications/issue-briefs/projected-effects-of-the-bipartisan-american-affordability-and-jobs-act-on-the-power-sector/) (October 2026).

**This is a modified version of ReEDS, not an official release from the National Laboratory of the Rockies (NLR).**
NLR has not reviewed the modifications described below.
The official ReEDS repository is [https://github.com/ReEDS-Model/ReEDS](https://github.com/ReEDS-Model/ReEDS), and the ReEDS documentation is at [https://reeds-model.github.io/ReEDS](https://reeds-model.github.io/ReEDS).


## What this branch contains

The branch is upstream ReEDS at commit [`43c4732d`](https://github.com/ReEDS-Model/ReEDS/commit/43c4732d) (July 15, 2026) plus a single commit with all changes used in the analysis.
That commit includes:

- **Transmission operation development work by Patrick Brown (NLR)**, from the [`pb/trans_op_merge`](https://github.com/ajsbergman/ReEDS/tree/pb/trans_op_merge) branch, including interregional (transreg) transmission requirements and costs (`GSw_TransInterRegRatio`, `GSw_TransCostMultInterReg`), the first year of transmission expansion (`GSw_TransFirstYear`, `GSw_TransFirstYearInterReg`), a separate interconnection cost multiplier (`GSw_InterconnectionCostMult`), and transmission financial assumptions (`financials_trans_suffix`).
- **Permitting reform features added for this analysis:**
    - Time-varying multipliers on transmission and interconnection costs (`GSw_TransCostMultScen`; see [inputs/transmission/README_cost_mult.md](inputs/transmission/README_cost_mult.md)).
    - Reduced interconnection costs on federal land (`GSw_FedLandCostMult`, using `inputs/supply_curve/fed_land_fraction_{upv,wind-ons}.csv`).
    - Uprating of existing transmission capacity from advanced transmission technologies (`GSw_ATTCapMult`, `GSw_ATTStartYear`).
    - A near-term national onshore wind constraint (`GSw_WindConstraint`) and an on/off switch for the interconnection queue constraint (`GSw_InterconnectionQueues`).
    - Enforcement of certain planned transmission, and a fix to the UPV supply-curve cost (ILR conversion) in the time-varying supply-curve cost.
- **Reporting additions:** time-varying supply-curve cost in system cost reporting, retail rates by state, and additional outputs in the reduced bokehpivot report.

The full set of changes can be viewed by comparing this branch with `43c4732d`.


## Reproducing the scenarios in the brief

All 16 runs in the brief (eight Baseline / Full Package pairs) are defined in [`cases_baaja.csv`](cases_baaja.csv). After setting up ReEDS (see the quick-start guide below), run them with:

```
python runreeds.py -b <batch_prefix> -c baaja
```

| Scenario in the brief | Baseline case | Full Package case |
|---|---|---|
| Central | `Baseline` | `FullPackage` |
| Advanced Clean | `Baseline_AdvTech` | `FullPackage_AdvTech` |
| Conservative Clean | `Baseline_ConsTech` | `FullPackage_ConsTech` |
| High NG | `Baseline_HighNG` | `FullPackage_HighNG` |
| High NG + Advanced Clean | `Baseline_HighNG_AdvTech` | `FullPackage_HighNG_AdvTech` |
| Low NG | `Baseline_LowNG` | `FullPackage_LowNG` |
| Low NG + Advanced Clean | `Baseline_LowNG_AdvTech` | `FullPackage_LowNG_AdvTech` |
| Low NG + Conservative Clean | `Baseline_ConsTech_LowNG` | `FullPackage_ConsTech_LowNG` |

Notes on the run setup:

- **Model years:** the runs solve through 2041 (`endyear`). The present value of system cost "through 2050" reported in the brief uses the standard ReEDS system cost reporting (`Discounted through 2050` in bokehpivot), which annualizes capital costs and holds operating costs after the final model year at their final-year levels.
- **Resource adequacy weather years:** the runs use seven weather years, 2007–2013 (`resource_adequacy_years`), rather than the ReEDS default.
- **Software and platform:** the runs used GAMS 52.2.0 with CPLEX, using the solver settings in [reeds/solver/cplex.opt](reeds/solver/cplex.opt) (8 threads), on Linux (AWS EC2 r7a instances). CPLEX barrier results are deterministic for a given thread count and platform. On other platforms or software versions, expect results that match to within solver tolerance rather than exactly.


## Provenance

The brief's runs were made from commits on the [`rff_trans`](https://github.com/ajsbergman/ReEDS/tree/rff_trans) branch, which contains the full development history:

- The 12 Central, Advanced Clean, High NG, and Low NG runs were made at `564dc046` (cases file from `c4d11c41`), and their reports were generated with `afb7bb49`, which changed only cost reporting.
- The 4 Conservative Clean runs were made at `3a4dd66b`.

This branch differs from those commits only in ways that do not affect the brief's results:

- Switches and input files added for other sensitivities, which were off by default in the brief's runs, have been removed.
- Diagnostic checks on load data, which did not change any inputs, have been removed.
- The four Conservative Clean runs were made with a later version that caps the year-by-year supply-curve cost at $10M/MW, matching the cap ReEDS applies to the static supply-curve cost. This cap affects only three UPV supply-curve bins that are not built in any scenario, so it does not change results. The cap is not included in this branch, matching the other 12 runs.


<a name="About"></a>

## About ReEDS

The ReEDS model is developed by NLR. ReEDS training videos are available on the [NLR Learning YouTube channel](https://youtube.com/playlist?list=PLmIn8Hncs7bG558qNlmz2QbKhsv7QCKiC&si=NgGBaL_MxNcYiIEX).



<a name="Introduction"></a>

## Introduction

[ReEDS](https://www.nlr.gov/analysis/reeds/) is a capacity planning and dispatch model for the U.S. electricity system.

As NLR's flagship long-term power sector model, ReEDS has served as the primary analytic tool for [many studies](https://reeds-model.github.io/ReEDS/publications.html) of electricity sector research questions.
Example model results are available in the [Scenario Viewer](https://scenarioviewer.nlr.gov/).




<a name="Software"></a>

## Quick-start guide

The ReEDS model is written in [Python](https://www.python.org/), [GAMS](https://www.gams.com/), and [Julia](https://julialang.org/).
Python and Julia are free, open-source languages;
GAMS requires a software license from the vendor.
A step-by-step guide for getting started with ReEDS is available [here](https://reeds-model.github.io/ReEDS/setup.html), and a quick-start guide for advanced users is outlined below.

1. Install Python using the Anaconda Distribution: <https://www.anaconda.com/download/success>
2. Set up GAMS:
    1. Install GAMS: <https://www.gams.com/download/>
    2. Obtain a combined GAMS/CPLEX license: <https://www.gams.com/sales/licensing/>
        1. Small ReEDS systems have been solved using the open-source [COIN-OR](https://www.coin-or.org/) solver as described [here](https://www.nlr.gov/docs/fy21osti/77907.pdf), but this capability is not actively maintained.
        2. Other commercial solvers have also been successfully applied to ReEDS, but setup details and some solver tuning are specific to the CPLEX solver.
3. Install Julia version 1.12.1 as described in the [documentation](https://reeds-model.github.io/ReEDS/setup.html#reeds2pras-julia-and-stress-periods-setup):
    1. Follow the platform-dependent installation instructions at <https://julialang.org/downloads/> to install both `julia` and `juliaup`
    2. Specify version 1.12.1 by running:
        1. `juliaup add 1.12.1`
        2. `juliaup default 1.12.1`
4. Open a command-line interface and set up your environments:
    1. Clone this repository and check out the `rff_baaja` branch (or the `baaja-brief-2026-10` tag): `git clone -b rff_baaja https://github.com/ajsbergman/ReEDS.git`
    2. Navigate to the cloned repository
    3. Create the `reeds2` [conda environment](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html): `conda env create -f environment.yml`
    4. Activate the `reeds2` environment: `conda activate reeds2`
    5. Instantiate the Julia environment: `julia --project=. instantiate.jl`
    6. (Optional) Several large data files are hosted remotely.
    These files are downloaded automatically as needed during a ReEDS run, but to finish all the internet-requiring steps up front, you can download them all by running `python reeds/remote.py`.
    Additional details on remote files and other topics can be found in the [user guide](https://reeds-model.github.io/ReEDS/user_guide.html#large-input-files).
5. Run ReEDS on a test case from the root of the cloned repository:
    1. For interactive setup: `python runreeds.py`
    2. For one-line operation: `python runreeds.py -b v20250314_main -c test`.
    In this example, "v20250314_main" is the prefix for this batch of cases, and "test" is the suffix of the cases file, in this case `cases_test.csv`, located in the root of the repository.
    Run `python runreeds.py -h` for information on other optional command-line arguments for ReEDS.




<a name="Contact"></a>

## Contact Us

For questions about this modified version and the BAAJA analysis, please contact RFF. For questions about ReEDS itself, you can contact the ReEDS team at [ReEDS.Inquiries@nlr.gov](mailto:ReEDS.Inquiries@nlr.gov) or post a question on the [discussion pages](https://github.com/ReEDS-Model/ReEDS/discussions).
