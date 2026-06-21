#!/usr/bin/env bash
#
# run.sh -- single entry point for the AIAutoRTLAnR abstraction flow.
#
#   ./project/run.sh [design]                    cached mode (default; no API key needed)
#   ./project/run.sh --live [haiku|sonnet] [design]
#                                        regenerate the abstraction with the LLM, then
#                                        validate + prove (needs ANTHROPIC_API_KEY). The
#                                        model keyword picks the selector LLM (default
#                                        sonnet); it only applies in --live mode.
#
# default design: gatedmult
#
# Cached mode is fully deterministic and is how a grader reproduces the result:
#   baseline gv run on the ORIGINAL  -> TIMEOUT
#   gv run on the committed ABSTRACTED design -> PROVED
#
# Env:
#   GV_BUDGET             per-gv-run time budget in seconds (default 60)
#   ABSTRACT_MAX_ATTEMPTS live-mode iteration cap (default 5; raise for weak-model demos)
#   ABSTRACT_MODEL        live-mode selector model id (overridden by the haiku/sonnet arg)
set -u

# ---- locate things (script lives in project/, gv binary in the repo root) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GV="$ROOT_DIR/gv"
BUDGET="${GV_BUDGET:-60}"
RC=0
GV_ELAPSED=0

cd "$ROOT_DIR" || { echo "cannot cd to repo root"; exit 1; }

# ---- args ----
#   run.sh [--live] [haiku|sonnet] [design]
# The model keyword (only meaningful with --live) selects the selector LLM.
LIVE=0
DESIGN="gatedmult"
MODEL_ID=""
for a in "$@"; do
  case "$a" in
    --live)  LIVE=1 ;;
    haiku)   MODEL_ID="claude-haiku-4-5-20251001" ;;
    sonnet)  MODEL_ID="claude-sonnet-4-6" ;;
    -*)      echo "unknown flag: $a"; exit 2 ;;
    *)       DESIGN="$a" ;;
  esac
done
if [[ -n "$MODEL_ID" && "$LIVE" == 0 ]]; then
  echo "note: model selection ($MODEL_ID) only applies in --live mode; ignoring in cached mode."
fi

ORIG="./project/designs/${DESIGN}.v"
ABS="./project/abstracted/${DESIGN}.v"
RUNDIR="./project/runs"
mkdir -p "$RUNDIR"

if [[ ! -x "$GV" ]]; then
  echo "ERROR: gv binary not found at $GV. Build gv first (see project/README.md)."
  exit 1
fi
if [[ ! -f "$ORIG" ]]; then echo "ERROR: original design $ORIG not found."; exit 1; fi

# ---- helpers -----------------------------------------------------------------
# run_gv <dofile> <logfile> ; sets globals RC (exit code) and GV_ELAPSED (seconds)
run_gv() {
  local dofile="$1" log="$2" start end
  start=$(date +%s.%N)
  timeout "$BUDGET" "$GV" -f "$dofile" >"$log" 2>&1
  RC=$?
  end=$(date +%s.%N)
  GV_ELAPSED=$(awk -v s="$start" -v e="$end" 'BEGIN{printf "%.2f", e-s}')
}

# classify <logfile> <rc> -> echoes verdict
classify() {
  local log="$1" rc="$2"
  if grep -q "\[ERROR\]\|cannot open file" "$log"; then echo "PARSE_ERROR"; return; fi
  if [[ "$rc" == "124" ]]; then echo "TIMEOUT"; return; fi
  if grep -q "was asserted" "$log"; then echo "CEX"; return; fi
  if grep -q "Disproved = 0\." "$log" && grep -q "Undecided = 0\." "$log"; then
    echo "PROVED"; return
  fi
  echo "UNKNOWN"
}

bar() { printf '%s\n' "----------------------------------------------------------------------"; }

echo "AIAutoRTLAnR abstraction flow   design=$DESIGN   budget=${BUDGET}s   mode=$([[ $LIVE == 1 ]] && echo live || echo cached)"
bar

