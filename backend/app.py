"""
Flask backend for the SDN QoS dashboard.

Run from the project root, as a normal user, from the venv:
    .venv/bin/python backend/app.py

- Binds to the host/port in config/config.yaml (127.0.0.1:5000).
- POST /api/ingest   the Ryu controller pushes metrics, events, heartbeats;
                     the lab script (sdn/lab.py) pushes end-host samples
- GET  /api/...      read-only data for the dashboard (see ROUTES below)
- Optional token: if SDN_QOS_API_TOKEN is set (environment or
  config/environment.env), every /api route except /api/health needs
  the header "Authorization: Bearer <token>".
- CORS: only the origins in SDN_QOS_CORS_ORIGINS (default: the local
  Vite dev server) may call the API from a browser.
- Remote access only through an HTTPS tunnel (see docs/deployment.md).
  A request that came through a proxy or tunnel (it carries a
  Forwarded / X-Forwarded-For / CF-Connecting-IP header) is refused
  unless a token is set, and /api/ingest never accepts such requests:
  only the controller and the lab on this machine may push data.

The backend never invents data. If the controller has not sent anything
recently, /api/status says so (controller.reachable = false) and the
dashboard must show an error state, not old or demo data.
"""
import collections
import csv
import glob
import json
import os
import re
import sys
import threading
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sdn'))
from qos_config import PROJECT_ROOT, link_capacity_mbps, load_config  # noqa: E402
from run_timeseries import build_timeseries  # noqa: E402

PROXY_HEADERS = ('Forwarded', 'X-Forwarded-For', 'X-Real-IP', 'CF-Connecting-IP')
LOOPBACK = ('127.0.0.1', '::1')
DEFAULT_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173'
SAFE_ID = re.compile(r'^[A-Za-z0-9_.-]+$')


def read_env_file(path):
    """KEY=VALUE lines from config/environment.env (if it exists)."""
    values = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    return values


def setting(name, default=None):
    env_file = read_env_file(os.path.join(PROJECT_ROOT, 'config', 'environment.env'))
    return os.environ.get(name) or env_file.get(name) or default


class LiveState:
    """Latest data pushed by the controller, kept in memory and on disk."""

    def __init__(self, live_dir, max_metrics=1800, max_events=2000):
        self.lock = threading.Lock()
        self.metrics = collections.deque(maxlen=max_metrics)   # 1 hour at 2 s polls
        self.events = collections.deque(maxlen=max_events)
        self.host = collections.deque(maxlen=3600)              # 1 hour at 1 s samples
        self.heartbeat = None
        self.last_seen = None          # controller only
        self.host_last_seen = None     # lab host reporter only
        self.live_dir = live_dir
        os.makedirs(live_dir, exist_ok=True)

    def add(self, kind, record):
        record = dict(record, received_ts=time.time())
        with self.lock:
            if kind == 'host':
                self.host_last_seen = record['received_ts']
                self.host.append(record)
            else:
                self.last_seen = record['received_ts']
            if kind == 'metrics':
                self.metrics.append(record)
            elif kind == 'event':
                self.events.append(record)
            elif kind == 'heartbeat':
                self.heartbeat = record
                return  # heartbeats are not stored on disk
            name = {'metrics': 'metrics.jsonl', 'event': 'events.jsonl', 'host': 'host.jsonl'}[kind]
            with open(os.path.join(self.live_dir, name), 'a') as f:
                f.write(json.dumps(record) + '\n')


