#!/usr/bin/env python3
"""
Interactive lab for the live demo (Phase 6).

Start it with scripts/start_lab.sh (as your normal user, it asks for sudo
once). Directly:
    sudo python3 sdn/lab.py [--mode qos|baseline] [--auto]

What it does:
1. cleans old Mininet state, then starts Ryu as your normal user (same
   code as the experiment runner), mode qos or baseline
2. builds the Mininet network with the OVS linux-htb queues
3. waits for the switches and the controller's rules
4. starts the receivers (iperf3 servers on h1 and h3) and a ping from
   h1 to h2, and sends one end-host sample per second to the backend
5. shows a menu to switch the video and background traffic on and off

Ryu sends its own metrics (port stats, utilization, reroutes) to the
backend by itself. Everything is saved under results/lab/<id>/.
Quitting (q, Ctrl-C, or scripts/stop_lab.sh) stops traffic, the network
and Ryu, and removes the OVS QoS rows.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import PROJECT_ROOT, load_config  # noqa: E402
from labutil import chown_to_sudo_user, read_jsonl, sh, wait_for_flows  # noqa: E402
from lab_traffic import Reporter, TrafficManager, read_env_file  # noqa: E402
from topology import apply_qos, build_network, clear_qos, wait_for_controller  # noqa: E402
from run_experiment import start_ryu, stop_ryu  # noqa: E402

from mininet.cli import CLI  # noqa: E402
from mininet.log import setLogLevel  # noqa: E402

SCENARIO = [(0, 'video'), (10, 'heavy'), (50, 'off')]   # auto demo, 60 s in total
SCENARIO_END = 60
PID_FILE = os.path.join(PROJECT_ROOT, 'results', 'lab', 'lab.pid')

MENU = """
  v  video on/off            l  light background (3 Mbit/s)
  h  heavy background        o  background off
  a  auto scenario: video, heavy background from 10 s to 50 s (60 s)
  s  status                  m  restart in the other mode (baseline/qos)
  c  Mininet CLI (exit to return)                q  quit
