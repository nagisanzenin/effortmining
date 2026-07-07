# effortmining

![version](https://img.shields.io/badge/version-0.5.2-blue)
![status](https://img.shields.io/badge/status-benchmark--proven-brightgreen)
![effort](https://img.shields.io/badge/effort-low%E2%80%A6max%20(5%20tiers)-green)
![telemetry](https://img.shields.io/badge/telemetry-100%25%20local-green)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

> Spend the reasoning each subtask deserves — no more, no less.

Claude Code has a "how hard should I think" dial with five settings (`low` → `max`), and thinking harder costs real tokens — in our measurements, **`max` produced ~7x the output tokens of `low` for identical results on most tasks**. The catch: when Claude spawns helper agents, every helper **inherits your session's dial setting**, and there is no way to set effort at spawn time. So the helper doing a one-line lookup thinks exactly as hard as the one debugging your worst code.

effortmining fixes that with a measured cheat-sheet: it classifies each subtask, looks up the cheapest effort tier *proven* sufficient for that kind of work, and dispatches to a worker pinned at that tier.

**TL;DR numbers** (~450 pre-registered runs on `claude-opus-4-8`): calibrated dispatch used **64.7% fewer output tokens** (95% CI [60.8, 67.8]) than effort inheritance **at an identical pass rate** · `max` never beat `xhigh` anywhere · 2 pre-registered tests failed and are published below, not buried.

## Quickstart

```
claude plugin marketplace add nagisanzenin/effortmining
claude plugin install effortmining@effortmining
```

Requires Python 3 (stdlib only). Then start a new session. You'll see two lines:

```
[effortmining] calibration table 6 cells, fitted 2026-07-07 · /effortmine to dispatch calibrated
[effortmining] ambient dispatch policy: ... T1-mechanical->miner-low · T3-moderate-reasoning->miner-high ...
```

That second line is the whole ambient feature: **from now on, when Claude delegates work to subagents, it picks the right-effort worker on its own.** Nothing else to do. Watch the task line when it delegates — you'll see `miner-low` doing your grunt work instead of a full-effort agent.

Want it explicit? Hand a multi-part job to the orchestrator:

```
/effortmine (1) extract the domains from these emails into a sorted list: a@x.io, B@y.com, b@y.com
(2) this function should return the second-largest unique number but breaks on some inputs — find and fix the bug:
def second_largest(xs): s = sorted(set(xs)); return s[-2]
```

It classifies (1) as mechanical → `miner-low`, (2) as diagnosis → `miner-high`, dispatches both, and tells you why. Your explicit effort requests always override the table.

## How it works

1. **The trick.** Claude Code's Agent tool has no per-spawn effort parameter (you can override a subagent's `model`, not its effort — verified against the CLI binary and docs, see `docs/research/`). The *only* place effort can be set is an agent's definition file. So effortmining ships **five workers that are byte-identical except one frontmatter line** (`effort: low` … `effort: max`). Choosing a tier = choosing which worker to dispatch. That indirection is the entire mechanism — no hidden API.
2. **The cheat-sheet.** `calibration.json` maps task classes to the cheapest tier that passed a benchmark at that class's quality ceiling. It ships fitted from real runs, carries its own provenance (model, run counts, date), and — where its fitting tasks proved too easy — carries **machine-readable warnings** that route genuinely hard work up to `xhigh`.
3. **The loop.** A SessionStart hook injects the table (with warnings) as a two-line policy into every session; a fail-open PostToolUse hook logs every dispatch locally; `effort.py calibrate` refits the table from graded benchmark receipts under guarded rules (min-sample gates, single-step moves, clamps). Refit the table and the injected policy updates itself.

```
 request → classify (T1..T4, R, C) → calibration.json → miner-<tier> → result
                                          ↑                    │
                             guarded refit ← graded benchmark receipts
```

## What the data says

> _Headline (pre-registered, could have failed) — **HELD**:_ a class-calibrated effort policy used **64.7% fewer output tokens** (95% CI [60.8, 67.8]) than the status-quo inheritance policy (every subagent at `xhigh`), at **equal** aggregate pass rate (1.000 vs 1.000), and was un-dominated against uniform-`high` and uniform-`low` too.

The shipped 6-class table and the evidence behind each row:

| class | the work | evidence (pass rate) | dispatches to |
|---|---|---|---|
| T1-mechanical | extraction, reformatting | 9/9 at `low` | `miner-low` |
| T2-simple-transform | small well-specified transforms | 9/9 at `low` | `miner-low` |
| T3-moderate-reasoning | diagnosis, logic, tracing | 6/9 at `low` → 9/9 at `high` | `miner-high` |
| T4-hard-reasoning | adversarial multi-step | 9/9 at `low` † | `miner-low` † |
| R-research | cross-document synthesis | 18/18 at `low` isolated † | `miner-low` † |
| C-coding | implement/fix vs hidden tests | 16/18 at `low` → 18/18 at `medium` (refit) | `miner-medium` |

† ships with a **fit-blindness warning**: these fitting tasks saturated (too easy for Opus 4.8), so the ambient policy routes *genuinely hard* instances in these classes to `miner-xhigh` instead. That caveat is measured, not decorative — see finding 3.

**Three findings worth your time:**

1. **Cost climbs even when quality doesn't.** Median output tokens per tier across the suite: `low` 101 → `high` 158 → `xhigh` 295 → `max` 696. `max` never improved a single pass rate over `xhigh` — it saturates, it doesn't regress.
2. **Genuinely tier-demanding tasks exist but are rare and specific.** A diagnosis class (T3), a formal-invariant coding task (breaks `low`, fixed by the refit moving C-coding to `medium`), and one research question that only `xhigh` reliably solves — and only when embedded in a bigger job (difficulty turned out to be *contextual*: the same question passes at `low` in isolation).
3. **Low effort doesn't just skim — it fabricates.** In the composite test's one persistent failure, the model at `low` invented a plausible ticket ID that appears nowhere in its documents. This is why the warnings and the `xhigh` route exist.

Two pre-registered composite tests returned **no-win verdicts and are published as such** — the full chronological record (pilot → v2 → refit, including both failures and what they taught) is in [`docs/BENCHMARK-STORY.md`](docs/BENCHMARK-STORY.md); machine-generated reports in [`bench/RESULTS.md`](bench/RESULTS.md) and [`bench/RESULTS-v2.md`](bench/RESULTS-v2.md).

## Honest claims

- **The knob is Anthropic's, shipped.** Per-subagent `effort:` frontmatter exists; effortmining invents no capability — it operates the knob from measurements.
- **Auto-calibration is an open, recurring request** — Claude Code [#43083](https://github.com/anthropics/claude-code/issues/43083) (open), #37783, #25669; OpenAI Codex #8649; OpenCode #21483. Only *model* is configurable per spawn today; effort is not.
- **The closest research is Ares** (arXiv 2603.07915) — per-step effort routing, unshipped. effortmining differs in granularity (per subagent role), method (offline pre-registered A/B), and the fact that you can install it.
- **The economics are real:** multi-agent systems use ~15x chat tokens and token spend explains ~80% of performance variance (Anthropic's own engineering data). A handful of recurring subagent roles carries most of the waste.

## Using it

- **Ambient (default):** install and forget — the SessionStart policy nudges every delegation to the calibrated worker. Explicit user effort requests always win.
- **Precise:** `/effortmine <multi-part request>` — deliberate decompose → classify → dispatch, with the reasoning shown.
- **Measured:** `/effort-bench` — re-run Phase 0 + the matrix on your own account, or refit for a different model (`python3 bench/effort.py calibrate`). The whole pipeline is deterministic and resumable.

## Caveats, honestly

n = 3 reps per cell (confidence is labeled `low` by design; intervals are wide); one model (`claude-opus-4-8` — re-fit per model, it's one command); self-contained tasks that may be easier than your real work — the misclassification checks flag exactly where that's true; `auto` and `ultracode` are out of scope by construction (`auto` = the model default = the `high` column; `ultracode` is an orchestration mode that sends `xhigh`, not an API effort level).

## Repo map

```
effortmining/
├── .claude-plugin/            # manifest + marketplace entry
├── agents/                    # miner-low..max (byte-identical except effort:) + blind effort-grader
├── skills/                    # effortmine (calibrated dispatch) · effort-bench (harness driver)
├── hooks/                     # SessionStart policy injection · fail-open dispatch logger
├── bench/                     # effort.py (stdlib harness) · tasks/ + tasks-v2/ · state/calibration.json · RESULTS*.md
└── docs/                      # architecture · BENCHMARK-STORY · research/ (mechanism, literature, methodology)
```

## More from the same workshop

effortmining is the third repo in a family with one shared discipline: *let a deterministic core decide, and never let the producer of work grade it.*

- **[engram](https://github.com/nagisanzenin/engram)** — an evidence-based learning engine: first-principles curricula, generation-first tutoring, blind-graded free recall, FSRS scheduling. This repo's blind grader and guarded refit are engram patterns, transposed.
- **[claude-code-production-grade-plugin](https://github.com/nagisanzenin/claude-code-production-grade-plugin)** — turns "build me X" into a gated multi-agent pipeline with receipts for every phase. effortmining was built *with* it — the receipts are in this repo.

Pattern provenance: `docs/research/03-pattern-mining.md`.

## License

MIT.
