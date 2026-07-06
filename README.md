# effortmining

![version](https://img.shields.io/badge/version-0.1.0-blue)
![status](https://img.shields.io/badge/status-pre--pilot%20scaffold-orange)
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
| **Measured**: a pre-registered A/B benchmark fits the table from real pass/token data | Vibes. Numbers come from `bench/effort.py`, not assertion (pilot pending) |

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
     │  (fitted table)    │      (fitted from the benchmark;
     └─────────┬──────────┘       ships with unproven defaults)
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
             dispatch-log.jsonl  ->  calibrate  ->  updated table
```

**The trick:** Claude Code's Agent/Task tool has **no per-spawn effort parameter**. You can override a subagent's `model` at the call site, but not its effort (verified against the installed CLI and the docs — see `docs/research/01-mechanism-investigation.md` and `01b-docs-verification.md`). The only place a subagent's effort can be set is its *definition frontmatter*. So effortmining ships one worker per tier — `miner-low` through `miner-max`, byte-identical except for `effort:` — and selecting a tier means dispatching to the matching agent. That indirection is the whole mechanism; there is no hidden API.

## Honest claims

- **The knob is real and shipped.** Anthropic ships per-subagent `effort:` frontmatter (`low/medium/high/xhigh/max`) that overrides session effort. effortmining uses exactly this. It invents no capability.
- **Auto-calibration is an open, recurring request — not a shipped feature.** Configurable/automatic per-subagent effort is asked for across at least three harnesses: Claude Code [#43083](https://github.com/anthropics/claude-code/issues/43083) (open), [#37783](https://github.com/anthropics/claude-code/issues/37783) (closed as duplicate), and #25669; OpenAI Codex #8649; OpenCode #21483. Today only *model* is configurable per subagent; effort is not.
- **The closest research is Ares — per-step, unshipped.** *Ares: Adaptive Reasoning Effort Selection for Efficient LLM Agents* (Yang et al., arXiv 2603.07915, Mar 2026) trains an outcome-labeled router that picks effort **per decision-step within one agent's loop** (up to −52.7% tokens). effortmining differs on three axes: granularity (**per-subagent role**, not per-step), productization (**a shipped plugin** operating the vendor's black-box knob, not a fine-tuned router), and method (**offline A/B benchmark calibration**, not an online per-step model). See `docs/research/02-literature-review.md`.
- **The economics are large.** Multi-agent systems use ~15x the tokens of chat, and token usage explains ~80% of performance variance (Anthropic). Calibrating a handful of recurring subagent roles captures most of the waste.

## Numbers — pending pilot benchmark

This scaffold ships **no measured results yet**. The calibration table it dispatches from is an a-priori difficulty-to-effort ladder (`version: 0`, marked unproven). The pre-registered pilot benchmark — 12 tasks x 5 effort tiers x 3 reps = 180 runs on `claude-opus-4-8` — fills in the real pass-rate and token curves and fits a `version >= 1` table.

> _Headline claim to be tested (may fail — that is a real outcome):_ a class-calibrated effort policy uses **X% fewer output tokens** (95% CI) than the status-quo inheritance policy (every subagent at `xhigh`), while aggregate pass rate stays non-inferior (difference CI lower bound >= −5pp).

Run it yourself once installed: `/effort-bench validate` then `/effort-bench run`. Methodology is pre-registered in `docs/research/04-benchmark-methodology.md`.

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
