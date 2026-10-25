#!/usr/bin/env python3
"""
Phase 2 verification: monitoring and congestion detection with real traffic.

Needs the Ryu controller already running and writing to --run-dir
(scripts/verify_phase2.sh does both). Run with sudo and the SYSTEM python3:
    sudo python3 sdn/verify_phase2.py --run-dir results/verify/phase2-<ts>

Traffic timeline (all iperf3 UDP, all in the server -> client direction,
so background and video share the same links s4->s2->s1):
    0-12 s   video only (4 Mbit/s)                 -> about 40% on Path A
    12-30 s  video + light background (3 Mbit/s)   -> about 70%, under threshold
    30-50 s  video + heavy background (9 Mbit/s)   -> link full, congestion
    50-62 s  video only                            -> congestion clears
h1 pings h2 every 0.2 s the whole time (host-side delay measurement).
Phase 2 does NOT reroute: this run only proves that the controller sees
the load rise and fall and detects congestion correctly.
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import load_config  # noqa: E402
from labutil import iperf3_json, sh  # noqa: E402
from topology import apply_qos, build_network, clear_qos, wait_for_controller  # noqa: E402
from labutil import wait_for_flows  # noqa: E402

from mininet.log import setLogLevel  # noqa: E402

WINDOWS = [('video_only', 0, 12), ('light', 12, 30), ('heavy', 30, 50), ('after', 50, 62)]
SETTLE_S = 4   # ignore the first seconds of each window when averaging

results = []


def check(name, ok, detail=''):
    results.append((name, ok))
    print('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def header(text):
    print('\n' + '=' * 70 + '\n' + text + '\n' + '=' * 70)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def window_of(rel):
    for name, a, b in WINDOWS:
        if a <= rel < b:
            return name
    return None


def run_traffic(net, cfg, host_dir):
    v, bg = cfg['video'], cfg['background']
    server, client, bghost = net.get(v['server']), net.get(v['client']), net.get(bg['host'])
    total = WINDOWS[-1][2]
    pids = [server.cmd('iperf3 -s -p %d > %s/iperf_server_video.log 2>&1 & echo $!'
                       % (v['port'], host_dir)).strip(),
            server.cmd('iperf3 -s -p %d > %s/iperf_server_bg.log 2>&1 & echo $!'
                       % (bg['port'], host_dir)).strip()]
    time.sleep(1)
    t0 = time.time()
    client.cmd('ping -D -i 0.2 -w %d %s > %s/ping.log 2>&1 &' % (total, server.IP(), host_dir))
    client.cmd('iperf3 -c %s -u -R -p %d -b %dM -t %d -J > %s/iperf_video.json 2>&1 &'
               % (server.IP(), v['port'], v['bitrate_mbps'], total, host_dir))
    for name, start, end in WINDOWS:
        while time.time() - t0 < start:
            time.sleep(0.1)
        rate = {'light': bg['light_mbps'], 'heavy': bg['heavy_mbps']}.get(name)
        print('  t=%5.1fs  window %-10s background %s' % (time.time() - t0, name,
                                                          '%s Mbit/s' % rate if rate else 'off'))
        if rate:
            bghost.cmd('iperf3 -c %s -u -R -p %d -b %dM -t %d -J > %s/iperf_bg_%s.json 2>&1 &'
                       % (server.IP(), bg['port'], rate, end - start - 1, host_dir, name))
    while time.time() - t0 < total + 3:
        time.sleep(0.2)
    for pid in pids:
        if pid.isdigit():
            server.cmd('kill %s' % pid)
    return t0


def analyse(cfg, run_dir, host_dir, t0):
    mon = cfg['monitoring']
    th = mon['utilization_threshold']
    end = t0 + WINDOWS[-1][2]
    metrics = [m for m in read_jsonl(os.path.join(run_dir, 'metrics.jsonl')) if t0 <= m['ts'] <= end + 2]
    events = [e for e in read_jsonl(os.path.join(run_dir, 'events.jsonl')) if e['ts'] >= t0 - 1]
    v = cfg['video']
    watch = ['s4->s2', 's2->s1', 's4->s3', 's3->s1']

    header('Controller metrics, one row per poll (utilization = tx rate / capacity)')
    print('   t(s) window      ' + ' '.join('%-15s' % l for l in watch) + ' video@s4  congested')
    per_window = {}
    for m in metrics:
        rel = m['ts'] - t0
        w = window_of(rel) or '-'
        cells = []
        for l in watch:
            x = m['links'].get(l)
            cells.append('%5.2fM %4.0f%%%s' % (x['mbps'], 100 * x['utilization'], '*' if x['stale'] else ' ')
                         if x else '%-15s' % '-')
        print('  %5.1f %-11s ' % (rel, w) + ' '.join('%-15s' % c for c in cells) +
              ' %6.2fM  %s' % (m['video_mbps_by_switch'].get('s4', 0), ','.join(m['congested_links']) or '-'))
        if w != '-':
            start = dict((n, a) for n, a, _ in WINDOWS)[w]
            if rel - start >= SETTLE_S and 's4->s2' in m['links']:
                per_window.setdefault(w, []).append(m)
    print('  (* = stale: switch did not answer this poll, last value kept)')

    header('Events during the run')
    for e in events:
        if e['event'].startswith('congestion') or e['event'] == 'stats_missing':
            print('  t=%5.1fs %s %s' % (e['ts'] - t0, e['event'],
                                       {k: e[k] for k in e if k not in ('ts', 'event')}))

    header('Checks')
    expected_polls = WINDOWS[-1][2] / mon['poll_interval_s']
    check('metrics recorded every poll', len(metrics) >= 0.8 * expected_polls,
          '(%d records, about %d expected)' % (len(metrics), expected_polls))

    def avg(w, link, field='utilization'):
        xs = [m['links'][link][field] for m in per_window.get(w, []) if link in m['links']]
        return sum(xs) / len(xs) if xs else None

    vid_expect = v['bitrate_mbps'] / cfg['links']['default_capacity_mbps']
    u = avg('video_only', 's4->s2')
    check('video only: s4->s2 near video rate', u is not None and abs(u - vid_expect) < 0.15,
          '(avg %.2f, expected about %.2f)' % (u or -1, vid_expect))
    u = avg('light', 's4->s2')
    check('light load: utilization rises but stays under threshold',
          u is not None and vid_expect + 0.1 < u < th, '(avg %.2f, threshold %.2f)' % (u or -1, th))

    def ev_in(kind, w, link='s4->s2'):
        a, b = [(s, e) for n, s, e in WINDOWS if n == w][0]
        return [e for e in events if e['event'] == kind and e.get('link') == link
                and a <= e['ts'] - t0 < b + (SETTLE_S if kind.endswith('cleared') else 0)]

    check('light load: no congestion detected', not ev_in('congestion_detected', 'light'))
    u = avg('heavy', 's4->s2')
    check('heavy load: utilization over threshold', u is not None and u > th,
          '(avg %.2f, threshold %.2f)' % (u or -1, th))
    det = ev_in('congestion_detected', 'heavy')
    heavy_start = [s for n, s, _ in WINDOWS if n == 'heavy'][0]
    max_delay = (mon['consecutive_polls'] + 2) * mon['poll_interval_s']
    check('heavy load: congestion detected on s4->s2', bool(det),
          '(%.1f s after heavy load started; at most about %d s expected for %d polls of %d s)'
          % (det[0]['ts'] - t0 - heavy_start, max_delay, mon['consecutive_polls'],
             mon['poll_interval_s']) if det else '')
    check('detected event says the link is on the video path', bool(det) and det[0]['on_video_path'])
    check('congestion cleared after heavy load stopped', bool(ev_in('congestion_cleared', 'after')))
    s3 = [m['video_mbps_by_switch'].get('s3', 0) for m in metrics]
    check('video classified on Path A only (s3 video rate 0)', all(x < 0.05 for x in s3))
    vs4 = [m['video_mbps_by_switch'].get('s4', 0) for m in per_window.get('video_only', [])]
    check('video classified by port: video rule rate at s4 near %d Mbit/s' % v['bitrate_mbps'],
          bool(vs4) and abs(sum(vs4) / len(vs4) - v['bitrate_mbps']) < 0.6,
          '(avg %.2f)' % (sum(vs4) / len(vs4)) if vs4 else '')
    drops = [m['links']['s4->s2']['tx_dropped_per_s'] for m in per_window.get('heavy', [])]
    print('  info: OVS port tx_dropped on s4->s2 during heavy load: %s per s'
          % (drops and round(sum(drops) / len(drops), 1)))

    header('Host-side measurements (NOT from the controller)')
    ping = {}
    with open(os.path.join(host_dir, 'ping.log')) as f:
        for line in f:
            m = re.match(r'\[([\d.]+)\].*time=([\d.]+) ms', line)
            if m:
                w = window_of(float(m.group(1)) - t0)
                if w:
                    ping.setdefault(w, []).append(float(m.group(2)))
    vid = iperf3_json(open(os.path.join(host_dir, 'iperf_video.json')).read())
    loss = {}
    if vid and 'intervals' in vid:
        for iv in vid['intervals']:
            s = iv['sum']
            w = window_of(s['start'])
            if w and 'lost_packets' in s:
                lp = loss.setdefault(w, [0, 0, []])
                lp[0] += s['lost_packets']
                lp[1] += s['packets']
                lp[2].append(s.get('jitter_ms', 0))
    print('  %-11s %22s %24s %12s' % ('window', 'ping RTT avg/max (ms)', 'video loss (iperf3)', 'jitter avg'))
    for name, _, _ in WINDOWS:
        p = ping.get(name, [])
        lp = loss.get(name)
        print('  %-11s %22s %24s %12s' % (
            name,
            '%.2f / %.2f (n=%d)' % (sum(p) / len(p), max(p), len(p)) if p else '-',
            '%d/%d (%.1f%%)' % (lp[0], lp[1], 100.0 * lp[0] / lp[1]) if lp and lp[1] else '-',
            '%.3f ms' % (sum(lp[2]) / len(lp[2])) if lp and lp[2] else '-'))
    if vid and 'end' in vid:
        s = vid['end']['sum']
        print('  whole run: video %.2f Mbit/s received, loss %d/%d (%.2f%%), jitter %.3f ms'
              % (s['bits_per_second'] / 1e6, s['lost_packets'], s['packets'],
                 s['lost_percent'], s['jitter_ms']))
    elif vid is None:
        print('  [WARN] could not parse iperf_video.json')
    print('  Note: this is the no-reroute behaviour (Phase 2). Rerouting and the')
    print('  priority queue come in Phase 3.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True, help='directory the controller writes to')
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit('Run with sudo')
    setLogLevel('warning')
    cfg = load_config()
    run_dir = os.path.abspath(args.run_dir)
    host_dir = os.path.join(run_dir, 'hosts')
    os.makedirs(host_dir, exist_ok=True)
    net = build_network(cfg)
    qos_ports = []
    try:
        qos_ports = apply_qos(cfg)
        states = wait_for_controller(net)
        check('all switches connected', all(states.values()), states)
        if not all(states.values()):
            return finish(run_dir)
        check('forwarding rules installed', wait_for_flows(list(cfg['topology']['switches']),
                                                           'nw_dst=', timeout=40))
        print('Waiting 2 polls so the controller has a first rate sample...')
        time.sleep(2 * cfg['monitoring']['poll_interval_s'] + 1)
        header('Running traffic (%d s)' % WINDOWS[-1][2])
        t0 = run_traffic(net, cfg, host_dir)
        time.sleep(cfg['monitoring']['poll_interval_s'] + 1)  # let the last records land
        analyse(cfg, run_dir, host_dir, t0)
    finally:
        clear_qos(qos_ports)
        net.stop()
    finish(run_dir)


def finish(run_dir):
    # Files written as root here should belong to the normal user.
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if uid and gid:
        sh('chown -R %s:%s %s' % (uid, gid, run_dir))
    header('SUMMARY')
    for name, ok in results:
        print('  [%s] %s' % ('PASS' if ok else 'FAIL', name))
    failed = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed' % (len(results), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
