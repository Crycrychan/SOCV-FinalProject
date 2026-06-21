# Abstraction notes — `gatedmult3` (the counterexample-recovery benchmark)

## Why this benchmark exists
`gatedmult` / `gatedmult2` exercise the PROVED and "free one more" (TIMEOUT) branches of
the loop. `gatedmult3` is built to exercise the **COUNTEREXAMPLE → revert** branch: it
contains a deliberate **load-bearing decoy** that *looks* freeable but isn't.

## The design
Two gated 16×16 multiplier self-checks (the timeout source) plus a wide 32-bit register
`shadow` that increments and **saturates at 100**:

```
p1 = (mismatch1 & active) | (mismatch2 & done) | (shadow > 100)
```
- `active = (state==3)` is never reached, `done <= active` so `done ≡ 0` → the two
  multiplier terms are gated off. Freeing a **product register** (`prod1`/`prod2`) is a
  sound cut that removes the hard arithmetic.
- `shadow > 100` is `≡ 0` **only because `shadow` saturates at 100** — i.e. the property
  genuinely depends on `shadow`. `shadow` is therefore **load-bearing**.

## The trap
`shadow` is a wide, monotonic counter — it pattern-matches the classic "free the
irrelevant wide counter" move. But freeing it (→ fresh primary input) lets `shadow` take
any value, so `shadow > 100` becomes satisfiable and `p1` can be 1. That is a **spurious
counterexample**: the cut was inside the property's true cone of influence.

## Mechanics (measured)
| Cut | gv (PDR) |
|---|---|
| none (original) | **TIMEOUT** (>60 s) |
| free `shadow` (the decoy) | **COUNTEREXAMPLE** (`p1` asserted in frame 0) |
| free `prod1` (a product reg) | **PROVED** (~0.5 s) |

## What the models did (live)
- **Sonnet (claude-sonnet-4-6):** usually *avoids* the decoy — it sees `shadow > 100` is
  load-bearing and frees a product register → PROVED. (It is not infallible: on some runs
  it wanders into the control registers, see "limitation" below.)
- **Haiku (claude-haiku-4-5) selector:** *falls for the decoy*. Real transcript:
  ```
  [1/5] LLM chose: shadow  -- "shadow ... never exceeds 100 ... safe to free"
        gv verdict: CEX  -> 'shadow' is load-bearing. Reverting and asking for a different register.
  [2/5] LLM chose: done   -> gv: TIMEOUT (kept)
  [3/5] LLM chose: state  -> gv: TIMEOUT (kept)
  [4/5] LLM chose: ra2    -> gv: CEX  -> revert
  ...
  ```
  The **COUNTEREXAMPLE → revert** branch fires exactly as designed: a real (weaker) model
  proposes an unsound cut, gv catches it, the loop reverts and tries another register.
  Reproduce with `ABSTRACT_MODEL=claude-haiku-4-5-20251001 python3 project/src/abstract.py gatedmult3`.

## The key guarantee, stress-tested
Across these runs the weak selector proposed **three** unsound cuts (`shadow`, `ra2`,
`rb2`). gv returned a counterexample for **every one**, and the flow **never reported a
false proof**. This is the soundness guarantee holding under an adversarially-bad
proposer — exactly what naïve "ask the LLM and trust it" cannot offer.

## The finding that motivated backtracking
Freeing the *control* registers `done`/`state` is sound in isolation (an
over-approximation) but **opens the gates** `active`/`done`, which makes the multiplier
operands load-bearing and turns later operand cuts into counterexamples. A greedy
forward-only loop gets stranded: because free-input localization is **monotonic** (it
only removes constraints), no additional cut can repair a counterexample — only undoing
the bad cut can. The loop in `src/abstract.py` is therefore a **backtracking DFS**: when a
node runs out of candidates it pops the last accepted cut and bans it at the parent. This
makes the search **complete** given enough budget — it finds a proving set if one exists
(verified with a worst-first selector in a mocked run under a raised attempt budget). The
default cap is 5 iterations (CLAUDE.md §9/§11), so a weak selector on this design may still
hit the cap; raise `ABSTRACT_MAX_ATTEMPTS` to watch it recover fully. The committed cached
artifact frees `prod1` directly (a known-good sound cut) so `run.sh gatedmult3` is
deterministic and fast.
