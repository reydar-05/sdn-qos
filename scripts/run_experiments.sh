#!/usr/bin/env bash
# Phase 4: run the baseline vs QoS experiments for real.
# Run as your normal user (NOT with sudo); sudo is asked once.
#   bash scripts/run_experiments.sh                       # both modes, both loads, 3 runs, 60 s
#   bash scripts/run_experiments.sh --load heavy --runs 1 # quick single case
# Default plan: 12 runs, about 18 minutes, runs unattended.
# Optional: start the backend first (.venv/bin/python backend/app.py) to
# watch the runs live; experiments work without it.
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lab_common.sh
require_normal_user

mkdir -p results/experiments
LOG="results/experiments/run-$(date +%Y%m%d-%H%M%S).log"
pkill -f ryu-manager 2>/dev/null && echo "stopped a running ryu-manager (the runner starts its own)"
sudo python3 sdn/run_experiment.py "$@" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
echo
python3 sdn/print_summary.py 2>&1 | tee -a "$LOG"
echo
echo "Saved: $LOG"
exit "$STATUS"
