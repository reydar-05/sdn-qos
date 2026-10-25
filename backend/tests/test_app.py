"""Backend API tests (no network, no sudo):
    .venv/bin/python -m unittest discover -s backend/tests -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import app as backend  # noqa: E402

METRIC = {'ts': 0, 'poll': 1, 'mode': 'qos', 'video_path': 'A',
          'links': {'s4->s2': {'mbps': 10.0, 'utilization': 1.0, 'congested': True}},
          'video_mbps_by_switch': {'s4': 4.0}, 'congested_links': ['s4->s2'],
          'queues': {'s4-eth2:q1': {'mbps': 4.0}}, 'reroutes': 0}


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.pop('SDN_QOS_API_TOKEN', None)
        self.app = backend.create_app(results_dir=self.tmp.name)
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, kind, data):
        return self.c.post('/api/ingest', json={'kind': kind, 'data': data, 'mode': 'qos', 'run_id': 'r1'})

    def test_no_data_means_unreachable_not_demo(self):
        s = self.c.get('/api/status').get_json()
        self.assertFalse(s['controller']['reachable'])
        self.assertFalse(s['live'])
        self.assertIsNone(s['video_path'])
        self.assertEqual(self.c.get('/api/metrics').get_json()['metrics'], [])

    def test_ingest_then_status_and_metrics(self):
        self.assertEqual(self.push('metrics', dict(METRIC, ts=time.time())).status_code, 200)
        s = self.c.get('/api/status').get_json()
        self.assertTrue(s['controller']['reachable'])
        self.assertTrue(s['live'])
        self.assertEqual(s['video_path'], 'A')
        self.assertEqual(s['congested_links'], ['s4->s2'])
        m = self.c.get('/api/metrics').get_json()['metrics']
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]['run_id'], 'r1')
        # also written to disk
        with open(os.path.join(self.tmp.name, 'live', 'metrics.jsonl')) as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_stale_controller_is_reported(self):
        self.push('metrics', dict(METRIC, ts=time.time()))
        self.app.state.last_seen -= 3600
        s = self.c.get('/api/status').get_json()
        self.assertFalse(s['controller']['reachable'])
        self.assertFalse(s['live'])
        self.assertIn('no data from the controller', s['controller']['reason'])
        # old numbers are not served as the current state
        self.assertIsNone(s['video_path'])
        self.assertIsNone(self.c.get('/api/flows').get_json()['video_path'])
        self.assertNotIn('directions', self.c.get('/api/topology').get_json()['links'][0])
        self.assertIsNone(self.c.get('/api/queues').get_json()['live'])

    def test_bad_ingest_rejected(self):
        self.assertEqual(self.c.post('/api/ingest', json={'kind': 'x', 'data': {}}).status_code, 400)
        self.assertEqual(self.c.post('/api/ingest', data='not json').status_code, 400)

    def test_events_filter(self):
        self.push('event', {'ts': 1, 'event': 'congestion_detected', 'link': 's4->s2'})
        self.push('event', {'ts': 2, 'event': 'reroute', 'from_path': 'A', 'to_path': 'B'})
        ev = self.c.get('/api/events?type=reroute').get_json()['events']
        self.assertEqual([e['event'] for e in ev], ['reroute'])

    def test_heartbeat_gives_controller_details(self):
        self.push('heartbeat', {'ts': time.time(), 'mode': 'qos', 'switches_connected': ['s1', 's2'],
                                'flows_installed': True})
        ctl = self.c.get('/api/status').get_json()['controller']
        self.assertTrue(ctl['reachable'])
        self.assertEqual(ctl['switches_connected'], ['s1', 's2'])

    def test_token_required_when_set(self):
        os.environ['SDN_QOS_API_TOKEN'] = 'secret'
        try:
            c = backend.create_app(results_dir=self.tmp.name).test_client()
            self.assertEqual(c.get('/api/health').status_code, 200)       # health stays open
            self.assertEqual(c.get('/api/status').status_code, 401)
            self.assertEqual(c.post('/api/ingest', json={'kind': 'metrics', 'data': {}}).status_code, 401)
            ok = c.get('/api/status', headers={'Authorization': 'Bearer secret'})
            self.assertEqual(ok.status_code, 200)
        finally:
            os.environ.pop('SDN_QOS_API_TOKEN')

    def test_tunnelled_requests(self):
        fwd = {'X-Forwarded-For': '203.0.113.9'}
        # no token: remote reads refused, local reads fine
        self.assertEqual(self.c.get('/api/status', headers=fwd).status_code, 403)
        self.assertEqual(self.c.get('/api/status').status_code, 200)
        # ingest never through a tunnel, and never from another address
        r = self.c.post('/api/ingest', json={'kind': 'metrics', 'data': METRIC}, headers=fwd)
        self.assertEqual(r.status_code, 403)
        r = self.c.post('/api/ingest', json={'kind': 'metrics', 'data': METRIC},
                        environ_base={'REMOTE_ADDR': '10.1.2.3'})
        self.assertEqual(r.status_code, 403)
        os.environ['SDN_QOS_API_TOKEN'] = 'secret'
        try:
            c = backend.create_app(results_dir=self.tmp.name).test_client()
            auth = dict(fwd, Authorization='Bearer secret')
            self.assertEqual(c.get('/api/status', headers=auth).status_code, 200)
            self.assertEqual(c.get('/api/status', headers=fwd).status_code, 401)
            self.assertEqual(c.post('/api/ingest', json={'kind': 'metrics', 'data': METRIC},
                                    headers=auth).status_code, 403)
        finally:
            os.environ.pop('SDN_QOS_API_TOKEN')

    def test_cors_allowlist(self):
        good = self.c.get('/api/health', headers={'Origin': 'http://localhost:5173'})
        bad = self.c.get('/api/health', headers={'Origin': 'http://evil.example'})
        self.assertEqual(good.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173')
        self.assertIsNone(bad.headers.get('Access-Control-Allow-Origin'))

    def test_settings_and_topology_from_config(self):
        st = self.c.get('/api/settings').get_json()
        self.assertEqual(st['video']['port'], 5004)
        topo = self.c.get('/api/topology').get_json()
        self.assertEqual(set(topo['paths']), {'A', 'B'})
        self.assertEqual(len(topo['links']), 4)

    def test_experiments_listing_and_safe_ids(self):
        d = os.path.join(self.tmp.name, 'experiments', '20261025-1')
        os.makedirs(d)
        json.dump({'started': 1}, open(os.path.join(d, 'meta.json'), 'w'))
        json.dump({'groups': []}, open(os.path.join(d, 'summary.json'), 'w'))
        with open(os.path.join(d, 'runs.csv'), 'w') as f:
            f.write('mode,load,run\nqos,heavy,1\n')
        items = self.c.get('/api/experiments').get_json()['experiments']
        self.assertEqual(items[0]['id'], '20261025-1')
        e = self.c.get('/api/experiments/latest').get_json()
        self.assertEqual(e['runs'][0]['mode'], 'qos')
        self.assertEqual(e['run_dirs'], [])
        self.assertEqual(self.c.get('/api/experiments/..%2F..%2Fetc').status_code, 404)
        self.assertEqual(self.c.get('/api/experiments/bad$id').status_code, 400)

    def test_run_timeseries_from_saved_files(self):
        run = os.path.join(self.tmp.name, 'experiments', 'e1', 'qos-heavy-run1')
        os.makedirs(os.path.join(run, 'hosts'))
        json.dump({'name': 'qos-heavy-run1', 'mode': 'qos', 'load': 'heavy', 'bg_mbps': 9, 't0': 100.0},
                  open(os.path.join(run, 'run.json'), 'w'))
        iv = {'intervals': [{'sum': {'start': 0, 'seconds': 1, 'bytes': 500000, 'packets': 100,
                                     'lost_packets': 10, 'jitter_ms': 0.5}}]}
        json.dump(iv, open(os.path.join(run, 'hosts', 'iperf_video.json'), 'w'))
        with open(os.path.join(run, 'hosts', 'ping.log'), 'w') as f:
            f.write('[100.5] 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=2.0 ms\n'
                    '[100.7] no answer yet for icmp_seq=2\n')
        with open(os.path.join(run, 'events.jsonl'), 'w') as f:
            f.write(json.dumps({'ts': 101.0, 'event': 'reroute', 'from_path': 'A', 'to_path': 'B'}) + '\n')
        ts = self.c.get('/api/experiments/e1/runs/qos-heavy-run1/timeseries').get_json()
        self.assertEqual(ts['host'][0]['video_mbps'], 4.0)
        self.assertEqual(ts['host'][0]['video_loss_pct'], 10.0)
        self.assertEqual(ts['host'][0]['ping_ms'], 2.0)
        self.assertEqual(ts['host'][0]['ping_lost'], 1)
        self.assertEqual(ts['events'][0]['t'], 1.0)
        self.assertEqual(self.c.get('/api/experiments/e1/runs/nope/timeseries').status_code, 404)
        self.assertEqual(self.c.get('/api/experiments/e1/runs/b$d/timeseries').status_code, 400)
        self.assertEqual(self.c.get('/api/experiments/latest').status_code, 404)  # no summary yet

    def test_host_samples_do_not_count_as_controller(self):
        self.assertFalse(self.c.get('/api/host').get_json()['reporter']['reachable'])
        sample = {'ts': time.time(), 'video': {'mbps': 4.0, 'loss_pct': 0.0, 'jitter_ms': 0.1},
                  'background': None, 'ping': {'avg_ms': 0.2, 'lost': 0}, 'traffic': {'video': True}}
        self.assertEqual(self.push('host', sample).status_code, 200)
        h = self.c.get('/api/host').get_json()
        self.assertTrue(h['reporter']['reachable'])
        self.assertEqual(h['samples'][0]['video']['mbps'], 4.0)
        # host data alone must not make the controller look alive
        self.assertFalse(self.c.get('/api/status').get_json()['controller']['reachable'])
        with open(os.path.join(self.tmp.name, 'live', 'host.jsonl')) as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_environment_counts_live_check_lines_only(self):
        d = os.path.join(self.tmp.name, 'verify')
        os.makedirs(d)
        with open(os.path.join(d, 'phase1-20261025-1.log'), 'w') as f:
            f.write('[PASS] a\n[FAIL] b\nSUMMARY\n  [PASS] a\n  [FAIL] b\n')
        env = self.c.get('/api/environment').get_json()
        self.assertEqual(env['latest'][0]['passed'], 1)
        self.assertEqual(env['latest'][0]['failed'], 1)


if __name__ == '__main__':
    unittest.main()
