# The benchmark story — how the numbers were measured, in order

This is the full chronological record of the three measurement campaigns (pilot, v2, refit),
kept exactly as they were reported — including the pre-registered tests that failed.
The short version lives in the README; the machine-generated reports are
[`bench/RESULTS.md`](../bench/RESULTS.md) and [`bench/RESULTS-v2.md`](../bench/RESULTS-v2.md);
the pre-registrations are `docs/research/04-benchmark-methodology.md` (pilot) and
`docs/research/05-benchmark-v2-methodology.md` (v2 + Amendment A).

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


Reproduce any of it once installed: `/effort-bench validate` then `/effort-bench run`
(or `python3 bench/effort.py --help` in a clone).
