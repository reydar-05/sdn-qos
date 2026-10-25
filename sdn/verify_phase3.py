#!/usr/bin/env python3
"""
Phase 3 verification: rerouting and the video priority queue.

One scenario per run (scripts/verify_phase3.sh runs all three, each with
a freshly started controller in the matching mode):
    baseline    controller mode baseline: Path A only, no queue
    queue_only  mode qos, SDN_QOS_REROUTE=0: video in the priority queue,
                still on Path A next to the background traffic
    qos         mode qos: priority queue + reroute to the other path

Identical traffic in every scenario (60 s):
    0-60 s   video 4 Mbit/s, server h2 -> client h1, UDP port 5004
    10-50 s  background 9 Mbit/s, h2 -> h3, same links as the video
Analysis windows: video_only 0-10, heavy_early 10-20 (detection and
reroute happen here), heavy_late 20-50, after 50-60.

    sudo python3 sdn/verify_phase3.py --scenario qos --run-dir results/verify/phase3-<ts>/qos
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import load_config  # noqa: E402
from labutil import (chown_to_sudo_user, dump_flows, iperf_by_window, ping_by_window,  # noqa: E402
                     read_jsonl, run_traffic, sender_mbps, sh, tc_class_stats, tc_leaf_limits,
                     wait_for_flows, window_of)
from topology import apply_qos, build_network, clear_qos, wait_for_controller  # noqa: E402

from mininet.log import setLogLevel  # noqa: E402

TOTAL_S = 60
BG = (10, 50)
WINDOWS = [('video_only', 0, 10), ('heavy_early', 10, 20), ('heavy_late', 20, 50), ('after', 50, 60)]
SETTLE_S = 3
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def header(text):
    print('\n' + '=' * 70 + '\n' + text + '\n' + '=' * 70)


def snapshot(cfg, run_dir, label, store):
    """Save dump-flows, OVS queue stats and kernel tc class stats."""
    switches = list(cfg['topology']['switches'])
    with open(os.path.join(run_dir, 'flows_%s.txt' % label), 'w') as f:
        for s in switches:
            f.write('--- %s\n%s\n' % (s, dump_flows(s)))
            f.write(sh('ovs-ofctl -O OpenFlow13 queue-stats %s' % s).stdout + '\n')
    store[label] = {intf: tc_class_stats(intf) for intf in ('s4-eth2', 's4-eth3')}
    store[label + '_ts'] = time.time()


def video_rule_lines(path, cfg):
    """{switch: [video data rules, server -> client]} from a saved flows file."""
    server_ip = cfg['topology']['hosts'][cfg['video']['server']]['ip']
    port = cfg['video']['port']
    out, sw = {}, None
    for line in open(path):
        if line.startswith('--- '):
            sw = line[4:].strip()
        elif (' udp,' in line or ',udp,' in line) and 'nw_src=%s,' % server_ip in line \
                and ('tp_dst=%d ' % port in line or 'tp_src=%d ' % port in line):
            out.setdefault(sw, []).append(line.strip())
    return out


def analyse(cfg, scenario, run_dir, host_dir, t0, tc):
    mon = cfg['monitoring']
    th = mon['utilization_threshold']
    vrate = cfg['video']['bitrate_mbps']
    metrics = [m for m in read_jsonl(os.path.join(run_dir, 'metrics.jsonl'))
               if t0 <= m['ts'] <= t0 + TOTAL_S + 2]
    events = [e for e in read_jsonl(os.path.join(run_dir, 'events.jsonl')) if e['ts'] >= t0 - 1]

    header('[%s] controller metrics per poll' % scenario)
    print('   t(s) window       path  s4->s2  s4->s3  video@s2 video@s3  q1@s4-eth2 q1@s4-eth3  congested')
    by_window = {}
    for m in metrics:
        rel = m['ts'] - t0
        w = window_of(WINDOWS, rel)
        L, V, Q = m['links'], m['video_mbps_by_switch'], m.get('queues', {})
        u = lambda n: '%5.0f%%' % (100 * L[n]['utilization']) if n in L else '     -'
        q = lambda n: '%7.2fM' % Q[n]['mbps'] if n in Q else '       -'
        print('  %5.1f %-12s %-4s %s  %s  %7.2fM %7.2fM  %s  %s   %s' % (
            rel, w or '-', m['video_path'], u('s4->s2'), u('s4->s3'), V.get('s2', 0), V.get('s3', 0),
            q('s4-eth2:q1'), q('s4-eth3:q1'), ','.join(m['congested_links']) or '-'))
        if w and rel - dict((n, a) for n, a, _ in WINDOWS)[w] >= SETTLE_S:
            by_window.setdefault(w, []).append(m)

    header('[%s] controller events' % scenario)
    for e in events:
        if e['event'].startswith(('congestion', 'reroute', 'stats_missing')):
            print('  t=%5.1fs %-20s %s' % (e['ts'] - t0, e['event'],
                                          {k: e[k] for k in e if k not in ('ts', 'event')}))

    def avg(w, fn):
        xs = [fn(m) for m in by_window.get(w, [])]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    def link_u(name):
        return lambda m: m['links'][name]['utilization'] if name in m['links'] else None

    def queue_mbps(name):
        return lambda m: m.get('queues', {}).get(name, {}).get('mbps')

    # ---- host-side numbers -------------------------------------------
    header('[%s] host-side measurements (ping, iperf3) - NOT from the controller' % scenario)
    video, vdata = iperf_by_window(os.path.join(host_dir, 'iperf_video.json'), WINDOWS)
    bgw, bgdata = iperf_by_window(os.path.join(host_dir, 'iperf_bg_heavy.json'), WINDOWS, offset=BG[0])
    sent_video = sender_mbps(os.path.join(host_dir, 'iperf_video_sender.json'))
    sent_bg = sender_mbps(os.path.join(host_dir, 'iperf_bg_heavy_sender.json'))
    print('  senders actually sent: video %s Mbit/s (asked %s), background %s Mbit/s (asked %s)' % (
        '%.2f' % sent_video if sent_video else '?', vrate,
        '%.2f' % sent_bg if sent_bg else '?', cfg['background']['heavy_mbps']))
    ping = ping_by_window(os.path.join(host_dir, 'ping.log'), t0, WINDOWS)
    print('  %-12s %-28s %-22s %-26s' % ('window', 'video Mbit/s, loss, jitter', 'ping avg/max, lost',
                                          'background Mbit/s, loss'))
    host = {}
    for name, _, _ in WINDOWS:
        v, p, b = video.get(name), ping.get(name), bgw.get(name)
        rt = p['rtts'] if p else []
        host[name] = dict(
            video_mbps=v and round(v['mbps'], 3), video_loss_pct=v and round(v['loss_pct'], 3),
            video_lost=v and v['lost'], video_packets=v and v['packets'],
            jitter_ms=v and round(v['jitter_avg_ms'], 4),
            ping_avg_ms=round(sum(rt) / len(rt), 3) if rt else None,
            ping_max_ms=max(rt) if rt else None, ping_lost=p['lost'] if p else None,
            bg_mbps=b and round(b['mbps'], 3), bg_loss_pct=b and round(b['loss_pct'], 2))
        h = host[name]
        print('  %-12s %-28s %-22s %-26s' % (
            name,
            '%.2f, %.2f%%, %.3f ms' % (h['video_mbps'], h['video_loss_pct'], h['jitter_ms']) if v else '-',
            '%.2f/%.2f ms, %d' % (h['ping_avg_ms'], h['ping_max_ms'], h['ping_lost']) if rt else '-',
            '%.2f, %.1f%%' % (h['bg_mbps'], h['bg_loss_pct']) if b else '-'))

    # ---- kernel queue counters on the bottleneck port ------------------
    header('[%s] kernel HTB counters on s4 ports during heavy load (tc -s class)' % scenario)
    drops = {}
    for intf in ('s4-eth2', 's4-eth3'):
        for cls in ('1:1', '1:2'):
            a = tc.get('before', {}).get(intf, {}).get(cls)
            b = tc.get('end_heavy', {}).get(intf, {}).get(cls)
            if a and b:
                d = {k: b[k] - a[k] for k in a}
                drops['%s %s' % (intf, cls)] = d
                print('  %s class %s (queue %s): sent %d pkts, dropped %d' % (
                    intf, cls, int(cls.split(':')[1]) - 1, d['pkts'], d['dropped']))

    # ---- checks ---------------------------------------------------------
    header('[%s] checks' % scenario)
    det = [e for e in events if e['event'] == 'congestion_detected' and e.get('link') == 's4->s2'
           and BG[0] <= e['ts'] - t0 < BG[1]]
    reroutes = [e for e in events if e['event'] == 'reroute']
    confirmed = [e for e in events if e['event'] == 'reroute_confirmed']
    bg_rate = cfg['background']['heavy_mbps']
    check('senders were not slowed down by the host (sent >= 97% of asked)',
          sent_video and sent_bg and sent_video >= 0.97 * vrate and sent_bg >= 0.97 * bg_rate,
          '(so loss happens at the switch queue, as in a real network)')
    check('congestion detected on s4->s2 under heavy load', det,
          '(%.1f s after background started)' % (det[0]['ts'] - t0 - BG[0]) if det else '')
    q1_a = avg('heavy_late', queue_mbps('s4-eth2:q1'))

    if scenario == 'baseline':
        check('no reroute (baseline)', not reroutes)
        check('video not in the priority queue (q1 on s4-eth2 ~ 0)',
              q1_a is not None and q1_a < 0.1, '(%.2f Mbit/s)' % (q1_a or 0))
        d = drops.get('s4-eth2 1:1', {}).get('dropped', 0)
        check('bottleneck now drops packets (queue limit active)', d > 0, '(%d dropped in queue 0)' % d)
    elif scenario == 'queue_only':
        check('no reroute (reroute disabled)', not reroutes)
        check('video carried by priority queue 1 on s4-eth2',
              q1_a is not None and abs(q1_a - vrate) < 0.6, '(%.2f Mbit/s, video %s)' % (q1_a or 0, vrate))
        d = drops.get('s4-eth2 1:2', {}).get('dropped')
        check('video queue had no drops during heavy load', d == 0, '(%s dropped)' % d)
        dq0 = drops.get('s4-eth2 1:1', {}).get('dropped', 0)
        print('  info: default queue 0 dropped %d packets (background takes the loss)' % dq0)
    else:
        check('exactly one reroute', len(reroutes) == 1, '(%d)' % len(reroutes))
        if reroutes:
            r = reroutes[0]
            # Either Path A video link can be the trigger: it depends on
            # which switch's stats reply arrived first in that poll.
            path_a_video_links = {'s4->s2', 's2->s1'}
            check('reroute A -> B triggered by a congested Path A video link',
                  r['from_path'] == 'A' and r['to_path'] == 'B' and r['trigger_links']
                  and set(r['trigger_links']) <= path_a_video_links,
                  '(%s, at t=%.1f s, %.1f s after background started)'
                  % (','.join(r['trigger_links']), r['ts'] - t0, r['ts'] - t0 - BG[0]))
            check('new rules confirmed by barrier', confirmed,
                  '(%.1f ms)' % confirmed[0]['install_ms'] if confirmed else '')
        before = video_rule_lines(os.path.join(run_dir, 'flows_before.txt'), cfg)
        after = video_rule_lines(os.path.join(run_dir, 'flows_end_heavy.txt'), cfg)
        print('  video data rules BEFORE: ' + json.dumps(before, indent=1))
        print('  video data rules AFTER : ' + json.dumps(after, indent=1))
        check('before: video rule on s2, none on s3', before.get('s2') and not before.get('s3'))
        check('after: video rule on s3 with set_queue, none on s2',
              after.get('s3') and any('set_queue:1' in l for l in after['s3']) and not after.get('s2'))
        v3 = avg('heavy_late', lambda m: m['video_mbps_by_switch'].get('s3'))
        v2 = avg('heavy_late', lambda m: m['video_mbps_by_switch'].get('s2'))
        check('video rate now counted on s3, not s2', v3 and abs(v3 - vrate) < 0.6 and (v2 or 0) < 0.1,
              '(s3 %.2f, s2 %.2f Mbit/s)' % (v3 or 0, v2 or 0))
        ub = avg('heavy_late', link_u('s4->s3'))
        check('Path B port counters show the video (s4->s3 ~ video rate)',
              ub is not None and abs(ub - vrate / 10.0) < 0.15, '(%.0f%%)' % (100 * (ub or 0)))
        ua = avg('heavy_late', link_u('s4->s2'))
        print('  info: Path A s4->s2 after reroute: %.0f%% (background only)' % (100 * (ua or 0)))
        q1b = avg('heavy_late', queue_mbps('s4-eth3:q1'))
        check('video in priority queue 1 on the new path (s4-eth3)',
              q1b is not None and abs(q1b - vrate) < 0.6, '(%.2f Mbit/s)' % (q1b or 0))
        skips = [e['reason'] for e in events if e['event'] == 'reroute_skipped']
        print('  info: reroute_skipped reasons: %s' % (skips or 'none'))

    summary = dict(scenario=scenario, t0=t0, windows=WINDOWS, background=BG,
                   bg_mbps=cfg['background']['heavy_mbps'], video_mbps=vrate,
                   host=host, tc_heavy=drops, sent_video_mbps=sent_video, sent_bg_mbps=sent_bg,
                   reroutes=[{k: e[k] for k in e if k != 'event'} for e in reroutes],
                   reroute_confirmed=confirmed,
                   congestion_detected_s=round(det[0]['ts'] - t0 - BG[0], 2) if det else None,
                   checks=results)
    with open(os.path.join(run_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', required=True, choices=['baseline', 'queue_only', 'qos'])
    ap.add_argument('--run-dir', required=True)
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
        header('[%s] setup' % args.scenario)
        qos_ports = apply_qos(cfg)
        limits = tc_leaf_limits('s4-eth2')
        print('  queue buffer (tc qdisc show dev s4-eth2): %s' % limits)
        want = cfg['links']['queue_limit_packets']
        check('queue buffer limit applied (%d packets)' % want,
              limits and all(v == want for v in limits.values()))
        print(sh('ovs-vsctl --columns=_uuid,type,other_config,queues list qos').stdout.strip()[:600])
        states = wait_for_controller(net)
        check('all switches connected', all(states.values()), states)
        if not all(states.values()):
            sys.exit(1)  # 'finally' below still cleans up and prints the summary
        check('forwarding rules installed', wait_for_flows(list(cfg['topology']['switches']),
                                                           'nw_dst=', timeout=40))
        time.sleep(2 * cfg['monitoring']['poll_interval_s'] + 1)
        header('[%s] running traffic (%d s)' % (args.scenario, TOTAL_S))
        tc = {}
        hooks = {8: lambda: snapshot(cfg, run_dir, 'before', tc),
                 BG[1] - 1: lambda: snapshot(cfg, run_dir, 'end_heavy', tc)}
        t0 = run_traffic(net, cfg, host_dir, TOTAL_S,
                         [(BG[0], BG[1], cfg['background']['heavy_mbps'], 'heavy')], hooks)
        time.sleep(cfg['monitoring']['poll_interval_s'] + 1)
        analyse(cfg, args.scenario, run_dir, host_dir, t0, tc)
    finally:
        clear_qos(qos_ports)
        net.stop()
        chown_to_sudo_user(run_dir)
        header('[%s] SUMMARY' % args.scenario)
        for name, ok in results:
            print('  [%s] %s' % ('PASS' if ok else 'FAIL', name))
        failed = [n for n, ok in results if not ok]
        print('\n%d checks, %d failed' % (len(results), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