def create_app(cfg=None, results_dir=None):
    cfg = cfg or load_config()
    results_dir = results_dir or os.path.join(PROJECT_ROOT, cfg['results']['dir'])
    app = Flask(__name__)
    app.json.sort_keys = False
    state = LiveState(os.path.join(results_dir, 'live'))
    token = setting('SDN_QOS_API_TOKEN')
    origins = [o.strip() for o in setting('SDN_QOS_CORS_ORIGINS', DEFAULT_ORIGINS).split(',') if o.strip()]
    CORS(app, resources={r'/api/*': {'origins': origins}},
         allow_headers=['Content-Type', 'Authorization'])
    poll = cfg['monitoring']['poll_interval_s']
    stale_after = 3 * poll + 2
    app.state = state

    @app.before_request
    def check_access():
        via_proxy = any(h in request.headers for h in PROXY_HEADERS)
        if request.path == '/api/ingest' and (via_proxy or request.remote_addr not in LOOPBACK):
            return jsonify(error='ingest is only accepted from this machine'), 403
        if via_proxy and not token and request.path.startswith('/api/') and request.method != 'OPTIONS':
            return jsonify(error='remote access needs SDN_QOS_API_TOKEN to be set on the backend'), 403
        if not token or request.method == 'OPTIONS' or request.path == '/api/health':
            return None
        if request.path.startswith('/api/') and \
                request.headers.get('Authorization', '') != 'Bearer ' + token:
            return jsonify(error='missing or wrong API token'), 401
        return None

    def latest_metrics():
        with state.lock:
            return state.metrics[-1] if state.metrics else None

    def controller_status():
        now = time.time()
        with state.lock:
            last, hb = state.last_seen, state.heartbeat
        if last is None:
            return dict(reachable=False, reason='no data received from the controller yet')
        age = now - last
        status = dict(reachable=age <= stale_after, last_seen_s_ago=round(age, 1),
                      stale_after_s=stale_after)
        if not status['reachable']:
            status['reason'] = 'no data from the controller for %.0f s' % age
        if hb:
            status.update(mode=hb.get('mode'), run_id=hb.get('run_id'),
                          switches_connected=hb.get('switches_connected'),
                          flows_installed=hb.get('flows_installed'),
                          reroute_enabled=hb.get('reroute_enabled'),
                          queues_enabled=hb.get('queues_enabled'))
        return status

    def live_metrics():
        """Latest metrics, but only while the controller is reachable: old
        numbers are never served as the current state."""
        return latest_metrics() if controller_status()['reachable'] else None

    # ------------------------------------------------------------------
    @app.get('/api/health')
    def health():
        return jsonify(ok=True, time=time.time(), service='sdn-qos-backend')

    @app.post('/api/ingest')
    def ingest():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get('kind') not in ('metrics', 'event', 'heartbeat', 'host') \
                or not isinstance(body.get('data'), dict):
            return jsonify(error='expected {"kind": metrics|event|heartbeat|host, "data": {...}}'), 400
        record = dict(body['data'], run_id=body.get('run_id'), mode=body.get('mode'))
        state.add(body['kind'], record)
        return jsonify(ok=True)

    @app.get('/api/status')
    def status():
        m = live_metrics()
        ctl = controller_status()
        live = ctl['reachable'] and m is not None
        return jsonify(
            controller=ctl,
            live=live,
            latest_metrics_ts=m and m.get('ts'),
            video_path=m and m.get('video_path'),
            congested_links=m and m.get('congested_links'),
            reroutes=m and m.get('reroutes'),
            mode=(m and m.get('mode')) or ctl.get('mode'))

    @app.get('/api/metrics')
    def metrics():
        since = request.args.get('since', type=float)
        limit = min(request.args.get('limit', default=300, type=int), 1800)
        with state.lock:
            rows = [m for m in state.metrics if since is None or m['ts'] > since]
        return jsonify(controller=controller_status(), metrics=rows[-limit:])

    def host_status():
        with state.lock:
            last = state.host_last_seen
        if last is None:
            return dict(reachable=False, reason='no end-host samples yet (start traffic from the lab menu)')
        age = time.time() - last
        out = dict(reachable=age <= 5, last_seen_s_ago=round(age, 1))
        if not out['reachable']:
            out['reason'] = 'no end-host samples for %.0f s' % age
        return out

    @app.get('/api/host')
    def host():
        """End-host measurements (iperf3 receivers and ping), one sample per second."""
        since = request.args.get('since', type=float)
        limit = min(request.args.get('limit', default=300, type=int), 3600)
        with state.lock:
            rows = [h for h in state.host if since is None or h['ts'] > since]
        return jsonify(reporter=host_status(), source='end hosts: iperf3 receiver reports and ping',
                       samples=rows[-limit:])

    @app.get('/api/events')
    def events():
        limit = min(request.args.get('limit', default=200, type=int), 2000)
        kind = request.args.get('type')
        with state.lock:
            rows = [e for e in state.events if not kind or e.get('event', '').startswith(kind)]
        return jsonify(controller=controller_status(), events=rows[-limit:])

    @app.get('/api/flows')
    def flows():
        m = live_metrics()
        topo = cfg['topology']
        v = cfg['video']
        return jsonify(
            controller=controller_status(),
            paths=topo['paths'], default_path=topo['primary_path'],
            video_path=m and m.get('video_path'),
            classification=dict(
                video=dict(match='UDP port %d (source or destination), %s <-> %s'
                           % (v['port'], v['server'], v['client']),
                           queue=cfg['queues']['video_queue_id'],
                           ping_probe_follows_video=v.get('ping_follows_video')),
                other=dict(match='IPv4 by destination address', queue=cfg['queues']['default_queue_id'])),
            video_mbps_by_switch=m and m.get('video_mbps_by_switch'),
            mode=m and m.get('mode'))

    @app.get('/api/topology')
    def topology():
        m = live_metrics()
        topo = cfg['topology']
        links = []
        for l in topo['links']:
            entry = dict(a=l['a'], a_port=l['a_port'], b=l['b'], b_port=l['b_port'],
                         capacity_mbps=link_capacity_mbps(cfg, l))
            if m:
                entry['directions'] = {d: m['links'].get(d) for d in
                                       ('%s->%s' % (l['a'], l['b']), '%s->%s' % (l['b'], l['a']))}
            links.append(entry)
        return jsonify(controller=controller_status(), switches=topo['switches'],
                       hosts=topo['hosts'], links=links, paths=topo['paths'],
                       primary_path=topo['primary_path'],
                       video_path=m and m.get('video_path'),
                       congested_links=m and m.get('congested_links'))

    @app.get('/api/queues')
    def queues():
        m = live_metrics()
        return jsonify(controller=controller_status(), config=cfg['queues'],
                       capacity_mbps=cfg['links']['default_capacity_mbps'],
                       queue_limit_packets=cfg['links'].get('queue_limit_packets'),
                       enabled=controller_status().get('queues_enabled'),
                       live=m and m.get('queues'))

    @app.get('/api/settings')
    def settings():
        keys = ('video', 'monitoring', 'links', 'queues', 'background', 'experiment', 'playout_model')
        out = {k: cfg[k] for k in keys if k in cfg}
        out['ports'] = dict(openflow=cfg['controller']['openflow_port'], backend=cfg['backend']['port'])
        out['config_file'] = os.path.relpath(cfg['_path'], PROJECT_ROOT)
        return jsonify(out)

    # ------------------------------------------------------------------
    # Experiment results (written by sdn/run_experiment.py)
    # ------------------------------------------------------------------
    exp_root = os.path.join(results_dir, 'experiments')

    def read_json(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    @app.get('/api/experiments')
    def experiments():
        items = []
        for d in sorted(glob.glob(os.path.join(exp_root, '*')), reverse=True):
            if not os.path.isdir(d):
                continue
            meta = read_json(os.path.join(d, 'meta.json')) or {}
            items.append(dict(id=os.path.basename(d), started=meta.get('started'),
                              finished=meta.get('finished'), args=meta.get('args'),
                              complete=os.path.exists(os.path.join(d, 'summary.json'))))
        return jsonify(experiments=items)

    @app.get('/api/experiments/<exp_id>')
    def experiment(exp_id):
        if exp_id == 'latest':
            done = [d for d in sorted(glob.glob(os.path.join(exp_root, '*')), reverse=True)
                    if os.path.exists(os.path.join(d, 'summary.json'))]
            if not done:
                return jsonify(error='no finished experiment yet'), 404
            exp_id = os.path.basename(done[0])
        if not SAFE_ID.match(exp_id):
            return jsonify(error='bad experiment id'), 400
        d = os.path.join(exp_root, exp_id)
        if not os.path.isdir(d):
            return jsonify(error='experiment not found'), 404
        runs = []
        if os.path.exists(os.path.join(d, 'runs.csv')):
            with open(os.path.join(d, 'runs.csv')) as f:
                runs = list(csv.DictReader(f))
        run_dirs = sorted(os.path.basename(r) for r in glob.glob(os.path.join(d, '*'))
                          if os.path.exists(os.path.join(r, 'run.json')))
        return jsonify(id=exp_id, meta=read_json(os.path.join(d, 'meta.json')),
                       summary=read_json(os.path.join(d, 'summary.json')), runs=runs,
                       run_dirs=run_dirs)

    @app.get('/api/experiments/<exp_id>/runs/<run>/timeseries')
    def run_timeseries(exp_id, run):
        """Per-second host and controller series of one recorded run."""
        if not SAFE_ID.match(exp_id) or not SAFE_ID.match(run) or '..' in exp_id + run:
            return jsonify(error='bad id'), 400
        d = os.path.join(exp_root, exp_id, run)
        if not os.path.exists(os.path.join(d, 'run.json')):
            return jsonify(error='run not found'), 404
        meta = read_json(os.path.join(exp_root, exp_id, 'meta.json')) or {}
        bg_start = (meta.get('timeline') or {}).get('bg_start', cfg['experiment']['background_start_s'])
        out = build_timeseries(d, bg_start)
        out['experiment'] = exp_id
        out['timeline'] = meta.get('timeline')
        return jsonify(out)

    @app.get('/api/environment')
    def environment():
        """Results of the verification scripts (results/verify/*.log)."""
        checks = []
        for path in sorted(glob.glob(os.path.join(results_dir, 'verify', '*.log'))):
            text = open(path, errors='replace').read()
            passed = len(re.findall(r'^\[PASS\]', text, re.M))  # live lines only, not the indented summary
            failed = len(re.findall(r'^\[FAIL\]', text, re.M))
            name = os.path.basename(path)[:-4]
            checks.append(dict(name=name, phase=name.split('-')[0], passed=passed,
                               failed=failed, file=os.path.relpath(path, PROJECT_ROOT)))
        latest = {}
        for c in checks:  # newest log per phase (names sort by time)
            latest[c['phase']] = c
        return jsonify(latest=list(latest.values()), all=checks)

    return app


if __name__ == '__main__':
    cfg = load_config()
    host, port = cfg['backend']['host'], cfg['backend']['port']
    if host not in ('127.0.0.1', 'localhost'):
        sys.exit('Refusing to bind to %s: the backend must stay on localhost.' % host)
    create_app(cfg).run(host=host, port=port, debug=False, threaded=True)
