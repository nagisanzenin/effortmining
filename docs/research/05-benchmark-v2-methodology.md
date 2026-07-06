# 05 — Benchmark v2 Methodology & Task Suite (No-Regression on Real Work)

**Task V1 · Data Scientist · effortmining**
**Status:** design complete, **pre-registered before any v2 data is collected.** Extends and inherits the v1 protocol (`04-benchmark-methodology.md`); only the v2-specific deltas are restated here.
**Date:** 2026-07-07 · **Benchmark model (binding):** `claude-opus-4-8` · **Grader effort (binding):** `medium`

---

## 0. What this document is (and the requirement it must satisfy)

The v1 pilot (12 synthetic micro-tasks, 180 runs) did its job: it proved the *mechanism* — a class-calibrated effort policy used **64.7% fewer output tokens than inheritance@`xhigh`** at no measured quality loss. But it also exposed a validity gap that v2 exists to close. In v1, **11 of 12 tasks passed at 100% across every tier** (`bench/RESULTS.md` §2); only `T3c` showed a real effort→quality gradient (0% → 33% → 100% at low/medium/high). The suite was too easy to *regress*, so "no quality loss" was demonstrated only where there was almost no quality to lose.

v2 exists to answer the user's requirement, quoted verbatim:

> "we must prove that this plugin not only saves cost but does not regress in quality in those works."

— where **"those works"** are high-value real jobs: **deep research, real coding, and composite multi-part jobs**. This document pre-registers the v2 suite (9 tasks, `bench/tasks-v2/`), its grading, its experimental matrix, and the decision rules — all fixed *before* any generation run, so the analysis is confirmatory, not exploratory. Oracle integrity is proven by `bench/tools/validate_oracles_v2.py` (**114/114 checks green, exit 0**) and must be re-run in CI before any v2 sweep.

**What v2 keeps from v1 (inherited, not re-derived).** The instrument facts (§0 of doc 04), Phase-0 effort-fidelity gate (04 §4), the primary metrics (pass rate; output tokens incl. thinking), the uncertainty machinery (Wilson / Newcombe / stratified bootstrap), the class-pooling non-inferiority rule (04 §5.4: **δ = 0.10**, ceiling-referenced, **n = 9 trials/cell** at n=3 reps), the failure taxonomy (04 §6), the guarded-refit rule (04 §7.2), and the run-order/nonce/politeness controls (04 §3.3). v2 changes only the **tasks**, adds a **blind-grader path** and a **composite-policy arm test**, and adds three hypotheses (H4–H6).

---

## 1. The three task classes

| class | id(s) | what it proves | checker |
|---|---|---|---|
| **R — deep research** | R1, R2, R3 | quality holds on document-grounded cross-source synthesis over a realistic volume (8k–20k tokens of provided documents), not lookup trivia | R1 `exact`; R2, R3 `blind-grader` |
| **C — real coding** | C1, C2, C3 | quality holds on genuine coding difficulty (spec-implementation, bug-hunting, refactor-under-constraint) against **hidden adversarial** tests, replacing v1's too-easy T4 | all `pytest-asserts` |
| **X — composite jobs** | X1, X2, X3 | a **per-subtask calibrated policy** does not regress aggregate quality on realistic multi-part jobs while cutting tokens | `composite` (5 deterministically-checkable subtasks each) |

Every document, product name, version, date, figure, paper, and incident in the R and X suites is **invented** so no answer can be recalled from training data (contamination control, inherited from 04 §2.2). R documents are deliberately long and interleave authoritative and secondary sources, so the load-bearing facts are **buried in realistic volume** and skimming to the wrong source is a live failure mode — the opposite of v1's micro-tasks.

### 1.1 The suite (authored, validated, shipped)

