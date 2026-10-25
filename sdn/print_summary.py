#!/usr/bin/env python3
"""
Print the baseline vs QoS table of an experiment (no sudo needed):
    python3 sdn/print_summary.py                    # latest experiment
    python3 sdn/print_summary.py results/experiments/<id>
Values are mean (min-max) over the valid runs; n = number of valid runs.
"""
import glob
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ROWS = [
    ('Video received (Mbit/s)', 'steady_video_mbps', 'host'),
    ('Video loss (%)', 'steady_video_loss_pct', 'host'),
    ('Video jitter (ms)', 'steady_video_jitter_ms', 'host'),
    ('Ping RTT avg (ms)', 'steady_ping_avg_ms', 'host'),
    ('Ping RTT max (ms)', 'steady_ping_max_ms', 'host'),
    ('Ping probes lost', 'steady_ping_lost', 'host'),
    ('Background received (Mbit/s)', 'steady_bg_mbps', 'host'),
    ('Background loss (%)', 'steady_bg_loss_pct', 'host'),
    ('Buffering events (model)', 'model_stall_count', 'model'),
    ('Buffering time s (model)', 'model_stall_time_s', 'model'),
    ('Congestion detected after (s)', 'ctl_congestion_detected_s', 'controller'),
    ('Reroute after (s)', 'ctl_reroute_s', 'controller'),
    ('Rule install (ms)', 'ctl_reroute_install_ms', 'controller'),
    ('Reroutes per run', 'ctl_reroutes', 'controller'),
    ('Util s4->s2 Path A', 'ctl_util_steady_s4->s2', 'controller'),
    ('Util s4->s3 Path B', 'ctl_util_steady_s4->s3', 'controller'),
    ('Drops queue 0 s4-eth2', 'tc_s4-eth2:q0_dropped', 'kernel tc'),
    ('Drops queue 1 s4-eth2', 'tc_s4-eth2:q1_dropped', 'kernel tc'),
]


def cell(g, key):
    m = g['metrics'].get(key) if g else None
    if not m:
        return '-'
    if m['min'] == m['max']:
        return '%.3g' % m['mean']
    return '%.3g (%.3g-%.3g)' % (m['mean'], m['min'], m['max'])


def main():
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        done = sorted(p for p in glob.glob(os.path.join(ROOT, 'results', 'experiments', '*'))
                      if os.path.exists(os.path.join(p, 'summary.json')))
        if not done:
            sys.exit('no finished experiment in results/experiments/')
        d = done[-1]
    s = json.load(open(os.path.join(d, 'summary.json')))
    groups = {(g['mode'], g['load']): g for g in s['groups']}
    print('Experiment %s' % os.path.basename(d.rstrip('/')))
    tl = s.get('timeline')
    if tl:
        print('Steady window: %s s to %s s of each run (background %s-%s s)' % (
            tl['windows']['steady'][0], tl['windows']['steady'][1], tl['bg_start'], tl['bg_end']))
    for load in ('light', 'heavy'):
        b, q = groups.get(('baseline', load)), groups.get(('qos', load))
        if not b and not q:
            continue
        print('\n%s load   (n valid: baseline %s, qos %s)' % (
            load.upper(), b and b['valid_runs'], q and q['valid_runs']))
        print('  %-31s %-24s %-24s %s' % ('metric', 'baseline', 'qos', 'source'))
        for label, key, src in ROWS:
            print('  %-31s %-24s %-24s %s' % (label, cell(b, key), cell(q, key), src))
        for g in (b, q):
            for inv in (g or {}).get('invalid', []):
                print('  invalid: %s run %s: %s' % (g['mode'], inv['run'], inv['problems']))
    print('\nNotes: one VM, Mininet emulation, links shaped by OVS HTB. Buffering is a playout')
    print('buffer MODEL fed by measured received video, not a real player. Delay, jitter and')
    print('loss are host measurements (ping, iperf3); the controller measures only rates.')


if __name__ == '__main__':
    main()
