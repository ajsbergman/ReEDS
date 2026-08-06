"""Log system and per-run memory/cpu usage while ReEDS runs.

Launch it alongside a batch and leave it alone -- it stops on its own 30 minutes
after the last ReEDS process exits.

    nohup python helpers/monitor.py &                 # -> monitor.csv
    nohup python helpers/monitor.py bigbatch.csv &    # keep one under its own name
    nohup python helpers/monitor.py -i 10 -e 0 &      # 10s samples, run until killed

Order does not matter. Runs are discovered from process command lines on every
tick, so starting before, during, or after `runreeds.py` all work; start it first
if you want a baseline of the machine at rest. Starting first is safe because the
exit-when-idle countdown only arms once a run has actually been seen. The flip
side of that: if no ReEDS run ever shows up, nothing arms it and it keeps going
until killed with `pkill -f monitor.py`.

Run one per machine, not one per batch. A single monitor attributes every sample
to whichever run produced it, so it covers concurrent and back-to-back batches
alike. A second monitor launched while one is live refuses and exits rather than
corrupting the first one's csv.

Output is one row per tracked process per tick -- roughly 10-16 rows per tick with
three runs going -- and the headline peaks are appended as '#' comment lines. The
mem/cpu/disk columns are machine-wide, counting everything on the box rather than
just ReEDS, and repeat identically across the rows of a tick:

    df = pd.read_csv('monitor.csv', comment='#')
    df.groupby('timestamp')[['mem_used_gb', 'cpu_pct_sys']].first().max()
    df.groupby(['case', 'phase'])['rss_gb'].max()            # peak by phase
    df.groupby(['timestamp', 'case'])['rss_gb'].sum().max()  # peak run footprint
"""
#%% Imports
import os
import re
import sys
import csv
import time
import signal
import argparse
import datetime
import psutil

# #%% Inputs for debugging
# outfile = 'monitor.csv'
# interval = 30
# exit_when_idle = 30

#%%### Constants
### Every ReEDS worker process names its own run directory somewhere in its
### command line (--reedscase= for PRAS, --casedir= for GAMS setup, a bare path
### argument for the input-processing and solve scripts), or else runs with the
### case directory as its working directory. Runs are therefore discovered fresh
### on every tick -- never from a one-time scan of runs/, which would miss every
### run created after the monitor started.
RUNDIR = re.compile(r'[/\\]runs[/\\](v\d{8}_\d{6}_[^/\\ ]+)')
BATCHCASE = re.compile(r'^(v\d{8}_\d{6})_(.+)$')
YEAR = re.compile(r'--(?:solve_year|cur_year)[= ](\d{4})')
BARE_YEAR = re.compile(r'(?:^|\s)(20\d{2})(?:\s|$)')

### Checked in order; first match wins
PHASES = [
    ('run_pras.jl', 'pras'),
    ('3_solve_oneyear.gms', 'gams_solve'),
    ('a_createmodel.gms', 'gams_setup'),
    ('report.gms', 'gams_report'),
    ('input_processing', 'inputs'),
    ('solve/solve.py', 'solve'),
    ('report_dump.py', 'postprocess'),
    ('retail_rate_calculations.py', 'postprocess'),
    ('health_damage_calculations.py', 'postprocess'),
    ('reeds_to_rev.py', 'postprocess'),
    ('single_case_plots.py', 'plots'),
    ('diagnostic_plots.py', 'plots'),
    ('runreeds.py', 'batch'),
]

### The first five are machine-wide and repeat on every row of a tick; the rest
### describe the one process the row is about. Note the two cpu columns are on
### different scales: cpu_pct_sys is 0-100 across the whole machine, while a
### single process's cpu_pct can reach 100 per core it keeps busy.
COLUMNS = [
    'timestamp', 'mem_used_gb', 'mem_avail_gb', 'cpu_pct_sys', 'disk_avail_gb',
    'batch', 'case', 'phase', 'year', 'pid', 'proc', 'rss_gb', 'cpu_pct',
]

### Positions of the fields read back by update_peaks, named so that inserting a
### column stays a one-line change. The I_ prefix keeps them clear of the regexes
I_TIME, I_MEM, I_CPUSYS, I_DISK, I_BATCH, I_CASE, I_PHASE, I_YEAR, I_PID, I_RSS = (
    COLUMNS.index(c) for c in
    ['timestamp', 'mem_used_gb', 'cpu_pct_sys', 'disk_avail_gb',
     'batch', 'case', 'phase', 'year', 'pid', 'rss_gb'])

