# CLAUDE.md — AIAutoRTLAnR

> **How to use this file:** Place it at the root of the `gv` repo, cloned from
> `https://github.com/DVLab-NTU/gv.git` (Claude Code auto-loads root `CLAUDE.md`). Then
> you can simply say: *"Build this project according to CLAUDE.md."* Everything you
> need is below — do not assume anything not stated here; when `gv` behavior, command
> syntax, build steps, or repo layout are unknown, **read the actual README/docs in
> this repo, don't guess** (see §3 and "Discovering gv's API", §7). Some details below
> (exact build command, exact GV command names, folder layout) are **best-effort, not
> confirmed** for this specific repo — verify each against the real repo before relying
> on it; the project must work with whatever this repo actually contains.

---

## 1. What this project is

**AIAutoRTLAnR** is a System-on-Chip Verification course project: an **AI-assisted
agentic flow** that performs **RTL design abstraction** so the course's verification
tool `gv` can *prove* a safety property it otherwise **fails / times out** on.

The LLM is the **proposer** (it rewrites the RTL). `gv` is the **checker** (it decides
whether the property holds). A script is the **control loop** that ties them together
and enforces the rules. That separation is the whole point — see §4.

**Working solo. Proving-only scope** (the optional CEGAR refinement loop is explicitly
out of scope — see §10).

---

## 2. The core idea (read this before writing any code)

