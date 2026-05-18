#%% Imports
import os
import sys
import argparse
import shutil
import pandas as pd
import subprocess
import gdxpds
from glob import glob
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))
import reeds
from reeds.core.solve import heatRate_cf_adjustment as HR


#%% Main function
def run_reeds(casepath, t, iteration=0, onlygams=False, onlyra=False):
    """
    """
    # #%% Arguments for testing
    # casepath = os.path.expanduser('~/github/ReEDS/runs/v20230512_prasM0_ERCOT')
    # t = 2020
    # iteration = 0
    # onlygams = 0
    # onlyra = 0
    # os.chdir(casepath)

    #%% Get the run settings
    sw = reeds.io.get_switches(casepath)
    years = pd.read_csv(
        os.path.join(casepath,'inputs_case','modeledyears.csv')
    ).columns.astype(int).values
    tprev = {**{years[0]:years[0]}, **dict(zip(years[1:], years))}
    tnext = {**dict(zip(years, years[1:])), **{years[-1]:years[-1]}}

    #%%### Run GAMS LP
    if not onlyra:
        #%% Ensure heatRateData output directory exists for GEN_data export
        os.makedirs(os.path.join(casepath, 'outputs', 'heatRateData'), exist_ok=True)

        #%% Get the command to run GAMS for this solve year
        batch_case = os.path.basename(casepath)
        stress_year = f"{t}i{iteration}"
        ### Get the restartfile (last iteration from previous year)
        if t == min(years):
            restartfile = batch_case
        else:
            restartfile = sorted(
                glob(os.path.join(casepath,'g00files',f"{batch_case}_{tprev[t]}i*"))
            )[-1]

        cmd_gams = reeds.inputs.solvestring_sequential(
            batch_case=batch_case,
            caseSwitches=sw,
            cur_year=t,
            next_year=tnext[t],
            prev_year=tprev[t],
            stress_year=stress_year,
            restartfile=restartfile,
            hpc=int(sw['hpc']),
            iteration=iteration,
        )
        print(cmd_gams)

        ### Run GAMS LP
        result = subprocess.run(cmd_gams, shell=True)
        if result.returncode:
            raise Exception(f'3_solve_oneyear.gms failed with return code {result.returncode}')

        #%% Add solve time to run metadata
        try:
            cmd_log = (
                f"python {os.path.join(casepath, 'reeds', 'log.py')}"
                f" --year={t}\n"
            )
            subprocess.run(cmd_log, shell=True)
        except Exception as err:
            print(err)

        #%% Check to see if the restart file exists
        savefile = f"{batch_case}_{t}i{iteration}"
        if not os.path.isfile(os.path.join("g00files", savefile+".g00")):
            raise Exception(f"Missing {savefile}.g00")


    #%%### Run resource adequacy calculations
    if (not onlygams) and (tnext[t] > int(sw.GSw_SkipRAyear)):
        reeds.resource_adequacy.ra_calcs.main(
            t=t,
            tnext=tnext[t],
            casedir=casepath,
            iteration=iteration,
        )


