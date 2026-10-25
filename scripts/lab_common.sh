#!/usr/bin/env bash
# Shared helpers for the lab wrapper scripts. Source it, do not run it.
# Order rule: 'mn -c' kills every ryu-manager, so always clean up BEFORE
# starting Ryu, never after.

require_normal_user() {
  if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not with sudo."; exit 1
  fi
}

clean_before_start() {
  pkill -f ryu-manager 2>/dev/null && sleep 1
  echo "Cleaning old Mininet state (sudo)..."
  sudo mn -c > /dev/null 2>&1
}

# start_ryu <baseline|qos> <ryu log file> <controller run dir>
start_ryu() {
  mkdir -p "$3"
  SDN_QOS_MODE="$1" SDN_QOS_RUN_DIR="$3" .venv/bin/ryu-manager \
    --ofp-listen-host 127.0.0.1 --ofp-tcp-listen-port 6653 \
    --observe-links sdn/controller.py > "$2" 2>&1 &
  RYU_PID=$!
  sleep 3
  if ! kill -0 "$RYU_PID" 2>/dev/null; then
    echo "[FAIL] Ryu did not start:"; cat "$2"; exit 1
  fi
  echo "Ryu running (pid $RYU_PID, mode $1, log $2)"
  ss -ltn | grep ':6653 '
}

# stop_ryu: returns 1 if Ryu had already died during the test
stop_ryu() {
  local alive=0
  kill -0 "$RYU_PID" 2>/dev/null || alive=1
  kill "$RYU_PID" 2>/dev/null; wait "$RYU_PID" 2>/dev/null
  return $alive
}
