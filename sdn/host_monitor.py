"""
Live end-host measurements for the lab (Phase 6).

The lab runs, inside the Mininet hosts:
- iperf3 servers (receivers) with one report line per second
  (iperf3 -s -i 1 --forceflush), one for the video, one for background
- ping -D -O from the client h1 to the server h2

This module turns their text output into one sample per second:
received rate, loss and jitter (iperf3 receiver) and round trip delay
(ping). These are HOST measurements. The controller never measures
delay, jitter or loss, and the dashboard labels these as host data.

Plain python3, no Mininet, so the parsing is unit tested without sudo
(sdn/tests/test_host_monitor.py).
"""
import re
import threading

UNITS = {'': 1, 'K': 1e3, 'M': 1e6, 'G': 1e9}

# [  5]   1.00-2.00   sec   494 KBytes  4.05 Mbits/sec  0.117 ms  0/23 (0%)
IPERF_LINE = re.compile(
    r'^\[\s*\d+\]\s+([\d.]+)-([\d.]+)\s+sec\s+[\d.]+\s+\w?Bytes\s+'
    r'([\d.]+)\s+(\w?)bits/sec\s+([\d.]+)\s+ms\s+(-?\d+)/(\d+)\s+\(')
# [1792946602.578833] 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=1.23 ms
# [1792946602.978833] no answer yet for icmp_seq=3
PING_LINE = re.compile(r'^\[([\d.]+)\]\s+(.*)$')


def parse_iperf_line(line):
    """One per-second receiver interval, or None (headers, summaries, other text)."""
    if 'receiver' in line or 'sender' in line:
        return None  # end-of-test summary, not an interval
    m = IPERF_LINE.match(line.strip())
    if not m:
        return None
    start, end = float(m.group(1)), float(m.group(2))
    if end - start > 1.5 or end <= start:
        return None
    lost, total = int(m.group(6)), int(m.group(7))
    return dict(start=start, end=end, seconds=end - start,
                mbps=float(m.group(3)) * UNITS.get(m.group(4), 1) / 1e6,
                jitter_ms=float(m.group(5)), lost=max(lost, 0), packets=total)


def parse_ping_line(line):
    """(timestamp, rtt_ms) for a reply, (timestamp, None) for a lost probe, or None."""
    m = PING_LINE.match(line.strip())
    if not m:
        return None
    rest = m.group(2)
    r = re.search(r'time=([\d.]+) ms', rest)
    if r:
        return float(m.group(1)), float(r.group(1))
    if 'no answer yet' in rest:
        return float(m.group(1)), None
    return None


class StreamStats:
    """Collects iperf3 intervals of one receiver between two samples."""

    def __init__(self):
        self.intervals = []
        self.seen = set()
        self.session = 0

    def feed(self, line):
        if 'Accepted connection' in line:
            self.session += 1          # a new test restarts the interval clock
            self.seen = set()
            return
        iv = parse_iperf_line(line)
        if iv is None:
            return
        key = (self.session, iv['start'])
        if key in self.seen:           # iperf3 repeats the last line when the sender stops
            return
        self.seen.add(key)
        self.intervals.append(iv)

    def take(self):
        ivs, self.intervals = self.intervals, []
        secs = sum(i['seconds'] for i in ivs)
        if not ivs or secs <= 0:
            return None
        packets = sum(i['packets'] for i in ivs)
        lost = sum(i['lost'] for i in ivs)
        return dict(mbps=round(sum(i['mbps'] * i['seconds'] for i in ivs) / secs, 3),
                    loss_pct=round(100.0 * lost / packets, 2) if packets else None,
                    jitter_ms=round(ivs[-1]['jitter_ms'], 4), lost=lost, packets=packets)


class PingStats:
    def __init__(self):
        self.rtts = []
        self.lost = 0

    def feed(self, line):
        p = parse_ping_line(line)
        if p is None:
            return
        if p[1] is None:
            self.lost += 1
        else:
            self.rtts.append(p[1])

    def take(self):
        rtts, lost = self.rtts, self.lost
        self.rtts, self.lost = [], 0
        if not rtts and not lost:
            return None
        return dict(avg_ms=round(sum(rtts) / len(rtts), 3) if rtts else None,
                    max_ms=max(rtts) if rtts else None, replies=len(rtts), lost=lost)


class HostSampler:
    """Thread-safe: reader threads call feed(), the reporter calls sample() once a second."""

    def __init__(self):
        self.lock = threading.Lock()
        self.streams = {'video': StreamStats(), 'background': StreamStats()}
        self.ping = PingStats()

    def feed(self, source, line):
        with self.lock:
            if source == 'ping':
                self.ping.feed(line)
            else:
                self.streams[source].feed(line)

    def sample(self, ts, traffic):
        with self.lock:
            return dict(ts=ts, video=self.streams['video'].take(),
                        background=self.streams['background'].take(),
                        ping=self.ping.take(), traffic=dict(traffic))
