#!/usr/bin/env bash
# Phase 3 verification: rerouting + priority queue, three scenarios with
# identical traffic (baseline, queue_only, qos), then a comparison table.
# Run as your normal user (NOT with sudo); sudo is asked for Mininet.
#   bash scripts/verify_phase3.sh
# Takes about 4-5 minutes. Output: results/verify/phase3-<time>.log
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lab_common.sh
require_normal_user

TS=$(date +%Y%m%d-%H%M%S)
ROOT="$PWD/results/verify/phase3-$TS"
LOG="$ROOT.log"
mkdir -p "$ROOT"
STATUS=0

run_scenario() {   # <scenario> <controller mode> <reroute 0|1>
  local dir="$ROOT/$1"
  mkdir -p "$dir"
  clean_before_start
  SDN_QOS_REROUTE=$3 start_ryu "$2" "$dir/ryu.log" "$dir"
  sudo python3 sdn/verify_phase3.py --scenario "$1" --run-dir "$dir" 2>&1 | tee -a "$LOG"
  [ "${PIPESTATUS[0]}" -eq 0 ] || STATUS=1
  if ! stop_ryu; then
    echo "[FAIL] Ryu died during scenario $1" | tee -a "$LOG"; STATUS=1
  fi
  grep -E "WARN|ERROR|Traceback|failed" "$dir/ryu.log" | tee -a "$LOG"
}

run_scenario baseline   baseline 1
run_scenario queue_only qos      0
run_scenario qos        qos      1
sudo mn -c > /dev/null 2>&1

echo | tee -a "$LOG"
python3 sdn/compare_phase3.py "$ROOT" 2>&1 | tee -a "$LOG"
echo
echo "Saved: $LOG  (per-scenario files in $ROOT)"
exit "$STATUS"