| id | class | checker | one-line description |
|---|---|---|---|
| **R1** | R-research | `exact` | 8 conflicting Quasar-Gateway docs (changelog/migration/config-ref/runbook vs wiki/blog/KB/forum); output an 8-field key of correct-per-primary-source values + one source-attribution field. Traps: wiki says pool=128 & "removed 4.4"; blog says 250; KB says 3000. |
| **R2** | R-research | `blind-grader` | 5 docs (4 invented papers + a benchmark spec) that subtly disagree on 4-bit KV-cache quantization; synthesize the A-vs-B contradiction and Paper C's task-dependence reconciliation, excluding an off-topic distractor paper. Rubric /10, pass ≥ 7. |
| **R3** | R-research | `blind-grader` | 6 docs (3 postmortems w/ different local root causes + change-log + infra overview + war-room transcript) hiding one common root cause (change-set CS-2288 lowered a shared pool 200→20 fleet-wide). Rubric /10, pass ≥ 7. |
| **C1** | C-coding | `pytest-asserts` | implement `IntervalSet` (half-open add/remove/contains/measure/segments) against a spec; 24 hidden adversarial asserts (boundary half-openness, adjacency coalescing, remove-splits, empty/idempotent/order-independent, floats). |
| **C2** | C-coding | `pytest-asserts` | bug-hunt a ~120-line `usage_report` module with exactly 3 planted subtle bugs (pagination off-by-one; timezone-naive comparison; mutation-during-iteration); 14 hidden asserts exercising all three. |
| **C3** | C-coding | `pytest-asserts` | refactor a module-global accumulator into an instance-encapsulated `Metrics` class; 11 hidden asserts check behaviour preservation, two-instance isolation, and a no-module-level-mutable-state introspection constraint. |
| **X1** | X-composite | `composite` | incident triage: 5 subtasks (extract error signature / count affected users from JSON / identify root-cause job / fix a backoff fn / emit a status line in exact format). |
| **X2** | X-composite | `composite` | release readiness: 5 subtasks (version lookup / compute timeout budget / find the breaking key / implement `merge_config` / emit a go-no-go line in exact format). |
| **X3** | X-composite | `composite` | pipeline debug: 5 subtasks (extract failing record id / count negative amounts / find the changed schema field / fix `summarize_amounts` / emit a summary line in exact format). |

---

## 2. Grading strategy per class

**Design preference (inherited, 04 §10):** executable oracle > adversarial/blind > self-check. v2 uses deterministic checkers everywhere it can (R1 exact; all of C; every X subtask) and the blind grader only for the two synthesis tasks (R2, R3) that are inherently non-deterministic. Checker mix: **1 exact, 2 blind-grader, 3 pytest-asserts, 3 composite.**

**R1 — exact.** The whole deliverable is a fixed 8-line answer key; the harness canonicalises (`strip_outer_ws;rstrip_each_line`) and compares `==` to `expected`. A single wrong field fails the task, so grabbing a trap value (128/250/3000) or mis-counting renames fails deterministically. `validate_oracles_v2.py` re-derives all eight fields from the authoritative documents and confirms no drift.

**C1/C2/C3 — hidden adversarial pytest.** The harness extracts the last fenced `python` block, appends the task's hidden `asserts`, and runs `python3 -I` in the sandbox (04 §9.4). The asserts are **not shown to the model** and are calibrated so a low-effort happy-path solution plausibly fails the traps. Integrity is proven two ways in the validator: an independent reference solution **passes** every assert, and a wrong/buggy/stateful version **fails** (for C2/C3 the shipped broken code is extracted from the prompt and shown to fail its own asserts).

**X — composite (per-subtask deterministic).** Each of the 5 subtasks is an independent run with its own `exact` or `pytest-asserts` checker. The task-level `checker.type` is `"composite"` (an aggregator marker; see §8 coordination note) with `aggregate: "mean_subtask_pass"`. Aggregate quality for a job/arm = fraction of its 5 subtasks that pass.

### 2.1 Blind-grader protocol (R2, R3) — pre-registered and binding

The grader is the existing contract `agents/effort-grader.md`. The following is fixed before any grading run:

- **Blind payload.** The grader receives only `{task_id, prompt (incl. the provided documents), rubric, artifact}`. There is **no `tier`, `agent`, `effort`, `model`, or `cost` field** and never will be — blindness is enforced by the shape of the input, so a grade cannot be biased toward a cheap or expensive tier.
- **Fixed grader effort = `medium`.** The grader runs at one pinned effort tier for every artifact, so grader effort is not a confound and cannot co-vary with the miner tier being judged.
- **Rubric = the task's `checker.rubric`.** Numbered, point-weighted criteria (each worth stated points) with an embedded, pre-registered pass rule (`PASSES iff total >= 7/10`). The criteria are anchored to specific, checkable facts (the exact figures / IDs / mechanisms present in the documents), which bounds grader subjectivity: most points turn on "did they state −9.2% for Paper A" rather than on taste. `validate_oracles_v2.py` confirms the points sum to `max_score`, the threshold is consistent, and every anchor is grounded in the documents.
- **Stance.** Skeptic-first (enumerate what is missing per criterion before crediting it); meaning over wording; round down when torn; a confidently-stated wrong claim is a fail. Strict-JSON verdict only.
- **Scoring output.** The grader scores each criterion (full / half / zero of its points), sums to a total in `[0, max_score]`, and the harness computes `pass = (total >= pass_threshold)`.
- **Verdicts are FINAL (no regrade shopping).** A rubric artifact is graded once at `medium`; its verdict stands. The only permitted second pass is the H6 reproducibility check (§4), which is a *measurement of the grader*, not an appeal of a result. No task is re-graded to obtain a more favourable number.

