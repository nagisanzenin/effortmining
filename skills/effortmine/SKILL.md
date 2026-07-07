---
name: effortmine
description: "Decompose a request into subtasks, classify each by difficulty (T1 mechanical through T4 hard reasoning, plus R-research and C-coding), and dispatch each to the cheapest calibrated reasoning-effort tier a blind grader still accepts. Use when you want a multi-part job done at the right effort per part instead of burning one uniform (usually too-high) effort on everything. The per-subtask effort is applied by dispatching to a tier-pinned worker agent (miner-low through miner-max), because Claude Code has no per-spawn effort parameter."
argument-hint: <the request to dispatch at calibrated effort>
---

# effortmine — calibrated dispatch

`/effortmine <request>` spends the right amount of reasoning on each part of a job: it breaks the request into subtasks, labels each with a difficulty class, looks up the cheapest effort tier that class is calibrated for, and dispatches each subtask to a worker pinned at that tier. Cheap parts run cheap; hard parts get the reasoning they need. Nothing runs at a blanket session effort just because that is what you happened to set.

Read this whole file before acting.

## What this does, and does NOT, do

**Does:** class-level effort calibration. It maps each subtask to one of six difficulty *classes* and dispatches at the tier the calibration table recommends for that class. The shipped table is fitted from 450+ real runs on `claude-opus-4-8` (2026-07-06 pilot + 2026-07-07 v2/refit; provenance stamped in `calibration.json`), so that choice is measured and benchmark-backed; if the live table is missing, the skill falls back to an embedded snapshot of those same v1 values.

**Does NOT: per-prompt magic.** There is no model that reads a specific prompt and divines its exact optimal effort. The unit of calibration is the *class*, not the individual prompt. Two different T3 subtasks get the same tier. If you need a specific subtask run at a specific effort, say so and it is honored over the table.

**Does NOT: invent a spawn-site effort knob.** Claude Code's Agent/Task tool takes `model` but not `effort` (verified against the installed CLI and the docs, `docs/research/01-mechanism-investigation.md`). effortmine applies a tier by choosing *which agent* to spawn: the tier-pinned `miner-<tier>` workers, identical except for their frontmatter `effort:`. That indirection IS the mechanism; there is no hidden API.

