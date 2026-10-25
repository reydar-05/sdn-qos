"""
Helpers shared by the root-side lab scripts (verify_*.py, run_experiment.py).
System python3 only: these call ovs-ofctl/ovs-vsctl and run commands
inside Mininet hosts.
"""
import json
import os
import re
import subprocess
import time


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def dump_flows(switch):
    """Raw dump-flows text for one switch (OpenFlow 1.3)."""
    return sh('ovs-ofctl -O OpenFlow13 dump-flows %s' % switch).stdout


def flow_lines(switch):
    """dump-flows lines, without the reply header."""
    return [l.strip() for l in dump_flows(switch).splitlines() if 'priority=' in l]


def flow_packets(line):
    m = re.search(r'n_packets=(\d+)', line)
    return int(m.group(1)) if m else 0


def wait_for_flows(switches, pattern, timeout=30):
    """Wait until every switch has at least one rule containing pattern."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(any(pattern in l for l in flow_lines(s)) for s in switches):
            return True
        time.sleep(1)
    return False


def port_counters(switch):
    """{port_no: {'rx_pkts','rx_bytes','rx_drop','tx_pkts','tx_bytes','tx_drop'}}"""
    out = sh('ovs-ofctl -O OpenFlow13 --no-names dump-ports %s' % switch).stdout
    result = {}
    rx = re.finditer(r'port\s+(\w+):\s+rx pkts=(\d+), bytes=(\d+), drop=(\d+).*?\n'
                     r'\s+tx pkts=(\d+), bytes=(\d+), drop=(\d+)', out)
    for m in rx:
        if m.group(1) == 'LOCAL':
            continue
        result[int(m.group(1))] = dict(
            rx_pkts=int(m.group(2)), rx_bytes=int(m.group(3)), rx_drop=int(m.group(4)),
            tx_pkts=int(m.group(5)), tx_bytes=int(m.group(6)), tx_drop=int(m.group(7)))
    return result


def queue_counters(switch):
    """{(port_no, queue_id): {'tx_bytes','tx_pkts','tx_errors'}} from dump-queue-stats."""
    out = sh('ovs-ofctl -O OpenFlow13 --no-names queue-stats %s' % switch).stdout
    result = {}
    for m in re.finditer(r'port\s+(\d+)\s+queue\s+(\d+):\s+bytes=(\d+),\s*pkts=(\d+),\s*errors=(\d+)', out):
        result[(int(m.group(1)), int(m.group(2)))] = dict(
            tx_bytes=int(m.group(3)), tx_pkts=int(m.group(4)), tx_errors=int(m.group(5)))
    return result


def iperf3_json(text):
    """Parse iperf3 -J output; returns dict or None (with the raw text kept)."""
    start = text.find('{')
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def udp_summary(result):
    """Receiver-side numbers from an iperf3 UDP -J result."""
    s = result['end']['sum']
    return dict(mbps=s['bits_per_second'] / 1e6, jitter_ms=s['jitter_ms'],
                lost_packets=s['lost_packets'], packets=s['packets'],
                lost_percent=s['lost_percent'])


def parse_ping(text):
    """(transmitted, received, avg_ms, max_ms, mdev_ms) from ping summary, or None."""
    m = re.search(r'(\d+) packets transmitted, (\d+) received', text)
    r = re.search(r'= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', text)
    if not m:
        return None
    avg = float(r.group(2)) if r else None
    mx = float(r.group(3)) if r else None
    mdev = float(r.group(4)) if r else None
    return int(m.group(1)), int(m.group(2)), avg, mx, mdev


# ----------------------------------------------------------------------
# Traffic runs and host-side measurements (Phase 3 onwards)
# ----------------------------------------------------------------------
def tc_class_stats(intf):
    """{classid: {'bytes','pkts','dropped'}} from 'tc -s class show'.
    OVS linux-htb class 1:(N+1) is OpenFlow queue N."""
    out = sh('tc -s class show dev %s' % intf).stdout
    result = {}
    for m in re.finditer(r'class htb (\S+) .*?\n\s*Sent (\d+) bytes (\d+) pkt \(dropped (\d+)', out):
        result[m.group(1)] = dict(bytes=int(m.group(2)), pkts=int(m.group(3)),
                                  dropped=int(m.group(4)))
    return result


def tc_leaf_limits(intf):
    """{parent class: limit in packets} of the FIFO under each HTB class."""
    # HTB's default per-class FIFOs are hidden unless 'invisible' is given.
    out = sh('tc qdisc show dev %s invisible' % intf).stdout
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r'parent (\S+) limit (\d+)p', out)}


def run_traffic(net, cfg, host_dir, total_s, bg_schedule, hooks=None):
    """Video (server -> client) for total_s seconds, plus background traffic.

    bg_schedule: [(start_s, end_s, mbps, label), ...] background bursts
    hooks:       {seconds: function()} called once at that time (snapshots)

    iperf3 runs in its normal direction: the receiver is the iperf3 server
    (on the video client h1 / background host h3) and reports per-second
    received rate, loss and jitter; the sender (iperf3 client on the video
    server h2) reports what it really sent. iperf3 -R is not used: in
    iperf3 3.9 it produced corrupt loss counters (Phase 3 finding).
    Also pings the server from the client every 0.2 s. Returns t0.
    """
    v, bg = cfg['video'], cfg['background']
    server, client, bghost = net.get(v['server']), net.get(v['client']), net.get(bg['host'])
    pids = [client.cmd('iperf3 -s -1 -p %d -J > %s/iperf_video.json 2>&1 & echo $!'
                       % (v['port'], host_dir)).strip()]
    time.sleep(1)
    t0 = time.time()
    client.cmd('ping -D -O -i 0.2 -w %d %s > %s/ping.log 2>&1 &' % (total_s, server.IP(), host_dir))
    server.cmd('iperf3 -c %s -u -p %d -b %sM -t %d -J > %s/iperf_video_sender.json 2>&1 &'
               % (client.IP(), v['port'], v['bitrate_mbps'], total_s, host_dir))
    print('  t=  0.0s  video %s Mbit/s started (%d s)' % (v['bitrate_mbps'], total_s))

    def start_bg(start, end, mbps, label):
        def go():
            print('  t=%5.1fs  background %s Mbit/s for %d s (%s)'
                  % (time.time() - t0, mbps, end - start, label))
            pids.append(bghost.cmd('iperf3 -s -1 -p %d -J > %s/iperf_bg_%s.json 2>&1 & echo $!'
                                   % (bg['port'], host_dir, label)).strip())
            time.sleep(0.3)
            server.cmd('iperf3 -c %s -u -p %d -b %sM -t %d -J > %s/iperf_bg_%s_sender.json 2>&1 &'
                       % (bghost.IP(), bg['port'], mbps, end - start, host_dir, label))
        return go

    todo = [(t, fn) for t, fn in (hooks or {}).items()]
    todo += [(b[0] - 0.3, start_bg(*b)) for b in bg_schedule]
    for at, fn in sorted(todo, key=lambda x: x[0]):
        while time.time() - t0 < at:
            time.sleep(0.05)
        fn()
    while time.time() - t0 < total_s + 3:
        time.sleep(0.2)
    for pid in pids:  # -1 servers exit by themselves; this only catches leftovers
        if pid.isdigit():
            sh('kill %s 2>/dev/null' % pid)
    return t0


def sender_mbps(path):
    """Average rate the iperf3 client actually sent (from its -J output)."""
    data = iperf3_json(open(path).read()) if os.path.exists(path) else None
    try:
        return data['end']['sum']['bits_per_second'] / 1e6
    except (TypeError, KeyError):
        return None


def window_of(windows, rel):
    for name, a, b in windows:
        if a <= rel < b:
            return name
    return None


def ping_by_window(path, t0, windows):
    """{window: {'rtts': [ms, ...], 'lost': n}} from 'ping -D -O' output.
    -D puts a timestamp on every line, -O prints a line for every probe
    that got no reply, so both replies and losses land in a window."""
    out = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'\[([\d.]+)\]', line)
            if not m:
                continue
            w = window_of(windows, float(m.group(1)) - t0)
            if w is None:
                continue
            acc = out.setdefault(w, {'rtts': [], 'lost': 0})
            r = re.search(r'time=([\d.]+) ms', line)
            if r:
                acc['rtts'].append(float(r.group(1)))
            elif 'no answer yet' in line:
                acc['lost'] += 1
    return out


def iperf_by_window(path, windows, offset=0.0):
    """Per-window receiver stats from an iperf3 UDP server's -J output.
    offset: seconds between run start (t0) and this iperf3 client's start."""
    data = iperf3_json(open(path).read()) if os.path.exists(path) else None
    out = {}
    if not data or 'intervals' not in data:
        return out, data
    for iv in data['intervals']:
        s = iv['sum']
        w = window_of(windows, s['start'] + offset)
        if w is None or 'lost_packets' not in s:
            continue
        acc = out.setdefault(w, dict(lost=0, packets=0, bytes=0, seconds=0.0, jitter=[]))
        acc['lost'] += s['lost_packets']
        acc['packets'] += s['packets']
        acc['bytes'] += s['bytes']
        acc['seconds'] += s['seconds']
        acc['jitter'].append(s.get('jitter_ms', 0.0))
    for acc in out.values():
        acc['mbps'] = acc['bytes'] * 8 / 1e6 / acc['seconds'] if acc['seconds'] else 0.0
        acc['loss_pct'] = 100.0 * acc['lost'] / acc['packets'] if acc['packets'] else 0.0
        acc['jitter_avg_ms'] = sum(acc['jitter']) / len(acc['jitter']) if acc['jitter'] else 0.0
        del acc['jitter']
    return out, data


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def chown_to_sudo_user(path):
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if uid and gid:
        sh('chown -R %s:%s %s' % (uid, gid, path))
