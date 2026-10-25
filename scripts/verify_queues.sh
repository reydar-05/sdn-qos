#!/usr/bin/env bash
# Phase 0, Step 4.6: verify Open vSwitch linux-htb QoS queues actually
# rate-limit traffic (measured, not assumed). Runs sdn/test_queues_topo.py
# under sudo with the SYSTEM python3, as Mininet requires.
# Needs sudo and will prompt you.
set -uo pipefail
cd "$(dirname "$0")/.."

sudo python3 sdn/test_queues_topo.py
echo
echo "Cleaning up any leftover Mininet/OVS state..."
sudo mn -c
