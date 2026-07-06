---
name: effort-bench
description: "Drive the effortmining A/B benchmark harness, the deterministic Python core (bench/effort.py) that measures pass-rate and token cost per (task-class, effort-tier) and fits the calibration table the effortmine skill dispatches from. Use to validate the instrument, run the matrix, grade, analyze, report, or refit. This skill shells out to the harness; it does not compute results itself."
argument-hint: "[validate|run|grade|analyze|report|calibrate]"
---

# effort-bench — run the calibration benchmark

This skill is a thin driver over `bench/effort.py`, the stdlib-only harness that produces effortmining's one deliverable of value: a **calibration table** stating, per class of subtask, the cheapest reasoning-effort tier that does not measurably hurt quality. The harness is the deterministic source of truth; the model never computes a pass rate, a token count, or a tier decision here. It shells out and reports what the CLI returns. Methodology is pre-registered in `docs/research/04-benchmark-methodology.md`.

The harness itself is built by the software-engineer agent against `docs/research/04` section 9. This skill only *invokes* its subcommands; it does not reimplement them.

## Resolve the harness

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:?effort-bench must run as an installed plugin}"
BENCH="$ROOT/bench/effort.py"
```

Run everything as `python3 "$BENCH" <subcommand> [args]`. Python 3 stdlib only; no dependencies to install.

## The flow

The benchmark is a gated pipeline. Run the phases in order; do not skip the gate.

```
  validate  →  run  →  grade  →  analyze  →  report        (+ calibrate at runtime)
     │          │        │          │           │
   Phase 0    matrix   checkers   stats +     RESULTS.md
    gate     180 runs             NI decision
```

| step | command | what it does | gate |
|---|---|---|---|
| **1. validate** | `python3 "$BENCH" validate` | Phase 0 (04 section 4): confirms `--effort` is accepted per tier, enumerates the result-envelope fields, checks effort actually modulates output tokens (median max >= 2x median low), and sanitizes the child env (`CLAUDE_CODE_EFFORT_LEVEL` MUST be unset, it overrides `--effort`). Writes `bench/state/phase0.json`. | **Hard gate.** `run` refuses until this passes. If effort does not modulate in headless mode, the premise fails; stop and escalate. |
| **2. run** | `python3 "$BENCH" run [--scale pilot\|fallback\|reduced\|extended]` | Executes the matrix: 12 tasks x 5 tiers x n reps (pilot n=3 gives 180 runs). Seeded shuffle, concurrency 3, backoff, 300 s per-run timeout, per-run nonce. Resumable; never re-bills a completed cell. Appends raw records to `bench/raw/results.jsonl`. | — |
| **3. grade** | `python3 "$BENCH" grade` | Applies each task's deterministic checker (exact-match or pytest-asserts in a sandbox). The pilot suite is 100% deterministic oracles (**blind-grader count 0**), so this step needs no LLM. Writes `pass` and `failure_class` to `bench/state/graded.jsonl`. | — |
| **4. analyze** | `python3 "$BENCH" analyze` | Cell pass rates with Wilson CIs, pools tasks to class level, applies the pre-registered non-inferiority rule (margin 0.10) to pick the cheapest non-inferior tier per class, bootstraps the policy savings %. Writes `bench/state/analysis.json` and the fitted `bench/state/calibration.json` (version >= 1). | — |
| **5. report** | `python3 "$BENCH" report` | Renders `bench/RESULTS.md`: run manifest, the full matrix, per-class curves, the calibration table, and the headline A/B (calibrated vs inheritance-at-`xhigh`). | — |
| **runtime. calibrate** | `python3 "$BENCH" calibrate` | Guarded refit from accumulated real-usage receipts (`dispatch-log.jsonl` plus graded outcomes). Moves a class's tier at most one step, only past a min-N gate (>= 9 outcomes per cell) and only if the non-inferiority decision actually flips; prints a human-readable diff. This is how the table stays current as `/effortmine` logs real dispatches. | — |

## The non-deterministic path (specced, not used by the pilot)

For future benchmark tasks that are not deterministically checkable, grading routes to the `effort-grader` agent: the blind grader whose payload deliberately omits any tier/agent label, pinned to `medium` effort to avoid grader-effort confounds. The pilot's 12 tasks are all executable oracles (04 section 2), so the grader is not exercised yet; it is wired for when it is needed and for runtime audit of dispatched work.

## Reporting

Surface what the CLI returns, in mission-control style: no emoji, Unicode box-drawing, and every completion line carries a concrete number (the count of runs, the pass rate, the savings %). Do not paraphrase or round the numbers the harness reports; they are the evidence. Example completion line:

```
  ✓ analyze    4 classes calibrated · savings 41% vs inherit-xhigh (95% CI 28-52) · agg pass non-inferior
```

If a step reports a non-convergent or aborted state (Phase 0 fail, an incomplete cell, wide CIs marked low-confidence), state it plainly. A benchmark that hides its failures is worthless.
