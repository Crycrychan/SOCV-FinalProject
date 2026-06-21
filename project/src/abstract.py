#!/usr/bin/env python3
"""
abstract.py -- LLM-driven RTL abstraction orchestrator for AIAutoRTLAnR (live mode).

Role separation (CLAUDE.md §4):
    * LLM      = PROPOSER -- rewrites the RTL using ONLY free-input localization.
    * gv       = CHECKER  -- decides whether the safety property holds.
    * this file = LOOP    -- ties them together, validates syntax, runs gv, and
                            iterates on gv's real feedback (capped at 5 rounds).

We NEVER claim a result gv did not return. The only transformation requested of the
LLM is free-input localization (delete a register's driving logic, replace the signal
it drives with a fresh primary input) -- a sound OVER-APPROXIMATION by construction.

Usage:
    python3 src/abstract.py <design-name>      # e.g. gatedmult
Run from the project/ directory (or anywhere; paths are resolved from this file).
Requires ANTHROPIC_API_KEY (env or project/.env) and the `anthropic` package.
If either is missing the script exits non-zero so run.sh can fall back to cached mode.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Single model variable (CLAUDE.md §8). Overridable via env for experiments
# (e.g. demonstrating the counterexample-recovery branch with a weaker selector).
MODEL = os.environ.get("ABSTRACT_MODEL", "claude-sonnet-4-6")
# Cap on propose->check iterations (CLAUDE.md §9/§11: cap the loop at 5). A backtrack
# (popping an accepted cut) does NOT consume an attempt -- only a gv proof call does.
# Overridable via env for experiments (e.g. driving a weak selector out of a deep dead end).
MAX_ATTEMPTS = int(os.environ.get("ABSTRACT_MAX_ATTEMPTS", "5"))
BUDGET_SECONDS = 60    # per-gv-run time budget for the proof

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent      # .../gv/project
ROOT_DIR = PROJECT_DIR.parent                             # .../gv  (gv binary lives here)
GV_BIN = ROOT_DIR / "gv"
DESIGNS = PROJECT_DIR / "designs"
ABSTRACTED = PROJECT_DIR / "abstracted"
RUNS = PROJECT_DIR / "runs"


def banner(stage, total, msg):
    print(f"\n[{stage}/{total}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# gv driver  (CHECKER)
# ---------------------------------------------------------------------------
def run_gv(dofile_text, label):
    """Run gv on an inline dofile under a hard timeout. Returns (stdout, timed_out)."""
    RUNS.mkdir(exist_ok=True)
    dofile = RUNS / f"_{label}.dofile"
    dofile.write_text(dofile_text)
    try:
        proc = subprocess.run(
            [str(GV_BIN), "-f", str(dofile)],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=BUDGET_SECONDS,
        )
        return proc.stdout + proc.stderr, False
    except subprocess.TimeoutExpired as e:
        # On timeout, e.stdout/e.stderr may be bytes even with text=True. Decode each.
        def _s(x):
            if x is None:
                return ""
            return x.decode(errors="replace") if isinstance(x, bytes) else x
        return _s(e.stdout) + _s(e.stderr), True


def classify(output, timed_out):
    """Map raw gv output to PROVED / CEX / TIMEOUT / PARSE_ERROR / UNKNOWN."""
    if "[ERROR]" in output or "cannot open file" in output:
        return "PARSE_ERROR"
    if timed_out:
        return "TIMEOUT"
    m = re.search(r"Disproved\s*=\s*(\d+).*?Undecided\s*=\s*(\d+)", output, re.S)
    if "was asserted" in output:
        return "CEX"
    if m:
        disproved, undecided = int(m.group(1)), int(m.group(2))
        if disproved == 0 and undecided == 0:
            return "PROVED"
        if disproved > 0:
            return "CEX"
    return "UNKNOWN"


def parse_ok(verilog_path):
    """Use gv's OWN front-end to confirm the RTL parses (CLAUDE.md §9 step 4)."""
    out, _ = run_gv(f"cirread -v {verilog_path}\nq -f\n", "parse")
    return ("[ERROR]" not in out and "cannot open" not in out), out


def prove(verilog_path, label):
    out, t = run_gv(
        f"cirread -v {verilog_path}\nse sys vrf\npdr -o 0\nq -f\n", label
    )
    return classify(out, t), out


# ---------------------------------------------------------------------------
# Mechanical operator (APPLIER) -- free-input localization of ONE register.
# The LLM only SELECTS which register to free; this code performs the actual,
# guaranteed-sound transformation. That keeps the action space hard-constrained
# (CLAUDE.md §4.2) and the output always syntactically valid by construction.
# ---------------------------------------------------------------------------
class FreeError(Exception):
    pass


