#!/usr/bin/env bash
# Phase 2 verification: monitoring + congestion detection with real traffic.
# Run as your normal user (NOT with sudo); sudo is asked for the Mininet part.
#   bash scripts/verify_phase2.sh
# Takes about 2 minutes. Output: results/verify/phase2-<time>.log
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lab_common.sh
require_normal_user

TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$PWD/results/verify/phase2-$TS"
LOG="$RUN_DIR.log"
RYU_LOG="$RUN_DIR/ryu.log"
mkdir -p "$RUN_DIR"

clean_before_start
start_ryu baseline "$RYU_LOG" "$RUN_DIR"

sudo python3 sdn/verify_phase2.py --run-dir "$RUN_DIR" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}

if ! stop_ryu; then
  echo "[FAIL] Ryu was no longer running at the end of the test." | tee -a "$LOG"
  STATUS=1
fi
{
  echo; echo "=== Ryu errors/warnings (if any) ==="
  grep -E "WARN|ERROR|Traceback|failed" "$RYU_LOG" || echo "(none)"
} | tee -a "$LOG"

sudo mn -c > /dev/null 2>&1
echo
echo "Saved: $LOG  (controller metrics/events in $RUN_DIR)"
exit "$STATUS"