"""


LOG_FILE = None  # set to <run dir>/lab.log once the run directory exists


def log(msg):
    print(msg, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, 'a') as f:
            f.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), msg))


def kill_lab_traffic():
    """Leftover lab traffic processes only (matched by their exact options)."""
    sh("pkill -f '^iperf3 -s -p [0-9]+ -i 1 --forceflush' ; "
       "pkill -f '^iperf3 -c 10\\.0\\.0\\.[0-9]+ -u -p [0-9]+ -b [0-9.]+M -t 86400' ; "
       "pkill -f '^ping -D -O -i 0.2 10\\.0\\.0\\.'")


class Lab:
    def __init__(self, cfg, mode):
        self.cfg, self.mode = cfg, mode
        self.ryu = self.net = self.traffic = None
        self.qos_ports = []
        self.run_dir = None
        env = read_env_file(os.path.join(PROJECT_ROOT, 'config', 'environment.env'))
        self.backend = os.environ.get('SDN_QOS_BACKEND_URL') or env.get('SDN_QOS_BACKEND_URL') \
            or cfg['backend']['url']
        self.token = os.environ.get('SDN_QOS_API_TOKEN') or env.get('SDN_QOS_API_TOKEN')

    # -- start / stop ------------------------------------------------------
    def up(self):
        cfg = self.cfg
        run_id = 'lab-%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), self.mode)
        self.run_dir = os.path.join(PROJECT_ROOT, cfg['results']['dir'], 'lab', run_id)
        os.makedirs(self.run_dir, exist_ok=True)
        # Ryu runs as the normal user and writes metrics/events here
        chown_to_sudo_user(os.path.dirname(self.run_dir))
        global LOG_FILE
        LOG_FILE = os.path.join(self.run_dir, 'lab.log')
        log('\n=== Starting the lab in %s mode (%s)' % (self.mode.upper(), run_id))
        log('  cleaning old Mininet state')
        sh('mn -c')  # BEFORE Ryu starts: mn -c kills every ryu-manager
        kill_lab_traffic()
        log('  starting Ryu (log %s/ryu.log)' % os.path.relpath(self.run_dir, PROJECT_ROOT))
        self.ryu = start_ryu(cfg, self.mode, self.run_dir, run_id)
        log('  building the network and the OVS queues')
        self.net = build_network(cfg)
        self.qos_ports = apply_qos(cfg)
        states = wait_for_controller(self.net)
        if not all(states.values()):
            raise RuntimeError('switches not connected to the controller: %s' % states)
        log('  switches connected; waiting for the controller to install paths')
        if not wait_for_flows(list(cfg['topology']['switches']), 'nw_dst=', timeout=40):
            raise RuntimeError('controller did not install forwarding rules (see ryu.log)')

        v, b = cfg['video'], cfg['background']
        hosts = {'server': v['server'], 'client': v['client'], 'background': b['host']}
        net = self.net

        def spawn(role, cmd, capture):
            h = net.get(hosts[role])
            if capture:
                return h.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
            return h.popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        addr = {role: net.get(name).IP() for role, name in hosts.items()}
        reporter = Reporter(self.backend, self.token, self.mode, run_id, log=log)
        self.traffic = TrafficManager(spawn, addr, v['port'], v['bitrate_mbps'], b['port'],
                                      {'light': b['light_mbps'], 'heavy': b['heavy_mbps']},
                                      reporter=reporter,
                                      record_path=os.path.join(self.run_dir, 'host.jsonl'), log=log)
        self.traffic.start()
        chown_to_sudo_user(self.run_dir)
        log('=== Lab ready in %s mode. Dashboard: http://127.0.0.1:5173 (LIVE LAB)' % self.mode.upper())

    def down(self):
        if self.traffic:
            self.traffic.stop()
            self.traffic = None
        kill_lab_traffic()
        if self.net is not None:
            clear_qos(self.qos_ports)
            self.net.stop()
            self.net = None
        stop_ryu(self.ryu)
        self.ryu = None
        if self.run_dir:
            chown_to_sudo_user(self.run_dir)

    # -- menu actions --------------------------------------------------------
    def status(self):
        t = self.traffic.traffic()
        log('  mode %s | video %s | background %s (%s Mbit/s)'
            % (self.mode, 'ON' if t['video'] else 'off', t['background'], t['background_mbps']))
        metrics = read_jsonl(os.path.join(self.run_dir, 'metrics.jsonl'))
        if metrics:
            m = metrics[-1]
            log('  controller (%.0f s ago): video on Path %s, congested %s, reroutes %s'
                % (time.time() - m['ts'], m.get('video_path'), m.get('congested_links') or 'none',
                   m.get('reroutes')))
        else:
            log('  controller: no metrics written yet')
        hostf = os.path.join(self.run_dir, 'host.jsonl')
        samples = read_jsonl(hostf)[-1:] if os.path.exists(hostf) else []
        if samples:
            s = samples[0]
            vid, png = s.get('video') or {}, s.get('ping') or {}
            log('  hosts (last second): video %s Mbit/s, loss %s%%, jitter %s ms | ping %s ms'
                % (vid.get('mbps', '-'), vid.get('loss_pct', '-'), vid.get('jitter_ms', '-'),
                   png.get('avg_ms', '-')))
        r = self.traffic.reporter
        state = {True: 'OK', False: 'not reachable', None: 'nothing sent yet'}[r.ok]
        log('  backend %s: %s (%d samples sent)' % (self.backend, state, r.sent))

    def scenario(self):
        log('  auto scenario (%d s). Ctrl-C stops it and returns to the menu.' % SCENARIO_END)
        t0 = time.time()
        try:
            for at, action in SCENARIO + [(SCENARIO_END, None)]:
                while time.time() - t0 < at:
                    time.sleep(0.2)
                if action is None:
                    break
                log('  t=%2.0f s' % (time.time() - t0))
                if action == 'video':
                    self.traffic.set_video(True)
                else:
                    self.traffic.set_background(action)
        except KeyboardInterrupt:
            self.traffic.set_background('off')
            log('  scenario stopped')
            return
        log('  scenario finished; video keeps running (v to stop it)')

    def menu(self):
        log(MENU)
        while True:
            try:
                choice = input('lab[%s]> ' % self.mode).strip().lower()
            except EOFError:
                return
            t = self.traffic.traffic()
            if choice == 'v':
                self.traffic.set_video(not t['video'])
            elif choice in ('l', 'h'):
                self.traffic.set_background('light' if choice == 'l' else 'heavy')
            elif choice == 'o':
                self.traffic.set_background('off')
            elif choice == 'a':
                self.scenario()
            elif choice == 's':
                self.status()
            elif choice == 'm':
                new = 'baseline' if self.mode == 'qos' else 'qos'
                log('  restarting everything in %s mode (about 20 s)' % new.upper())
                self.down()
                self.mode = new
                self.up()
            elif choice == 'c':
                log('  Mininet CLI: try "h1 ping -c 3 h2". Type exit to come back.')
                CLI(self.net)
            elif choice == 'q':
                return
            elif choice:
                log(MENU)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mode', choices=['qos', 'baseline'], default='qos')
    ap.add_argument('--auto', action='store_true', help='run the auto scenario once, then show the menu')
    args = ap.parse_args()
    if os.geteuid() != 0 or 'SUDO_USER' not in os.environ:
        sys.exit('Run it from your normal user with: bash scripts/start_lab.sh')

    def to_exit(signum, frame):
        raise SystemExit('stopped by signal %d' % signum)
    signal.signal(signal.SIGTERM, to_exit)   # scripts/stop_lab.sh
    signal.signal(signal.SIGHUP, to_exit)    # terminal closed

    setLogLevel('warning')
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    lab = Lab(load_config(), args.mode)
    try:
        lab.up()
        if args.auto:
            lab.scenario()
        lab.menu()
    except KeyboardInterrupt:
        log('\n  Ctrl-C')
    finally:
        log('=== Stopping traffic, network and Ryu')
        lab.down()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        log('=== Lab stopped. Saved under %s' % (os.path.relpath(lab.run_dir, PROJECT_ROOT) if lab.run_dir else 'results/lab'))


if __name__ == '__main__':
    main()
