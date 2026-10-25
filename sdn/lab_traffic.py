"""
Traffic and live host measurements for the interactive lab (Phase 6).

TrafficManager starts and stops the video and background streams and
keeps the receivers and the ping running. Their text output is read line
by line (HostSampler), and once a second a sample is sent to the Flask
backend (kind "host") and appended to <run dir>/host.jsonl.

Nothing here imports Mininet: the lab passes a spawn(host, cmd) function
that runs a command inside a Mininet host. The same code is tested on
localhost with plain subprocesses (sdn/tests/test_lab_traffic_local.py).
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

from host_monitor import HostSampler


def read_env_file(path):
    values = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                values[k.strip()] = v.strip()
    return values


class Reporter:
    """POSTs samples to the backend. Failures are logged once per change, never fatal."""

    def __init__(self, url, token=None, mode=None, run_id=None, log=print):
        self.url = url.rstrip('/') + '/api/ingest' if url and url != 'off' else None
        self.token, self.mode, self.run_id, self.log = token, mode, run_id, log
        self.ok = None
        self.sent = 0

    def send(self, sample):
        if not self.url:
            return False
        body = json.dumps({'kind': 'host', 'data': sample, 'mode': self.mode,
                           'run_id': self.run_id}).encode()
        req = urllib.request.Request(self.url, data=body, method='POST',
                                     headers={'Content-Type': 'application/json'})
        if self.token:
            req.add_header('Authorization', 'Bearer ' + self.token)
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                ok, why = r.status == 200, 'HTTP %d' % r.status
        except (urllib.error.URLError, OSError) as e:
            ok, why = False, str(getattr(e, 'reason', e))
        if ok != self.ok:
            self.log('  [host reporter] %s' % ('sending live host samples to the backend' if ok
                                              else 'backend not reachable (%s); samples still saved to file' % why))
            self.ok = ok
        self.sent += ok
        return ok


class TrafficManager:
    """
    spawn(host, cmd, capture) -> subprocess.Popen-like object
      host:    'server' (h2), 'client' (h1) or 'background' (h3)
      capture: True when stdout must be readable line by line
    addr:  {'server': ip, 'client': ip, 'background': ip}
    """

    def __init__(self, spawn, addr, video_port, video_mbps, bg_port, bg_levels,
                 reporter=None, record_path=None, interval=1.0, log=print):
        self.spawn, self.addr, self.log = spawn, addr, log
        self.video_port, self.video_mbps = video_port, video_mbps
        self.bg_port, self.bg_levels = bg_port, bg_levels
        self.reporter, self.record_path, self.interval = reporter, record_path, interval
        self.sampler = HostSampler()
        self.lock = threading.Lock()
        self.receivers = []
        self.video = None
        self.bg = None
        self.bg_level = 'off'
        self.stop_event = threading.Event()
        self.threads = []

    # -- helpers -------------------------------------------------------------
    def _reader(self, proc, source):
        def run():
            try:
                for line in proc.stdout:
                    self.sampler.feed(source, line)
            except (ValueError, OSError):
                pass  # pipe closed while stopping
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.threads.append(t)

    @staticmethod
    def _stop(proc):
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        for f in (proc.stdout, proc.stderr):
            if f:
                f.close()

    def traffic(self):
        with self.lock:
            return {'video': self.video is not None and self.video.poll() is None,
                    'video_mbps': self.video_mbps, 'background': self.bg_level,
                    'background_mbps': self.bg_levels.get(self.bg_level, 0)}

    # -- lifecycle -------------------------------------------------------------
    def start(self):
        """Receivers and ping run for the whole lab session."""
        for host, port, source in (('client', self.video_port, 'video'),
                                   ('background', self.bg_port, 'background')):
            p = self.spawn(host, ['iperf3', '-s', '-p', str(port), '-i', '1', '--forceflush'], True)
            self.receivers.append(p)
            self._reader(p, source)
        # stdbuf: ping only flushes per line when stdout is a terminal
        p = self.spawn('client', ['stdbuf', '-oL', 'ping', '-D', '-O', '-i', '0.2', self.addr['server']], True)
        self.receivers.append(p)
        self._reader(p, 'ping')
        t = threading.Thread(target=self._report_loop, daemon=True)
        t.start()
        self.threads.append(t)

    def _report_loop(self):
        nxt = time.time() + self.interval
        while not self.stop_event.wait(max(0.0, nxt - time.time())):
            nxt += self.interval
            sample = self.sampler.sample(round(time.time(), 3), self.traffic())
            if self.record_path:
                with open(self.record_path, 'a') as f:
                    f.write(json.dumps(sample) + '\n')
            if self.reporter:
                self.reporter.send(sample)

    def set_video(self, on):
        with self.lock:
            running = self.video is not None and self.video.poll() is None
            if on and not running:
                self.video = self.spawn('server', [
                    'iperf3', '-c', self.addr['client'], '-u', '-p', str(self.video_port),
                    '-b', '%sM' % self.video_mbps, '-t', '86400'], False)
            elif not on and running:
                self._stop(self.video)
                self.video = None
        self.log('  video %s' % ('ON (%s Mbit/s UDP port %d, h2 to h1)' % (self.video_mbps, self.video_port)
                                 if on else 'OFF'))

    def set_background(self, level):
        with self.lock:
            self._stop(self.bg)
            self.bg = None
            self.bg_level = 'off'
            if level != 'off':
                time.sleep(0.5)  # let the receiver finish the previous test
                self.bg = self.spawn('server', [
                    'iperf3', '-c', self.addr['background'], '-u', '-p', str(self.bg_port),
                    '-b', '%sM' % self.bg_levels[level], '-t', '86400'], False)
                self.bg_level = level
        self.log('  background %s' % ('OFF' if level == 'off' else '%s (%s Mbit/s, h2 to h3)'
                                      % (level.upper(), self.bg_levels[level])))

    def stop(self):
        self.stop_event.set()
        with self.lock:
            for p in [self.video, self.bg] + self.receivers:
                self._stop(p)
            self.video = self.bg = None
            self.bg_level = 'off'
