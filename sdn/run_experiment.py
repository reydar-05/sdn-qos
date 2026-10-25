#!/usr/bin/env python3
"""
Experiment runner: baseline vs QoS, light vs heavy load, N runs each.

Run with sudo and the SYSTEM python3 (scripts/run_experiments.sh does
this for you):
    sudo python3 sdn/run_experiment.py --mode both --load both --duration 60 --runs 3

For every run it:
 1. cleans old Mininet state, then starts a fresh Ryu controller as the
    normal user (sudo -u $SUDO_USER, from the project .venv) in the
    run's mode: baseline (static Path A, no queue, no reroute) or qos
    (priority queue + reroute)
 2. builds the same topology with the same OVS capacity and queues
 3. runs the same traffic: video (UDP port 5004) for the whole run,
    background on the same bottleneck from background_start_s, ping
    from the client every 0.2 s
 4. saves raw files, stops Ryu, tears the network down
Then it analyses every run (sdn/run_analysis.py) and writes
    results/experiments/<id>/meta.json     args, versions, timestamps
    results/experiments/<id>/config.yaml   exact config used
    results/experiments/<id>/runs.csv      one row per run (raw numbers)
    results/experiments/<id>/summary.json  mean/min/max/stdev per case
    results/experiments/<id>/summary.csv
    results/experiments/<id>/<mode>-<load>-run<k>/  all raw files
Runs are interleaved (run 1 of every case, then run 2, ...) so slow drift
on the VM affects every case equally. Runs where a host sender could not
send its full rate are marked invalid and left out of the summary.
"""
import argparse
import csv
import json
import os
import pwd
import shutil
import signal
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import PROJECT_ROOT, load_config  # noqa: E402
from labutil import (chown_to_sudo_user, dump_flows, run_traffic, sh, tc_class_stats,  # noqa: E402
                     wait_for_flows)
from run_analysis import analyse_run, flat_row, timeline  # noqa: E402
from topology import apply_qos, build_network, clear_qos, wait_for_controller  # noqa: E402

from mininet.log import setLogLevel  # noqa: E402

RYU = os.path.join(PROJECT_ROOT, '.venv', 'bin', 'ryu-manager')
WATCHDOG_EXTRA_S = 120   # a run taking longer than duration + this is aborted


class WatchdogTimeout(Exception):
    pass


def on_watchdog(signum, frame):
    raise WatchdogTimeout('run took longer than its time limit (watchdog)')
CONTROLLER = os.path.join(PROJECT_ROOT, 'sdn', 'controller.py')

# Numbers summarised per (mode, load). Keys are flat_row() column names.
SUMMARY_FIELDS = [
    'steady_video_mbps', 'steady_video_loss_pct', 'steady_video_jitter_ms',
    'steady_ping_avg_ms', 'steady_ping_max_ms', 'steady_ping_stdev_ms', 'steady_ping_lost',
    'steady_bg_mbps', 'steady_bg_loss_pct',
    'load_video_loss_pct', 'load_video_jitter_ms', 'load_ping_avg_ms', 'load_bg_loss_pct',
    'model_stall_count', 'model_stall_time_s', 'model_startup_delay_s',
    'ctl_congestion_detected_s', 'ctl_reroute_s', 'ctl_reroute_install_ms', 'ctl_reroutes',
    'ctl_util_steady_s4->s2', 'ctl_util_steady_s4->s3',
    'tc_s4-eth2:q0_dropped', 'tc_s4-eth2:q1_dropped', 'tc_s4-eth3:q0_dropped', 'tc_s4-eth3:q1_dropped',
]


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def listening(port):
    # Checked with ss, not by connecting: a non-OpenFlow connection would
    # make Ryu log a broken-switch error.
    return bool(sh("ss -ltnH 'sport = :%d'" % port).stdout.strip())


def start_ryu(cfg, mode, run_dir, run_id):
    """Start ryu-manager directly as the normal (sudo) user, not as root."""
    pw = pwd.getpwnam(os.environ['SUDO_USER'])
    port = cfg['controller']['openflow_port']
    env = dict(PATH='/usr/local/bin:/usr/bin:/bin', HOME=pw.pw_dir, USER=pw.pw_name,
               LANG=os.environ.get('LANG', 'C.UTF-8'),
               SDN_QOS_MODE=mode, SDN_QOS_RUN_DIR=run_dir, SDN_QOS_RUN_ID=run_id)
    cmd = [RYU, '--ofp-listen-host', cfg['controller']['openflow_host'],
           '--ofp-tcp-listen-port', str(port), '--observe-links', CONTROLLER]
    logf = open(os.path.join(run_dir, 'ryu.log'), 'w')
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT, env=env,
                            user=pw.pw_uid, group=pw.pw_gid, extra_groups=[])
    for _ in range(40):
        if proc.poll() is not None:
            raise RuntimeError('Ryu exited at start, see %s/ryu.log' % run_dir)
        if listening(port):
            return proc
        time.sleep(0.25)
    stop_ryu(proc)
    raise RuntimeError('Ryu did not open port %d' % port)