GB = 1024**3


#%%### Functions
def find_running_monitor():
    """Return (pid, outfile) of another live monitor.py, or None"""
    me = psutil.Process(os.getpid())
    mine = (me.create_time(), me.pid)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        if proc.info['pid'] == me.pid:
            continue
        ## Require an actual interpreter, so wrappers whose command line merely
        ## mentions this script (timeout, nohup, a launching shell) don't match
        if not (proc.info['name'] or '').startswith('python'):
            continue
        cmdline = proc.info['cmdline'] or []
        if not any(c.endswith('monitor.py') for c in cmdline):
            continue
        ## Only stand down for a monitor that started before us. Two launched
        ## in the same instant would otherwise both defer, leaving none running
        if (proc.info['create_time'], proc.info['pid']) >= mine:
            continue
        ## The output file is the first positional argument after the script
        after = cmdline[[i for i, c in enumerate(cmdline)
                         if c.endswith('monitor.py')][0] + 1:]
        positional = [c for c in after if not c.startswith('-')]
        return proc.info['pid'], (positional[0] if positional else 'monitor.csv')
    return None


def classify(cmdline):
    """Map a command line to a coarse ReEDS phase label"""
    for needle, phase in PHASES:
        if needle in cmdline:
            return phase
    return 'other'


def get_year(cmdline):
    """Pull the solve year off a command line if it advertises one"""
    match = YEAR.search(cmdline)
    if match:
        return match.group(1)
    ## solve.py takes the year as a bare trailing argument
    if 'solve/solve.py' in cmdline:
        match = BARE_YEAR.search(cmdline)
        if match:
            return match.group(1)
    return ''


def get_run(proc, cmdline):
    """Identify the run a process belongs to, by command line then by cwd"""
    match = RUNDIR.search(cmdline)
    if not match:
        try:
            match = RUNDIR.search(proc.cwd())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return '', ''
    if not match:
        return '', ''
    rundir = match.group(1)
    split = BATCHCASE.match(rundir)
    return split.groups() if split else ('', rundir)


def sample(cache):
    """One pass over the process table; returns rows for tracked processes"""
    now = datetime.datetime.now().replace(microsecond=0).isoformat()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    ## interval=None averages over the time since the previous call, i.e. the
    ## whole sampling interval, rather than blocking here to measure a window
    header = [now, round((mem.total - mem.available) / GB, 2),
              round(mem.available / GB, 2), round(psutil.cpu_percent(), 1),
              round(disk.free / GB, 2)]
    me = os.getpid()

    rows = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        pid = proc.info['pid']
        if pid == me:
            continue
        cmdline = ' '.join(proc.info['cmdline'] or [])
        if not cmdline:
            continue
        batch, case = get_run(proc, cmdline)
        ## Track anything belonging to a run, plus the batch launcher itself
        if not batch and 'runreeds.py' not in cmdline:
            continue
        try:
            ## Reuse Process objects so cpu_percent() measures a real interval
            if pid not in cache:
                cache[pid] = psutil.Process(pid)
                cache[pid].cpu_percent()
            rss = cache[pid].memory_info().rss
            cpu = cache[pid].cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cache.pop(pid, None)
            continue
        rows.append(header + [batch, case, classify(cmdline), get_year(cmdline),
                              pid, proc.info['name'], round(rss / GB, 3), round(cpu, 1)])

    ## Log system totals even when nothing ReEDS-related is running
    if not rows:
        rows.append(header + ['', '', 'idle', '', '', '', 0.0, 0.0])
    for pid in set(cache) - {r[I_PID] for r in rows}:
        cache.pop(pid, None)
    return rows


