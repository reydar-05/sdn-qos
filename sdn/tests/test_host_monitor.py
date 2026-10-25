"""Parsing of live iperf3 / ping output (no Mininet, no sudo):
    .venv/bin/python -m unittest discover -s sdn/tests -v
The sample text below is real iperf3 3.9 server output captured on this VM.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from host_monitor import HostSampler, parse_iperf_line, parse_ping_line  # noqa: E402

IPERF = """-----------------------------------------------------------
Server listening on 5004
-----------------------------------------------------------
Accepted connection from 10.0.0.2, port 34310
[  5] local 10.0.0.1 port 5004 connected to 10.0.0.2 port 37736
[ ID] Interval           Transfer     Bitrate         Jitter    Lost/Total Datagrams
[  5]   0.00-1.00   sec   473 KBytes  3.87 Mbits/sec  0.139 ms  0/22 (0%)
[  5]   1.00-2.00   sec   494 KBytes  4.05 Mbits/sec  0.117 ms  0/23 (0%)
[  5]   1.00-2.00   sec   494 KBytes  4.05 Mbits/sec  0.117 ms  0/23 (0%)
iperf3: the client has terminated
- - - - - - - - - - - - - - - - - - - - - - - - -
[ ID] Interval           Transfer     Bitrate         Jitter    Lost/Total Datagrams
[  5]   0.00-2.00   sec  1.15 MBytes  4.84 Mbits/sec  0.108 ms  0/55 (0%)  receiver
Accepted connection from 10.0.0.2, port 34316
[  5]   0.00-1.00   sec   305 KBytes  2.50 Mbits/sec  0.800 ms  120/336 (36%)
[  5]   1.00-2.00   sec  1.02 MBytes  8.60 Mbits/sec  0.050 ms  0/730 (0%)
"""


class HostMonitorTest(unittest.TestCase):
    def test_interval_line(self):
        iv = parse_iperf_line('[  5]   1.00-2.00   sec   494 KBytes  4.05 Mbits/sec  0.117 ms  0/23 (0%)  ')
        self.assertAlmostEqual(iv['mbps'], 4.05)
        self.assertEqual((iv['lost'], iv['packets']), (0, 23))
        self.assertAlmostEqual(iv['jitter_ms'], 0.117)

    def test_kbit_rate_and_summary_ignored(self):
        self.assertAlmostEqual(parse_iperf_line(
            '[  5]   3.00-4.00   sec  12.0 KBytes  98.3 Kbits/sec  0.2 ms  5/10 (50%)')['mbps'], 0.0983)
        self.assertIsNone(parse_iperf_line(
            '[  5]   0.00-2.00   sec  1.15 MBytes  4.84 Mbits/sec  0.108 ms  0/55 (0%)  receiver'))
        self.assertIsNone(parse_iperf_line('[ ID] Interval           Transfer     Bitrate'))

    def test_sampler_dedupes_and_restarts(self):
        s = HostSampler()
        for line in IPERF.splitlines():
            s.feed('video', line)
        v = s.sample(1.0, {'video': True})['video']
        # 2 intervals of the first test (duplicate dropped) + 2 of the second
        self.assertEqual(v['packets'], 22 + 23 + 336 + 730)
        self.assertEqual(v['lost'], 120)
        self.assertAlmostEqual(v['mbps'], round((3.87 + 4.05 + 2.50 + 8.60) / 4, 3))
        self.assertIsNone(s.sample(2.0, {})['video'])  # nothing new

    def test_ping(self):
        self.assertEqual(parse_ping_line('[1792946602.578833] 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=1.23 ms'),
                         (1792946602.578833, 1.23))
        self.assertEqual(parse_ping_line('[1792946603.0] no answer yet for icmp_seq=4'), (1792946603.0, None))
        self.assertIsNone(parse_ping_line('PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.'))
        s = HostSampler()
        for l in ('[1.0] 64 bytes from x: icmp_seq=1 ttl=64 time=2.0 ms',
                  '[1.2] 64 bytes from x: icmp_seq=2 ttl=64 time=4.0 ms',
                  '[1.4] no answer yet for icmp_seq=3'):
            s.feed('ping', l)
        p = s.sample(2.0, {})['ping']
        self.assertEqual((p['avg_ms'], p['max_ms'], p['replies'], p['lost']), (3.0, 4.0, 2, 1))


if __name__ == '__main__':
    unittest.main()