## Resolve paths first

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:?effortmine must run as an installed plugin}"
CALIB="$ROOT/bench/state/calibration.json"
DLOG="$ROOT/bench/state/dispatch-log.jsonl"
```

## Phase 1 — Decompose

Break the request into the smallest subtasks that are each independently dispatchable and independently checkable. A subtask is one unit of delegated work with one deliverable. If the request is already a single unit, that is one subtask; proceed.

## Phase 2 — Classify each subtask

Assign every subtask exactly one class. Judge by the *nature of the reasoning the task demands*, not by how long the output is or how important it feels.

| class | the work is... | tier hint | examples |
|---|---|---|---|
| **T1-mechanical** | retrieval, extraction, reformatting to an explicit template; no reasoning, no ambiguity | cheapest | extract fields from log lines into `ts\|svc\|code`; dedupe and sort a tag list; aggregate JSON into sorted `key=value` lines |
| **T2-simple-transform** | one well-specified transform with light, local reasoning and shallow edge cases | cheap | implement `normalize_phone`; run-length-encode a string; count inclusive business days between two dates |
| **T3-moderate-reasoning** | diagnosis, multi-constraint logic, or tracing; the work is figuring out *what*, the answer is short | mid | find and fix a subtle bug in a function; solve a small logic puzzle with a unique solution; trace a stack-machine program to its output |
| **T4-hard-reasoning** | multi-step reasoning with adversarial or overfit-punishing edge cases | high | implement a ledger with holds/releases where a naive version passes the visible cases; count length-6 strings with no 3-in-a-row; topologically resolve dependencies including the cycle case |
| **R-research** | cross-source synthesis over provided documents: extract, reconcile conflicts, attribute claims | cheap* | which two changelogs conflict on the timeout default and what does the primary source say; identify the common root cause across three postmortems |
| **C-coding** | implement/fix/refactor real code against a spec with hidden edge cases | mid | implement an IntervalSet vs spec; fix interlocking bugs in a 150-line module; implement a spec with a formal invariant (refit 2026-07-07: low breaks on invariant edge cases; medium is the ceiling) |

*R-research carries a fit-blindness warning (isolated fitting tasks saturate at `low` even at hard-recipe difficulty, but **contextual** hard research — the benchmark's `X1.3`, a multi-document root-cause question inside a composite job — defeats `low` and needs `xhigh`): route genuinely hard research to **xhigh** rather than the table tier. Across composite draws this caveat-aware routing held 100% quality at equal-or-lower cost than effort inheritance; the reliable double-digit savings come from isolated dispatch (v1: −64.7%).

Rules of thumb when torn: if a correct answer needs *no* deliberation, it is T1. If it needs a single obvious step, T2. If the difficulty is in the *diagnosis* and the output is short, T3. If a plausible-looking wrong answer would pass a shallow check, it is T4. When still unsure between two adjacent classes, pick the harder one; over-spending one tier is a smaller sin than shipping a wrong cheap answer.

## Phase 3 — Load the calibration table

Read `$CALIB`. It maps each class to a `recommended_tier`. Schema (see `docs/research/04-benchmark-methodology.md` section 7.1):

- top-level `version` (>= 1 means fitted from real benchmark data; `0` would mean an un-fitted a-priori default), `fitted_date`, `model`, `margin_delta`.
- `classes.<class>.recommended_tier` in `low | medium | high | xhigh | max`, plus `confidence`, `n_graded`, and the measured pass-rate / token fields.

**If `$CALIB` is absent or unreadable, fall back to the embedded snapshot below** — the fitted values — and tell the user you are dispatching from the shipped v1 snapshot because the live calibration file could not be read (measured, but possibly older than the installed file).

### Embedded fallback table — fitted snapshot (v1 + v2 + refit, 2026-07-07)

```json
{
  "version": 1,
  "source": "fitted-snapshot",
  "fitted_date": "2026-07-07",
  "model": "claude-opus-4-8",
  "suite_version": "pilot-12 + v2-15",
  "margin_delta": 0.10,
  "note": "Snapshot of the fitted table (bench/state/calibration.json, v1+v2 merged). Shown here only as the no-file fallback; the installed file is authoritative and may be newer. Per-class confidence is 'low' at n=3/cell.",
  "warnings": [
    "class R-research fit rests on tasks flagged misclassed",
    "class T4-hard-reasoning fit rests on tasks flagged misclassed"
  ],
  "classes": {
    "T1-mechanical":         {"recommended_tier": "low",  "confidence": "low", "n_graded": 9, "rationale": "9/9 pass at low; saturates at max (more tokens, no quality gain)"},
    "T2-simple-transform":   {"recommended_tier": "low",  "confidence": "low", "n_graded": 9, "rationale": "9/9 pass at low (a-priori guess was medium; low tested non-inferior)"},
    "T3-moderate-reasoning": {"recommended_tier": "high", "confidence": "low", "n_graded": 9, "rationale": "real quality gradient: low 6/9, high 9/9 at ~157 median out-tokens"},
    "T4-hard-reasoning":     {"recommended_tier": "low",  "confidence": "low", "n_graded": 9, "caveat": "9/9 at low, BUT flagged: fitting tasks too easy — prefer xhigh for genuinely hard work until the suite is extended"},
    "R-research":            {"recommended_tier": "low",  "confidence": "low", "n_graded": 18, "caveat": "flagged: isolated fitting tasks saturate at low even at X1.3-recipe difficulty, but the composite X1.3 (multi-doc root cause) needed xhigh (low 0/3, xhigh 3/3) — route genuinely hard research to xhigh"},
    "C-coding":              {"recommended_tier": "medium", "confidence": "low", "n_graded": 18, "rationale": "refit 2026-07-07: C6 invariant task breaks low (16/18); medium at the 18/18 ceiling; warning shed — fit includes proven-hard tasks"}
  }
}
```

`max` is recommended for no class: the pilot found saturation at `max` in every class — it never improved quality over `xhigh` and always cost more (no strict regression observed) — so it stays reserved for work harder than the pilot suite, never a default; it is the most expensive tier and is session-only.

## Phase 4 — Dispatch each subtask at its tier

For each subtask, map its class to `recommended_tier`, then map the tier to the worker agent:

| tier | agent (`subagent_type`) |
|---|---|
| low | `miner-low` |
| medium | `miner-medium` |
| high | `miner-high` |
| xhigh | `miner-xhigh` |
| max | `miner-max` |

Dispatch with the Agent/Task tool. **The tier is applied by the choice of `subagent_type`: the miner agent's frontmatter `effort:` sets the reasoning level. Do not pass an `effort` argument to the tool; there is none.** Use the dispatch formula: state the role, the exact subtask, the inputs to re-anchor from disk, and the required output format; tell the worker to return the raw result as its final message.

```
Agent(subagent_type="miner-<tier>",
      description="<3-5 word label>",
      prompt="<the subtask, self-contained: what to do, which files/inputs to read from disk, the exact output format required, and 'return only the result as your final message'>")