#%% Driver function
def main(casepath, t, overwrite=False):
    """
    """
    ### Get the run settings
    sw = reeds.io.get_switches(casepath)
    years = pd.read_csv(
        os.path.join(casepath, 'inputs_case', 'modeledyears.csv')
    ).columns.astype(int).values
    tprev = {**{years[0]: years[0]}, **dict(zip(years[1:], years))}
    tnext = {**dict(zip(years, years[1:])), **{years[-1]: years[-1]}}

    max_iterations = max(
        int(sw.GSw_PRM_StressIterateMax),
        int(sw.GSw_HR_AdjIterateMax),
    )

    for iteration in range(max_iterations):

        stress_i = 0
        for i in range(20):
            if os.path.isfile(
                os.path.join(casepath, 'inputs_case', f'stress{t}i{i}', 'cf_vre.csv')
            ):
                stress_i = i
        print(f'iteration: {iteration}, PRAS iteration: {stress_i}')

        #%% If not overwriting, skip iterations that have already finished
        if (
            (not overwrite)
            ## Check if GAMS finished
            and os.path.isfile(
                os.path.join(
                    sw.casedir, 'g00files',
                    f"{os.path.basename(sw.casedir)}_{t}i{iteration}.g00"))
            ## Check if the output of hourly_writetimeseries.py for this year/iteration
            ## exists, indicating stress period calcluations finished (or that we're not
            ## using stress periods)
            and os.path.isfile(
                os.path.join(
                    sw.casedir, 'inputs_case', f'stress{t}i{iteration+1}', 'cf_vre.csv'))
            ## Check if resource adequacy calculations finished
            and os.path.isfile(
                os.path.join(
                    sw.casedir, 'handoff', 'reeds_data', f'ccdata_{t}.gdx'))
        ):
            print(f'Already ran {t}i{iteration} so continuing to next iteration')
            continue

        #%% Run ReEDS and RA calculations
        run_reeds(casepath, t, iteration=iteration)

        #%% Copy GEN data for HR iteration tracking
        heatrate_dir = os.path.join(casepath, 'outputs', 'heatRateData')
        os.makedirs(heatrate_dir, exist_ok=True)
        gen_data_src = os.path.join(heatrate_dir, f'GEN_data_{t}.gdx')
        if os.path.isfile(gen_data_src):
            shutil.copy(
                gen_data_src,
                os.path.join(heatrate_dir, f'GEN_data_{t}_{iteration}.gdx'),
            )

        #%% Check stress period convergence
        PRAS_satisfied = False
        if not os.path.isfile(
            os.path.join(
                sw.casedir, 'inputs_case', f'stress{t}i{stress_i+1}', 'period_szn.csv')
        ):
            print('No new stress periods to add, so moving to next solve year')
            PRAS_satisfied = True
        elif stress_i + 1 >= int(sw.GSw_PRM_StressIterateMax):
            print('Exceeded PRAS iteration limit, moving on')
            PRAS_satisfied = True
        else:
            print(f'NEUE threshold was not met, so performing iteration {stress_i+1}')

        #%% Check heat rate convergence
        HR_satisfied = False
        if float(sw.GSw_CF_Heatrate_adj):
            if t > min(years):
                output_HR_table, vom, fom = HR.heatrate_main(t, casepath, iteration)
                if iteration == 0:
                    # Compare against last iteration of the previous year
                    i_max = 0
                    for i in range(20):
                        if os.path.isfile(
                            os.path.join(heatrate_dir,
                                         f'heatrate_cf_adj_{tprev[t]}_{i}.csv')
                        ):
                            i_max = i
                    prev_output_HR = pd.read_csv(os.path.join(
                        heatrate_dir, f'heatrate_cf_adj_{tprev[t]}_{i_max}.csv'))
                else:
                    prev_output_HR = pd.read_csv(os.path.join(
                        heatrate_dir, f'heatrate_cf_adj_{t}_{iteration-1}.csv'))

                prev_output_HR.set_index(['i', 'v', 'r'], inplace=True)
                output_HR_table.set_index(['i', 'v', 'r'], inplace=True)

                diff = pd.merge(
                    left=output_HR_table.rename(columns={'HR_pct': 'new', 'Level': 'CAP_new'}),
                    right=prev_output_HR.rename(columns={'HR_pct': 'old', 'Level': 'CAP_old'}),
                    left_index=True, right_index=True, how='inner',
                )
                i_vals = diff.reset_index(drop=False).i
                diff['delta'] = diff.new - diff.old
                diff = diff.loc[
                    [('gas' in tech.lower() or 'coal' in tech.lower())
                     and ('h2' not in tech)
                     for tech in i_vals]
                ]
                diff['delta_wt'] = diff['delta'].abs() * diff['CAP_new']

                sq_weighted_diff = (
                    ((diff['delta_wt'] ** 2) / (diff['CAP_new'].sum())).sum()
                ) ** 0.5
                max_diff = diff['delta'].abs().max()
                print(f'Max HR diff: {max_diff}, RMS weighted diff: {sq_weighted_diff}')

                if sq_weighted_diff >= float(sw.GSw_HR_AdjThreshold):
                    HR_satisfied = False
                    print('Heat rate must be adjusted and more iterations performed')
                else:
                    HR_satisfied = True
                    print('Heat rate differences are adequate for moving on')
            else:
                output_HR_table, vom, fom = HR.heatrate_main(t, casepath, iteration)
                HR_satisfied = True

            if iteration + 1 >= int(sw.GSw_HR_AdjIterateMax):
                HR_satisfied = True
                print('Heat rate iteration count exceeds maximum, moving to next year')
        else:
            # HR adjustment is off; compute identity adjustments and mark satisfied
            output_HR_table, vom, fom = HR.heatrate_main(t, casepath, iteration)
            HR_satisfied = True

        #%% Break if either condition is satisfied
        if HR_satisfied or PRAS_satisfied:
            print(f'Satisfied, moving to {tnext[t]}')
            # Write final GDX files for next year
            # Ensure output_HR_table has i/v/r as columns (not index)
            if output_HR_table.index.names != [None]:
                output_HR_table = output_HR_table.reset_index(drop=False)
            output_HR_table_out = output_HR_table[['i', 'v', 'r', 'HR_pct']]

            data = {'heatrate_cf_adj': output_HR_table_out}
            gdxpds.to_gdx(
                data,
                os.path.join(heatrate_dir, f'heatrate_cf_adj{tnext[t]}.gdx'),
            )

            fom_out = fom[['i', 'v', 'r', 'OM_pct']]
            data = {'fom_cf_adj': fom_out}
            gdxpds.to_gdx(
                data,
                os.path.join(heatrate_dir, f'fom_cf_adj{tnext[t]}.gdx'),
            )

            vom_out = vom[['i', 'v', 'r', 'OM_pct']]
            data = {'vom_cf_adj': vom_out}
            gdxpds.to_gdx(
                data,
                os.path.join(heatrate_dir, f'vom_cf_adj{tnext[t]}.gdx'),
            )
            break

    ### Delete old restart files if desired
    years = pd.read_csv(
        os.path.join(casepath,'inputs_case','modeledyears.csv')
    ).columns.astype(int).values
    tprev = {**{years[0]:years[0]}, **dict(zip(years[1:], years))}

    if ((not int(sw['keep_g00_files'])) and (not int(sw['debug']))) and (min(years) < t):
        g00files = glob(os.path.join(casepath, 'g00files', f'*{tprev[t]}i*.g00'))
        for i in g00files:
            os.remove(i)


#%% Procedure
if __name__ == '__main__':
    #%% Argument inputs
    import argparse
    parser = argparse.ArgumentParser(description='Sequential ReEDS')
    parser.add_argument('casepath', type=str,
                        help='path to ReEDS run folder')
    parser.add_argument('t', type=int,
                        help='year to run')
    parser.add_argument('--iteration', '-i', type=int, default=0,
                        help='iteration counter for this run')
    parser.add_argument('--overwrite', '-o', action='store_true',
                        help='Overwrite iterations that have already finished')

    args = parser.parse_args()
    casepath = args.casepath
    t = args.t
    iteration = args.iteration
    overwrite = args.overwrite

    #%% Switch to run folder
    os.chdir(casepath)

    #%% Set up logger
    log = reeds.log.makelog(
        scriptname=__file__,
        logpath=os.path.join(casepath,'gamslog.txt'),
    )

    #%% Run it
    main(casepath=casepath, t=t, overwrite=overwrite)