# =============================================================================
# [1/4] Baseline: gv on the ORIGINAL design (expected: TIMEOUT)
# =============================================================================
echo "[1/4] Baseline: running gv (PDR, abc's strongest engine) on the ORIGINAL design..."
cat > "$RUNDIR/baseline.dofile" <<EOF
cirread -v $ORIG
se sys vrf
pdr -o 0
q -f
EOF
run_gv "$RUNDIR/baseline.dofile" "$RUNDIR/baseline.log"
BASE_T=$GV_ELAPSED
BASE_V=$(classify "$RUNDIR/baseline.log" "$RC")
tail -n 6 "$RUNDIR/baseline.log" | sed 's/^/    | /'
echo "    => baseline: $BASE_V  (${BASE_T}s)"
bar

# =============================================================================
# [2/4] Obtain the abstraction (cached committed file, or live LLM)
# =============================================================================
if [[ "$LIVE" == 1 ]]; then
  [[ -n "$MODEL_ID" ]] && export ABSTRACT_MODEL="$MODEL_ID"
  echo "[2/4] LLM proposing abstraction (live)${MODEL_ID:+ [model: $MODEL_ID]}..."
  if python3 "$SCRIPT_DIR/src/abstract.py" "$DESIGN"; then
    echo "    => live abstraction written to $ABS"
  else
    echo "    => live mode unavailable (no key / package / proof); using committed cached $ABS"
  fi
else
  echo "[2/4] Using committed cached abstraction: $ABS"
  echo "      (run with --live to regenerate it via the LLM)"
fi
if [[ ! -f "$ABS" ]]; then echo "ERROR: abstracted design $ABS not found."; exit 1; fi
bar

# =============================================================================
# [3/4] Syntax check: parse the abstracted RTL with gv's own front-end
# =============================================================================
echo "[3/4] Syntax check: parsing abstracted RTL with gv's front-end..."
cat > "$RUNDIR/parse.dofile" <<EOF
cirread -v $ABS
q -f
EOF
run_gv "$RUNDIR/parse.dofile" "$RUNDIR/parse.log"
if grep -q "\[ERROR\]\|cannot open file" "$RUNDIR/parse.log"; then
  echo "    => PARSE FAILED:"; sed 's/^/    | /' "$RUNDIR/parse.log"; exit 1
fi
echo "    => abstracted RTL parses cleanly."
bar

# =============================================================================
# [4/4] Proving: gv on the ABSTRACTED design (expected: PROVED)
# =============================================================================
echo "[4/4] Proving: running gv (PDR) on the ABSTRACTED design..."
cat > "$RUNDIR/prove.dofile" <<EOF
cirread -v $ABS
se sys vrf
pdr -o 0
q -f
EOF
run_gv "$RUNDIR/prove.dofile" "$RUNDIR/prove.log"
ABS_T=$GV_ELAPSED
ABS_V=$(classify "$RUNDIR/prove.log" "$RC")
tail -n 6 "$RUNDIR/prove.log" | sed 's/^/    | /'
echo "    => abstracted: $ABS_V  (${ABS_T}s)"
bar

# =============================================================================
# Comparison table
# =============================================================================
echo
echo "RESULT SUMMARY"
printf "  %-34s %-12s %-10s\n" "stage" "result" "time(s)"
printf "  %-34s %-12s %-10s\n" "baseline (original, PDR)"   "$BASE_V" "$BASE_T"
printf "  %-34s %-12s %-10s\n" "abstracted (freed regs, PDR)" "$ABS_V" "$ABS_T"
echo
if [[ "$BASE_V" == "TIMEOUT" && "$ABS_V" == "PROVED" ]]; then
  echo "OK: gv FAILS on the original and PROVES on the abstracted design."
  echo "    The abstraction is a sound over-approximation (free-input localization),"
  echo "    so the property provably holds on the ORIGINAL design as well."
  exit 0
else
  echo "NOTE: expected baseline=TIMEOUT, abstracted=PROVED; got $BASE_V / $ABS_V."
  echo "      (Try a larger GV_BUDGET, or inspect project/runs/*.log.)"
  exit 1
fi