```

Independent subtasks may be dispatched concurrently (one Agent call each, in a single message). Dependent subtasks wait for their inputs.

A user's explicit per-subtask effort instruction overrides the table; honor it, and note the override in your summary.

## Phase 5 — Log each dispatch

After a subtask's worker returns, append one JSONL record to `$DLOG`. Today this log is telemetry only — the 0.2.0 refit path (`effort.py calibrate`) consumes graded *benchmark* receipts; folding this live dispatch log into the refit is roadmap. Create `bench/state/` if it does not exist.

Record shape (controlled-vocabulary fields only; do NOT put raw subtask prompt text in the log, it is both an injection surface and noise):

```json
{"ts":"<ISO-8601 UTC>","source":"effortmine","session_id":"<if known, else null>","task_class":"T3-moderate-reasoning","tier":"high","subagent_type":"miner-high","table_version":1,"accepted":null}
```

`accepted` is `null` unless you also ran the artifact past `effort-grader` (optional here; the benchmark path in `/effort-bench` is where grading is systematic). `table_version` echoes the `version` of the table you dispatched from, so a refit can tell default-driven dispatches from calibrated ones.

**Shell-safety:** never interpolate subtask text, user input, or model output into a shell command line; a stray quote or `$(...)` would execute. Build the record from controlled values (class, tier, and agent names are all fixed vocabularies) and append it, or write it with the Write tool to a temp file and concatenate. This mirrors the deterministic-core rule in `docs/research/03-pattern-mining.md` (A3).

## Present the result

Report back in mission-control style: no emoji, Unicode box-drawing characters, and every completion line carries a concrete number (the visual-identity discipline the suite ships; `docs/research/03-pattern-mining.md`, B4). Show, per subtask, its class, the tier it ran at, and its result. Make the calibration legible; the point is that cheap parts visibly ran cheap.

```
┌─ effortmine ─────────────────────────────── N subtasks ─┐
│                                                         │
│  ✓ T1-mechanical    low     <one-line result>           │
│  ✓ T3-moderate      high    <one-line result>           │
│  ✓ T4-hard          xhigh   <one-line result>           │
│                                                         │
│  N/N dispatched · table v1 (fitted 2026-07-06)          │
└─────────────────────────────────────────────────────────┘
```

If you fell back to the embedded snapshot (the live file was unreadable), add one honest line: you dispatched from the shipped pilot-v1 snapshot — measured, but possibly older than the installed `calibration.json` (refresh it with `/effort-bench`). Either way, note that at the pilot's n the per-class confidence is `low`, and T4's `low` tier rests on tasks the misclassification check flagged too easy — prefer `xhigh` for genuinely hard T4 work.