def free_register(rtl, reg):
    """Delete register `reg`'s declaration and driving (<=) assignments, and
    re-declare it as a primary input. Returns the rewritten RTL.
    Assumes one register per `reg` declaration line (the benchmark style)."""
    # 1. Find + remove the declaration:  reg [W:0] name;   (width optional, trailing
    #    line-comment tolerated).
    decl = re.search(
        rf"^[ \t]*reg\s*(\[[^\]]*\])?\s*{re.escape(reg)}\s*;[ \t]*(//[^\n]*)?\n",
        rtl, re.M)
    if not decl:
        raise FreeError(f"no single-register declaration found for '{reg}'")
    width = decl.group(1) or ""
    rtl = rtl[:decl.start()] + rtl[decl.end():]

    # 2. Remove every  name <= ...;  assignment (reset and normal blocks).
    rtl, n = re.subn(rf"^[ \t]*{re.escape(reg)}\s*<=.*?;[ \t]*(//[^\n]*)?\n", "",
                     rtl, flags=re.M)
    if n == 0:
        raise FreeError(f"no '<=' assignments found for '{reg}'")

    # 3. Add `reg` to the module header port list.
    hdr = re.search(r"(module\s+\w+\s*\()(.*?)(\)\s*;)", rtl, re.S)
    if not hdr:
        raise FreeError("could not locate module header port list")
    ports = hdr.group(2).rstrip()
    new_ports = ports + (",\n            " + reg if ports.strip() else reg)
    rtl = rtl[:hdr.start(2)] + new_ports + rtl[hdr.end(2):]

    # 4. Insert the `input` declaration right after the header `;`.
    hdr2 = re.search(r"module\s+\w+\s*\(.*?\)\s*;\n", rtl, re.S)
    inp = f"   input {width + ' ' if width else ''}{reg};   // FREED by abstraction\n"
    rtl = rtl[:hdr2.end()] + inp + rtl[hdr2.end():]
    return rtl


def collect_regs(rtl):
    """Names of registers (one-per-line `reg` declarations), in source order --
    the set of registers the loop may choose to free."""
    out = []
    for m in re.finditer(r"^\s*reg\s*(?:\[[^\]]*\])?\s*(\w+)\s*;", strip_comments(rtl), re.M):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def apply_cuts(rtl, regs):
    for r in regs:
        rtl = free_register(rtl, r)
    return rtl


# ---------------------------------------------------------------------------
# LLM driver  (PROPOSER / SELECTOR)
# The LLM chooses ONE register to free per iteration; it does not write Verilog.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You select ONE register to abstract away from an RTL design for
formal verification.

The tool will then apply FREE-INPUT LOCALIZATION to your chosen register: delete its
driving logic and turn it into a fresh primary input that can take ANY value each
cycle. This is a sound OVER-APPROXIMATION, so any safety property proved on the result
holds on the original.

Your job each step: pick exactly ONE register whose exact value cannot affect whether
the safety property output `p1` can ever be asserted -- e.g. a datapath register that
is gated off by a control signal that is never active. Do NOT pick the controller/FSM
registers or anything the property truly depends on; freeing those produces a spurious
counterexample. If told a choice caused a counterexample, pick a DIFFERENT register.

You may be told some registers are ALREADY freed; pick one that is not already freed.

Respond with ONLY a JSON object, no prose:
{"register": "<one register name>", "reason": "<one short sentence>"}"""


def strip_comments(src):
    """Remove // line comments and /* */ block comments so the LLM must reason from
    the logic, not from any answer-giving comments left in the design."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return "\n".join(ln for ln in src.splitlines() if ln.strip()) + "\n"


def propose(client, design_name, current_rtl, avoid, feedback):
    # The LLM sees the real RTL (real signal names) with comments stripped, plus a
    # neutral prompt that does NOT say which logic is irrelevant. The design files
    # themselves carry no comment about the abstraction/verification, so the model
    # must select the register by reasoning about the logic.
    rtl_for_llm = strip_comments(current_rtl)
    user = f"""The safety property is output `p1`, which gv must prove is ALWAYS 0.
gv currently times out on this design. Choose ONE register to free (turn into a free
primary input) so that the property becomes provable while remaining true -- i.e. a
register whose value can never make `p1` become 1. Do NOT free registers the property
genuinely depends on.

Do NOT pick any of these (already freed, or known to cause a counterexample): {avoid if avoid else "none"}

RTL:
```verilog
{rtl_for_llm}
```
Reply with JSON: {{"register": "<one register name>", "reason": "<one sentence>"}}"""
    if feedback:
        user += f"\n\nFeedback from gv on the previous step:\n{feedback}"

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    # The model may reason in prose first. Scan every '{' and return the first JSON
    # object that decodes and carries a "register" key.
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "register" in obj:
            return obj["register"], obj.get("reason", "")
    raise FreeError(f"LLM did not return register JSON: {text[:200]}")


