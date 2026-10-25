#!/usr/bin/env bash
# Phase 6: start the whole chain for a live demo, with one command.
# Run as your normal user (NOT with sudo); sudo is asked once.
#   bash scripts/start_lab.sh              # QoS mode (reroute + priority queue)
#   bash scripts/start_lab.sh baseline     # best-effort baseline
#   bash scripts/start_lab.sh qos --auto   # also run the 60 s scenario at once
#
# Order:
#   1. Flask backend    127.0.0.1:5000  (kept running, reused if already up)
#   2. Dashboard (Vite) 127.0.0.1:5173  (kept running, reused if already up)
#   3. sudo python3 sdn/lab.py: cleans Mininet, starts Ryu (as you),
#      builds the network and queues, then shows the traffic menu.
# Quitting the menu stops the network and Ryu. Flask and the dashboard
# keep running until: bash scripts/stop_lab.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lab_common.sh
require_normal_user

MODE=qos
if [ "${1:-}" = "qos" ] || [ "${1:-}" = "baseline" ]; then MODE=$1; shift; fi
mkdir -p results/lab
port_open() { ss -ltnH "sport = :$1" | grep -q .; }

if pgrep -f "python3 sdn/lab.py" > /dev/null; then
  echo "The lab is already running in another terminal. Stop it first: bash scripts/stop_lab.sh"
  exit 1
fi
[ -x .venv/bin/python ] || { echo "[FAIL] .venv not found (Phase 0 setup)"; exit 1; }

# 1. Flask backend --------------------------------------------------------
if port_open 5000; then
  if curl -s --max-time 2 http://127.0.0.1:5000/api/health | grep -q sdn-qos-backend; then
    echo "[ok] backend already running on 127.0.0.1:5000 (reused)"
  else
    echo "[FAIL] port 5000 is used by something that is not the backend"; exit 1
  fi
else
  setsid .venv/bin/python backend/app.py > results/lab/flask.log 2>&1 < /dev/null &
  echo $! > results/lab/flask.pid
  for _ in $(seq 20); do
    curl -s --max-time 1 http://127.0.0.1:5000/api/health > /dev/null && break
    sleep 0.5
  done
  if curl -s --max-time 2 http://127.0.0.1:5000/api/health | grep -q sdn-qos-backend; then
    echo "[ok] backend started on 127.0.0.1:5000 (log results/lab/flask.log)"
  else
    echo "[FAIL] backend did not start:"; tail -20 results/lab/flask.log; exit 1
  fi
fi

# 2. Dashboard -------------------------------------------------------------
if port_open 5173; then
  echo "[ok] dashboard already running on http://127.0.0.1:5173 (reused)"
elif [ -d frontend/node_modules ]; then
  (cd frontend && setsid npm run dev > ../results/lab/dashboard.log 2>&1 < /dev/null & echo $! > ../results/lab/dashboard.pid)
  for _ in $(seq 20); do port_open 5173 && break; sleep 0.5; done
  port_open 5173 && echo "[ok] dashboard on http://127.0.0.1:5173 (log results/lab/dashboard.log)" \
                 || echo "[warn] dashboard did not start, see results/lab/dashboard.log (the lab still works)"
else
  echo "[warn] frontend/node_modules missing: run 'cd frontend && npm install' for the dashboard"
fi

# 3. Network, controller and traffic menu (needs root for Mininet) --------
echo
echo "Starting the network (sudo). Open http://127.0.0.1:5173 and choose LIVE LAB."
pkill -f ryu-manager 2>/dev/null && echo "stopped an old ryu-manager (the lab starts its own)"
sudo python3 sdn/lab.py --mode "$MODE" "$@"
STATUS=$?
echo
echo "Network and controller stopped. Backend and dashboard are still running"
echo "(recorded results stay visible). Stop them with: bash scripts/stop_lab.sh"
exit $STATUS
