# effortmining

![version](https://img.shields.io/badge/version-0.2.0-blue)
![status](https://img.shields.io/badge/status-pilot--proven-brightgreen)
![effort](https://img.shields.io/badge/effort-low%E2%80%A6max%20(5%20tiers)-green)
![telemetry](https://img.shields.io/badge/telemetry-100%25%20local-green)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

> Spend the reasoning each subtask deserves — no more, no less. effortmining classifies every subtask and dispatches it to the cheapest reasoning-effort tier a blind grader still accepts.

Claude Code lets you pin a subagent's reasoning effort (`low` through `max`), and effort is roughly proportional to token burn. But nothing decides *how much* effort a spawned subagent actually needs: a subagent inherits the session's effort by default, so a one-line lookup and a multi-file reasoning task spawned in the same session burn the *same* effort. effortmining fills that gap: a shipped, benchmark-calibrated, per-subagent effort layer.

## Wait — what is this?

| effortmining **is** | effortmining **is not** |
|---|---|
| A per-subagent effort **calibration layer**: classify a subtask, dispatch it at the tier proven cheapest-sufficient for its class | A new model or a fine-tune. It operates Anthropic's shipped `effort` knob as a black box |
| A **shipped Claude Code plugin** — skills, tier-pinned agents, hooks, and a deterministic benchmark harness | A per-*prompt* oracle. The unit of calibration is the task *class*, not the individual prompt |
| **Honest about provenance**: the science (Snell, Ares) and the knob (Anthropic) already exist; this is the productized per-subagent layer | The first to think of difficulty-adaptive compute. It is the first to *ship* it per-subagent for a production harness |
| **Measured**: a pre-registered A/B benchmark fits the table from real pass/token data | Vibes. Numbers come from `bench/effort.py`, not assertion (pilot complete, 2026-07-06) |

## The mechanism

```
          your request
               │
     ┌─────────▼──────────┐
     │  /effortmine       │   1. decompose into subtasks
     │  (orchestrator)    │   2. classify each: T1 -> T4
     └─────────┬──────────┘
               │  3. look up the class
     ┌─────────▼──────────┐
     │  calibration.json  │   cheapest tier per class
     │  (fitted table)    │      (fitted from the pilot benchmark;
     └─────────┬──────────┘       version 1, 2026-07-06)
               │  4. tier -> agent
   ┌───────────┼───────────────────────────┐
   ▼           ▼             ▼               ▼
 miner-low  miner-medium  miner-high   …  miner-max
 (effort:   (effort:      (effort:         (effort:
  low)       medium)       high)            max)
   │           │             │               │
   └───────────┴──────┬──────┴───────────────┘
                      ▼
             raw result  ->  blind effort-grader (when non-deterministic)
                      │
                      ▼
             graded bench receipts  ->  calibrate  ->  updated table
             (dispatch-log.jsonl is collected today; folding it
              into the refit is roadmap, not yet a shipped loop)
```

**The trick:** Claude Code's Agent/Task tool has **no per-spawn effort parameter**. You can override a subagent's `model` at the call site, but not its effort (verified against the installed CLI and the docs — see `docs/research/01-mechanism-investigation.md` and `01b-docs-verification.md`). The only place a subagent's effort can be set is its *definition frontmatter*. So effortmining ships one worker per tier — `miner-low` through `miner-max`, byte-identical except for `effort:` — and selecting a tier means dispatching to the matching agent. That indirection is the whole mechanism; there is no hidden API.

## Honest claims

- **The knob is real and shipped.** Anthropic ships per-subagent `effort:` frontmatter (`low/medium/high/xhigh/max`) that overrides session effort. effortmining uses exactly this. It invents no capability.
- **Auto-calibration is an open, recurring request — not a shipped feature.** Configurable/automatic per-subagent effort is asked for across at least three harnesses: Claude Code [#43083](https://github.com/anthropics/claude-code/issues/43083) (open), [#37783](https://github.com/anthropics/claude-code/issues/37783) (closed as duplicate), and #25669; OpenAI Codex #8649; OpenCode #21483. Today only *model* is configurable per subagent; effort is not.
- **The closest research is Ares — per-step, unshipped.** *Ares: Adaptive Reasoning Effort Selection for Efficient LLM Agents* (Yang et al., arXiv 2603.07915, Mar 2026) trains an outcome-labeled router that picks effort **per decision-step within one agent's loop** (up to −52.7% tokens). effortmining differs on three axes: granularity (**per-subagent role**, not per-step), productization (**a shipped plugin** operating the vendor's black-box knob, not a fine-tuned router), and method (**offline A/B benchmark calibration**, not an online per-step model). See `docs/research/02-literature-review.md`.
- **The economics are large.** Multi-agent systems use ~15x the tokens of chat, and token usage explains ~80% of performance variance (Anthropic). Calibrating a handful of recurring subagent roles captures most of the waste.

## Measured results (pilot, 2026-07-06)

The pre-registered pilot ran **12 tasks x 5 effort tiers x 3 reps = 180 runs** on `claude-opus-4-8`: 0 API errors, 0 effort-fidelity violations, 175/180 pass (5 `wrong_answer`, 0 `parse_fail`). It fit the `version: 1` calibration table the plugin now dispatches from — provenance (model, suite, fitted-date, run count) stamped in `calibration.json`. Full report: `bench/RESULTS.md`; methodology pre-registered in `docs/research/04-benchmark-methodology.md`.

> _Headline claim (pre-registered RQ3) — **HELD**:_ a class-calibrated effort policy uses **64.7% fewer output tokens** (bootstrap 95% CI [60.9, 67.7]) than the status-quo inheritance policy (every subagent at `xhigh`), at **equal** aggregate pass rate (1.000 vs 1.000). It also beat the model-default `uniform-high` by **20.5%** fewer tokens [12.3, 27.8], and out-scored the `uniform-low` heuristic by **+8.3 pp** aggregate pass (1.000 vs 0.917) — so it is **un-dominated** on the pre-registered Pareto test. This was a real test that could have failed; a null or negative result would have shipped as-is.

**Per-class calibration (v1).** Pass rates pool 3 tasks x 3 reps = 9 trials per (class, tier). The recommended tier is the *cheapest* one non-inferior to that class's empirical quality ceiling (margin δ = 10 pp).

| class | low | medium | high | xhigh | max | recommended | median out-tok @ rec |
|---|---|---|---|---|---|---|---|
| T1-mechanical | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 | **low** | 33 |
| T2-simple-transform | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 | **low** | 121 |
| T3-moderate-reasoning | 6/9 | 7/9 | 9/9 | 9/9 | 9/9 | **high** | 157 |
| T4-hard-reasoning | 9/9 | 9/9 | 9/9 | 9/9 | 9/9 | **low** † | 141 |

**What each tier costs** — median output tokens pooled across the suite: low **101** → medium **101** → high **158** → xhigh **295** → max **696**. The top tier burns ≈ **6.9x** the bottom tier for the same work.

**Overthinking is real (H3, confirmed in all four classes) — as saturation, not regression.** `max` spends strictly more tokens than `xhigh` with **zero** pass-rate gain in every class (it never *lost* quality in the pilot; it bought nothing), so the non-inferiority reference is each class's empirical ceiling tier, never mechanically `max` — which is why no class is calibrated to `max`.

**Honest caveats — this is a pilot.** n = 3 reps/cell, so per-class confidence is **low** by design: the pre-registered Wilson/bootstrap intervals are wide, and "non-inferior" means *no evidence of >10 pp degradation*, not proof of parity. **† T4's three tasks were flagged by the pre-registered misclassification check** (all pass at `low` — too easy for Opus 4.8), so T4's `low` recommendation reflects the *task-suite difficulty ceiling*, not a claim that hard reasoning needs no effort; harder T4 tasks are queued as future work. **T3 is the class with the real quality gradient**: `low` fails a third of the time (6/9) while `high` is the sweet spot (157 median tokens for 9/9, vs `max`'s 648 for the same 9/9). Single model, self-contained prompt-only tasks, one machine — re-fit per model.

Reproduce it once installed: `/effort-bench validate` then `/effort-bench run`.

## Install

**From the plugin marketplace:**

```
claude plugin marketplace add nagisanzenin/effortmining
claude plugin install effortmining@effortmining
```

**Manually (clone plus local marketplace):**

```
git clone https://github.com/nagisanzenin/effortmining
claude plugin marketplace add ./effortmining
claude plugin install effortmining@effortmining
```

Then, in a session: `/effortmine <your multi-part request>` to dispatch at calibrated effort, or `/effort-bench` to drive the benchmark. Requires Python 3 (stdlib only) for the benchmark harness and hooks.

## Repo map

```
effortmining/
├── .claude-plugin/
│   ├── plugin.json           # manifest (single source of the version)
│   └── marketplace.json      # marketplace entry
├── agents/
│   ├── miner-low.md          # ┐
│   ├── miner-medium.md       # │ five tier-pinned delegate workers,
│   ├── miner-high.md         # │ identical except frontmatter effort:
│   ├── miner-xhigh.md        # │
│   ├── miner-max.md          # ┘
│   └── effort-grader.md      # blind grader (medium, tier-blind payload)
├── skills/
│   ├── effortmine/SKILL.md   # classify -> calibrate -> dispatch orchestrator
│   └── effort-bench/SKILL.md # thin driver over the benchmark harness
├── hooks/
│   ├── hooks.json            # SessionStart + PostToolUse(Task) wiring
│   ├── session-start.sh      # silent-unless-useful ambient line
│   └── log-dispatch.sh       # fail-open dispatch telemetry logger
├── bench/                    # deterministic harness + task suite (separate owner)
│   ├── effort.py             # stdlib CLI: validate|run|grade|analyze|report|calibrate
│   ├── tasks/                # 12 pilot tasks, 4 classes x 3
│   └── state/                # calibration.json, dispatch-log.jsonl (raw runs gitignored)
└── docs/
    ├── architecture.md       # components + data flow + "why tiered agents"
    └── research/             # mechanism, docs-verification, literature, patterns, methodology
```

## How it works (the lineage)

effortmining is the third repo in a lineage by the same author: [engram](https://github.com/nagisanzenin/engram) (a learning plugin — deterministic scheduler, blind assessor, guarded refit) and [claude-code-production-grade-plugin](https://github.com/nagisanzenin/claude-code-production-grade-plugin) (a build orchestrator — mode-scaled effort, oracle loops, receipt telemetry). It transposes their shared discipline — *let a deterministic core decide, and never let the producer of work grade it* — from learning and software verification to **effort calibration**: pick the cheapest agent configuration that still passes a blind grader. Patterns and provenance are documented in `docs/research/03-pattern-mining.md`.

## License

MIT.