def stop_ryu(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def kill_traffic_leftovers():
    """Only the traffic processes this runner starts (by their exact options)."""
    sh("pkill -f '^iperf3 -s -1 -p ' ; pkill -f '^iperf3 -c 10\\.0\\.0\\.[0-9]+ -u ' ; "
       "pkill -f '^ping -D -O -i 0.2 '")


def snapshot(cfg, run_dir, label, store):
    with open(os.path.join(run_dir, 'flows_%s.txt' % label), 'w') as f:
        for s in cfg['topology']['switches']:
            f.write('--- %s\n%s\n' % (s, dump_flows(s)))
            f.write(sh('ovs-ofctl -O OpenFlow13 queue-stats %s' % s).stdout + '\n')
    store[label] = {intf: tc_class_stats(intf) for intf in ('s4-eth2', 's4-eth3')}


def run_one(cfg, exp_dir, mode, load, k):
    name = '%s-%s-run%d' % (mode, load, k)
    run_dir = os.path.join(exp_dir, name)
    host_dir = os.path.join(run_dir, 'hosts')
    os.makedirs(host_dir, exist_ok=True)
    chown_to_sudo_user(run_dir)  # Ryu runs as the normal user and writes here
    tl = timeline(cfg)
    bg = cfg['background']['%s_mbps' % load]
    info = dict(name=name, mode=mode, load=load, run=k, bg_mbps=bg, started=time.time())
    ryu = net = None
    qos_ports = []
    tc = {}
    limit = tl['duration'] + WATCHDOG_EXTRA_S
    signal.signal(signal.SIGALRM, on_watchdog)
    signal.alarm(limit)
    try:
        sh('mn -c')  # BEFORE starting Ryu: mn -c kills any ryu-manager
        ryu = start_ryu(cfg, mode, run_dir, os.path.basename(exp_dir) + '/' + name)
        net = build_network(cfg)
        qos_ports = apply_qos(cfg)
        states = wait_for_controller(net)
        if not all(states.values()):
            raise RuntimeError('switches not connected: %s' % states)
        if not wait_for_flows(list(cfg['topology']['switches']), 'nw_dst=', timeout=40):
            raise RuntimeError('controller did not install forwarding rules')
        time.sleep(2 * cfg['monitoring']['poll_interval_s'] + 1)
        hooks = {tl['bg_start'] - 2: lambda: snapshot(cfg, run_dir, 'before', tc),
                 tl['bg_end'] - 1: lambda: snapshot(cfg, run_dir, 'end_load', tc)}
        for t in range(15, tl['duration'], 15):   # "still alive" lines
            hooks.setdefault(t, lambda t=t: log('  ... %d/%d s of traffic' % (t, tl['duration'])))
        info['t0'] = run_traffic(net, cfg, host_dir, tl['duration'],
                                 [(tl['bg_start'], tl['bg_end'], bg, load)], hooks)
        time.sleep(cfg['monitoring']['poll_interval_s'] + 1)  # last metrics land
    except Exception as e:  # keep going with the other runs (includes the watchdog)
        info['error'] = '%s: %s' % (type(e).__name__, e)
        log('run %s FAILED: %s' % (name, info['error']))
    finally:
        signal.alarm(0)  # cleanup itself must not be interrupted
        kill_traffic_leftovers()
        if net is not None:
            clear_qos(qos_ports)
            net.stop()
        stop_ryu(ryu)
        with open(os.path.join(run_dir, 'tc.json'), 'w') as f:
            json.dump(tc, f)
        info['finished'] = time.time()
        with open(os.path.join(run_dir, 'run.json'), 'w') as f:
            json.dump(info, f, indent=1)
        chown_to_sudo_user(run_dir)
    return info


def analyse(cfg, exp_dir, infos):
    rows, results = [], {}
    for info in infos:
        meta = dict(name=info['name'], mode=info['mode'], load=info['load'], run=info['run'],
                    bg_mbps=info['bg_mbps'])
        if 'error' in info or 't0' not in info:
            rows.append(dict(meta, valid=False, problems=info.get('error', 'no traffic run')))
            continue
        r = analyse_run(cfg, os.path.join(exp_dir, info['name']), info['t0'], info['load'], info['bg_mbps'])
        results[info['name']] = r
        with open(os.path.join(exp_dir, info['name'], 'analysis.json'), 'w') as f:
            json.dump(r, f, indent=1)
        rows.append(flat_row(meta, r))
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols]
    with open(os.path.join(exp_dir, 'runs.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return rows


def summarise(rows):
    groups = []
    for mode in ('baseline', 'qos'):
        for load in ('light', 'heavy'):
            case = [r for r in rows if r['mode'] == mode and r['load'] == load]
            if not case:
                continue
            valid = [r for r in case if r.get('valid') in (True, 'True')]
            g = dict(mode=mode, load=load, runs=len(case), valid_runs=len(valid),
                     invalid=[dict(run=r['run'], problems=r.get('problems')) for r in case if r not in valid],
                     metrics={})
            for f in SUMMARY_FIELDS:
                xs = []
                for r in valid:
                    try:
                        if r.get(f) not in (None, ''):
                            xs.append(float(r[f]))
                    except (TypeError, ValueError):
                        pass
                if xs:
                    g['metrics'][f] = dict(mean=round(statistics.mean(xs), 4), min=min(xs), max=max(xs),
                                           stdev=round(statistics.stdev(xs), 4) if len(xs) > 1 else None,
                                           n=len(xs), values=xs)
            groups.append(g)
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=['baseline', 'qos', 'both'], default='both')
    ap.add_argument('--load', choices=['light', 'heavy', 'both'], default='both')
    ap.add_argument('--duration', type=int, help='seconds per run (default from config)')
    ap.add_argument('--runs', type=int, help='runs per case (default from config)')
    ap.add_argument('--name', default='', help='optional label added to the experiment id')
    args = ap.parse_args()
    if os.geteuid() != 0 or 'SUDO_USER' not in os.environ:
        sys.exit('Run with sudo from your normal user: bash scripts/run_experiments.sh')
    setLogLevel('warning')
    cfg = load_config()
    if args.duration:
        cfg['experiment']['duration_s'] = args.duration
    runs = args.runs or cfg['experiment']['runs']
    tl = timeline(cfg)
    if tl['bg_end'] - tl['bg_start'] <= cfg['experiment']['settle_s']:
        sys.exit('duration too short: no steady window left after settle_s')
    modes = ['baseline', 'qos'] if args.mode == 'both' else [args.mode]
    loads = ['light', 'heavy'] if args.load == 'both' else [args.load]
    plan = [(k, load, mode) for k in range(1, runs + 1) for load in loads for mode in modes]

    exp_id = time.strftime('%Y%m%d-%H%M%S') + ('-' + args.name if args.name else '')
    exp_dir = os.path.join(PROJECT_ROOT, cfg['results']['dir'], 'experiments', exp_id)
    os.makedirs(exp_dir)
    shutil.copy(cfg['_path'], os.path.join(exp_dir, 'config.yaml'))
    meta = dict(id=exp_id, started=time.time(), started_local=time.strftime('%Y-%m-%d %H:%M:%S'),
                args=dict(mode=args.mode, load=args.load, duration_s=tl['duration'], runs=runs),
                timeline=tl, config=cfg['_path'], plan=['%s-%s-run%d' % (m, l, k) for k, l, m in plan],
                versions=dict(
                    kernel=sh('uname -r').stdout.strip(),
                    ovs=sh('ovs-vsctl --version').stdout.splitlines()[0],
                    mininet=sh('mn --version').stdout.strip() or sh('mn --version').stderr.strip(),
                    iperf3=sh('iperf3 --version').stdout.splitlines()[0],
                    ryu=sh('%s --version' % RYU).stdout.strip() or sh('%s --version' % RYU).stderr.strip()),
                note='Mininet emulation on one VM; links shaped by OVS linux-htb; '
                     'video is iperf3 UDP, buffering is a playout buffer model.')
    with open(os.path.join(exp_dir, 'meta.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    chown_to_sudo_user(exp_dir)
    per_run = tl['duration'] + 30
    log('experiment %s: %d runs, about %d min. A new run starts about every %d s; '
        'a stuck run is aborted after %d s and the next one starts.'
        % (exp_id, len(plan), len(plan) * per_run // 60 + 1, per_run, tl['duration'] + WATCHDOG_EXTRA_S))

    infos = []
    try:
        for i, (k, load, mode) in enumerate(plan, 1):
            log('run %d/%d: %s, %s load, run %d' % (i, len(plan), mode, load, k))
            infos.append(run_one(cfg, exp_dir, mode, load, k))
            rows = analyse(cfg, exp_dir, infos)   # partial results survive a crash
            last = rows[-1]
            log('  valid=%s video loss %s%% ping %s ms reroutes %s %s' % (
                last.get('valid'), last.get('steady_video_loss_pct'), last.get('steady_ping_avg_ms'),
                last.get('ctl_reroutes'), last.get('problems') or ''))
    finally:
        sh('mn -c')
        rows = analyse(cfg, exp_dir, infos) if infos else []
        groups = summarise(rows)
        summary = dict(id=exp_id, finished=time.time(), groups=groups, timeline=tl,
                       note=meta['note'], fields=SUMMARY_FIELDS,
                       windows_explained={'steady': 'from settle_s after background start to background end',
                                          'load': 'whole background period'})
        with open(os.path.join(exp_dir, 'summary.json'), 'w') as f:
            json.dump(summary, f, indent=1)
        with open(os.path.join(exp_dir, 'summary.csv'), 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['mode', 'load', 'valid_runs', 'metric', 'mean', 'min', 'max', 'stdev', 'n'])
            for g in groups:
                for m, s in g['metrics'].items():
                    w.writerow([g['mode'], g['load'], g['valid_runs'], m, s['mean'], s['min'], s['max'],
                                s['stdev'], s['n']])
        meta['finished'] = time.time()
        with open(os.path.join(exp_dir, 'meta.json'), 'w') as f:
            json.dump(meta, f, indent=1)
        chown_to_sudo_user(exp_dir)
        log('done: %s' % exp_dir)


if __name__ == '__main__':
    main()
