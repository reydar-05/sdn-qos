"""
Ryu controller (OpenFlow 1.3) for SDN-based QoS management of video.

Start it from the project root, as a normal user, from the venv:
    .venv/bin/ryu-manager --ofp-listen-host 127.0.0.1 --ofp-tcp-listen-port 6653 \
        --observe-links sdn/controller.py

What it does (Phase 1):
1. Switch connect: installs a table-miss DROP rule and an ARP-to-controller
   rule, and asks the switch for its port list (names and numbers).
2. Topology: Ryu's LLDP discovery (--observe-links) reports every
   switch-to-switch link. The controller checks them against
   config/config.yaml and waits until all expected links are seen.
3. ARP without flooding: every ARP request comes to the controller,
   which answers it from the host table in the config. Nothing is ever
   flooded, so the loop s1-s2-s4-s3-s1 cannot cause a broadcast storm.
4. Forwarding: explicit rules per destination host along the primary path
   (Path A), plus higher-priority rules for the video flow (matched by
   its UDP port) between the video server and client.

Phase 2 (monitoring and congestion detection):
5. Every poll_interval_s it asks each switch for port statistics and for
   the counters of the video rules. Byte deltas give throughput per
   directed link; throughput / capacity gives utilization.
6. A link is congested after consecutive_polls samples in a row above
   utilization_threshold (sdn/monitor.py). Detection and clearing are
   logged as events. A switch that does not answer is logged as
   stats_missing and skipped; its links keep their last values, marked
   stale.
7. Every poll writes one metrics record (JSON line) to metrics.jsonl.

Phase 3 (rerouting and priority queue, mode "qos" only):
8. Every poll, if a link on the video's current path is congested, the
   controller picks the least loaded other path. It only moves the video
   if that path would stay under the threshold with the video added,
   no reroute happened in the last cooldown_s, and fewer than
   max_reroutes_per_run reroutes were done. Otherwise it logs why not.
9. Make-before-break: the new video rules are installed with a higher
   priority and a new cookie, a barrier confirms them, then the old
   rules are deleted by cookie. The barrier round trip is logged as the
   rule install time.
10. Video packets (and the ping probe) get a set_queue action to the
   video queue on every switch-to-switch port, so they use the HTB
   queue with the guaranteed rate. Other traffic stays in queue 0.
Mode "baseline": same forwarding on Path A, no reroute, no set_queue.
Env SDN_QOS_REROUTE=0 or SDN_QOS_QUEUES=0 turns one part off in qos mode
(used to measure each mechanism on its own).
Phase 4: every metrics record, event and a heartbeat per poll are also
pushed to the Flask backend (POST /api/ingest) from a background green
thread with a bounded queue, so a slow or stopped backend never blocks
the controller. Backend URL/token: SDN_QOS_BACKEND_URL ('off' disables)
and SDN_QOS_API_TOKEN, from the environment or config/environment.env.
The controller only measures throughput, utilization and drop counters.
Delay, jitter and loss are measured at the hosts, never here.
"""
import collections
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import (PROJECT_ROOT, dpid_of, link_capacity_mbps, load_config,  # noqa: E402
                        switch_of_dpid)
from monitor import CongestionDetector, RateTracker  # noqa: E402

from ryu import cfg as ryu_cfg  # noqa: E402
from ryu.base import app_manager  # noqa: E402
from ryu.controller import ofp_event  # noqa: E402
from ryu.lib import hub  # noqa: E402
from ryu.controller.handler import (CONFIG_DISPATCHER, DEAD_DISPATCHER,  # noqa: E402
                                    MAIN_DISPATCHER, set_ev_cls)
from ryu.lib.packet import arp, ethernet, ether_types, packet  # noqa: E402
from ryu.ofproto import inet, ofproto_v1_3  # noqa: E402
from ryu.topology import event as topo_event  # noqa: E402

# Rule priorities: a higher number wins when several rules match.
PRIO_TABLE_MISS = 0     # anything unknown: drop
PRIO_DEFAULT = 10       # normal traffic, by destination IP
PRIO_VIDEO = 20         # video flow (UDP video port) and the ping probe
PRIO_ARP = 100          # ARP goes to the controller

