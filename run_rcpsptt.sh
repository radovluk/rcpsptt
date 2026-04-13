#!/bin/bash
# =============================================================================
# RCPSPTT Benchmark Runner
# =============================================================================
# Runs OptalCP and IBM CPO on RCPSPTT instances.
# Supports PSPLIB (.sm) and Kraus JSON formats, flow and setup-time formulations.
#
# Usage:
#   bash run_rcpsptt.sh              # Run everything (all formulations, all data)
#   bash run_rcpsptt.sh psplib       # Only PSPLIB instances
#   bash run_rcpsptt.sh kraus        # Only Kraus JSON instances (all 100)
#   bash run_rcpsptt.sh kraus_setup  # Kraus with setup-time formulation only
#   bash run_rcpsptt.sh kraus_flow   # Kraus with flow formulation only
# =============================================================================

set -e

PYTHON="${PYTHON:-python3}"
WORKERS="${WORKERS:-16}"
TIME_LIMIT="${TIME_LIMIT:-180}"     # solver time limit
TOTAL_LIMIT="${TOTAL_LIMIT:-270}"   # build + solve hard kill (90s build + 180s solve)
LOG_LEVEL="${LOG_LEVEL:-0}"
OUTPUT_DIR="${OUTPUT_DIR:-results/rcpsptt}"
PSPLIB_DATA="data/rcpsp_tt_instances"
KRAUS_DATA="kraus-diplomka/rcpsptt_docplex_solver-master/data/generated"

mkdir -p "$OUTPUT_DIR"

run_mode="${1:-all}"

echo "============================================================"
echo "RCPSPTT Benchmark Runner"
echo "============================================================"
echo "  Workers:    $WORKERS"
echo "  Time limit: ${TIME_LIMIT}s (solver)"
echo "  Total limit:${TOTAL_LIMIT}s (build+solve)"
echo "  Output:     $OUTPUT_DIR"
echo "  Mode:       $run_mode"
echo "============================================================"

# --- PSPLIB instances (j30, j60, j90, j120) ---
if [[ "$run_mode" == "all" || "$run_mode" == "psplib" ]]; then
    echo ""
    echo ">>> PSPLIB instances"
    for SET in j30 j60 j90 j120; do
        for SOLVER in optal optal_setup cpo cpo_setup; do
            echo ""
            echo "=== ${SET} — ${SOLVER} ==="
            $PYTHON solve_rcpsptt.py \
                --data "$PSPLIB_DATA" --set "$SET" \
                --solver "$SOLVER" \
                --timeLimit "$TIME_LIMIT" --workers "$WORKERS" \
                --logLevel "$LOG_LEVEL" \
                --output "$OUTPUT_DIR"
        done
    done
fi

# --- Kraus JSON instances (setup-time: OptalCP + CPO) ---
if [[ "$run_mode" == "all" || "$run_mode" == "kraus" ]]; then
    echo ""
    echo ">>> Kraus JSON instances (setup-time formulation)"
    for SOLVER in optal_setup cpo_setup; do
        echo ""
        echo "=== Kraus — ${SOLVER} ==="
        $PYTHON solve_rcpsptt.py \
            --data "$KRAUS_DATA" --format kraus \
            --solver "$SOLVER" \
            --timeLimit "$TIME_LIMIT" --totalLimit "$TOTAL_LIMIT" \
            --workers "$WORKERS" --logLevel "$LOG_LEVEL" \
            --output "$OUTPUT_DIR"
    done
fi

echo ""
echo "============================================================"
echo "All runs complete. Results in: $OUTPUT_DIR"
echo "============================================================"
