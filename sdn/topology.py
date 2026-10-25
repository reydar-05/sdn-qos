#!/usr/bin/env python3
"""
Mininet topology for the SDN QoS project.

    h1 (client) ----+             +---- s2 ----+
                    s1                         s4 ---- h2 (server)
    h3 (backgr) ----+             +---- s3 ----+

    Path A: s1-s2-s4    Path B: s1-s3-s4

- Switches are Open vSwitch, OpenFlow 1.3, fail-mode secure (they do
  nothing on their own; every rule comes from the Ryu controller).
- Remote controller at 127.0.0.1:6653 (start Ryu first).
- Port numbers are fixed from config/config.yaml, so OpenFlow port N is
  interface sX-ethN.
- Link capacity is enforced with Open vSwitch linux-htb QoS on both ends
  of every switch-to-switch link, with two queues (0 default, 1 video).
  Mininet TCLink is deliberately NOT used: it would put its own tc qdisc
  on the same interfaces and conflict with the OVS one.

Run with sudo and the SYSTEM python3 (a venv is not visible under sudo):
    sudo python3 sdn/topology.py            # build, then Mininet CLI
    sudo python3 sdn/topology.py --no-qos   # same, without capacity/queues
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import load_config, link_capacity_mbps  # noqa: E402

from mininet.cli import CLI  # noqa: E402
from mininet.link import Link  # noqa: E402
from mininet.log import info, setLogLevel  # noqa: E402
from mininet.net import Mininet  # noqa: E402
from mininet.node import OVSSwitch, RemoteController  # noqa: E402

QOS_TAG = 'external_ids:owner=sdn-qos'


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def build_network(cfg):
    """Create and start the Mininet network described in the config."""
    topo = cfg['topology']
    ctl = cfg['controller']
    net = Mininet(switch=OVSSwitch, controller=None, link=Link,
                  autoSetMacs=False, build=False)
    net.addController('c0', controller=RemoteController,
                      ip=ctl['openflow_host'], port=ctl['openflow_port'])
    for name, dpid in topo['switches'].items():
        net.addSwitch(name, dpid='%016x' % dpid, protocols='OpenFlow13',
                      failMode='secure')
    for name, h in topo['hosts'].items():
        net.addHost(name, ip=h['ip'] + '/24', mac=h['mac'])
        # host side is always eth0, switch side gets the configured port
        net.addLink(name, h['switch'], port1=0, port2=h['port'])
    for link in topo['links']:
        net.addLink(link['a'], link['b'], port1=link['a_port'], port2=link['b_port'])
    net.build()
    net.start()
    for host in net.hosts:
        # IPv6 is not used; turning it off in the host namespaces stops
        # neighbour-discovery noise from showing up in the counters.
        host.cmd('sysctl -qw net.ipv6.conf.all.disable_ipv6=1')
    return net


def apply_qos(cfg):
    """Put a linux-htb QoS with two queues on both ends of every switch link.

    tc/HTB shapes EGRESS traffic, so a queue on port sX-ethN limits what
    leaves sX through that port. Doing both ends covers both directions.
    """
    q = cfg['queues']
    ports = []
    for link in cfg['topology']['links']:
        cap = int(link_capacity_mbps(cfg, link) * 1e6)
        vmin = int(q['video_min_mbps'] * 1e6)
        dmin = int(q['default_min_mbps'] * 1e6)
        for sw, port in ((link['a'], link['a_port']), (link['b'], link['b_port'])):
            intf = '%s-eth%d' % (sw, port)
            # HTB gives each queue a packet FIFO whose size is the port's
            # txqueuelen at the moment the queue is created, so set it first.
            limit = cfg['links'].get('queue_limit_packets')
            if limit:
                r = sh('ip link set dev %s txqueuelen %d' % (intf, limit))
                if r.returncode != 0:
                    raise RuntimeError('txqueuelen on %s failed: %s' % (intf, r.stderr.strip()))
            cmd = (
                'ovs-vsctl -- set port {intf} qos=@qos '
                '-- --id=@qos create qos type=linux-htb other-config:max-rate={cap} '
                '{tag} queues={dq}=@qd,{vq}=@qv '
                '-- --id=@qd create queue other-config:min-rate={dmin} '
                'other-config:max-rate={cap} other-config:priority=1 {tag} '
                '-- --id=@qv create queue other-config:min-rate={vmin} '
                'other-config:max-rate={cap} other-config:priority=0 {tag}'
            ).format(intf=intf, cap=cap, dmin=dmin, vmin=vmin, tag=QOS_TAG,
                     dq=q['default_queue_id'], vq=q['video_queue_id'])
            r = sh(cmd)
            if r.returncode != 0:
                raise RuntimeError('QoS setup failed on %s: %s' % (intf, r.stderr.strip()))
            ports.append(intf)
    return ports


def clear_qos(ports):
    """Detach our QoS from the ports and delete only the rows we created."""
    for intf in ports:
        sh('ovs-vsctl --if-exists clear port %s qos' % intf)
    problems = []
    for table in ('qos', 'queue'):
        uuids = sh('ovs-vsctl --bare --columns=_uuid find %s %s' % (table, QOS_TAG)).stdout.split()
        for u in uuids:
            r = sh('ovs-vsctl destroy %s %s' % (table, u))
            if r.returncode != 0:
                problems.append(r.stderr.strip())
    left = sh('ovs-vsctl --bare --columns=_uuid find qos %s' % QOS_TAG).stdout.strip()
    if problems or left:
        print('[WARN] QoS cleanup incomplete:', problems, left)


def wait_for_controller(net, timeout=30):
    """Wait until every switch reports is_connected=true to the controller."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        states = {}
        for sw in net.switches:
            uuids = sh('ovs-vsctl get bridge %s controller' % sw.name).stdout.strip(' []\n')
            conn = [sh('ovs-vsctl get controller %s is_connected' % u.strip()).stdout.strip()
                    for u in uuids.split(',') if u.strip()]
            states[sw.name] = bool(conn) and all(c == 'true' for c in conn)
        if all(states.values()):
            return states
        time.sleep(1)
    return states


