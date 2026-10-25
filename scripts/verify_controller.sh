#!/usr/bin/env bash
# Phase 0, Step 4.3: Ryu <-> Mininet <-> OVS OpenFlow 1.3 wiring test.
# Uses the throwaway learning-switch app in sdn/test_controller_app.py
# on a simple, loop-free Mininet topology. This is NOT the real project
# controller or topology - see the comment at the top of that file.
# Needs sudo for the Mininet part and will prompt you.
set -uo pipefail
cd "$(dirname "$0")/.."

LOG=/tmp/ryu_verify.log

echo "Starting Ryu in the background (log: $LOG)..."
.venv/bin/ryu-manager --ofp-tcp-listen-port 6653 sdn/test_controller_app.py > "$LOG" 2>&1 &
RYU_PID=$!
sleep 3

if ! kill -0 "$RYU_PID" 2>/dev/null; then
  echo "[FAIL] Ryu did not start. Log:"
  cat "$LOG"
  exit 1
fi
echo "Ryu running (pid $RYU_PID)."

echo
echo "Running Mininet with a remote OpenFlow13 controller..."
sudo mn --controller=remote,ip=127.0.0.1,port=6653 \
        --switch ovsk,protocols=OpenFlow13 \
        --test pingall

echo
echo "--- Ryu log: datapath connection lines ---"
grep -i "datapath connected" "$LOG" || echo "(none found - check $LOG)"

echo
echo "Stopping Ryu..."
kill "$RYU_PID" 2>/dev/null
wait "$RYU_PID" 2>/dev/null

echo "Cleaning up Mininet state..."
sudo mn -c

echo
echo "If pingall above showed 0% dropped AND a 'Datapath connected' line"
echo "appeared in the log excerpt, the controller<->OVS wiring is verified."
