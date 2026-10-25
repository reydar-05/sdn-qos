#!/usr/bin/env python3
"""
Phase 0 verification only (Step 4.6): prove that Open vSwitch linux-htb
QoS queues actually rate-limit traffic, measured with iperf3.

This is NOT the final project mechanism. The real project selects a
queue per-flow with an OpenFlow "set-queue" action pushed by the Ryu
controller once real flows exist. Here there is no controller yet, so
queue selection is done directly with a 'tc filter', which is the
standard way to test OVS HTB queues in isolation. Only after this is
measured does docs/environment-report.md call OVS queues verified.

Must run with the SYSTEM python3 under sudo (Mininet requirement), not
the project .venv:
    sudo python3 sdn/test_queues_topo.py
"""
import re
import subprocess
import sys
import time

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.log import setLogLevel, info


def sh(cmd):
    info('*** ' + cmd + '\n')
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def main():
    setLogLevel('info')
    # failMode='standalone': OVS behaves like a normal learning switch
    # with no controller attached, which is all this isolated test needs.
    net = Mininet(switch=OVSSwitch, controller=None)
    s1 = net.addSwitch('s1', failMode='standalone')
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    net.addLink(h1, s1)
    net.addLink(h2, s1)
    net.start()

    # tc/htb qdiscs rate-limit EGRESS traffic on an interface. We are
    # about to test h1->h2 traffic, which egresses the switch through
    # the port facing h2 (not h1) - that is the port the qdisc/queues
    # must go on. Putting it on the port facing h1 would instead only
    # affect h2->h1 traffic, the reverse direction.
    port = s1.connectionsTo(h2)[0][0].name
    info('*** Switch port facing h2 (egress for h1->h2 traffic): %s\n' % port)

    info('*** Removing any stale QoS config on this port\n')
    sh('ovs-vsctl -- clear port %s qos' % port)

    info('*** Creating linux-htb QoS: queue 0 ~8-10mbit, queue 1 ~1-2mbit\n')
    result = sh(
        'ovs-vsctl set port %s qos=@newqos -- '
        '--id=@newqos create qos type=linux-htb '
        'other-config:max-rate=10000000 '
        'queues=0=@q0,1=@q1 -- '
        '--id=@q0 create queue '
        'other-config:min-rate=8000000 other-config:max-rate=10000000 -- '
        '--id=@q1 create queue '
        'other-config:min-rate=1000000 other-config:max-rate=2000000'
        % port
    )
    if result.returncode != 0:
        print('[FAIL] could not create QoS/queues:', result.stderr)
        net.stop()
        sys.exit(1)

    print('--- ovs-vsctl list qos ---')
    print(sh('ovs-vsctl list qos').stdout)
    print('--- ovs-vsctl list queue ---')
    print(sh('ovs-vsctl list queue').stdout)

    # Find the real tc htb class ids OVS created for this port, and pick
    # the one with the smallest ceiling as "the low-rate queue". OVS's
    # internal class numbering is an implementation detail, so we read
    # it back instead of assuming it.
    tc_classes = sh('tc class show dev %s' % port).stdout
    print('--- tc class show %s ---' % port)
    print(tc_classes)

    classes = []
    for line in tc_classes.splitlines():
        m = re.search(r'class htb (\S+).*?ceil (\d+)(K|M)?bit', line)
        if m:
            classid, num, unit = m.group(1), int(m.group(2)), m.group(3)
            bits = num * (1_000_000 if unit == 'M' else 1_000 if unit == 'K' else 1)
            classes.append((classid, bits))

    if len(classes) < 2:
        print('[FAIL] expected at least 2 htb classes, found:', classes)
        net.stop()
        sys.exit(1)

    classes.sort(key=lambda c: c[1])
    low_classid, low_bits = classes[0]
    print('Low-rate class picked: %s (ceil %d bit/s)' % (low_classid, low_bits))

    h2.cmd('iperf3 -s -D')
    time.sleep(1)

    info('*** Baseline run (no tc filter - default/high-rate queue)\n')
    baseline = h1.cmd('iperf3 -c %s -t 5' % h2.IP())
    print('--- baseline iperf3 (expect ~port max-rate, 10mbit) ---')
    print(baseline)

    info('*** Forcing h1->h2 traffic into the low-rate class %s\n' % low_classid)
    sh('tc filter add dev %s parent 1: protocol ip prio 1 u32 '
       'match ip dst %s/32 flowid %s' % (port, h2.IP(), low_classid))

    time.sleep(1)
    throttled = h1.cmd('iperf3 -c %s -t 5' % h2.IP())
    print('--- throttled iperf3 (expect near the low queue cap, ~1-2mbit) ---')
    print(throttled)

    info('*** Cleaning up tc filter and QoS config\n')
    sh('tc filter del dev %s parent 1: protocol ip prio 1' % port)
    sh('ovs-vsctl -- clear port %s qos' % port)
    # NOTE: '--all' is a global flag that must come BEFORE the command,
    # not after a '--' separator. 'ovs-vsctl destroy qos -- --all' (the
    # original, wrong form here) silently does nothing and leaves
    # orphaned qos/queue rows in the OVSDB - confirmed by checking
    # 'ovs-vsctl list qos' after a run and finding leftover rows.
    r1 = sh('ovs-vsctl --all destroy qos')
    r2 = sh('ovs-vsctl --all destroy queue')
    if r1.returncode != 0 or r2.returncode != 0:
        print('[WARN] qos/queue cleanup may have failed:', r1.stderr, r2.stderr)

    net.stop()

    print()
    print('Compare the "sender" Mbits/sec line of the baseline run vs the')
    print('throttled run above. If throttled is clearly capped near the')
    print('low queue rate, OVS QoS queues are verified as working.')


if __name__ == '__main__':
    main()
