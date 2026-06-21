# Abstraction notes — `gatedmult`

## Property under proof
`p1 = mismatch & active` (the only module output). A safety property: `p1` must
**always be 0**. `gv` reports this as `Proved` with `Disproved = 0`.

## Baseline (original) result — engine sweep
| Engine | Command | Result | Time |
|---|---|---|---|
| **PDR** (abc IC3 — gv's strongest) | `pdr -o 0` | **TIMEOUT** | > 60 s (killed) |
| **BDD** | `bcons -all` … `pcheckp -o 0` | **TIMEOUT** | > 60 s (`bcons` explodes) |
| `satv itp` | `satv itp -o 0` | not available in this build (`Illegal command`) | — |

The baseline genuinely fails under gv's strongest engine, not just its default.

## Cone-of-influence analysis
`p1` depends on `mismatch` and `active`.
- `active = (state == 3)`; `state` cycles `0 → 1 → 2 → 0` and never reaches 3, so
  `active` is **identically 0**.
- `mismatch = (prod != ra*rb)`; `prod`, `ra`, `rb` are the 16×16 multiplier
  datapath registers. They are **combinationally inside p1's COI**, so gv keeps the
  whole multiplier and is dragged into proving the arithmetic self-check can never
  mismatch — a hard invariant for both IC3 and BDDs.

**Semantic observation the LLM exploits:** because `active ≡ 0`, the *value* of
`mismatch` (and therefore the entire multiplier) is **irrelevant to the truth of
p1**. A purely structural tool keeps the multiplier (it is in the fan-in cone); a
semantic reasoner sees it cannot matter.

## Transformation applied (the sound operator)
**Free-input localization** of the single register `prod`: delete its driving logic
(`prod <= a*b`) and declare it a **fresh primary input** that may take any value every
cycle. This is the *minimal* cut — it breaks the multiplier's self-check equivalence
(the engine no longer has to prove `prod == ra*rb`), which is exactly the hard part PDR
was grinding on. (Freeing `ra`/`rb` instead would work too; one product-register cut is
enough here.)

This is the entire action space allowed by the project (CLAUDE.md §5). No
under-approximation, no width/parameter reduction.

**Architecture (selector / applier).** The LLM is the *selector*: it returns one
register name to free. The *applier* is mechanical Python (`free_register` in
`src/abstract.py`) that performs the actual transformation. The LLM never writes
Verilog, so the action space is hard-constrained to this one sound operator and the
output is valid and over-approximating by construction. For this design the loop
converges in **one** iteration (select `prod` → PROVED); the companion benchmark
`gatedmult2` needs **two** (see its notes).

## Soundness (over-approximation by construction)
Freeing a register only ever **removes constraints**: the original behavior of
`prod/ra/rb` is one of the many a free input now permits, so the abstract design's
behavior set is a **superset** of the original's. Any safety property `gv` proves on
the abstract design therefore **provably holds on the original**. No separate
proof-checker is needed — the soundness is structural.

After the cut, `mismatch` is an arbitrary function of free inputs, but
`p1 = mismatch & active` and `active ≡ 0`, so `p1 ≡ 0` still holds — no spurious
counterexample is introduced.

## Abstracted result
| Engine | Command | Result | Time |
|---|---|---|---|
| **PDR** | `pdr -o 0` | **PROVED** (`All = 1, Proved = 1, Disproved = 0`) | 0.02 s |

TIMEOUT → PROVED, soundly.

## Honest framing vs. abc (CLAUDE.md §2)
Free-input localization is exactly what abc does automatically at the gate level, so
the **operator is not novel**. What gv/abc's *structural* localization does **not**
do here is drop the multiplier: it is structurally in p1's fan-in, so abc keeps it
and times out. The contribution is (1) the **level** — the cut is made on a
human-readable RTL datapath (whole registers), as the assignment requires, and
(2) the **selection** — choosing what to free from the *semantics* of the design and
property (`active ≡ 0 ⇒ the multiplier is irrelevant`), not from gate-level
structure. We do **not** claim to beat abc; we claim a sound, RTL-level, LLM-driven
abstraction flow.
