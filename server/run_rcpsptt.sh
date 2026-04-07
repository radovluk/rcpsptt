#!/bin/bash
# Run RCPSPTT benchmarks (IBM CPO + OptalCP) on all instance sets.
#
# Runs each set separately so results are saved per-set.
# Safe to restart — skips already-solved instances automatically.
#
# Usage (inside Docker on krocan):
#   PYTHON=$(which python3) bash run_rcpsptt.sh
#   TIME_LIMIT=120 WORKERS=8 bash run_rcpsptt.sh
#
# Environment variables:
#   TIME_LIMIT   - Solver time limit in seconds (default: 120)
#   WORKERS      - Solver worker threads (default: 8)
#   LOG_LEVEL    - Solver log level 0-3 (default: 0)
#   PYTHON       - Python interpreter path (default: python3)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Configurable parameters ---
TIME_LIMIT="${TIME_LIMIT:-120}"
WORKERS="${WORKERS:-8}"
LOG_LEVEL="${LOG_LEVEL:-0}"
PYTHON="${PYTHON:-python3}"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"

SETS="j30 j60 j90 j120"
SOLVERS="optal cpo"

echo "################################################################"
echo "#  RCPSPTT Benchmarks — Full Run"
echo "################################################################"
echo "#  Time limit:   ${TIME_LIMIT}s per instance"
echo "#  Workers:      $WORKERS"
echo "#  Python:       $PYTHON"
echo "#  Results:      $RESULTS_DIR"
echo "################################################################"
echo ""

START_TIME=$(date +%s)

for SOLVER in $SOLVERS; do
    echo ""
    echo "###############################################################"
    echo "###  Solver: $SOLVER"
    echo "###############################################################"

    for SET in $SETS; do
        echo ""
        echo ">>> solver=$SOLVER  set=$SET"
        "$PYTHON" "$SCRIPT_DIR/solve_rcpsptt.py" \
            --set "$SET" \
            --solver "$SOLVER" \
            --timeLimit "$TIME_LIMIT" \
            --workers "$WORKERS" \
            --logLevel "$LOG_LEVEL" \
            --output "$RESULTS_DIR" \
            || true
    done
done

# ===================================================================
# Final summary
# ===================================================================
END_TIME=$(date +%s)
ELAPSED=$(( (END_TIME - START_TIME) / 60 ))

echo ""
echo "################################################################"
echo "#  ALL DONE — ${ELAPSED} minutes total"
echo "################################################################"
echo ""
echo "Results directory: $RESULTS_DIR"
echo "Files:"
ls -lh "$RESULTS_DIR"/*.json 2>/dev/null || echo "  (no results yet)"
