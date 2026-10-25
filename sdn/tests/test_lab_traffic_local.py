"""End-to-end check of the lab traffic code on localhost (real iperf3 and
ping, no Mininet, no sudo, about 8 s). Skipped if iperf3 is missing.
    .venv/bin/python -m unittest sdn/tests/test_lab_traffic_local.py -v
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from lab_traffic import Reporter, TrafficManager  # noqa: E402


def spawn(host, cmd, capture):
    if capture:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Collector(http.server.BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        Collector.got.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *a):
        pass


@unittest.skipUnless(shutil.which('iperf3') and shutil.which('stdbuf'), 'iperf3/stdbuf not installed')
class LabTrafficLocalTest(unittest.TestCase):
    def test_video_and_background_measured_and_reported(self):
        srv = http.server.HTTPServer(('127.0.0.1', 0), Collector)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tmp = tempfile.mkdtemp()
        rec = os.path.join(tmp, 'host.jsonl')
        rep = Reporter('http://127.0.0.1:%d' % srv.server_port, mode='test', run_id='t', log=lambda m: None)
        addr = {'server': '127.0.0.1', 'client': '127.0.0.1', 'background': '127.0.0.1'}
        tm = TrafficManager(spawn, addr, 15004, 4, 15201, {'light': 3, 'heavy': 9},
                            reporter=rep, record_path=rec, log=lambda m: None)
        try:
            tm.start()
            time.sleep(1)
            tm.set_video(True)
            tm.set_background('heavy')
            time.sleep(4.5)
            tm.set_background('off')
            time.sleep(1.5)
        finally:
            tm.stop()
            srv.shutdown()
        samples = [json.loads(l) for l in open(rec)]
        video = [s['video'] for s in samples if s['video']]
        bg = [s['background'] for s in samples if s['background']]
        ping = [s['ping'] for s in samples if s['ping']]
        self.assertGreaterEqual(len(video), 3)
        self.assertTrue(all(3.0 < v['mbps'] < 5.0 for v in video[1:]), video)
        self.assertTrue(any(7.0 < b['mbps'] < 11.0 for b in bg), bg)
        self.assertGreaterEqual(len(ping), 4)            # ping lines arrive live (stdbuf works)
        self.assertTrue(any(s['traffic']['background'] == 'heavy' for s in samples))
        self.assertEqual(samples[-1]['traffic']['background'], 'off')
        self.assertEqual(len(Collector.got), len(samples))
        self.assertEqual(Collector.got[0]['kind'], 'host')
        for p in tm.receivers:
            self.assertIsNotNone(p.poll())                # everything stopped


if __name__ == '__main__':
    unittest.main()
