#!/usr/bin/env bash
# Phase 1 verification: real topology + real controller.
# Run as your normal user (NOT with sudo): Ryu starts from the venv as
# you, then sudo is asked once for the Mininet part.
#   bash scripts/verify_phase1.sh
# Output is saved to results/verify/phase1-<time>.log
set -uo pipefail
cd "$(dirname "$0")/.."

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not with sudo."; exit 1
fi

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p results/verify results/logs
LOG=results/verify/phase1-$TS.log
RYU_LOG=results/logs/ryu-phase1-$TS.log
export SDN_QOS_RUN_DIR="$PWD/results/verify/phase1-$TS-controller"

# Clean leftovers FIRST. 'mn -c' also kills any ryu-manager, so it must
# never run after Ryu has been started.
pkill -f ryu-manager 2>/dev/null && sleep 1
echo "Cleaning old Mininet state (sudo)..."
sudo mn -c > /dev/null 2>&1

echo "Starting Ryu (log: $RYU_LOG)"
SDN_QOS_MODE=baseline .venv/bin/ryu-manager --ofp-listen-host 127.0.0.1 \
  --ofp-tcp-listen-port 6653 --observe-links sdn/controller.py > "$RYU_LOG" 2>&1 &
RYU_PID=$!
sleep 3
if ! kill -0 "$RYU_PID" 2>/dev/null; then
  echo "[FAIL] Ryu did not start:"; cat "$RYU_LOG"; exit 1
fi
ss -ltn | grep ':6653 '

sudo python3 sdn/verify_phase1.py 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}

if ! kill -0 "$RYU_PID" 2>/dev/null; then
  echo "[FAIL] Ryu was no longer running at the end of the test." | tee -a "$LOG"
  STATUS=1
fi

kill "$RYU_PID" 2>/dev/null; wait "$RYU_PID" 2>/dev/null

{
  echo; echo "=== Ryu controller log (events) ==="
  grep -E "EVENT|ARP|WARN|ERROR|Traceback" "$RYU_LOG"
} | tee -a "$LOG"

sudo mn -c > /dev/null 2>&1
echo
echo "Saved: $LOG"
exit "$STATUS"