---

## 3. Experimental matrix & scale

**Factors.** R and C are single-prompt tasks swept over the full 5-tier grid; X is a policy test swept over 3 arms.

- **R + C:** 6 tasks × **5 tiers** (`low, medium, high, xhigh, max`) × **3 reps** = **90 generation runs.** Class pooling gives **n = 9 trials per (class, tier)** — identical power to the v1 pilot, so the 04 §5.4 non-inferiority rule applies unchanged.
- **X:** 3 jobs × **3 arms** × **3 reps** = **27 composite sessions**, each = **5 subtask runs** = **135 subtask runs.**
- **Grading (R2, R3 only):** 2 tasks × 5 tiers × 3 reps = **30 blind-grader calls**, once each at `medium`. H6 adds a one-time double-grade of a fixed 12-artifact subset (**+12 calls**).

**Total: 225 generation runs + ~42 grader calls.** Run order is seeded-shuffled and nonce-wrapped across the whole set (04 §3.3); every run records requested **and** effective effort and is discarded on mismatch (04 §4.6).

### 3.1 The three X arms (pre-registered)

Each X subtask carries a `class` ∈ {`mechanical`, `transform`, `research-lite`, `coding`, `format`}. An arm assigns a tier to each subtask:

- **`P_calibrated`** — each subtask at its class's recommended tier. Pre-registered mapping: `mechanical → low`, `transform → low`, `format → low` (the v1-saturated cheap classes, T1/T2 analogues), `research-lite → ` the R-research recommended tier from this run's RQ2 analysis, `coding → ` the C-coding recommended tier from this run's RQ2 analysis. The two data-dependent tiers are fixed by the R/C matrix *before* the X arms are composed; they are not chosen post hoc.
- **`P_inherit_xhigh`** — all 5 subtasks at `xhigh` (the status quo: a power-user session at `xhigh`, every spawned subagent inherits it).
- **`P_uniform_high`** — all 5 subtasks at `high` (the model default).

The calibrated arm is the plugin's behaviour; the other two are the baselines it must beat on tokens without losing quality.

---

## 4. Metrics, statistics & hypotheses (pre-registered)

**Inherited unchanged from 04 §5:** pass rate per cell (parse_fail/wrong_answer/timeout = fail; api_error retried then excluded); output tokens (incl. thinking) as the primary cost metric; Wilson 95% for rates; stratified bootstrap (10,000 resamples, within-cell) for token totals and savings; the class-pooled, ceiling-referenced non-inferiority rule with **δ = 0.10**; the overthinking-tail flag (H3); the mis-classed-task flag (pooled low-tier pass ≥ 0.80). For R and C this produces the same `calibration.json` shape as v1, now for the R-research and C-coding classes.

**New for the X policy test (RQ-X).** For each arm compute, per job and pooled: **summed output tokens** (sum over the 5 subtask runs) and **aggregate pass** (mean subtask pass). Compare arms with a **stratified bootstrap 95% CI** (resample within subtask-cells, recompute both policies per draw). Aggregate-pass non-inferiority margin **δ_agg = 0.05** (tighter, matching 04 §5.5, because the aggregate pools 5 subtasks × reps).

### 4.1 Hypotheses (falsifiable, reported confirmed/refused regardless of outcome)

