#!/usr/bin/env python3
"""
Phase 1 verification: topology + controller basics. Non-interactive.

Needs the Ryu controller already running (scripts/verify_phase1.sh starts
it). Run with sudo and the SYSTEM python3:
    sudo python3 sdn/verify_phase1.py

Checks, in order:
 1. network builds, OVS QoS (capacity + queues) applied
 2. port mapping
 3. all four switches connected to the controller
 4. controller installed forwarding rules
 5. no broadcast storm (idle counters do not grow, no flood actions)
 6. end-to-end ping h1 -> h2 (and pingall)
 7. iperf3 TCP h1 -> h2 and UDP video h2 -> h1 on the video port
 8. video rules on Path A counted the video packets, Path B did not
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qos_config import load_config  # noqa: E402
from labutil import (dump_flows, flow_lines, flow_packets, iperf3_json,  # noqa: E402
                     port_counters, sh, udp_summary, wait_for_flows)
from topology import apply_qos, build_network, clear_qos, print_port_map, wait_for_controller  # noqa: E402

from mininet.log import setLogLevel  # noqa: E402

results = []


def check(name, ok, detail=''):
    results.append((name, ok))
    print('[%s] %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def header(text):
    print('\n' + '=' * 70 + '\n' + text + '\n' + '=' * 70)


def main():
    if os.geteuid() != 0:
        sys.exit('Run with sudo')
    setLogLevel('warning')
    cfg = load_config()
    switches = list(cfg['topology']['switches'])
    v = cfg['video']
    # No 'mn -c' here: it kills ryu-manager. The wrapper cleans up first.
    net = build_network(cfg)
    qos_ports = []
    try:
        header('1. Build network and apply OVS QoS')
        qos_ports = apply_qos(cfg)
        check('OVS QoS applied', len(qos_ports) == 2 * len(cfg['topology']['links']),
              ' '.join(qos_ports))
        print(sh('tc class show dev s4-eth2').stdout)

        header('2. Port mapping (OpenFlow port -> interface -> peer)')
        print_port_map(net)

        header('3. Switches connected to the controller')
        states = wait_for_controller(net)
        print(states)
        check('all switches connected', all(states.values()))
        print(sh('ovs-vsctl show').stdout)
        if not all(states.values()):
            print('Controller not reachable: is ryu-manager running on 127.0.0.1:6653? '
                  'Stopping here, later checks would be meaningless.')
            return

        header('4. Controller installed forwarding rules')
        ok = wait_for_flows(switches, 'nw_dst=', timeout=40)
        check('IPv4 forwarding rules present on every switch', ok)

        header('5. Broadcast storm check')
        flood = [l for s in switches for l in flow_lines(s)
                 if 'FLOOD' in l or 'ALL' in l.split('actions=')[-1]]
        check('no flood/all actions in any rule', not flood, flood)
        # Send one ARP-triggering ping so ARP handling is exercised first.
        net.get(v['client']).cmd('ping -c1 -W1 %s' % net.get(v['server']).IP())
        def lldp(s):
            # LLDP probes Ryu sends for link discovery (about 1 per port per 0.9 s)
            return sum(flow_packets(l) for l in flow_lines(s) if 'dl_type=0x88cc' in l)

        before = {s: (port_counters(s), lldp(s)) for s in switches}
        time.sleep(10)
        after = {s: (port_counters(s), lldp(s)) for s in switches}
        other_total = 0
        for s in switches:
            rx = sum(after[s][0][p]['rx_pkts'] - before[s][0][p]['rx_pkts'] for p in after[s][0])
            ll = after[s][1] - before[s][1]
            other_total += rx - ll
            print('  %s: %d packets in 10 s idle (%d LLDP discovery, %d other)' % (s, rx, ll, rx - ll))
        # A storm would be thousands of packets per second; idle non-LLDP should be ~0.
        check('idle non-LLDP traffic stays tiny (no storm)', other_total < 50,
              '(%d non-LLDP packets in 10 s)' % other_total)

        header('6. Connectivity')
        h1, h2 = net.get(v['client']), net.get(v['server'])
        out = h1.cmd('ping -c 5 -i 0.2 %s' % h2.IP())
        print(out)
        check('ping h1 -> h2', ' 0% packet loss' in out)
        loss = net.pingAll(timeout=1)
        check('pingall', loss == 0, '(%s%% dropped)' % loss)

        header('7. iperf3')
        h2.cmd('iperf3 -s -1 -p %d > /tmp/sdnqos_iperf_tcp.log 2>&1 &' % cfg['background']['port'])
        time.sleep(1)
        out = h1.cmd('iperf3 -c %s -p %d -t 5 -J' % (h2.IP(), cfg['background']['port']))
        r = iperf3_json(out)
        if r and 'end' in r and 'sum_received' in r['end']:
            mbps = r['end']['sum_received']['bits_per_second'] / 1e6
            check('iperf3 TCP h1 -> h2', mbps > 1, '%.2f Mbit/s received (link capacity %s)'
                  % (mbps, cfg['links']['default_capacity_mbps']))
        else:
            check('iperf3 TCP h1 -> h2', False, out[-500:])

        video_before = {s: sum(flow_packets(l) for l in flow_lines(s) if 'tp_src=%d' % v['port'] in l)
                        for s in switches}
        h2.cmd('iperf3 -s -1 -p %d > /tmp/sdnqos_iperf_udp.log 2>&1 &' % v['port'])
        time.sleep(1)
        out = h1.cmd('iperf3 -c %s -u -R -p %d -b %dM -t 5 -J'
                     % (h2.IP(), v['port'], v['bitrate_mbps']))
        r = iperf3_json(out)
        if r and 'end' in r and 'sum' in r['end']:
            u = udp_summary(r)
            check('iperf3 UDP video h2 -> h1 (port %d)' % v['port'], u['mbps'] > 0,
                  '%.2f Mbit/s, jitter %.3f ms, loss %d/%d (%.2f%%)'
                  % (u['mbps'], u['jitter_ms'], u['lost_packets'], u['packets'], u['lost_percent']))
        else:
            check('iperf3 UDP video', False, out[-500:])

        header('8. Which path carried the video? (video rule packet counters)')
        video_after = {s: sum(flow_packets(l) for l in flow_lines(s) if 'tp_src=%d' % v['port'] in l)
                       for s in switches}
        for s in switches:
            print('  %s: video rule packets +%d' % (s, video_after[s] - video_before[s]))
        path = cfg['topology']['paths'][cfg['topology']['primary_path']]
        other = [s for s in switches if s not in path]
        check('video counted on every Path A switch',
              all(video_after[s] > video_before[s] for s in path))
        check('video NOT counted on Path B only switches',
              all(video_after[s] == video_before[s] for s in other))

        header('dump-flows (OpenFlow 1.3), all switches')
        for s in switches:
            print('--- %s' % s)
            print(dump_flows(s))
    finally:
        clear_qos(qos_ports)
        net.stop()

    header('SUMMARY')
    for name, ok in results:
        print('  [%s] %s' % ('PASS' if ok else 'FAIL', name))
    failed = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed' % (len(results), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
