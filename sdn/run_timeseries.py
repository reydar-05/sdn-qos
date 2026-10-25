"""
Per-second time series of one recorded experiment run, for the dashboard
charts. Plain python3, reads only the saved files of the run:

    python3 sdn/run_timeseries.py results/experiments/<id>/<run dir>

Every series says where it comes from:
- host:       iperf3 receiver report (video rate, loss, jitter) and ping (delay)
- controller: port statistics (link throughput and utilization), video path
- model:      playout buffer MODEL (not a real player)
Times are seconds since the start of the video flow (t0 in run.json).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from labutil import iperf3_json, read_jsonl  # noqa: E402

CHART_LINKS = ['s4->s2', 's2->s1', 's4->s3', 's3->s1']
KEEP_EVENTS = ('congestion_detected', 'congestion_cleared', 'reroute', 'reroute_confirmed',
               'reroute_skipped', 'reroute_unconfirmed', 'stats_missing', 'flows_installed')


def _load_iperf(path):
    if not os.path.exists(path):
        return None
    data = iperf3_json(open(path).read())
    return data if data and 'intervals' in data else None


def _iperf_rows(data, offset):
    """{second: {mbps, loss_pct, jitter_ms}} keyed by the whole second of run time."""
    rows = {}
    for iv in (data or {}).get('intervals', []):
        s = iv['sum']
        if 'lost_packets' not in s or not s['seconds']:
            continue
        t = int(round(s['start'] + offset))
        rows[t] = dict(mbps=round(s['bytes'] * 8 / 1e6 / s['seconds'], 3),
                       loss_pct=round(100.0 * s['lost_packets'] / s['packets'], 2) if s['packets'] else None,
                       jitter_ms=round(s.get('jitter_ms', 0.0), 4))
    return rows


def _ping_rows(path, t0):
    """{second: {avg_ms, lost}} from 'ping -D -O' output."""
    acc = {}
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        for line in f:
            m = re.match(r'\[([\d.]+)\]', line)
            if not m:
                continue
            sec = int(float(m.group(1)) - t0)
            a = acc.setdefault(sec, {'rtts': [], 'lost': 0})
            r = re.search(r'time=([\d.]+) ms', line)
            if r:
                a['rtts'].append(float(r.group(1)))
            elif 'no answer yet' in line:
                a['lost'] += 1
    return {s: dict(avg_ms=round(sum(a['rtts']) / len(a['rtts']), 3) if a['rtts'] else None,
                    lost=a['lost']) for s, a in acc.items()}


def build_timeseries(run_dir, bg_start_s):
    info = json.load(open(os.path.join(run_dir, 'run.json')))
    t0 = info['t0']
    hosts = os.path.join(run_dir, 'hosts')
    video = _iperf_rows(_load_iperf(os.path.join(hosts, 'iperf_video.json')), 0.0)
    bg = _iperf_rows(_load_iperf(os.path.join(hosts, 'iperf_bg_%s.json' % info['load'])), bg_start_s)
    ping = _ping_rows(os.path.join(hosts, 'ping.log'), t0)
    analysis = {}
    if os.path.exists(os.path.join(run_dir, 'analysis.json')):
        analysis = json.load(open(os.path.join(run_dir, 'analysis.json')))
    levels = (analysis.get('playout_model') or {}).get('buffer_levels_s') or []

    last = max(list(video) + list(ping) + [0])
    host = []
    for t in range(0, last + 1):
        v, b, p = video.get(t, {}), bg.get(t, {}), ping.get(t, {})
        host.append(dict(t=t, video_mbps=v.get('mbps'), video_loss_pct=v.get('loss_pct'),
                         video_jitter_ms=v.get('jitter_ms'), ping_ms=p.get('avg_ms'),
                         ping_lost=p.get('lost'), bg_mbps=b.get('mbps'), bg_loss_pct=b.get('loss_pct'),
                         buffer_s=levels[t] if t < len(levels) else None))

    controller = []
    for m in read_jsonl(os.path.join(run_dir, 'metrics.jsonl')):
        rel = m['ts'] - t0
        if rel < -2:
            continue
        row = dict(t=round(rel, 1), video_path=m.get('video_path'),
                   congested=m.get('congested_links', []))
        for l in CHART_LINKS:
            d = m['links'].get(l) or {}
            row['util_' + l] = d.get('utilization')
            row['mbps_' + l] = d.get('mbps')
        for sw in ('s2', 's3'):
            row['video_mbps_' + sw] = m.get('video_mbps_by_switch', {}).get(sw)
        controller.append(row)

    events = [dict(e, t=round(e['ts'] - t0, 2)) for e in read_jsonl(os.path.join(run_dir, 'events.jsonl'))
              if e.get('event') in KEEP_EVENTS and e['ts'] >= t0 - 2]
    return dict(run=info['name'], mode=info['mode'], load=info['load'], bg_mbps=info['bg_mbps'],
                valid=analysis.get('valid'), host=host, controller=controller, events=events,
                sources=dict(host='iperf3 receiver report and ping on the end hosts',
                             controller='Ryu port statistics (OpenFlow), every poll',
                             model=(analysis.get('playout_model') or {}).get('model')))


if __name__ == '__main__':
    out = build_timeseries(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10.0)
    print(json.dumps({k: (v if not isinstance(v, list) else '%d rows' % len(v)) for k, v in out.items()}, indent=1))
    print('host[25]:', out['host'][25] if len(out['host']) > 25 else None)
    print('events:', [(e['t'], e['event']) for e in out['events']])