- **H4 — R and C classes exhibit a real effort→quality gradient (unlike v1).** At least one of the R-research and C-coding classes shows pooled `low`-tier pass **materially below** its quality-ceiling tier (a drop **> δ = 10 pp**), i.e. `low` degrades. This is the direct fix for v1's saturation: if H4 fails (everything still passes at `low`), the v2 tasks are *still* too easy and "no regression" remains untested — a real, reportable negative outcome. *(Design intent, not a guarantee: R1's trap fields, C's hidden edge asserts, and R2/R3's buried reconciliations are built so low effort plausibly fails; whether they do is what H4 measures.)*
- **H5 — the calibrated arm dominates both X baselines.** `P_calibrated` uses **≤ the summed output tokens of both** `P_inherit_xhigh` **and** `P_uniform_high` (bootstrap CI upper bound ≤ 0 for the token difference, i.e. a real saving vs `inherit_xhigh` and no worse than `uniform_high`) at **non-inferior aggregate pass** (pass-difference CI lower bound ≥ −δ_agg = −0.05 against each baseline). This is the headline no-regression claim for composite work.
- **H6 — blind-grader verdicts are reproducible (Phase-0 gate).** Running the grader **twice on the same 12 artifacts** at fixed `medium` effort yields the **same pass/fail verdict ≥ 90%** of the time. This is a **Phase-0 hard gate**: if grader reproducibility is < 90%, the blind-grader tasks (R2, R3) are not trustworthy and are **held back** from the scored run until the rubric is tightened. It is measured before, and independently of, any calibration data.

### 4.2 Phase 0 additions (v2-specific; the rest inherited from 04 §4)

Before the matrix runs, in addition to the 04 §4 gates (flag acceptance, envelope binding, effort-modulation ≥ 2×, env sanitation, **effort-fidelity requested == effective**):

1. **H6 grader-reproducibility gate** (above): double-grade 12 fixed artifacts; require ≥ 90% verdict agreement.
2. **Composite plumbing check:** confirm the harness runs all 5 subtasks of one X job as 5 independent runs, each at the arm's per-class tier, and aggregates correctly on a dry-run job.
3. **Blind-payload check:** confirm the grader payload carries no tier/agent/effort/model field (blindness assertion) on a sample call.

---

## 5. Cost estimate (API-price-equivalent; the real currency is *runs* on the user's plan)

Assumptions (output tokens/run incl. thinking, mid estimate; input incl. system+tools+task+documents). Prices are the binding **$5/M input, $25/M output**; R/X/grader inputs are dominated by a **stable document prefix that is ~70% cache-reused** across tiers, reps, and subtasks, so effective input cost is well below the raw figure.

| component | runs | output tok (mid) | raw input tok | notes |
|---|---|---|---|---|
| R (R1 exact + R2/R3 synthesis) | 45 | ~51k | ~520k | 8k–9k doc prefix/run, ~70% cacheable |
| C (impl / bug-hunt / refactor) | 45 | ~68k | ~150k | small prompts; C2 reprints the module |
| X (3 jobs × 3 arms × 3 reps × 5 subtasks) | 135 | ~70k | ~610k | doc prefix cacheable per job |
| Blind grader (R2/R3 + H6 subset) | ~42 | ~27k | ~460k | fixed `medium`; ~11k input/call |
| **Total** | **~267** | **~216k** | **~1.74M** | |

Dollar bounds (API-equivalent): **output** ≈ 216k × $25/M ≈ **$5.4**. **Input** ≈ **$8.7** with no cache (upper bound) down to ≈ **$3.6** with ~65% cache-read at ~$0.5/M. **Total ≈ $9–$14 (mid ≈ $11)**, ± the wide variance effort adds at `max`.

| scale option | runs | est. total (API-equiv) | when |
|---|---|---|---|
| **Reduced** (R + C only, skip X) | 90 + grading | **~$5–8** | shake out harness + grader before spending on X |
| **Recommended** (full v2, n=3) | 225 + ~42 grader | **~$9–14** | the pre-registered design |
| **Extended** (undecided classes → n=5) | up to ~375 | **~$15–22** | only classes whose CIs straddle δ after n=3 |

These are estimates pending the Phase-0 latency/token measurement (04 §4.5), which replaces them with measured values before the matrix is sized for real. Actual runs consume the user's subscription, so the true budget unit is *runs*, not dollars.

---

## 6. Threats to validity (pre-registered, stated before data)