def update_peaks(peaks, rows):
    """Track running maxima so the summary needs no second pass over the csv"""
    used, cpu, disk = rows[0][I_MEM], rows[0][I_CPUSYS], rows[0][I_DISK]
    if used > peaks['sys'][0]:
        peaks['sys'] = (used, rows[0][I_TIME])
    if cpu > peaks['cpu'][0]:
        peaks['cpu'] = (cpu, rows[0][I_TIME])
    if disk < peaks['disk'][0]:
        peaks['disk'] = (disk, rows[0][I_TIME])
    ## A run's footprint is all of its processes at once -- solve.py holding
    ## prepped data while julia parses, say -- so sum them before comparing
    totals = {}
    for row in rows:
        if not row[I_CASE]:
            continue
        entry = totals.setdefault((row[I_BATCH], row[I_CASE]), [0.0, 0.0, '', ''])
        entry[0] += row[I_RSS]
        if row[I_RSS] >= entry[1]:
            ## Label the peak by whichever process dominates it
            entry[1], entry[2], entry[3] = row[I_RSS], row[I_PHASE], row[I_YEAR]
    for key, (total, _, phase, year) in totals.items():
        if total > peaks['runs'].get(key, (0,))[0]:
            peaks['runs'][key] = (total, phase, year, rows[0][I_TIME])


def summarize(peaks):
    """Headline numbers, as '#' comment lines for the csv and plain for stdout"""
    total = round(psutil.virtual_memory().total / GB, 1)
    lines = [
        f"peak system memory: {peaks['sys'][0]:.1f} GB used / {total} GB"
        f"  (at {peaks['sys'][1]})",
        f"peak system cpu: {peaks['cpu'][0]:.0f}% of {psutil.cpu_count()} cores"
        f"  (at {peaks['cpu'][1]})",
        f"min disk free: {peaks['disk'][0]:.1f} GB  (at {peaks['disk'][1]})",
    ]
    if peaks['runs']:
        lines.append('peak by run:')
        for (batch, case), (rss, phase, year, when) in sorted(
                peaks['runs'].items(), key=lambda kv: -kv[1][0]):
            year = f', {year}' if year else ''
            lines.append(f"    {batch}_{case}: {rss:.1f} GB ({phase}{year}, {when})")
    else:
        lines.append('peak by run: no ReEDS processes seen')
    return lines


#%% Procedure
if __name__ == '__main__':
    #%% Argument inputs
    parser = argparse.ArgumentParser(
        description='Log system and per-run memory/cpu while ReEDS runs',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('outfile', type=str, nargs='?', default='monitor.csv',
                        help='csv to write (overwritten on start)')
    parser.add_argument('--interval', '-i', type=int, default=30,
                        help='seconds between samples')
    parser.add_argument('--exit-when-idle', '-e', type=int, default=30,
                        help='stop after this many minutes with no ReEDS '
                             'processes; 0 to run until killed. The countdown '
                             'only starts once a run has been seen, so it is '
                             'safe to launch this before the batch')

    args = parser.parse_args()

    #%% Refuse to double-start, before touching the output file
    other = find_running_monitor()
    if other:
        print(f'monitor already running (pid {other[0]}), writing to {other[1]}')
        print('not starting a second one -- it would corrupt that file')
        sys.exit(1)

    #%% Run it
    stopping = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.append(True))

    peaks = {'sys': (0.0, ''), 'cpu': (0.0, ''), 'disk': (float('inf'), ''),
             'runs': {}}
    cache = {}
    ## Prime the system-wide counter; the short pause gives the first tick a real
    ## measurement window instead of the 0.0 it would report over no elapsed time
    psutil.cpu_percent()
    time.sleep(0.1)
    seen_a_run = False
    idle_since = None

    print(f'monitor -> {args.outfile} (interval {args.interval}s)', flush=True)
    with open(args.outfile, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        while not stopping:
            rows = sample(cache)
            writer.writerows(rows)
            f.flush()
            update_peaks(peaks, rows)

            ## Idle timer only arms after the first run appears, so starting
            ## the monitor ahead of the batch never trips it
            active = any(row[I_CASE] for row in rows)
            if active:
                seen_a_run, idle_since = True, None
            elif seen_a_run and idle_since is None:
                idle_since = time.time()
            if (args.exit_when_idle and idle_since
                    and time.time() - idle_since > args.exit_when_idle * 60):
                print(f'no ReEDS processes for {args.exit_when_idle} min, stopping',
                      flush=True)
                break

            for _ in range(args.interval):
                if stopping:
                    break
                time.sleep(1)

        for line in summarize(peaks):
            f.write(f'# {line}\n')
            print(line, flush=True)
