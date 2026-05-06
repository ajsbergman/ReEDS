'''
Summarizes new PRs and issues since a given date.

To run: python summarize_prs_and_issues.py -l 20241201

Prior to running the first time, authenticate with GitHub: 
    gh auth login
'''

import os 
import sys
import subprocess
import json
import pandas as pd
from datetime import datetime
import argparse

## read in json files
def process_json(json_filename):
    with open(json_filename) as f:
        df_json = json.load(f)
    df = pd.json_normalize(df_json)
    df['createdAt'] = pd.to_datetime(df['createdAt'])
    df['closedAt'] = pd.to_datetime(df['closedAt'])
    return df

## save file
def save_file(df,filename):
    now = '{dt.year}{dt.month:02}{dt.day:02}'.format(dt=datetime.now())
    filename = f"{now}_{filename}.txt"
    if os.path.exists(filename):
        os.remove(filename)

    if isinstance(df, dict):
        with open(filename, 'a') as f:
            for key in df:
                f.writelines(key + "\n")
                for i, l in df[key].items():
                    if pd.notna(l):
                        f.writelines(l + "\n")
                f.writelines("\n")
    else:
        df.to_csv(filename, index=False, header=False, sep="\t")

    print(f"...saved {filename}")

## format list
def output_file(df, add_branch=True):
    df['first_name'] = df['author.name'].replace(".*, ", "", regex=True)
    df['first_name'] = df['first_name'].replace(" .*", "", regex=True)

    if 'isDraft' in df.columns:
        df['draft_status'] = df.isDraft.replace({True: " [Draft]", False: ""})
    else:
        df['draft_status'] = ""

    if add_branch and 'baseRefName' in df.columns:
        df['branch'] = df.baseRefName.replace({"main": ""})
    else:
        df['branch'] = ""

    return "-" + df.number.map(str) + ": " + df.title + " (" + df.first_name + ")" + \
           df.draft_status + " " + df.branch

def main():
    parser = argparse.ArgumentParser(description='Collect ReEDS PRs and Issues')
    parser.add_argument('--last_meeting', '-l', type=str, default=None, help='Date of last ReEDS meeting (YYYYMMDD)')
    args = parser.parse_args()

    if args.last_meeting is None:
        print("Please enter a last meeting date!")
        sys.exit()

    # assumes meetings occur at 1 pm MT
    last_meeting = pd.Timestamp(args.last_meeting, tz='America/Denver') + pd.tseries.offsets.Hour(13)
    today = pd.Timestamp.now(tz='America/Denver')
    print(f"Loading issues and PRs since {last_meeting}")

    home_path = os.path.dirname(os.path.realpath(__file__)) + '/'
    os.chdir(home_path)

    # remove old jsons
    for f in ["issues.json", "prs.json"]:
        if os.path.exists(f):
            os.remove(f)

    # run shell script to dump fresh data
    shellscript = subprocess.Popen([os.path.join(home_path, "dump_issues_prs.sh")], shell=True)
    shellscript.wait()

    prs = process_json("prs.json")
    issues = process_json("issues.json")

    combined = {
        "Issues": output_file(issues.loc[issues.createdAt.between(last_meeting, today)].copy()),
        "Open PRs": output_file(prs.loc[prs.closedAt.isna()].copy()),
        "Recently closed PRs": output_file(prs.loc[prs.closedAt.between(last_meeting, today)].copy()),
    }

    save_file(combined, "all")
    print("Finished summarizing issues and PRs")

if __name__ == "__main__":
    main()