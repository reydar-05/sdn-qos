#!/usr/bin/env bash
# Stop and clean up anything the lab scripts might have left running:
# Mininet state, stray Ryu processes, leftover OVS QoS/queue records.
# Does NOT touch firewall, SSH or sudoers, and does not uninstall
# anything. Needs sudo for the Mininet/OVS parts and will prompt you.
set -uo pipefail

echo "Killing any ryu-manager processes..."
pkill -f ryu-manager 2>/dev/null && echo "killed" || echo "none running"

echo "Cleaning Mininet state (sudo mn -c)..."
sudo mn -c

echo "Removing any leftover OVS QoS/queue records from test runs..."
# '--all' must come BEFORE the command (a global flag), not after a
# '--' separator - the other order silently does nothing.
sudo ovs-vsctl --all destroy qos 2>/dev/null || true
sudo ovs-vsctl --all destroy queue 2>/dev/null || true

echo "Done."
