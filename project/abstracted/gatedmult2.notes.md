# Abstraction notes — `gatedmult2` (the iteration benchmark)

## Why this benchmark exists
`gatedmult` is solved by a single cut, so it never exercises the **loop**.
`gatedmult2` is built so that **one cut is not enough** — it forces the
proposer→checker→loop to iterate on gv's real feedback (CLAUDE.md §9).

## Property under proof
`p1 = (mismatch1 & active) | (mismatch2 & done)` (the only output). Safety: `p1`
must **always be 0**.

Two independent 16×16 multiplier self-checks, each gated by an always-false control:
- `mismatch1 = (prod1 != ra1*rb1)`, gated by `active = (state==3)` — `state` cycles
  `0→1→2→0`, so `active ≡ 0` (easy to see).
- `mismatch2 = (prod2 != ra2*rb2)`, gated by `done`, where `done <= active`, so
  `done ≡ 0` (one extra hop to see).

Both products always equal their recomputation, so both `mismatch`es are ≡0 — but
proving that requires reasoning about **two** 16×16 multipliers. PDR times out.

## Why one cut is not enough (measured)
| Cut | gv (PDR) |
|---|---|
| none (original) | TIMEOUT (60 s) |
| free `prod1` only | **STILL TIMEOUT** (multiplier #2's equivalence remains) |
| free `prod1` **and** `prod2` | **PROVED** (0.02 s) |

Freeing a product register `prodi` breaks that multiplier's self-check equivalence
(the engine no longer has to prove `prodi == rai*rbi`). One multiplier remains after a
single cut, so gv still times out; both must be freed.

## What the live loop actually did (model = claude-sonnet-4-6)
The LLM is shown **comment-stripped RTL** with a neutral prompt (no hint of which logic
is irrelevant), so the selection is genuine reasoning, not a comment lookup.
```
[1/5] LLM selected: prod2   ("done is always 0 since it is driven by active which is
                             never true -- state never reaches 2'd3")
      tool freed prod2 -> gv verdict: TIMEOUT
      -> sound but not enough; keep prod2, free one more
[2/5] LLM selected: prod1   ("prod1 == ra1*rb1 always, so mismatch1 is always 0")
      tool freed prod1 -> gv verdict: PROVED
PROVED after freeing ['prod2','prod1'] over 2 iterations.
```
This is the **STILL TIMES OUT → free an additional register and repeat** branch of
CLAUDE.md §9 step 5, driven entirely by gv's real output — not by the LLM guessing.
(The two product registers are symmetric, so the order it picks them in may vary.)

## Architecture note (selector / applier)
The LLM is the **selector**: each iteration it returns one register name (JSON) to
free. The **applier** is mechanical Python (`free_register` in `src/abstract.py`):
it deletes that register's declaration and `<=` assignments and re-declares it as a
primary input. This hard-constrains the action space to the single sound operator
(CLAUDE.md §4.2) and guarantees the output is syntactically valid and an
over-approximation by construction — the LLM never writes Verilog.

## Soundness
Identical to `gatedmult`: freeing registers only removes constraints, so the abstract
design over-approximates the original; a safety proof on it holds on the original.
Here `p1 = (mismatch1 & active) | (mismatch2 & done)` and both gates are ≡0, so `p1 ≡ 0`
regardless of the now-free `prod1`, `prod2`.

## Result
| Design | Engine | Baseline | Abstracted | Iterations |
|---|---|---|---|---|
| `gatedmult2` | PDR | TIMEOUT (60 s) | PROVED (0.02 s) | **2** |