- **Synthetic documents.** All R/X documents are invented (required for contamination control) and therefore may not capture the messiness of real corpora; the *structure* (conflicting sources, buried root causes, distractors, realistic volume) is designed to be representative, but realism is a judgement call. Mitigation: documents were authored to real-world patterns (vendor changelogs, ML preprints, incident postmortems) and validated for internal consistency by `validate_oracles_v2.py`.
- **Grader subjectivity — bounded, not eliminated.** R2/R3 verdicts come from an LLM grader. The rubric anchors most points to objective, checkable facts, verdicts are FINAL at fixed `medium` effort, and H6 quantifies reproducibility as a Phase-0 gate — but a residual subjective component remains, and any class resting on it is reported at `low-confidence` if H6 is near the 90% floor.
- **Single model.** Calibration is `claude-opus-4-8`-specific and must be re-fit per model (04 §5.6).
- **Small n.** Class pooling gives 9 trials/cell (R, C) and the X arms pool 5 subtasks × 3 reps; intervals are wide. "Non-inferior" means *no evidence of > δ degradation*, not proof of parity.
- **Difficulty calibration is itself a hypothesis.** H4 tests whether the v2 tasks are actually hard enough to regress; if H4 fails, the suite is still too easy and "no regression" is again untested — reported honestly rather than hidden.
- **Inherited threats** (effort-fidelity via capture hook, no temperature control, adaptive thinking as a constant background factor, prompt-cache effects, sandbox network isolation on macOS, subscription-billing dollars) carry over unchanged from 04 §5.6 / §8.

---

## 7. Pre-registered constants (v2 delta over 04 Appendix B)

| Constant | Value |
|---|---|
| v2 tasks | 9 (R×3, C×3, X×3) |
| Checker mix | 1 exact, 2 blind-grader, 3 pytest-asserts, 3 composite |
| Grader | `agents/effort-grader.md`, blind payload, effort = **medium**, verdicts FINAL |
| Blind-grader rubric | numbered point-weighted criteria; `max_score = 10`; **pass iff total ≥ 7** (R2, R3) |
| R + C matrix | 6 tasks × 5 tiers × 3 reps = 90 runs; pool → n = 9/cell |
| X matrix | 3 jobs × 3 arms × 3 reps × 5 subtasks = 135 subtask runs |
| X arms | `P_calibrated` (per-subtask-class tier), `P_inherit_xhigh` (all `xhigh`), `P_uniform_high` (all `high`) |
| Per-class NI margin δ (R, C) | 0.10 (inherited) |
| Aggregate NI margin δ_agg (X) | 0.05 |
| NI reference | empirical quality-ceiling tier (arg-max pass; ties → cheaper) — inherited |
| CIs | Wilson 95% (rates); Newcombe (diffs); stratified bootstrap 95%, 10,000 resamples (tokens, X arms) |
| H4 gradient threshold | pooled low-tier pass below ceiling by **> 10 pp** in ≥ 1 of R/C |
| H5 victory | calibrated ≤ tokens of both X baselines (CI) at aggregate pass diff ≥ −0.05 vs each |
| H6 gate (Phase 0) | grader agreement **≥ 90%** on 12 artifacts double-graded at `medium` |
| Oracle validator | `bench/tools/validate_oracles_v2.py` — 114 checks, exit 0, run in CI pre-sweep |

---

## 8. Coordination notes (cross-owner seams — flag before the harness/grader run)

Two places where v2 extends contracts owned outside this task (`bench/effort.py`, `agents/effort-grader.md`). Both are called out here so the harness and grader owners can align; neither is silently assumed.

1. **Grader must emit a numeric total score.** `agents/effort-grader.md` today emits `grade ∈ {pass, partial, fail} → score ∈ {1.0, 0.5, 0.0}` for a whole artifact. v2's point-weighted rubrics require the grader to score each criterion and return a **numeric total in `[0, max_score]`** (the rubric text itself instructs "score each criterion, sum to 10"), which the harness compares to `pass_threshold`. This is a small, additive extension to the grader's output schema (a numeric `score` field spanning `0..max_score` rather than only `{0, 0.5, 1}`); the blind stance, fixed-medium effort, and strict-JSON contract are unchanged. **Action:** the grader owner should confirm the numeric-score mode before R2/R3 are graded, or the harness must map the rubric-summed score itself from a criterion-by-criterion grader response.
2. **`composite` checker type for X.** The base checker enum in the schema contract is `exact | pytest-asserts | blind-grader`. X tasks add a task-level `checker.type = "composite"` (`aggregate: "mean_subtask_pass"`, `n_subtasks: 5`) as an **aggregator marker**; the real grading is per-subtask, and every subtask checker uses a base-enum type. A composite job cannot be graded by a single leaf checker, so this marker is necessary; the harness should special-case `class == "X-composite"` and iterate `task["subtasks"]`, running each under the arm's per-class tier. `validate_oracles_v2.py` treats `composite` as valid only for the X class.

---

*Numeric results are produced only by `bench/effort.py analyze`/`report` from real graded runs; this document pre-registers the design and fabricates no results.*
