# effortmining — Architecture

One page: what the components are, how data flows between them, and the one design decision everything hinges on (why tiered *agents* rather than a spawn-site effort knob).

## Why tiered agents (the load-bearing constraint)

effortmining exists to select reasoning effort **per subagent, by task difficulty**. The obvious way to do that would be to pass an `effort` argument when spawning each subagent, the way you can pass `model`. **That parameter does not exist.**

Verified against the installed Claude Code (`2.1.201`) binary and the official docs (`docs/research/01-mechanism-investigation.md`, `docs/research/01b-docs-verification.md`):

- The Agent/Task tool's input schema is `description, prompt, subagent_type, model, isolation, mode, name, run_in_background, team_name` — **no `effort`**. `model` is overridable per call; effort is not.
- A subagent's effort resolves as: **frontmatter `effort:` → else inherit the session effort.** There is no per-invocation override slot.
- So every ad-hoc subagent runs at the *session* effort. The only way to give one subagent a different, deliberate effort is to author a named agent with a static `effort:` in its frontmatter.

That constraint dictates the design. To offer five selectable effort tiers at dispatch time, effortmining ships **five otherwise-identical worker agents**, one per tier, differing only in `effort:`. Choosing a tier means choosing which agent to spawn. The five workers (`miner-low` through `miner-max`) are byte-identical in body — a fact the build verifies — so the *only* variable between them is reasoning effort, which is exactly what the calibration measures.

(Where a runtime exposes a real per-agent effort dial, for example Codex's `model_reasoning_effort`, the same tier abstraction maps onto it directly. On Claude Code today, tiered agents are the mechanism.)

## Components

```
┌───────────────────────── effortmining plugin ─────────────────────────┐
│                                                                        │
│  skills/                          agents/                              │
│  ┌────────────────────┐           ┌───────────────────────────────┐    │
│  │ effortmine         │  spawns   │ miner-low    (effort: low)    │    │
│  │  classify+dispatch │──────────▶│ miner-medium (effort: medium) │    │
│  │                    │           │ miner-high   (effort: high)   │    │
│  │ effort-bench       │           │ miner-xhigh  (effort: xhigh)  │    │
│  │  drive harness     │           │ miner-max    (effort: max)    │    │
│  └─────────┬──────────┘           │ effort-grader (effort: medium,│    │
│            │                      │   tier-blind payload)         │    │
│            │ shells out           └───────────────────────────────┘    │
│            ▼                                                            │
│  bench/                           hooks/                               │
│  ┌────────────────────┐           ┌───────────────────────────────┐    │
│  │ effort.py (CLI)    │           │ session-start.sh              │    │
│  │  validate|run|grade│           │   ambient table status line   │    │
│  │  |analyze|report|  │◀── reads ─│ log-dispatch.sh               │    │
│  │  calibrate         │  the log  │   PostToolUse(Task) telemetry │    │
│  │ tasks/  state/     │           └───────────────────────────────┘    │
│  └────────────────────┘                                                │
│   (bench/ owned by the harness engineer; skills+hooks reference it)    │
└────────────────────────────────────────────────────────────────────────┘
```

- **`skills/effortmine`** — the user-facing orchestrator. Decomposes a request, classifies each subtask into one of four difficulty classes (T1-mechanical through T4-hard-reasoning), reads the calibration table, and dispatches each subtask to the `miner-<tier>` the table recommends. Logs every dispatch.
- **`skills/effort-bench`** — a thin driver over the benchmark harness. Runs the gated pipeline `validate → run → grade → analyze → report`, plus the runtime `calibrate` refit. Computes nothing itself.
- **`agents/miner-*`** — five tier-pinned generic workers. Do exactly the delegated subtask, return the raw result, no scope creep.
- **`agents/effort-grader`** — the blind grader. Grades an artifact against a task plus rubric with **no** field naming the tier/agent that produced it, so the grade cannot be biased by effort. Pinned to `medium` (one tier below the workers) to avoid grader-effort confounds. Used for non-deterministic tasks and runtime audit.
- **`bench/effort.py`** *(owned by the harness engineer)* — the deterministic, stdlib-only source of truth. Every pass rate, token count, and tier decision comes from here; the model shells out. `state/calibration.json` is its fitted output and `/effortmine`'s input.
- **`hooks/`** — ambient, safe telemetry. `session-start.sh` prints one status line when a table exists (silent otherwise). `log-dispatch.sh` appends one record per subagent dispatch, fail-open.

## Data flow — the calibration loop

```
  /effortmine request
       │
       │  classify subtask -> class
       ▼
  read calibration.json ──────────────┐   (version 1, fitted by the
       │  class -> recommended_tier   │    2026-07-06 pilot)
       ▼                              │
  dispatch miner-<tier>               │
       │                              │
       │  raw artifact                │
       ▼                              │
  deterministic checker, or           │
  blind effort-grader -> verdict      │
       │                              │
       ▼                              │
  graded bench results ───────────────┤
       │                              │
       │  effort.py calibrate         │
       ▼    (guarded: min-N,          │
  refit calibration.json  ────────────┘
       (a class's tier moves at most one step,
        only if the non-inferiority decision flips)
```

In 0.2.0 the refit loop feeds on **graded benchmark receipts** (`effort.py run` → `grade` → `calibrate`), guarded exactly like engram's FSRS refit (sample-gated at >= 9 per cell, clamped, single-step, human-readable diff) so a noisy handful of records cannot thrash the table. Dispatch telemetry is *collected* today from two producers — the `PostToolUse(Task)` hook records **every** dispatch automatically (the tier is derivable from the `miner-<tier>` agent name), and the `/effortmine` skill adds the semantic **task-class** label the hook cannot know — but folding that live log into the refit is **roadmap**, not a shipped loop; the 0.2.0 refit path consumes benchmark data only.

## The oracle discipline (why the grader is blind)

The calibration is only as trustworthy as its grades. If the grader could see that an artifact came from `miner-low` versus `miner-max`, that label would leak into the grade and the whole table would be biased toward whatever the grader expected each tier to produce. So blindness is enforced by the **shape of the grader's input** — the payload has no tier/agent/model field — not by asking the grader to be fair. This is the independent-assessor pattern transposed from engram (`docs/research/03-pattern-mining.md`, A4), and it satisfies the loop-protocol rule that the producer of work must never control the check that judges it. For the pilot, every task uses a deterministic executable checker (an even stronger Tier-1 oracle), so the blind grader is specced and wired but not yet exercised.

## Provenance

Every structural choice traces to a mined pattern, documented in `docs/research/03-pattern-mining.md`: plugin manifest plus single-source version (A1), ambient silent-unless-useful hook plus injection guard (A2), deterministic CLI as source of truth (A3), the blind assessor (A4), guarded refit (A5), mode-classified orchestration (B1), the oracle-loop rulebook (B2), and receipt/effort telemetry (B3). The mechanism facts (no per-spawn effort parameter; effort inherits the session) are established in `docs/research/01-mechanism-investigation.md` and verified against the docs in `docs/research/01b-docs-verification.md`.
