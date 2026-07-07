# effortmining

![version](https://img.shields.io/badge/version-0.5.0-blue)
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

> _Headline claim (pre-registered RQ3) — **HELD**:_ a class-calibrated effort policy uses **64.7% fewer output tokens** (bootstrap 95% CI [60.8, 67.8]) than the status-quo inheritance policy (every subagent at `xhigh`), at **equal** aggregate pass rate (1.000 vs 1.000). It also beat the model-default `uniform-high` by **20.5%** fewer tokens [12.3, 27.7], and out-scored the `uniform-low` heuristic by **+8.3 pp** aggregate pass (1.000 vs 0.917) — so it is **un-dominated** on the pre-registered Pareto test. This was a real test that could have failed; a null or negative result would have shipped as-is.

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

## Measured results v2 (real work: research, coding, composites — 2026-07-07)

A second pre-registered suite (`docs/research/05-benchmark-v2-methodology.md`) tested the user-facing question: does calibrated dispatch regress quality on **high-value work** — document-grounded research (8k-token invented-fact corpora), real coding (hidden adversarial pytest), and composite multi-part jobs run end-to-end under three policies? 225 additional real runs on `claude-opus-4-8`, zero API errors. Grader reliability gate: the blind grader agreed with itself **12/12 (100%)** on double-graded artifacts (H6, gate ≥90%).

- **Isolated research & coding saturate at `low`** (90/90 pass at every tier — H4 not confirmed): even interval-tree implementations against 24 hidden adversarial asserts and cross-document synthesis are quality-flat across tiers on Opus 4.8. The cost is not flat: the token ladder still climbs ~7x to `max`.
- **The composite A/B produced the project's first pre-registered NO-WIN — kept, not buried.** The as-fitted table (everything → `low`) scored 42/45 vs inheritance's 45/45: below the δ=5pp quality bar, so `calibrated_wins=false`. All three failures are one subtask.
- **That subtask is the find of the suite.** `X1.3` — name the single root-cause *job* from a stack of postmortems — is the first genuinely tier-discriminating research task: `low` 0/3, `high` 1/6, **`xhigh` 3/3**. Hard research exists; our isolated R-tasks just weren't it. The pre-registered misclassification check caught this, and `calibration.json` now ships machine-readable warnings on every class whose fit rests on saturated tasks (R-research, C-coding, T4).
- **The caveat-aware policy** — honoring the shipped warnings (hard research → `xhigh`, everything else per table) — scores **45/45 (100%)** on the composite workload at **equal-or-lower cost than inheritance** (across two independent draws: −15.6% and −0.1% tokens; composite token totals are noisy at n=3). This is exactly the policy the ambient hook injects: the fitted table *plus its own warnings*. The reliable double-digit savings live in isolated dispatch (v1's −64.7% with CIs), not in small composites.

### The refit (Amendment A, 2026-07-07 — the calibration loop proven end-to-end)

Six deliberately harder fitting tasks (X1.3-recipe research chains; coding with interacting corner rules, interlocking bugs, and a formal-invariant spec — every assert suite proven to fail 12 plausible-naive implementations) were added pre-registered, and the loop closed exactly as designed:

- **C-coding earned the project's first data-driven tier move: `low` → `medium`.** `C6` (semilattice-merge invariant) breaks `low` (16/18 pooled; crashes on tombstone edge cases) while `medium` sits at the 18/18 ceiling — and `max` burns ~6.9x `medium`'s tokens for nothing, again. The guarded refit stepped once, the ambient policy updated itself, and C-coding **shed its fit-blindness warning** because its fit now includes proven-hard tasks.
- **R-research stayed `low` — with its warning intact — because X1.3's difficulty is *contextual*.** Even X1.3-recipe questions saturate at `low` when asked in isolation (108/108 R-cells pass); the same recipe embedded in a 5-part job defeats `low`. Isolated fitting cannot price contextual difficulty; the warning + route-hard-to-`xhigh` mechanism is the honest answer, not a bug.
- **The pre-registered composite verdict stayed NO-WIN under the refitted table too** (44/45 vs 45/45; the single failure is X1.3 at `low`, 1 of 3 reps) — reported as-is. At composite sample sizes the non-inferiority interval guard is unforgiving, and 5-small-subtask jobs carry little reclaimable token waste versus inheritance.
- **A new low-effort failure mode, on the record:** X1.3's failing run didn't misread a distractor — it **fabricated** a plausible ticket ID that appears nowhere in its documents. Low effort doesn't just skim; it invents. (The fabricated ID coincidentally matches another task's independently-invented key — flagged in threats as an identifier-pattern guessability risk for future task authors.)

**Honest reading of v1+v2+refit together:** effort saturates on most self-contained work (savings are real and large), genuinely tier-demanding tasks exist but are rare and specific (T3 diagnosis, C6-grade invariants, X1.3-grade contextual research), and class-level calibration is exactly as sharp as its fitting tasks — the refit loop sharpens it, and the warnings carry what fitting cannot. Full v2 report: `bench/RESULTS-v2.md`.

**Scope — all five API effort levels were swept; the two pseudo-levels are out by construction.** `low/medium/high/xhigh/max` all ran (that is where the `uniform_max` row in `bench/RESULTS.md` §5 comes from — 9,520 tokens, 6.4x the calibrated policy at identical quality). `auto` is not a level — it resolves to the model's static default, i.e. the `high` column on Opus 4.8. `ultracode` is deliberately not benchmarked: it is a Claude Code setting, not an API effort level — it sends `xhigh` to the model and additionally changes *orchestration* (dynamic multi-agent workflows), is not requestable via `--effort`/settings/env, and comparing a whole workflow against a single tier-pinned invocation would not be a like-for-like test of per-invocation effort (see `docs/research/01b-docs-verification.md`).

Reproduce it once installed: `/effort-bench validate` then `/effort-bench run`.

## Using it — ambient by default, precise on demand

**Ambient (no command, just install it).** A SessionStart hook injects a two-line dispatch policy into every session, derived live from the fitted calibration table. From then on, whenever Claude delegates a subtask to a subagent on its own, it is nudged to pick the tier-pinned worker for that subtask's difficulty class (`miner-low` for mechanical work, `miner-high` for diagnosis/logic, and so on) instead of a default agent at inherited effort. No slash command required; a refit automatically updates the injected policy. An explicit effort request from you always overrides it.

**Precise (`/effortmine <request>`).** The full orchestrator: decomposes your request into subtasks, classifies each against the T1–T4 rubric, reads the calibration table, dispatches every subtask at its calibrated tier, and logs the dispatches. Use it when you hand over a multi-part job and want the classification done deliberately rather than opportunistically.

**Measured (`/effort-bench`).** Re-run the benchmark yourself — Phase 0 instrument gate, the matrix, grading, analysis, report — or refit the table for a different model.

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
