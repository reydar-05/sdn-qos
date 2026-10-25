"""
Turns the raw files of one experiment run into numbers. Plain python3,
no Mininet needed, so it can be re-run on saved data at any time:

    python3 sdn/run_analysis.py results/experiments/<id>/<run dir>

Sources, and what each one is allowed to claim:
- controller (metrics.jsonl / events.jsonl): throughput, utilization,
  video rate per switch, queue rates, congestion/reroute times
- hosts (hosts/*.json, ping.log): video loss, jitter, received rate,
  ping delay; background rate and loss
- kernel tc counters (tc.json): drops per HTB queue on the s4 ports
- playout buffer MODEL fed by the per-second received video bits
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from labutil import iperf3_json, ping_by_window, read_jsonl, sender_mbps  # noqa: E402
from playout_model import simulate  # noqa: E402

LINKS = ['s4->s2', 's2->s1', 's4->s3', 's3->s1']


def timeline(cfg):
    e = cfg['experiment']
    d = e['duration_s']
    bs, be = e['background_start_s'], d - e['background_stop_before_end_s']
    return dict(duration=d, bg_start=bs, bg_end=be,
                windows={'pre': (0, bs), 'load': (bs, be), 'steady': (bs + e['settle_s'], be),
                         'post': (be, d)})


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def iperf_window(data, a, b, offset=0.0):
    """Receiver stats for intervals that start inside [a, b) seconds of run time."""
    if not data or 'intervals' not in data:
        return None
    lost = packets = byts = 0
    secs = 0.0
    jit = []
    for iv in data['intervals']:
        s = iv['sum']
        if not a <= s['start'] + offset < b or 'lost_packets' not in s:
            continue
        lost += s['lost_packets']
        packets += s['packets']
        byts += s['bytes']
        secs += s['seconds']
        jit.append(s.get('jitter_ms', 0.0))
    if not secs:
        return None
    return dict(mbps=round(byts * 8 / 1e6 / secs, 3),
                loss_pct=round(100.0 * lost / packets, 3) if packets else None,
                lost=lost, packets=packets, jitter_ms=round(sum(jit) / len(jit), 4))


def analyse_run(cfg, run_dir, t0, load, bg_mbps):
    tl = timeline(cfg)
    hosts = os.path.join(run_dir, 'hosts')
    v = cfg['video']
    ratio = cfg['experiment']['min_sender_ratio']
    out = dict(load=load, bg_mbps=bg_mbps, video_mbps_cfg=v['bitrate_mbps'])

    # ---- validity: did the hosts send what they were asked? -----------
    sv = sender_mbps(os.path.join(hosts, 'iperf_video_sender.json'))
    sb = sender_mbps(os.path.join(hosts, 'iperf_bg_%s_sender.json' % load))
    out['sent_video_mbps'] = sv and round(sv, 3)
    out['sent_bg_mbps'] = sb and round(sb, 3)
    problems = []
    if sv is None or sv < ratio * v['bitrate_mbps']:
        problems.append('video sender sent %s of %s Mbit/s' % (sv, v['bitrate_mbps']))
    if sb is None or sb < ratio * bg_mbps:
        problems.append('background sender sent %s of %s Mbit/s' % (sb, bg_mbps))

    # ---- host side -------------------------------------------------------
    video = iperf3_json(open(os.path.join(hosts, 'iperf_video.json')).read()) \
        if os.path.exists(os.path.join(hosts, 'iperf_video.json')) else None
    bgf = os.path.join(hosts, 'iperf_bg_%s.json' % load)
    bg = iperf3_json(open(bgf).read()) if os.path.exists(bgf) else None
    if not video or 'intervals' not in video:
        problems.append('no video receiver report')
    ping = ping_by_window(os.path.join(hosts, 'ping.log'), t0,
                          [(n, a, b) for n, (a, b) in tl['windows'].items() if n != 'load'])
    ping_load = ping_by_window(os.path.join(hosts, 'ping.log'), t0, [('load',) + tl['windows']['load']])
    ping.update(ping_load)
    host = {}
    for name, (a, b) in tl['windows'].items():
        vw = iperf_window(video, a, b)
        bw = iperf_window(bg, a, b, offset=tl['bg_start']) if name != 'pre' else None
        p = ping.get(name) or {'rtts': [], 'lost': 0}
        rt = p['rtts']
        host[name] = dict(
            video_mbps=vw and vw['mbps'], video_loss_pct=vw and vw['loss_pct'],
            video_lost=vw and vw['lost'], video_jitter_ms=vw and vw['jitter_ms'],
            ping_avg_ms=round(sum(rt) / len(rt), 3) if rt else None,
            ping_max_ms=max(rt) if rt else None,
            ping_stdev_ms=round(statistics.pstdev(rt), 3) if len(rt) > 1 else None,
            ping_lost=p['lost'], ping_replies=len(rt),
            bg_mbps=bw and bw['mbps'], bg_loss_pct=bw and bw['loss_pct'])
    out['host'] = host

    # ---- playout buffer model ------------------------------------------
    if video and 'intervals' in video:
        bits = [iv['sum']['bytes'] * 8 for iv in video['intervals']]
        step = video['intervals'][0]['sum']['seconds'] if video['intervals'] else 1.0
        pm = simulate(bits, step, v['bitrate_mbps'] * 1e6,
                      cfg['playout_model']['startup_buffer_s'], cfg['playout_model']['resume_buffer_s'])
        out['playout_model'] = {k: pm[k] for k in ('startup_delay_s', 'stall_count', 'stall_time_s', 'model')}
        out['playout_model']['buffer_levels_s'] = pm['buffer_levels_s']

    # ---- controller side -------------------------------------------------
    metrics = [m for m in read_jsonl(os.path.join(run_dir, 'metrics.jsonl'))
               if t0 <= m['ts'] <= t0 + tl['duration'] + 2]
    events = [e for e in read_jsonl(os.path.join(run_dir, 'events.jsonl')) if e['ts'] >= t0 - 1]
    a, b = tl['windows']['steady']
    steady = [m for m in metrics if a <= m['ts'] - t0 < b]
    ctl = dict(polls=len(metrics), stats_missing=sum(e['event'] == 'stats_missing' for e in events))
    for l in LINKS:
        ctl['util_steady_' + l] = _mean([m['links'].get(l, {}).get('utilization') for m in steady])
    for sw in ('s2', 's3'):
        ctl['video_mbps_steady_' + sw] = _mean([m['video_mbps_by_switch'].get(sw) for m in steady])
    for q in ('s4-eth2:q1', 's4-eth3:q1', 's4-eth2:q0', 's4-eth3:q0'):
        ctl['queue_mbps_steady_' + q] = _mean([m.get('queues', {}).get(q, {}).get('mbps') for m in steady])
    bs = t0 + tl['bg_start']
    det = [e for e in events if e['event'] == 'congestion_detected' and e['ts'] >= bs
           and e.get('on_video_path')]
    rr = [e for e in events if e['event'] == 'reroute']
    conf = [e for e in events if e['event'] == 'reroute_confirmed']
    ctl['congestion_detected_s'] = round(det[0]['ts'] - bs, 2) if det else None
    ctl['reroutes'] = len(rr)
    ctl['reroute_s'] = round(rr[0]['ts'] - bs, 2) if rr else None
    ctl['reroute_install_ms'] = conf[0]['install_ms'] if conf else None
    ctl['video_path_end'] = metrics[-1]['video_path'] if metrics else None
    ctl['reroute_skipped'] = sorted({e['reason'] for e in events if e['event'] == 'reroute_skipped'})
    out['controller'] = ctl
    if not metrics:
        problems.append('no controller metrics')

    # ---- kernel tc counters ----------------------------------------------
    tc = {}
    tcf = os.path.join(run_dir, 'tc.json')
    if os.path.exists(tcf):
        snap = json.load(open(tcf))
        for intf in ('s4-eth2', 's4-eth3'):
            for cls, q in (('1:1', 'q0'), ('1:2', 'q1')):
                x = snap.get('before', {}).get(intf, {}).get(cls)
                y = snap.get('end_load', {}).get(intf, {}).get(cls)
                if x and y:
                    tc['%s:%s_dropped' % (intf, q)] = y['dropped'] - x['dropped']
                    tc['%s:%s_pkts' % (intf, q)] = y['pkts'] - x['pkts']
    out['tc_load'] = tc

    out['valid'] = not problems
    out['problems'] = problems
    return out


def flat_row(meta, result):
    """One CSV row per run: identifiers, then steady-window numbers."""
    row = dict(meta)
    row['valid'] = result['valid']
    row['problems'] = '; '.join(result['problems'])
    row['sent_video_mbps'] = result['sent_video_mbps']
    row['sent_bg_mbps'] = result['sent_bg_mbps']
    for window in ('steady', 'load'):
        for k, val in result['host'][window].items():
            row['%s_%s' % (window, k)] = val
    for k, val in result['controller'].items():
        row['ctl_' + k] = ';'.join(val) if isinstance(val, list) else val
    pm = result.get('playout_model', {})
    for k in ('startup_delay_s', 'stall_count', 'stall_time_s'):
        row['model_' + k] = pm.get(k)
    for k, val in result['tc_load'].items():
        row['tc_' + k] = val
    return row


if __name__ == '__main__':
    from qos_config import load_config
    run_dir = sys.argv[1]
    info = json.load(open(os.path.join(run_dir, 'run.json')))
    r = analyse_run(load_config(), run_dir, info['t0'], info['load'], info['bg_mbps'])
    print(json.dumps({k: v for k, v in r.items() if k != 'playout_model'}, indent=1))
    print('playout model:', {k: v for k, v in r.get('playout_model', {}).items() if k != 'buffer_levels_s'})
