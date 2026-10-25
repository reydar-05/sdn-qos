#!/usr/bin/env python3
"""
Side-by-side comparison of the Phase 3 scenarios (baseline, queue_only,
qos) from their summary.json files. No sudo needed:
    python3 sdn/compare_phase3.py results/verify/phase3-<ts>
All numbers are host-side (iperf3, ping) or kernel tc counters measured in
that run; one run per scenario, so treat differences as indicative only.
"""
import json
import os
import sys

SCENARIOS = ['baseline', 'queue_only', 'qos']


def fmt(x, spec):
    return spec % x if x is not None else '-'


def main():
    root = sys.argv[1]
    runs = {}
    for s in SCENARIOS:
        p = os.path.join(root, s, 'summary.json')
        if os.path.exists(p):
            runs[s] = json.load(open(p))
    if not runs:
        sys.exit('no summary.json found under %s' % root)
    print('Phase 3 comparison (one 60 s run each, video %s Mbit/s, background %s Mbit/s from 10-50 s)'
          % (next(iter(runs.values()))['video_mbps'], next(iter(runs.values()))['bg_mbps']))
    rows = [
        ('video Mbit/s', 'video_mbps', '%.2f'),
        ('video loss %', 'video_loss_pct', '%.2f'),
        ('video jitter ms', 'jitter_ms', '%.3f'),
        ('ping avg ms', 'ping_avg_ms', '%.2f'),
        ('ping max ms', 'ping_max_ms', '%.2f'),
        ('ping lost', 'ping_lost', '%d'),
        ('background Mbit/s', 'bg_mbps', '%.2f'),
        ('background loss %', 'bg_loss_pct', '%.1f'),
    ]
    for window in ('heavy_early', 'heavy_late'):
        print('\nWindow %s (%s)' % (window, '10-20 s: detection/reroute happen here'
                                    if window == 'heavy_early' else '20-50 s: steady state'))
        print('  %-20s' % 'metric' + ''.join('%14s' % s for s in runs))
        for label, key, spec in rows:
            print('  %-20s' % label + ''.join(
                '%14s' % fmt(runs[s]['host'].get(window, {}).get(key), spec) for s in runs))
    print('\nSender rate (whole run, from the iperf3 senders)')
    for label, key in (('video sent Mbit/s', 'sent_video_mbps'), ('backgr. sent Mbit/s', 'sent_bg_mbps')):
        print('  %-20s' % label + ''.join('%14s' % fmt(runs[s].get(key), '%.2f') for s in runs))
    print('\nController side')
    print('  %-20s' % 'congestion detected' + ''.join(
        '%14s' % fmt(runs[s]['congestion_detected_s'], '%.1f s') for s in runs))
    print('  %-20s' % 'reroutes' + ''.join('%14d' % len(runs[s]['reroutes']) for s in runs))
    print('  %-20s' % 'reroute at' + ''.join(
        '%14s' % (fmt(runs[s]['reroutes'][0]['ts'] - runs[s]['t0'] - runs[s]['background'][0], '+%.1f s')
                  if runs[s]['reroutes'] else '-') for s in runs))
    print('  %-20s' % 'rule install' + ''.join(
        '%14s' % (fmt(runs[s]['reroute_confirmed'][0]['install_ms'], '%.1f ms')
                  if runs[s]['reroute_confirmed'] else '-') for s in runs))
    print('\nKernel HTB drops on s4-eth2 (Path A bottleneck) during heavy load')
    for cls, label in (('1:1', 'queue 0 (default)'), ('1:2', 'queue 1 (video)')):
        print('  %-20s' % label + ''.join(
            '%14s' % fmt(runs[s]['tc_heavy'].get('s4-eth2 ' + cls, {}).get('dropped'), '%d') for s in runs))
    print('\nChecks')
    for s in runs:
        failed = [n for n, ok in runs[s]['checks'] if not ok]
        print('  %-11s %d/%d passed%s' % (s, len(runs[s]['checks']) - len(failed), len(runs[s]['checks']),
                                         ('  FAILED: ' + '; '.join(failed)) if failed else ''))


if __name__ == '__main__':
    main()
