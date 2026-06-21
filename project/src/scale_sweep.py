#!/usr/bin/env python3
"""
scale_sweep.py -- runtime vs. problem size for the gatedmult benchmark.

For each operand width W it generates the ORIGINAL design (a W x W multiplier whose
registered product is self-checked, gated by an always-false controller state) and the
ABSTRACTED design (free-input localization of the product register `prod`), then times
gv's PDR proof on each under a hard budget.

The point: the ORIGINAL runtime climbs with W and crosses the timeout, while the
ABSTRACTED runtime stays flat -- one curve showing the abstraction moving the proof from
intractable to trivial, rather than a single lucky timeout point.

Run from the repo root:  python3 project/src/scale_sweep.py
"""

import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent      # .../gv
GV = ROOT / "gv"
RUNS = ROOT / "project" / "runs" / "sweep"
BUDGET = 60                       # seconds, hard cap per gv run
WIDTHS = [4, 6, 8, 10, 12, 14, 16]
REPEATS = 3                       # averaged runs for finite (solved) cases


def design(W, abstracted):
    P = 2 * W
    if not abstracted:
        return f"""module top (clk, reset, a, b, p1);
   input clk; input reset;
   input [{W-1}:0] a; input [{W-1}:0] b;
   output p1;
   reg [{P-1}:0] prod;
   reg [{W-1}:0] ra; reg [{W-1}:0] rb;
   reg [1:0] state;
   wire active = (state == 2'd3);
   wire mismatch = (prod != ra * rb);
   assign p1 = mismatch & active;
   always @(posedge clk) begin
      if (!reset) begin prod <= 0; ra <= 0; rb <= 0; state <= 0; end
      else begin
         ra <= a; rb <= b; prod <= a * b;
         case (state) 2'd0: state<=2'd1; 2'd1: state<=2'd2; 2'd2: state<=2'd0;
                      default: state<=2'd0; endcase
      end
   end
endmodule
"""
    return f"""module top (clk, reset, a, b, prod, p1);
   input clk; input reset;
   input [{W-1}:0] a; input [{W-1}:0] b;
   input [{P-1}:0] prod;
   output p1;
   reg [{W-1}:0] ra; reg [{W-1}:0] rb;
   reg [1:0] state;
   wire active = (state == 2'd3);
   wire mismatch = (prod != ra * rb);
   assign p1 = mismatch & active;
   always @(posedge clk) begin
      if (!reset) begin ra <= 0; rb <= 0; state <= 0; end
      else begin
         ra <= a; rb <= b;
         case (state) 2'd0: state<=2'd1; 2'd1: state<=2'd2; 2'd2: state<=2'd0;
                      default: state<=2'd0; endcase
      end
   end
endmodule
"""


def run_once(vfile, label):
    do = RUNS / f"{label}.do"
    do.write_text(f"cirread -v {vfile}\nse sys vrf\npdr -o 0\nq -f\n")
    t0 = time.time()
    try:
        p = subprocess.run([str(GV), "-f", str(do)], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=BUDGET)
        dt = time.time() - t0
        out = p.stdout + p.stderr
        if ("Disproved = 0." in out and "Undecided = 0." in out
                and "was asserted" not in out):
            return dt, "PROVED"
        return dt, "OTHER"
    except subprocess.TimeoutExpired:
        return float(BUDGET), "TIMEOUT"


def measure(vfile, label):
    """First run; if it times out, report TIMEOUT (no point repeating). Otherwise
    average REPEATS runs."""
    dt, verd = run_once(vfile, label)
    if verd != "PROVED":
        return None, verd
    times = [dt] + [run_once(vfile, label)[0] for _ in range(REPEATS - 1)]
    return statistics.median(times), "PROVED"


def main():
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"# gv PDR runtime vs multiplier width  (budget {BUDGET}s, "
          f"median of {REPEATS} runs)\n")
    print(f"| W (operand) | prod bits | original | abstracted | speedup |")
    print(f"|---|---|---|---|---|")
    rows = []
    for W in WIDTHS:
        of = RUNS / f"orig_{W}.v"
        af = RUNS / f"abs_{W}.v"
        of.write_text(design(W, False))
        af.write_text(design(W, True))
        ot, ov = measure(str(of), f"orig_{W}")
        at, av = measure(str(af), f"abs_{W}")
        o_str = "TIMEOUT" if ov != "PROVED" else f"{ot:.2f}s"
        a_str = f"{at:.3f}s" if av == "PROVED" else av
        if ov == "PROVED" and av == "PROVED":
            sp = f"{ot / at:.0f}x"
        elif ov != "PROVED" and av == "PROVED":
            sp = f">{BUDGET / at:.0f}x"
        else:
            sp = "-"
        print(f"| {W} | {2*W} | {o_str} | {a_str} | {sp} |", flush=True)
        rows.append((W, ot, ov, at, av))
    print("\nDone.")
    return rows


if __name__ == "__main__":
    main()