# Cookies tag our rules so they can be found and deleted as a group.
COOKIE_BASE = 0x1
COOKIE_DEFAULT = 0x10
COOKIE_VIDEO = 0x20


class QoSController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QoSController, self).__init__(*args, **kwargs)
        self.cfg = load_config()
        self.mode = os.environ.get('SDN_QOS_MODE', 'qos')
        if self.mode not in ('baseline', 'qos'):
            raise ValueError('SDN_QOS_MODE must be baseline or qos, got %r' % self.mode)
        topo = self.cfg['topology']
        self.expected_dpids = set(topo['switches'].values())
        self.hosts = topo['hosts']
        self.arp_table = {h['ip']: h['mac'] for h in self.hosts.values()}
        self.server_ip = self.hosts[self.cfg['video']['server']]['ip']

        self.datapaths = {}     # dpid -> datapath
        self.port_names = {}    # dpid -> {port_no: name}
        self.adj = {}           # dpid -> {neighbour dpid: local port}, learned by LLDP
        self.flows_installed = False
        self.video_path = topo['primary_path']
        self.arp_replies = 0

        run_dir = os.environ.get('SDN_QOS_RUN_DIR',
                                 os.path.join(PROJECT_ROOT, self.cfg['results']['dir'], 'controller'))
        os.makedirs(run_dir, exist_ok=True)
        self.events_file = os.path.join(run_dir, 'events.jsonl')
        self.metrics_file = os.path.join(run_dir, 'metrics.jsonl')

        # Monitoring state. Directed links: 's4->s2' means traffic leaving
        # s4 toward s2, measured by the tx counter of s4's port to s2.
        mon = self.cfg['monitoring']
        self.directed_links = {}
        for link in topo['links']:
            cap = link_capacity_mbps(self.cfg, link)
            for a, ap, b in ((link['a'], link['a_port'], link['b']),
                             (link['b'], link['b_port'], link['a'])):
                self.directed_links['%s->%s' % (a, b)] = dict(
                    dpid=dpid_of(self.cfg, a), port=ap, capacity_mbps=cap)
        self.rates = RateTracker()
        self.detector = CongestionDetector(mon['utilization_threshold'], mon['consecutive_polls'])
        self.link_metrics = {}   # link name -> latest computed values
        self.video_mbps = {}     # switch -> video data rate through it
        self.pending = {}        # dpid -> time the outstanding stats request was sent
        self.fresh = set()       # links updated since the last metrics record
        self.poll_no = 0

        # Phase 3: rerouting and queues (only in qos mode)
        qos = self.mode == 'qos'
        self.reroute_enabled = qos and os.environ.get('SDN_QOS_REROUTE', '1') != '0'
        self.queues_enabled = qos and os.environ.get('SDN_QOS_QUEUES', '1') != '0'
        self.max_reroutes = min(mon['max_reroutes_per_run'], 14)  # keeps cookies/priorities in range
        self.video_gen = 0           # generation of the video rules now in use
        self.reroute_count = 0
        self.last_reroute_ts = None
        self.last_skip_reason = None
        self.barriers = {}           # xid -> (reroute id, dpid)
        self.reroute_pending = None  # info about a reroute waiting for barrier replies
        self.queue_metrics = {}

        if not ryu_cfg.CONF.observe_links:
            self.logger.error('Started without --observe-links: links will never be '
                              'discovered and no forwarding rules will be installed.')
        # Phase 4: push to the Flask backend
        env_file = {}
        env_path = os.path.join(PROJECT_ROOT, 'config', 'environment.env')
        if os.path.exists(env_path):
            for line in open(env_path):
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    env_file[k.strip()] = v.strip()
        setting = lambda k, d=None: os.environ.get(k) or env_file.get(k) or d
        url = setting('SDN_QOS_BACKEND_URL', self.cfg['backend']['url'])
        self.backend_url = None if url == 'off' else url.rstrip('/') + '/api/ingest'
        token = setting('SDN_QOS_API_TOKEN')
        self.backend_headers = {'Authorization': 'Bearer ' + token} if token else {}
        self.run_id = os.environ.get('SDN_QOS_RUN_ID', 'live')
        self.outbox = collections.deque(maxlen=500)   # oldest dropped if backend is down
        self.backend_ok = None
        if self.backend_url:
            self.sender_thread = hub.spawn(self.backend_sender)

        self.log_event('controller_started', mode=self.mode, config=self.cfg['_path'],
                       poll_interval_s=mon['poll_interval_s'],
                       threshold=mon['utilization_threshold'],
                       consecutive_polls=mon['consecutive_polls'],
                       reroute_enabled=self.reroute_enabled,
                       queues_enabled=self.queues_enabled,
                       cooldown_s=mon['cooldown_s'])
        self.monitor_thread = hub.spawn(self.monitor_loop)

    # ------------------------------------------------------------------
    # Event log (JSON lines, one object per line)
    # ------------------------------------------------------------------
    def log_event(self, kind, **data):
        record = {'ts': time.time(), 'event': kind}
        record.update(data)
        with open(self.events_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
        self.logger.info('EVENT %s %s', kind, json.dumps(data))
        self.publish('event', record)

    def publish(self, kind, data):
        if getattr(self, 'backend_url', None):
            self.outbox.append({'kind': kind, 'data': data, 'mode': self.mode, 'run_id': self.run_id})

    def backend_sender(self):
        """Send queued records to Flask. Logs only when reachability changes."""
        session = requests.Session()
        while True:
            if not self.outbox:
                hub.sleep(0.2)
                continue
            item = self.outbox[0]
            try:
                r = session.post(self.backend_url, json=item, headers=self.backend_headers, timeout=2)
                ok = r.status_code == 200
                problem = None if ok else 'HTTP %d %s' % (r.status_code, r.text[:100])
            except requests.RequestException as e:
                ok, problem = False, type(e).__name__
            if ok:
                self.outbox.popleft()
            if ok != self.backend_ok:
                if ok:
                    self.logger.info('backend reachable at %s', self.backend_url)
                else:
                    self.logger.warning('backend not reachable at %s (%s); keeping the last %d '
                                        'records and retrying', self.backend_url, problem,
                                        self.outbox.maxlen)
                self.backend_ok = ok
            if not ok:
                hub.sleep(2)

    def sw(self, dpid):
        return switch_of_dpid(self.cfg, dpid) or 'dpid%s' % dpid

    # ------------------------------------------------------------------
    # Switch connection
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_switch_features(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        # Start clean: remove forwarding rules left from an earlier controller
        # session (only our cookies, so Ryu's own LLDP rule is untouched).
        for cookie in (COOKIE_DEFAULT, COOKIE_VIDEO):
            self.delete_flows(dp, cookie)
        # Table-miss: no actions means drop. Unknown traffic is never flooded.
        self.add_flow(dp, PRIO_TABLE_MISS, parser.OFPMatch(), [], COOKIE_BASE)
        # All ARP goes to the controller, which answers it (proxy ARP).
        self.add_flow(dp, PRIO_ARP, parser.OFPMatch(eth_type=ether_types.ETH_TYPE_ARP),
                      [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)],
                      COOKIE_BASE)
        dp.send_msg(parser.OFPPortDescStatsRequest(dp, 0))

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def on_port_desc(self, ev):
        dp = ev.msg.datapath
        names = {}
        for p in ev.msg.body:
            if p.port_no < dp.ofproto.OFPP_MAX:
                names[p.port_no] = p.name.decode() if isinstance(p.name, bytes) else p.name
        self.port_names[dp.id] = dict(sorted(names.items()))
        self.log_event('switch_ports', switch=self.sw(dp.id), dpid=dp.id,
                       ports={str(k): v for k, v in self.port_names[dp.id].items()})

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def on_state_change(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if dp.id not in self.datapaths:
                self.datapaths[dp.id] = dp
                self.log_event('switch_connected', switch=self.sw(dp.id), dpid=dp.id,
                               known=dp.id in self.expected_dpids)
                # A (re)connected switch has an empty table: reinstall everything.
                self.flows_installed = False
                self.try_install()
        elif ev.state == DEAD_DISPATCHER and dp.id in self.datapaths:
            del self.datapaths[dp.id]
            self.adj.pop(dp.id, None)
            for nbrs in self.adj.values():
                nbrs.pop(dp.id, None)
            self.flows_installed = False
            self.log_event('switch_disconnected', switch=self.sw(dp.id), dpid=dp.id)

    # ------------------------------------------------------------------
    # Topology discovery (LLDP, from ryu.topology with --observe-links)
    # ------------------------------------------------------------------
    @set_ev_cls(topo_event.EventLinkAdd)
    def on_link_add(self, ev):
        s, d = ev.link.src, ev.link.dst
        if self.adj.get(s.dpid, {}).get(d.dpid) == s.port_no:
            return
        self.adj.setdefault(s.dpid, {})[d.dpid] = s.port_no
        a, b = self.sw(s.dpid), self.sw(d.dpid)
        expected = self.expected_port(a, b)
        self.log_event('link_discovered', src=a, src_port=s.port_no, dst=b,
                       dst_port=d.port_no, matches_config=expected == s.port_no)
        if expected != s.port_no:
            self.logger.warning('LLDP link %s:%s -> %s does not match config (expected port %s)',
                                a, s.port_no, b, expected)
        self.try_install()

    @set_ev_cls(topo_event.EventLinkDelete)
    def on_link_delete(self, ev):
        s, d = ev.link.src, ev.link.dst
        if self.adj.get(s.dpid, {}).pop(d.dpid, None) is not None:
            self.log_event('link_lost', src=self.sw(s.dpid), dst=self.sw(d.dpid))

    def expected_port(self, a, b):
        for link in self.cfg['topology']['links']:
            if (link['a'], link['b']) == (a, b):
                return link['a_port']
            if (link['b'], link['a']) == (a, b):
                return link['b_port']
        return None

    def topology_complete(self):
        if not self.expected_dpids.issubset(self.datapaths):
            return False
        for link in self.cfg['topology']['links']:
            a, b = dpid_of(self.cfg, link['a']), dpid_of(self.cfg, link['b'])
            if b not in self.adj.get(a, {}) or a not in self.adj.get(b, {}):
                return False
        return True

    # ------------------------------------------------------------------
    # Path computation
    # ------------------------------------------------------------------
    def out_port(self, sw_name, dst_host, path_name):
        """Port on switch sw_name toward dst_host when following path_name."""
        h = self.hosts[dst_host]
        if sw_name == h['switch']:
            return h['port']
        path = self.cfg['topology']['paths'][path_name]
        if sw_name not in path or h['switch'] not in path:
            return None
        i, j = path.index(sw_name), path.index(h['switch'])
        nxt = path[i + 1] if j > i else path[i - 1]
        return self.adj[dpid_of(self.cfg, sw_name)][dpid_of(self.cfg, nxt)]

    def default_path_for(self, sw_name, dst_host):
        """Primary path if it covers this switch, otherwise any path that does."""
        paths = self.cfg['topology']['paths']
        dst_sw = self.hosts[dst_host]['switch']
        order = [self.cfg['topology']['primary_path']] + sorted(paths)
        for name in order:
            if sw_name in paths[name] and dst_sw in paths[name]:
                return name
        return None

    def path_switches(self, path_name, src_host, dst_host):
        """Switches a packet visits from src_host to dst_host on path_name, in order."""
        path = list(self.cfg['topology']['paths'][path_name])
        if path.index(self.hosts[src_host]['switch']) > path.index(self.hosts[dst_host]['switch']):
            path.reverse()
        return path

    # ------------------------------------------------------------------
    # Flow installation
    # ------------------------------------------------------------------
    def add_flow(self, dp, priority, match, actions, cookie):
        parser, ofp = dp.ofproto_parser, dp.ofproto
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)] if actions else []
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, cookie=cookie))

    def delete_flows(self, dp, cookie, mask=0xF0):
        """Delete every rule whose cookie matches under mask.
        mask 0xF0: a whole group (e.g. all video generations); 0xFF: one generation."""
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                                      table_id=ofp.OFPTT_ALL, out_port=ofp.OFPP_ANY,
                                      out_group=ofp.OFPG_ANY, cookie=cookie,
                                      cookie_mask=mask, match=parser.OFPMatch()))

    def send_barrier(self, dp, tag):
        """A barrier reply means the switch finished every earlier message."""
        req = dp.ofproto_parser.OFPBarrierRequest(dp)
        dp.set_xid(req)
        self.barriers[req.xid] = (tag, dp.id)
        dp.send_msg(req)

    def try_install(self):
        if self.flows_installed or not self.topology_complete():
            return
        self.install_default_rules()
        self.install_video_rules(self.video_path, self.video_gen)
        self.flows_installed = True
        self.log_event('flows_installed', mode=self.mode, video_path=self.video_path,
                       default_path=self.cfg['topology']['primary_path'],
                       video_queue=self.queues_enabled)

    def install_default_rules(self):
        """One rule per (switch, destination host): forward by IPv4 destination."""
        for sw_name in self.cfg['topology']['switches']:
            dp = self.datapaths[dpid_of(self.cfg, sw_name)]
            parser = dp.ofproto_parser
            for host, h in self.hosts.items():
                path = self.default_path_for(sw_name, host)
                if path is None:
                    continue
                port = self.out_port(sw_name, host, path)
                match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=h['ip'])
                self.add_flow(dp, PRIO_DEFAULT, match, [parser.OFPActionOutput(port)],
                              COOKIE_DEFAULT)

    def video_matches(self, parser, src_host, dst_host):
        """Matches for the video class from src_host to dst_host."""
        v = self.cfg['video']
        src, dst = self.hosts[src_host]['ip'], self.hosts[dst_host]['ip']
        base = dict(eth_type=ether_types.ETH_TYPE_IP, ipv4_src=src, ipv4_dst=dst,
                    ip_proto=inet.IPPROTO_UDP)
        # The video port can be on either end (it depends on which side
        # opened the session), so match it as destination and as source.
        matches = [parser.OFPMatch(udp_dst=v['port'], **base),
                   parser.OFPMatch(udp_src=v['port'], **base)]
        base.pop('ip_proto')
        if v.get('ping_follows_video'):
            matches.append(parser.OFPMatch(ip_proto=inet.IPPROTO_ICMP, **base))
        return matches

    def install_video_rules(self, path_name, gen):
        """Video rules along path_name, both directions, installed from the
        destination end backwards so the downstream hops are ready before
        the first switch starts sending traffic onto the path.
        Generation gen gets priority PRIO_VIDEO+gen and cookie COOKIE_VIDEO+gen,
        so a newer set always wins over an older one still in the table."""
        v = self.cfg['video']
        qid = self.cfg['queues']['video_queue_id']
        for src_host, dst_host in ((v['server'], v['client']), (v['client'], v['server'])):
            for sw_name in reversed(self.path_switches(path_name, src_host, dst_host)):
                dpid = dpid_of(self.cfg, sw_name)
                dp = self.datapaths[dpid]
                parser = dp.ofproto_parser
                port = self.out_port(sw_name, dst_host, path_name)
                actions = [parser.OFPActionOutput(port)]
                # Queues exist only on switch-to-switch ports (OVS QoS is set there).
                if self.queues_enabled and port in self.adj.get(dpid, {}).values():
                    actions.insert(0, parser.OFPActionSetQueue(qid))
                for match in self.video_matches(parser, src_host, dst_host):
                    self.add_flow(dp, PRIO_VIDEO + gen, match, actions, COOKIE_VIDEO + gen)

    # ------------------------------------------------------------------
    # Rerouting (Phase 3)
    # ------------------------------------------------------------------
    def path_links(self, path_name):
        v = self.cfg['video']
        sws = self.path_switches(path_name, v['server'], v['client'])
        return ['%s->%s' % (a, b) for a, b in zip(sws, sws[1:])]

    def path_load(self, path_name):
        """Highest utilization on the path's links (video direction), or None
        if any of them has no fresh measurement."""
        utils = []
        max_age = 1.5 * self.cfg['monitoring']['poll_interval_s']
        for name in self.path_links(path_name):
            m = self.link_metrics.get(name)
            if m is None or time.time() - m['ts'] > max_age:
                return None
            utils.append(m['utilization'])
        return max(utils)

    def video_rate_mbps(self):
        """Measured video rate where it enters the network, else the configured rate."""
        server_sw = self.hosts[self.cfg['video']['server']]['switch']
        return self.video_mbps.get(server_sw) or self.cfg['video']['bitrate_mbps']

    def maybe_reroute(self):
        """Called once per poll. Decides whether to move the video."""
        if not self.reroute_enabled:
            return
        congested = [l for l in self.video_links() if self.detector.is_congested(l)]
        if not congested:
            self.last_skip_reason = None
            return
        mon = self.cfg['monitoring']
        th = mon['utilization_threshold']
        now = time.time()
        loads = {p: self.path_load(p) for p in self.cfg['topology']['paths'] if p != self.video_path}
        known = {p: u for p, u in loads.items() if u is not None}
        best = min(known, key=known.get) if known else None
        cap = min(self.directed_links[l]['capacity_mbps'] for l in self.path_links(best)) if best else None
        predicted = known[best] + self.video_rate_mbps() / cap if best else None

        rp = self.reroute_pending
        if rp is not None and now - rp['t0'] > mon['stats_timeout_s']:
            self.log_event('reroute_unconfirmed', waiting=[self.sw(d) for d in rp['waiting']],
                           waited_s=round(now - rp['t0'], 1))
            self.reroute_pending = None
        reason = None
        if self.reroute_count >= self.max_reroutes:
            reason = 'max_reroutes_reached'
        elif self.last_reroute_ts is not None and now - self.last_reroute_ts < mon['cooldown_s']:
            reason = 'cooldown'
        elif self.reroute_pending is not None:
            reason = 'previous_reroute_not_confirmed'
        elif best is None:
            reason = 'no_fresh_stats_for_other_paths'
        elif predicted >= th:
            reason = 'no_better_path'
        if reason:
            if reason != self.last_skip_reason:
                self.log_event('reroute_skipped', reason=reason, congested_links=congested,
                               video_path=self.video_path, other_paths=loads,
                               predicted_with_video=round(predicted, 4) if predicted else None)
            self.last_skip_reason = reason
            return
        self.reroute(best, congested, known, predicted)

    def reroute(self, to_path, congested, loads, predicted):
        old_gen, new_gen = self.video_gen, self.video_gen + 1
        from_path = self.video_path
        t0 = time.time()
        tag = 'reroute-%d' % new_gen
        # Set before any barrier is sent, so no reply can arrive unexpected.
        self.reroute_pending = {'tag': tag, 't0': t0, 'waiting': set(self.datapaths)}
        # 1. install the new path (higher priority, so it wins immediately)
        self.install_video_rules(to_path, new_gen)
        for dp in list(self.datapaths.values()):
            # 2. after the switch confirms the adds, remove the old generation
            self.send_barrier(dp, tag + '-added')
            self.delete_flows(dp, COOKIE_VIDEO + old_gen, mask=0xFF)
            self.send_barrier(dp, tag)
        self.video_gen = new_gen
        self.video_path = to_path
        self.reroute_count += 1
        self.last_reroute_ts = t0
        self.last_skip_reason = None
        self.log_event('reroute', reroute_no=self.reroute_count, from_path=from_path,
                       to_path=to_path, trigger_links=congested,
                       other_path_load=loads, predicted_with_video=round(predicted, 4),
                       video_rate_mbps=round(self.video_rate_mbps(), 3),
                       video_queue=self.queues_enabled, rule_generation=new_gen)

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def on_barrier(self, ev):
        tag, dpid = self.barriers.pop(ev.msg.xid, (None, None))
        rp = self.reroute_pending
        if rp is None or tag != rp['tag']:
            return
        rp['waiting'].discard(dpid)
        if not rp['waiting']:
            self.log_event('reroute_confirmed', video_path=self.video_path,
                           install_ms=round(1000 * (time.time() - rp['t0']), 1))
            self.reroute_pending = None

    # ------------------------------------------------------------------
    # Monitoring (Phase 2)
    # ------------------------------------------------------------------
    def video_links(self):
        """Directed links the video data uses (server -> client) right now."""
        v = self.cfg['video']
        sws = self.path_switches(self.video_path, v['server'], v['client'])
        return ['%s->%s' % (a, b) for a, b in zip(sws, sws[1:])]

    def monitor_loop(self):
        interval = self.cfg['monitoring']['poll_interval_s']
        while True:
            hub.sleep(interval)
            self.publish('heartbeat', {
                'ts': time.time(), 'mode': self.mode,
                'switches_connected': sorted(self.sw(d) for d in self.datapaths),
                'flows_installed': self.flows_installed, 'video_path': self.video_path,
                'reroute_enabled': self.reroute_enabled, 'queues_enabled': self.queues_enabled})
            try:
                self.poll_round()
            except Exception:  # never let one bad round stop monitoring
                self.logger.exception('poll round failed')

    def poll_round(self):
        if not self.flows_installed:
            return
        self.write_metrics()
        timeout = self.cfg['monitoring']['stats_timeout_s']
        now = time.time()
        for dpid in sorted(self.expected_dpids):
            sent = self.pending.get(dpid)
            if sent is not None and now - sent > timeout:
                self.log_event('stats_missing', switch=self.sw(dpid),
                               waited_s=round(now - sent, 1))
                del self.pending[dpid]
            dp = self.datapaths.get(dpid)
            if dp is None:
                continue
            parser, ofp = dp.ofproto_parser, dp.ofproto
            dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
            dp.send_msg(parser.OFPFlowStatsRequest(
                dp, 0, ofp.OFPTT_ALL, ofp.OFPP_ANY, ofp.OFPG_ANY,
                COOKIE_VIDEO, 0xF0, parser.OFPMatch()))
            dp.send_msg(parser.OFPQueueStatsRequest(dp, 0, ofp.OFPP_ANY, ofp.OFPQ_ALL))
            self.pending.setdefault(dpid, now)
        self.poll_no += 1

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def on_port_stats(self, ev):
        dpid = ev.msg.datapath.id
        self.pending.pop(dpid, None)
        by_port = {st.port_no: st for st in ev.msg.body}
        video_link_detected = False
        for name, link in self.directed_links.items():
            if link['dpid'] != dpid or link['port'] not in by_port:
                continue
            st = by_port[link['port']]
            t = st.duration_sec + st.duration_nsec / 1e9  # switch-side clock
            rates, info = self.rates.update(name, t, {
                'tx_bytes': st.tx_bytes, 'tx_dropped': st.tx_dropped,
                'tx_packets': st.tx_packets})
            if rates is None:
                self.logger.info('stats %s skipped: %s', name, info)
                continue
            mbps = rates['tx_bytes'] * 8 / 1e6
            util = mbps / link['capacity_mbps']
            change = self.detector.update(name, util)
            self.link_metrics[name] = dict(
                mbps=round(mbps, 3), utilization=round(util, 4),
                tx_dropped_per_s=round(rates['tx_dropped'], 2),
                tx_pps=round(rates['tx_packets'], 1),
                capacity_mbps=link['capacity_mbps'],
                over_count=self.detector.over_count(name),
                congested=self.detector.is_congested(name), ts=time.time())
            self.fresh.add(name)
            if change:
                self.log_event('congestion_' + change, link=name,
                               utilization=round(util, 4),
                               threshold=self.detector.threshold,
                               polls=self.detector.polls,
                               on_video_path=name in self.video_links(),
                               video_path=self.video_path)
                if change == 'detected' and name in self.video_links():
                    video_link_detected = True
        if video_link_detected:
            # React now (after this whole reply is stored, so the other
            # path's links from this switch are fresh) instead of waiting
            # for the next poll round.
            self.maybe_reroute()

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def on_flow_stats(self, ev):
        """Video data rate through each switch, from the video rule counters."""
        dpid = ev.msg.datapath.id
        total, seen = 0.0, False
        for st in ev.msg.body:
            m = st.match
            if m.get('ip_proto') != inet.IPPROTO_UDP or m.get('ipv4_src') != self.server_ip:
                continue  # only video data rules in the server -> client direction
            seen = True
            # One tracker entry per rule: there are two UDP video rules per
            # switch (port as source and as destination) with the same priority.
            key = ('video', dpid, st.priority, tuple(sorted(m.items())))
            rates, _ = self.rates.update(key, st.duration_sec + st.duration_nsec / 1e9,
                                         {'bytes': st.byte_count})
            if rates is not None:
                total += rates['bytes'] * 8 / 1e6
        self.video_mbps[self.sw(dpid)] = round(total, 3) if seen else 0.0

    @set_ev_cls(ofp_event.EventOFPQueueStatsReply, MAIN_DISPATCHER)
    def on_queue_stats(self, ev):
        """Per-queue rate on each switch port (queue 0 default, 1 video)."""
        dpid = ev.msg.datapath.id
        for st in ev.msg.body:
            name = '%s-eth%d:q%d' % (self.sw(dpid), st.port_no, st.queue_id)
            rates, _ = self.rates.update(('queue', name), st.duration_sec + st.duration_nsec / 1e9,
                                         {'tx_bytes': st.tx_bytes, 'tx_errors': st.tx_errors})
            if rates is not None:
                self.queue_metrics[name] = dict(mbps=round(rates['tx_bytes'] * 8 / 1e6, 3),
                                                tx_errors_per_s=round(rates['tx_errors'], 2))

    def write_metrics(self):
        """One record per poll with the latest value for every link."""
        if not self.link_metrics:
            return
        video_links = self.video_links()
        links = {}
        for name in self.directed_links:
            m = self.link_metrics.get(name)
            if m is None:
                continue
            links[name] = dict(m, stale=name not in self.fresh,
                               on_video_path=name in video_links)
            links[name].pop('ts', None)
        record = {'ts': time.time(), 'poll': self.poll_no, 'mode': self.mode,
                  'video_path': self.video_path, 'links': links,
                  'video_mbps_by_switch': dict(self.video_mbps),
                  'congested_links': sorted(n for n in links if links[n]['congested']),
                  'queues': dict(self.queue_metrics), 'reroutes': self.reroute_count}
        self.maybe_reroute()
        self.fresh = set()
        with open(self.metrics_file, 'a') as f:
            f.write(json.dumps(record) + '\n')
        self.publish('metrics', record)
        busiest = max(links, key=lambda n: links[n]['utilization'])
        self.logger.info('poll %d: busiest %s %.2f Mbit/s (%.0f%%), congested=%s',
                         self.poll_no, busiest, links[busiest]['mbps'],
                         100 * links[busiest]['utilization'], record['congested_links'])

    # ------------------------------------------------------------------
    # Packet-in: only ARP is expected here
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def on_packet_in(self, ev):
        msg = ev.msg
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # LLDP is handled by ryu.topology
        a = pkt.get_protocol(arp.arp)
        if a is not None:
            self.handle_arp(msg.datapath, msg.match['in_port'], eth, a)

    def handle_arp(self, dp, in_port, eth, a):
        if a.opcode != arp.ARP_REQUEST:
            return
        mac = self.arp_table.get(a.dst_ip)
        if mac is None:
            self.logger.info('ARP for unknown %s from %s ignored', a.dst_ip, a.src_ip)
            return
        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP,
                                             dst=eth.src, src=mac))
        reply.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=mac, src_ip=a.dst_ip,
                                   dst_mac=a.src_mac, dst_ip=a.src_ip))
        reply.serialize()
        ofp, parser = dp.ofproto, dp.ofproto_parser
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                                        in_port=ofp.OFPP_CONTROLLER,
                                        actions=[parser.OFPActionOutput(in_port)],
                                        data=reply.data))
        self.arp_replies += 1
        self.logger.info('ARP %s asks for %s -> answered %s (on %s port %s)',
                         a.src_ip, a.dst_ip, mac, self.sw(dp.id), in_port)