def port_map(net):
    """Return {switch: {ofport: 'intf -> peer'}} from the live network."""
    result = {}
    for sw in net.switches:
        ports = {}
        for intf in sw.intfList():
            if intf.name == 'lo' or intf.link is None:
                continue
            other = intf.link.intf2 if intf.link.intf1 is intf else intf.link.intf1
            ports[sw.ports[intf]] = '%s -> %s (%s)' % (intf.name, other.node.name, other.name)
        result[sw.name] = dict(sorted(ports.items()))
    return result


def print_port_map(net):
    for sw, ports in port_map(net).items():
        for p, desc in ports.items():
            print('  %s port %d: %s' % (sw, p, desc))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-qos', action='store_true',
                        help='do not apply OVS capacity/queues (debug only)')
    args = parser.parse_args()

    if os.geteuid() != 0:
        sys.exit('Run with sudo: sudo python3 sdn/topology.py')
    setLogLevel('info')
    cfg = load_config()
    # Note: do NOT run 'mn -c' here. Mininet's cleanup also kills every
    # ryu-manager process, which would kill the controller we need.
    # Clean up BEFORE starting Ryu instead (scripts/cleanup_lab.sh).
    net = build_network(cfg)
    qos_ports = []
    try:
        if not args.no_qos:
            qos_ports = apply_qos(cfg)
            info('*** OVS linux-htb QoS on: %s\n' % ' '.join(qos_ports))
        info('*** Port mapping\n')
        print_port_map(net)
        info('*** Waiting for switches to connect to the controller\n')
        print(wait_for_controller(net))
        CLI(net)
    finally:
        clear_qos(qos_ports)
        net.stop()


if __name__ == '__main__':
    main()
