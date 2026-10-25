#!/usr/bin/env bash
# Phase 0, Step 1: inspect the lab environment. Read-only - makes no changes.
# Run as your normal user: bash scripts/inspect_environment.sh
# One sub-check (network namespaces) needs sudo and will prompt you.
set -uo pipefail

section() { echo; echo "=== $1 ==="; }

section "OS"
lsb_release -a 2>/dev/null || cat /etc/os-release

section "Kernel"
uname -a

section "Virtualization (should say 'vmware')"
systemd-detect-virt 2>/dev/null || echo "unknown"

section "CPU / RAM / Disk"
echo "CPU cores: $(nproc)"
free -h
df -h /

section "git"
git --version 2>/dev/null || echo "git: NOT FOUND"

section "Python"
python3 --version 2>/dev/null || echo "python3: NOT FOUND"
python3 -m pip --version 2>/dev/null || echo "pip: NOT FOUND"
python3 -m venv --help >/dev/null 2>&1 && echo "venv module: OK" || echo "venv module: MISSING (needs python3.10-venv)"

section "Node.js / npm"
node -v 2>/dev/null || echo "node: NOT FOUND"
npm -v 2>/dev/null || echo "npm: NOT FOUND"

section "Mininet"
if command -v mn >/dev/null 2>&1; then mn --version; else echo "mininet: NOT FOUND"; fi

section "Open vSwitch"
if command -v ovs-vsctl >/dev/null 2>&1; then
  ovs-vsctl --version
  systemctl is-active openvswitch-switch 2>/dev/null
else
  echo "openvswitch-switch: NOT FOUND"
fi

section "Ryu (project .venv)"
if [ -x "$(dirname "$0")/../.venv/bin/ryu-manager" ]; then
  "$(dirname "$0")/../.venv/bin/ryu-manager" --version 2>&1
else
  echo "Ryu venv not installed yet"
fi

section "iperf3"
command -v iperf3 >/dev/null 2>&1 && iperf3 --version || echo "iperf3: NOT FOUND"

section "tc / iproute2"
command -v tc >/dev/null 2>&1 && tc -V || echo "tc: NOT FOUND"

section "Network namespaces / veth (requires sudo - will prompt)"
if sudo ip netns add claude_qos_test 2>/tmp/netns_err; then
  sudo ip netns del claude_qos_test
  echo "netns create/delete: OK"
else
  echo "netns test FAILED:"
  cat /tmp/netns_err
fi
rm -f /tmp/netns_err

echo
echo "Inspection complete."
