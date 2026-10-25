#!/usr/bin/env bash
# Phase 6: stop everything scripts/start_lab.sh started.
# Run as your normal user. sudo is only asked if the lab is still running
# or crashed and left Mininet state behind.
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lab_common.sh
require_normal_user

# stop_group <pid file> <text the command line must contain>
stop_group() {
  local f=$1 want=$2 pid
  [ -f "$f" ] || return 0
  pid=$(cat "$f")
  if [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "$want"; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    echo "[ok] stopped $want (pid $pid)"
  fi
  rm -f "$f"
}

# 1. the lab itself (root process): ask it to shut down cleanly
LAB_PID=$(pgrep -f "^python3 sdn/lab.py" | head -1)
if [ -n "$LAB_PID" ]; then
  echo "Stopping the lab (sudo)..."
  sudo kill -TERM "$LAB_PID"
  for _ in $(seq 60); do kill -0 "$LAB_PID" 2>/dev/null || break; sleep 0.5; done
  kill -0 "$LAB_PID" 2>/dev/null && echo "[warn] lab still running after 30 s" || echo "[ok] lab stopped"
fi

# 2. dashboard and backend started by start_lab.sh (not ones you started yourself)
stop_group results/lab/dashboard.pid "npm run dev"
stop_group results/lab/flask.pid backend/app.py

# 3. leftovers after a crash: Ryu first, then Mininet state
pkill -f ryu-manager 2>/dev/null && echo "[ok] stopped a leftover ryu-manager"
if ip -o link show 2>/dev/null | grep -q " s[1-4]-eth"; then
  echo "Mininet interfaces are still there (crash?), cleaning up..."
  bash scripts/cleanup_lab.sh
fi
echo "Done."