def get_client():
    # Load a .env if present. Prefer project/.env, then fall back to the repo
    # root .env (where the user keeps their key). An already-set environment
    # variable always wins (load_dotenv does not override by default).
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
        load_dotenv(ROOT_DIR / ".env")
    except Exception:
        pass
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set (env, project/.env, or root .env).",
              file=sys.stderr)
        return None
    try:
        import anthropic
    except ImportError:
        print("ERROR: `anthropic` package not installed (pip install anthropic).",
              file=sys.stderr)
        return None
    return anthropic.Anthropic()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 2:
        print("usage: python3 src/abstract.py <design-name>", file=sys.stderr)
        return 2
    name = sys.argv[1]
    original = DESIGNS / f"{name}.v"
    if not original.exists():
        print(f"ERROR: {original} not found.", file=sys.stderr)
        return 2

    client = get_client()
    if client is None:
        return 3  # run.sh interprets this as "fall back to cached mode"

    out_path = ABSTRACTED / f"{name}.v"
    abs_rel = out_path.as_posix().replace(str(ROOT_DIR) + "/", "./")
    original_rtl = original.read_text()
    regs = collect_regs(original_rtl)

    # Backtracking DFS over which registers to free. `freed` is the current path
    # (a stack of accepted, sound-but-still-TIMEOUT cuts). `banned[tuple(freed)]` is
    # the set of registers ruled out AT that node -- either they produced a
    # COUNTEREXAMPLE (so that superset is unsound) or the subtree under them was
    # exhausted. When a node has no candidates left, we BACKTRACK: pop the last
    # accepted cut and ban it at its parent. Because free-input localization only ever
    # removes constraints, a CEX cannot be repaired by freeing more -- so undoing an
    # accepted cut is the only way out, which is exactly what backtracking provides.
    # This makes the search COMPLETE: it finds a proving set if one exists.
    freed = []
    banned = {}
    feedback = ""

    print(f"== LIVE abstraction of '{name}' (model={MODEL}, "
          f"max {MAX_ATTEMPTS} proof attempts) ==")
    print("   policy: LLM selects ONE register; tool frees it; gv checks; "
          "loop backtracks on dead ends.")

    attempts = 0
    while attempts < MAX_ATTEMPTS:
        key = tuple(freed)
        bset = banned.setdefault(key, set())
        candidates = [r for r in regs if r not in freed and r not in bset]

        if not candidates:
            if not freed:
                print("\nNo proving set of cuts found (search exhausted).", file=sys.stderr)
                return 1
            popped = freed.pop()
            banned.setdefault(tuple(freed), set()).add(popped)
            print(f"  ~ dead end; BACKTRACK: undo '{popped}' "
                  f"(now freed: {freed or 'none'})")
            feedback = (f"Freeing '{popped}' led to a dead end and was undone. "
                        f"Pick a different register.")
            continue

        attempts += 1
        banner(attempts, MAX_ATTEMPTS,
               f"select a register to free (freed: {freed or 'none'})...")
        base_rtl = apply_cuts(original_rtl, freed)

        # LLM selects; must be one of `candidates` (fall back deterministically).
        try:
            reg, reason = propose(client, name, base_rtl, freed + sorted(bset), feedback)
        except (FreeError, json.JSONDecodeError, KeyError, ValueError) as e:
            reg, reason = None, f"(selection error: {e})"
        if reg not in candidates:
            note = "" if reg is None else f"LLM picked '{reg}' (not allowed); "
            reg = candidates[0]
            reason = f"{note}fallback to first candidate"
        print(f"    chose: {reg}  -- {reason}")

        candidate = free_register(base_rtl, reg)
        out_path.write_text(candidate)
        ok, parse_out = parse_ok(abs_rel)
        if not ok:
            print("    PARSE FAILED -- banning this register at this node.")
            bset.add(reg)
            feedback = "The transform did not parse:\n" + parse_out[-400:]
            continue

        verdict, gv_out = prove(abs_rel, f"prove_{name}")
        print(f"    gv verdict: {verdict}")

        if verdict == "PROVED":
            path = freed + [reg]
            prov = (
                f"// ================= GENERATED BY abstract.py (live mode) =============\n"
                f"// Model : {MODEL}\n"
                f"// Operator : free-input localization (sound over-approximation)\n"
                f"// Freed registers: {path}\n"
                f"// gv (PDR) PROVED p1 on this design, so by over-approximation the\n"
                f"// property holds on the ORIGINAL ../designs/{name}.v as well.\n"
                f"// (The block comment below is carried over from the original design.)\n"
                f"// ===================================================================\n\n"
            )
            out_path.write_text(prov + candidate)
            print(f"\nPROVED. Freed {path} ({attempts} proof attempt(s)). By "
                  f"over-approximation this proof holds on the original design too.")
            return 0
        if verdict == "TIMEOUT":
            # Sound but not enough: accept this cut and descend.
            freed.append(reg)
            print(f"    -> sound but STILL times out; keep '{reg}' and free one more.")
            feedback = (f"gv STILL TIMED OUT after freeing '{reg}'. It is sound but not "
                        f"enough. Pick ONE more register to free.")
        elif verdict == "CEX":
            # Unsound here (and in every superset): ban at this node, try a sibling.
            bset.add(reg)
            print(f"    -> COUNTEREXAMPLE; '{reg}' is load-bearing here. Trying another.")
            feedback = (f"gv produced a COUNTEREXAMPLE -- freeing '{reg}' is unsound. "
                        f"Pick a DIFFERENT register.\n" + gv_out[-400:])
        else:
            bset.add(reg)
            feedback = "gv gave an unexpected result:\n" + gv_out[-400:]

    print("\nReached attempt budget without a proof.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