- Formal engines fail on complex designs because of state explosion.
- **Abstraction** removes/frees parts of the design so the engine can prove the property.
- We commit to **OVER-APPROXIMATION ONLY** (the abstract design has a *superset* of the
  original's behaviors). Never under-approximate. Never mix the two in one proof flow.
- **Why over-approximation:** if `gv` proves a safety property on the abstract design,
  it provably holds on the original. State this guarantee every time you report a proof.
- **The sound operator we use: free-input localization.** Delete a register's driving
  logic and replace the signal it drives with a *fresh primary input* that can take any
  value each cycle. This only ever *removes* constraints, so the result is an
  over-approximation **by construction** — which is why we don't need a separate
  proof-checker. The soundness is structural.

**The key research question — and an honest caveat** (put this in the report):
free-input localization is *also* what abc does automatically at the gate level
(proof-based / counterexample-based abstraction). So the **operator itself is not
novel**, and on a simple design abc could localize the same register on its own. The
LLM's contribution is therefore **not** "a better abstraction operator" — it is two
other things: (1) the **level** — it abstracts the human-readable RTL on
semantically-meaningful units (a whole counter, a whole module), which is exactly what
the assignment requires ("on the RTL design, not the gate-level one"), and (2) the
**selection** — it picks what to free using semantic understanding of the design and the
property ("this wide timer only gates a transition; the mutual-exclusion property doesn't
depend on its value"), rather than abc's purely structural heuristics.

Do not overclaim that this beats abc. Claim only what is true: a **sound, RTL-level,
LLM-driven abstraction flow**. We keep every transformation inside the sound operator
above so results stay trustworthy, and we make the comparison fair by checking the
baseline against gv's strongest engine (see §6 and §12).

---

## 3. What gv is

- **Repo:** `https://github.com/DVLab-NTU/gv.git` — from NTU's Design Verification Lab
  (the same lab behind `qsyn`). Per the repo's own description, GV is a bridge between
  multiple verification engines, letting algorithms be implemented once against a common
  "GV" interface rather than per-engine.
- `gv` reads RTL and proves properties using underlying engines. The lab maintains forks
  of `abc` (Berkeley ABC) and `cadical` (a SAT solver), so expect at least an ABC-based
  engine and possibly a SAT-based one — but **confirm the exact RTL front-end and engine
  list for THIS repo by reading its README and running the built tool, not by assuming
  (e.g. don't assume a yosys front-end; verify what it actually uses).**
- It is a command-line / interactive tool that (in this style of tool) usually also runs
  **dofiles** (batch command scripts) — confirm the exact mechanism in this repo.
- **Confirmed build dependencies** (from this repo's README): it's a CMake-based C++
  build. Install with:
  ```
  sudo apt-get -y install libgmp-dev gperf build-essential bison flex libreadline-dev \
      gawk tcl-dev libffi-dev git cmake parallel
  sudo apt-get -y install graphviz xdot pkg-config python3 libboost-system-dev \
      libboost-python-dev libboost-filesystem-dev zlib1g-dev libgmp-dev
  ```
  Then `git clone https://github.com/DVLab-NTU/gv.git && cd ./gv` and **follow this
  repo's own README for the exact build command** (likely a `cmake -B build && cmake
  --build build` style flow, but confirm — do not guess the binary name or invocation;
  read the README to find out what to run after building, e.g. `./gv` or otherwise).
- **You only ever transform the RTL that gv reads — at the RTL level, never gate-level.
  Never modify gv's own source code.** Building it is fine; editing its source/engine/
  library directories is not.
- **Important honesty note:** earlier drafts of this plan referenced specific command
  names (`GV REad Design`, `GV Formal Verify`, etc.) from a different, related repo
  (`ric2k1/gv0-socv`). This repo may use the same, similar, or different command names
  and conventions. **Treat every `GV ...`-style command name in this file as a
  placeholder/example, not a confirmed fact for this repo.** Always verify the real
  command set via this repo's own `help` and README, and whatever documentation/example
  directories actually exist here, before writing any dofile or script that depends on
  it (see §7 — don't assume `doc/`/`tests/` exist; discover the real layout first).

---

## 4. What makes this an "agentic flow" (this is what gets graded)

Naive prompting = "abstract this design" → one unverified guess. This project is the
scaffolding that makes the LLM's output sound, checkable, and self-correcting:

1. **Ground every claim in real gv output.** Never report "proved," "fails," or
   "times out" unless `gv` actually returned that. Do not assert results you did not
   observe from the tool.
2. **Constrain the action space** to the sound operator(s) in §5.
3. **Verify mechanically** after every rewrite: does `gv`'s own front-end still parse
   it cleanly? did the proof outcome change?
4. **Loop** on the tool's feedback (§9).

The report must explicitly discuss this proposer / checker / loop distinction and where
the LLM helped vs. stumbled. The course note says *discussion and experiments matter
most* — weight effort accordingly.

---

## 5. Allowed transformations (the entire action space — use ONLY these)

1. **Free-input localization (DEFAULT):** delete a register's logic and replace its
   driven signal with a fresh primary input.
2. **Counter freeing:** replace a wide counter whose exact value doesn't affect the
   property with a free input on its output / "done" signal (a special case of #1).

Every free-input localization is sound regardless of which register you free. To get a
**clean proof without spurious counterexamples**, prefer freeing registers **outside the
property's cone of influence (COI)** first. Determine the COI by analyzing which signals
the property transitively depends on; free only signals outside it.

**Forbidden:**
- Under-approximation of any kind.
- Width / parameter reduction (shrinking a FIFO, "lowering the price") **as a claimed
  proof** — it is not guaranteed sound. You may mention it in the report as a research
  direction, never as a verified result.
- Mixing over- and under-approximation.

---

## 6. The benchmark design

**Decision: you choose the benchmark — check the repo first, generate only if needed.**

1. First inspect this `gv` repo's own design/example/test directories (names TBD — look
   for things like `design/`, `tests/`, `examples/`, `benchmark/`) for an existing
   Verilog design you can use or **scale up** (widen a counter/datapath, deepen a
   buffer) until `gv` fails to prove its property in a fixed time budget.
2. If nothing suitable exists, **generate** the canonical case: a small FSM controller
   (e.g. a 2-client arbiter or traffic-light) whose state transitions are gated by a
   **wide counter** (e.g. 32-bit, firing at a large constant). The safety property
   ("never two grants/greens simultaneously") depends only on the FSM, not the counter
   value — so freeing the counter is a clean, sound abstraction that makes it provable.

**Hard requirement:** the baseline must *genuinely fail or time out* in `gv` within a
fixed budget (e.g. 60s). If it proves instantly, widen it until it doesn't — there is no
experiment without a real baseline failure. Record the baseline result.

**Engine sweep (do this — it makes the result honest and strong):** `gv`'s default proof
path may not invoke its strongest abstraction-capable engine, but it might. So run the
*original* design under every engine/mode option this repo actually exposes (find the
real command names via `help` and the README/doc — don't assume the `GV SEt Engine` /
`GV ABCCMD`-style names from §3's honesty note apply here) and record which ones were
tried. The result is only compelling if the baseline fails under `gv`'s **strongest**
engine, not merely its default. If some built-in engine already proves the original,
that case is too easy — scale it up further, or pick a harder design, until even `gv`'s
best setting fails. Record the full engine sweep for the report.

One design done cleanly is a complete submission. A second is a bonus, not a priority.

---

## 7. Discovering gv's API (do this, don't guess)

This repo (`DVLab-NTU/gv`) is a different, more general tool than the one a previous
draft of this plan assumed. **Do not assume any specific folder names or command names
below — find the real ones first.** Before writing any dofile or script:

1. Read this repo's own `README.md` top to bottom.
2. List the repo root and look for documentation/example directories — candidates
   include `doc/`, `docs/`, `tests/`, `test/`, `examples/`, `benchmark/` — and use
   whichever actually exist.
3. Build the tool (per the confirmed steps in §3), launch it, and run `help` (and
   `help <command>` for specifics) to enumerate the **real** command set.
4. From that, determine the real syntax for: reading in a design, specifying/declaring a
   property and what "safe"/"proved" looks like in this tool's output, selecting an
   engine (this repo bridges multiple engines, and ships `abc` and `cadical` — a SAT
   solver — as sister repos/submodules, so expect at least an ABC-based and possibly a
   CaDiCaL/SAT-based engine option; find the real selection command), running a batch
   script (a "dofile" equivalent, if one exists — confirm the actual mechanism, e.g. a
   `-v`-style script flag as seen in this lab's sibling tool `qsyn`), and running
   simulation if available.

Mirror the property-spec convention used by the repo's own examples rather than
inventing one. **Do not hardcode any command syntax into this project until you have
confirmed it by actually running the built tool** — treat any `GV ...`-style name
elsewhere in this file as illustrative only, not a fact about this repo.

---

## 8. Architecture & repo layout

Keep ALL project work in a `project/` subdirectory so gv's tree stays clean:

```
gv/                          # this repo, cloned from DVLab-NTU/gv
  CLAUDE.md                 # this file
  (gv's own files — build, never edit)
  project/
    README.md               # install + run instructions for the grader
    run.sh                  # single entry point (cached by default, --live optional)
    designs/<name>.v        # ORIGINAL design (never modified)
    designs/<name>.<prop>   # property, in gv's convention (from §7)
    abstracted/<name>.v     # LLM-generated abstracted RTL (committed = cached artifact)
    abstracted/<name>.notes.md   # LLM's reasoning + exact transformation (provenance)
    dofiles/baseline.dofile # runs gv on the original → fail/timeout
    dofiles/prove.dofile    # runs gv on the abstracted → proved
    src/abstract.py         # LLM orchestration (live mode); Python + anthropic SDK
    report/report.md        # the write-up (see §12)
    .env.example            # ANTHROPIC_API_KEY=sk-ant-your-key-here
    .gitignore              # must include: .env, .env.local, *.key
```

*The `dofiles/*.dofile` names above are placeholders. Use whatever batch-script
mechanism `gv` actually supports — a dofile, a `-v script`-style flag (as in the sibling
tool `qsyn`), piped stdin, etc. (confirm per §7). The point is just two saved scripts:
one that runs the original design, one that runs the abstracted design.*

**Two modes, one script:**
- **Cached (default, no key):** `run.sh <design>` runs `baseline.dofile` (shows the
  failure), then runs `prove.dofile` on the *committed* `abstracted/<name>.v` (shows the
  proof), then prints the comparison table. Fully deterministic — this is how the grader
  reproduces your result.
- **Live (`run.sh --live <design>`):** if `ANTHROPIC_API_KEY` is set, `abstract.py`
  regenerates `abstracted/<name>.v` from the original via the LLM, then the same
  validation + prove path runs. If no key is set, print a clear message and fall back to
  cached mode. The committed cache is what guarantees grading works without a key.

**Output / UX requirement (for clarity in terminal use and the demo video):** `run.sh`
and `abstract.py` must print a clear numbered stage banner before each major step, e.g.:
```
[1/4] Baseline: running gv on original design...
[2/4] LLM proposing abstraction...
[3/4] Syntax check: parsing abstracted RTL...
[4/4] Proving: running gv on abstracted design...
```
Each banner should be followed by the real `gv`/LLM output, then a one-line result
summary (PASS/FAIL/PROVED/TIMEOUT + elapsed time). This keeps a screen recording
self-explanatory without heavy narration.

Orchestration: **Python + the `anthropic` SDK**, model `claude-sonnet-4-6` (make it a
single variable). Load the key from the environment (`anthropic.Anthropic()` reads
`ANTHROPIC_API_KEY` automatically; use `python-dotenv` + `load_dotenv()` to pick up
`.env`).

---

## 9. The abstraction loop (proving-only)

For a given design + property:

1. Read the design and property.
2. Run `baseline.dofile`. Confirm it fails/times out; record the result.
3. Identify the property's COI. Propose **one** free-input localization on a register
   **outside** the COI. Explain the choice.
4. Write the abstracted RTL to `abstracted/<name>.v`. **It must be 100% syntactically
   valid** — verify by having `gv`'s own RTL front-end parse it (find the real read/parse
   command per §7). If it doesn't parse, fix and re-check before continuing.
5. Run `prove.dofile` on the abstracted design:
   - **PROVED** → report success + the soundness statement (§2). Done.
   - **COUNTEREXAMPLE** → the cut was too aggressive (likely freed something in-COI).
     Revert it and pick a *different* out-of-COI register. (We do **not** do CEGAR
     refinement — see §10.)
   - **STILL TIMES OUT** → free an additional out-of-COI register and repeat from step 3.
6. **Cap the loop at 5 iterations** (protects API spend and prevents runaway).

Always write the chosen transformation and reasoning to `abstracted/<name>.notes.md`.

---

## 10. Out of scope — do NOT build

- **CEGAR refinement loop.** Proving-only scope. Do not implement spurious-CEX
  detection + putting-logic-back. If a CEX appears, handle it per §9 step 5 (try a
  different cut), not by refining.
- Any under-approximation path.
- A polished GUI or VS Code extension. The deliverable is the script + agent flow.

---

## 11. Hard constraints / guardrails

- Output RTL must be **100% syntactically correct**; always confirm via `gv`'s own
  front-end parse before claiming anything.
- **Never claim a proof** unless `gv` returned it on the abstracted design.
- **Over-approximation only.** Never mix in under-approximation.
- **Never modify** files under `designs/` (originals) or any of `gv`'s own source.
- **No secrets in the repo, ever.** Create `.gitignore` (with `.env`, `.env.local`,
  `*.key`) *before* the first commit; never write a real key into any committed file;
  provide `.env.example` with a placeholder only. If a key is ever committed by accident,
  it must be revoked and regenerated.
- Cap any LLM loop at 5 iterations.

---

## 12. Deliverables

**`project/README.md`** — for the grader:
- How to build `gv`: clone `https://github.com/DVLab-NTU/gv.git`, install the confirmed
  apt dependencies (§3), then **follow this repo's own README for the exact build
  command** (likely CMake-based — confirm and state precisely what command produces what
  binary, since "best-effort" guesses must not end up in the final README).
  State the precise, *tested* command sequence — do not leave any "confirm in README"
  hedge language in the final deliverable; resolve every TBD before submission.
- How to run cached mode (no key) and live mode (own key via env / `.env`).
- What result to expect (baseline fails; abstracted proves).

**`project/report/report.md`** — the graded core. Include:
- The problem (why `gv` fails on the chosen design).
- The approach: over-approximation via free-input localization, and the **one-paragraph
  soundness argument** (§2).
- The **results table**: design | baseline result/time **under each gv engine tried** |
  abstraction applied | abstracted result/time | sound? (yes). The baseline column must
  show the failure persists under `gv`'s strongest engine, not just the default.
- **Honest framing of the contribution** (§2): the localization *operator* coincides with
  abc's automated gate-level abstraction, so do **not** claim you beat abc. Claim a sound,
  RTL-level, LLM-driven flow whose value is the *level* (RTL / semantic units, as the
  assignment requires) and the *selection* (semantic, property-aware). The engine sweep is
  what keeps this fair.
- Discussion: where the LLM helped vs. failed; the proposer/checker/loop design;
  semantic vs. structural abstraction (§2); why over- not under-approximation; and a
  *discussion-only* look at a semantic abstraction abc can't do (e.g. collapsing the
  counter's meaning or shrinking a datapath), clearly flagged with soundness caveats and
  never reported as a verified proof.
- Limitations and honest caveats.

---

## 13. Build order (start here)

1. **Build `gv` first** and confirm the built binary launches (find its real name/path
   from the README — don't assume `./gv`). If the build fails, stop and report the error
   — nothing else works until this does.
2. Discover the real API per §7 (README, directory listing, `help`) — do not assume
   folder or command names from any other repo.
3. Select/scale or generate the benchmark; confirm the **baseline genuinely fails** —
   including the **engine sweep** so it fails under `gv`'s strongest engine, not just the
   default (§6).
4. Do **one** free-input localization by hand; confirm `gv` now proves it. This is the
   ground truth before any LLM involvement.
5. Build `src/abstract.py`, `run.sh`, and the two dofiles; commit the abstracted RTL +
   notes as the cached artifact; verify `run.sh <design>` reproduces baseline-fail →
   abstract-prove from a clean state.
6. Write `README.md` and `report/report.md`.

**Definition of done (MVP):** one design where `gv` fails on the original and proves on
the LLM-abstracted version, reproducible via `run.sh`, with the report and README
complete.
