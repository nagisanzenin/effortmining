# 04 — A/B Benchmark Methodology & Pilot Task Suite

**Task R4 · Data Scientist · effortmining**
**Status:** design complete, pre-registered. Awaiting Gate A approval before any run.
**Date:** 2026-07-06 · **Benchmark model (binding):** `claude-opus-4-8` · **CLI verified:** Claude Code `2.1.201`

---

## 0. What this document is (and the gate it feeds)

effortmining ships one thing of value: a **default calibration table** that tells the plugin, per class of subagent task, the *cheapest reasoning-effort tier that does not measurably hurt quality*. This document is the scientific protocol that produces that table with real numbers and proves the plugin's headline claim. It is pre-registered: every threshold, decision rule, and constant below is fixed **before** any data is seen (Appendix B). Nothing here may be run until the user approves at the gate; Section 4 (Phase 0) is the first thing the engineer executes after approval.

### 0.1 The niche this benchmark exploits (given, verified upstream)

From the docs-verification agent (source-cited, treat as given):

- Effort levels are `low | medium | high | xhigh | max`. Opus 4.8 supports all five; the model **default is `high`**. API surface: `output_config.effort`.
- **Adaptive thinking self-regulates *within* a fixed level.** Nothing in Claude Code selects the level *per task*: a spawned subagent **inherits the session effort** unless a static `effort:` frontmatter key overrides it. There is **no per-invocation effort parameter** (the model has one; *effort* does not). That gap — static, inherited, uncalibrated effort — is exactly what effortmining fills.
- Instrument: headless `claude -p --effort <level> --model claude-opus-4-8` is documented and session-scoped (flag overrides settings). The env var **`CLAUDE_CODE_EFFORT_LEVEL` takes precedence over everything** — the harness must guarantee it is UNSET (Section 4.4).

If effort did not modulate behavior in headless mode, the entire premise fails; **Phase 0.3 tests exactly that** and aborts the run if it does not hold.

### 0.2 Instrument facts verified locally for this doc

Run read-only against the installed CLI (`claude -p --help`, `claude --version`) — no generation:

| Fact | Result |
|---|---|
| `--effort <level>` accepts `low, medium, high, xhigh, max` | ✅ present in help |
| `--model <model>` (alias or full id) | ✅ present |
| `--output-format json` (single result envelope) | ✅ present |
| `-p / --print` non-interactive | ✅ present |
| `--seed` / temperature control | ❌ **absent** — no determinism knob exists |

Consequence of the missing `--seed`: run-order randomization and reproducibility live in the **Python harness** (seeded `random`), not the CLI; and cross-run nondeterminism is inherent and becomes the *object of study* (replicates), not something to suppress.

---

## 1. Research questions & claims

| ID | Question | How answered | Extra runs? |
|---|---|---|---|
| **RQ1** | How do **pass rate** and **token cost** scale with effort tier within each difficulty class? | Descriptive curves per (class, tier) from the full 5-tier matrix. | — (matrix) |
| **RQ2** | What is the **cheapest tier per class** that is **non-inferior** to `max`? | Pre-registered non-inferiority rule (Section 5.4) applied to class-aggregated cells. Produces `calibration.json`. | — (matrix) |
| **RQ3 (headline A/B)** | How much does a **calibrated** policy save vs the **status-quo inheritance** policy (all subagents at the session level) and vs **uniform-high**, at equal-or-better aggregate quality? | Policies composed arithmetically from the *same* matrix cell means. Bootstrap CI on the savings %. | **none** — reuses matrix |

**Headline claim to be tested (may fail — that is a real outcome):**

> *A class-calibrated effort policy uses **X% fewer output tokens** (95% CI) than the inheritance policy at a power-user session level (`xhigh`), while its aggregate pass rate is non-inferior (difference CI lower bound ≥ −5pp).*

The status-quo baseline is **inheritance at `xhigh`**, chosen because a power user running a demanding session sets a high session effort and *every* spawned subagent silently inherits it — the precise waste effortmining claims to remove. We also report vs **uniform-`high`** (the model default) as a second, more conservative baseline.

---

## 2. Task suite (authored, validated, shipped)

12 tasks = **4 difficulty classes × 3 tasks**, in `bench/tasks/*.json`. All are self-contained (pure prompt→text; no tools, files, web), objectively gradeable, unambiguous, and use **novel content** (no famous puzzles) to avoid memorization contamination. **Blind-grader count: 0** — every pilot task is deterministically checkable, satisfying the loop-protocol preference for executable oracles (Section 10).

| id | class | title | checker | answer convention | expected/entrypoint |
|---|---|---|---|---|---|
| T1a | T1-mechanical | ERROR-line extraction → `ts\|svc\|code` | exact | `<answer>` tags | 3 pipe-delimited lines |
| T1b | T1-mechanical | JSON aggregation → sorted `key=value` | exact | `<answer>` tags | 3 lines |
| T1c | T1-mechanical | tag normalize / dedupe / sort | exact | `<answer>` tags | `blue,green,red,yellow` |
| T2a | T2-simple-transform | `normalize_phone` | pytest-asserts | ```python block | 6 asserts |
| T2b | T2-simple-transform | `rle` (singleton rule, case-sensitive) | pytest-asserts | ```python block | 5 asserts |
| T2c | T2-simple-transform | `business_days` (inclusive weekdays) | pytest-asserts | ```python block | 5 asserts |
| T3a | T3-moderate-reasoning | find+fix the `median` bug | pytest-asserts | ```python block | 5 asserts |
| T3b | T3-moderate-reasoning | 4-friends drink logic (unique) | exact | `<answer>` tags | `Ada=juice,Ben=tea,Cy=water,Dot=cola` |
| T3c | T3-moderate-reasoning | trace stack-machine program | exact | `<answer>` tags | `1` |
| T4a | T4-hard-reasoning | `final_balance` ledger w/ holds | pytest-asserts | ```python block | 6 asserts |
| T4b | T4-hard-reasoning | count length-6 no-3-in-a-row strings | exact | `<answer>` tags | `26` |
| T4c | T4-hard-reasoning | `resolve` dependency ordering | pytest-asserts | ```python block | 7 asserts |

**Checker mix:** 6 exact, 6 pytest-asserts, 0 regex, 0 blind-grader.

### 2.1 Answer-parsing conventions (pre-registered, deterministic)

- **`<answer>` tags** (exact tasks): the harness extracts the text between the first `<answer>` and the next `</answer>`. **Canonicalization** = strip outer whitespace, then `rstrip` each line (removes trailing spaces / a trailing newline). Compare `==` against the same-canonicalized `expected`. No tags found → `parse_fail` (counts as fail, tracked separately, Section 6.3).
- **```python code block** (pytest tasks): the harness extracts the **last** fenced `python` block (fallback: last fenced block of any language). It appends the task's hidden `asserts`, then runs the combined program in a sandboxed subprocess (Section 9.4). All asserts pass → `pass`. `AssertionError` / exception / missing entrypoint → `wrong_answer`. No block → `parse_fail`. Timeout → `timeout`.

Prompts instruct the model to emit **only** the answer/code block, so preamble and any leaked reasoning are separated from the graded payload.

### 2.2 Novelty / contamination controls

- Reasoning tasks (T3b, T3c, T4b) use invented content (novel puzzle, invented opcodes, a specific count) so there is no memorized answer to recall. T3b's uniqueness and T4b's count are **brute-force-verified** (Appendix A).
- Code tasks hide their asserts from the model, so "famous transform" recognition cannot leak the graded edge cases; T4 asserts specifically punish overfitting to the visible examples (e.g. the ledger's ignored-withdraw path, `resolve`'s cycle case).
- Each run is prefixed with an **inert per-run nonce** header (Section 3.3) so no two runs share an identical user turn — this defeats cross-run prompt-cache reuse of the *answer* and any run-to-run contamination.

### 2.3 Oracle integrity (validated before ship)

Every oracle is validated by a committed, reproducible tool — `python3 bench/tools/validate_oracles.py` (stdlib only, **34/34 checks green**, exit 0). For each exact task it **recomputes** the expected answer from first principles and compares it to the shipped `expected` (and asserts the input still appears in the prompt, catching answer/prompt drift); for each pytest task it runs the file's own `asserts` against an independent reference solution in a sandboxed subprocess (all satisfiable, non-contradictory). Reference solutions are in **Appendix A** (they are NOT shown to the model — they exist only to prove the oracles are correct). Re-run this tool in CI before every benchmark run.

---

## 3. Experimental matrix & scale

### 3.1 Design

**Factors:** task (12) × effort tier (5: `low, medium, high, xhigh, max`) × replicate (n). Full 5-tier sweep is mandatory — a calibration table built on a partial curve is guesswork. Model fixed at `claude-opus-4-8`. One cell = one (task, tier); one run = one (task, tier, rep).

### 3.2 Scale options (estimated; **pending Phase 0 measurement**)

Per-tier assumptions (output tokens/run **including thinking**, averaged over the 12-task mix, mid estimate): low 120, medium 400, high 1000, xhigh 2200, max 4500. Input ≈ 2600 tok/run (system+tools+task), ~72% cacheable prefix. These are estimates; **Phase 0.2/0.5 replaces them with measured values before the matrix is sized for real.** Dollar figures use the binding prices **$5/M input, $25/M output** and are **API-price equivalents** — actual runs consume the user's subscription plan, so the true budget currency is *runs*, not dollars.

| Option | Reps | Runs | Output tok (lo–mid–hi) | Est. total $ (mid) [range] | Wall: sequential / @3× |
|---|---|---|---|---|---|
| **Reduced** (T1+T2 only) | 3 | **90** | 41k–83k–168k | **$2.50** [$1.43–5.38] | 47 min / 16 min |
| **Fallback** n=2 | 2 | **120** | 90k–197k–421k | **$5.48** [$2.81–12.09] | 93 min / 31 min |
| **Pilot** n=3 *(recommended)* | 3 | **180** | 135k–296k–632k | **$8.22** [$4.21–18.14] | 140 min / 47 min |
| **Extended** n=5 | 5 | **300** | 226k–493k–1.05M | **$13.70** [$7.01–30.23] | 233 min / 78 min |

Recommendation: **run Phase 0, then the n=3 pilot (180 runs, ≈$8, ≈2.3 h sequential / ≈45 min at 3× concurrency).** If Phase 0 latency comes in high or rate limits bite, fall back to n=2 (120 runs) or start with the Reduced set (T1+T2) to shake out the harness before spending on T3/T4. If the pilot's class-level CIs are too wide to decide a tier (Section 5.4), extend the *undecided* classes to n=5.

### 3.3 Run order, nonce, politeness

- **Seeded randomization:** the harness builds the full list of (task, tier, rep) runs, then shuffles with a fixed seed (`--seed`, default `20260706`) recorded in every record. This de-correlates tier from wall-clock position, so cache warmth, rate-limit throttling, and any diurnal drift cannot align with a tier and bias the comparison.
- **Per-run nonce:** each run's prompt is wrapped `"[run-id: <uuid4>]\n\n" + prompt`. The nonce is inert (the task never references it) but makes every user turn unique, preventing prompt-cache reuse of a prior run's answer and any replicate-to-replicate leakage.
- **Politeness:** default **concurrency 3**; exponential backoff (base 2s, cap 60s, jitter) on rate-limit/5xx; per-run hard timeout 300s; resumable so an interrupted sweep never re-bills completed cells (Section 9).

---

## 4. Phase 0 — instrument validation (gate before the matrix)

Phase 0 is a **hard gate**: the matrix does not run until all four checks pass. Output: `bench/phase0-report.json`. Command: `effort.py validate`.

### 4.1 Flag acceptance & envelope capture
For **each** tier: `claude -p --effort <tier> --model claude-opus-4-8 --output-format json "Reply with the single word: ok"`. Confirm exit 0 and that stdout parses as JSON. Record which tiers are accepted.

### 4.2 Envelope field enumeration
Dump the JSON keys and **bind the harness to the actual field names discovered here.** Expected (Claude Code result envelope — confirm, do not assume): `type, subtype, is_error, duration_ms, duration_api_ms, num_turns, result, session_id, total_cost_usd, usage{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}, modelUsage`. **Critical question to resolve here:** does `usage.output_tokens` **include thinking tokens**? If yes, it is our primary cost metric. If the envelope reports `total_cost_usd` (billed truth), prefer it for the dollar column; if absent, compute cost from token counts × prices. Record the answer; it changes which column is "primary" in Section 6.

### 4.3 Effort-modulation check (premise test)
On a fixed novel reasoning probe (NOT a suite task), run each tier ×3. Confirm output/thinking tokens are **roughly monotone increasing** `low→max`. **Pass criterion:** median `max` output tokens ≥ **2×** median `low` output tokens on the probe. If not monotone / no separation → effort is a no-op in headless mode → **ABORT** and take a fallback (4.6).

### 4.4 Env sanitization (exact, documented)
The harness constructs the child env explicitly:
- **`CLAUDE_CODE_EFFORT_LEVEL`** — **must be unset** (it overrides `--effort`). The harness `pop`s it and asserts absence; if present in the parent, log a loud warning and remove it for children.
- **`CLAUDE_CODE_EXTRA_BODY`** — pop if it contains an `output_config`/`effort` key (would inject a conflicting level).
- **`CLAUDE_CODE_MAX_OUTPUT_TOKENS`** — **must NOT be set** by the harness: a tight output cap would truncate the very thinking tokens the effort dimension produces, confounding the experiment.
- **Auth:** inherit the user's existing Claude Code login. The harness **must not** inject `ANTHROPIC_API_KEY` (would switch billing off-plan and possibly change effort semantics).
Phase 0 prints the sanitized env subset it will use for every run.

### 4.5 Overhead / latency sizing
Time N=5 trivial runs on 2 tiers to estimate startup + per-tier latency; set the wall-time budget and confirm the 300s hard timeout is comfortably above `max`-tier latency on a hard task. Replaces the Section 3.2 estimates with measured numbers.

### 4.6 Abort criteria & fallbacks
| Failure | Fallback |
|---|---|
| A tier's `--effort` value rejected | Route effort via `--settings <file>` (`output_config.effort`) or `CLAUDE_CODE_EXTRA_BODY='{"output_config":{"effort":"<tier>"}}'`; re-run 4.1. |
| Envelope lacks token counts | Parse from `--output-format stream-json` events, or fall back to `total_cost_usd` only + document. |
| Effort not monotone (4.3 fails) | Stop. Escalate: effort may be inherited differently under `-p`; investigate the settings-file route before spending on the matrix. |
| `CLAUDE_CODE_EFFORT_LEVEL` present & unclearable | Hard stop — the level cannot be trusted per-run. |

---

## 5. Metrics & statistics (pre-registered)

### 5.1 Primary quality metric
**Pass rate** per cell = fraction of a cell's replicates whose checker returns `pass`. `parse_fail`, `wrong_answer`, `timeout` all count as **fail** (pass=0); `api_error` runs are retried and, if still failing, **excluded** (not counted as quality failures) and the cell flagged incomplete.

### 5.2 Primary cost metric
**Output tokens per run** (median within a cell; includes thinking if 4.2 confirms). Secondary: total tokens, wall time, dollar-equivalent. Output tokens are primary because they dominate cost at $25/M and are the quantity effort actually moves.

### 5.3 Uncertainty
- Pass rates: **Wilson 95% score interval** (correct for small n and near-0/1 rates).
- Token totals & the policy savings %: **stratified bootstrap** (10,000 resamples), resampling replicate runs *within each cell* to preserve the design, 95% percentile CI.

### 5.4 The non-inferiority decision rule (RQ2) — pre-registered

Per-task cells (n=3) are underpowered, so the calibration decision is made at the **class level**: pool the 3 tasks × n reps into one Bernoulli sample per (class, tier) — **9 trials/cell at n=3**, 15 at n=5. Per-task curves are kept **descriptive** (RQ1) only.

Fixed constants: non-inferiority margin **δ = 0.10** (10 pp); reference = the class's `max`-tier pass rate.

A tier *t* is **non-inferior to `max`** for a class iff **both**:
1. **Point-estimate guard:** `p̂_t ≥ p̂_max − δ`, and
2. **Interval guard:** the **Newcombe 95% CI lower bound for the difference `(p_t − p_max)` is ≥ −δ`** (equivalently, no evidence the tier is worse than `max` by more than 10 pp).

**Cheapest non-inferior tier** for a class = among all non-inferior tiers, the one with the **lowest median output tokens** (tie-break: total tokens, then wall time). That tier is the class's recommended default in `calibration.json`.

Honest reading at pilot n: with 9 trials/cell the Wilson/Newcombe intervals are wide. "Non-inferior" here means *"no evidence of >10 pp degradation"*, **not** proof of parity. Classes whose decision is ambiguous (interval straddles the margin such that two adjacent tiers both qualify by point estimate but neither's interval clears) are marked **`low-confidence`** and are the priority for the n=5 extension.

### 5.5 Policy comparison (RQ3) — computed, no new runs
Workload = one run of each of the 12 tasks (equal weight); a class-weighted variant is also reported. Policies assign a tier to each task:

- **`P_inherit_xhigh`** — every task at `xhigh` (status-quo inheritance, power-user session).
- **`P_uniform_high`** — every task at `high` (model default).
- **`P_calibrated`** — each task at its class's RQ2 recommended tier.
- Bookends **`P_uniform_max`**, **`P_uniform_low`** for context.

For each policy: expected aggregate pass rate = mean over tasks of the cell-mean pass rate at the assigned tier; expected output tokens = sum over tasks of the cell-mean output tokens at the assigned tier. **Savings%** vs baseline B = `(tok_B − tok_calibrated) / tok_B × 100`, with a **bootstrap 95% CI** (resample within cells, recompute both policies each draw). The aggregate pass-rate difference gets its own difference-CI (margin **δ_agg = 0.05**, tighter because the aggregate pools all 12 tasks × n).

### 5.6 Pre-registered limitations (stated before data)
Small n (class-level pooling mitigates but power is low); single model (calibration is Opus-4.8-specific, re-fit per model); **no temperature control** (nondeterminism is the object of replication, not a nuisance to remove); prompt-cache effects (mitigated by per-run nonce; residual system-prompt cache read is tier-invariant and only touches cheap input cost); exact-match strictness (mitigated by explicit formats + `parse_fail` tracked separately, so we can tell strictness-failures from reasoning-failures); single machine (wall time is operational, not a scientific variable); subscription billing (dollars are API-equivalents). Full threats section in RESULTS.md (Section 8).

---

## 6. Failure taxonomy

Every graded run carries a `failure_class`:

| class | meaning | counts as fail? | tracked separately? |
|---|---|---|---|
| `none` | passed | — | — |
| `wrong_answer` | parsed a valid answer/code, but incorrect | yes | yes |
| `parse_fail` | no extractable `<answer>` / code block | yes | yes (isolates format strictness from reasoning) |
| `timeout` | run or checker exceeded its limit | yes | yes |
| `api_error` | infra error (rate limit, 5xx, transport) | **no** — retried; if persistent, cell marked incomplete & excluded | yes |

Separating `parse_fail` from `wrong_answer` is essential: if a tier "fails" only by not following the output format, that is an instruction-following artifact, not a reasoning deficit, and the report must say so.

---

## 7. Calibration table & guarded refit

### 7.1 `calibration.json` (v1 = output of the pilot's `analyze`)
```json
{
  "version": 1,
  "fitted_date": "2026-07-06",
  "model": "claude-opus-4-8",
  "suite_version": "pilot-12",
  "margin_delta": 0.10,
  "classes": {
    "T1-mechanical":        {"recommended_tier": "<tier>", "confidence": "high|low", "n_graded": 9, "pass_rate": 0.0, "pass_rate_max": 0.0, "delta_vs_max": 0.0, "median_out_tokens": 0},
    "T2-simple-transform":  {"...": "..."},
    "T3-moderate-reasoning":{"...": "..."},
    "T4-hard-reasoning":    {"...": "..."}
  },
  "policy": {
    "baseline_inherit_tier": "xhigh",
    "savings_pct_vs_inherit_xhigh": {"point": 0.0, "ci95": [0.0, 0.0]},
    "savings_pct_vs_uniform_high":  {"point": 0.0, "ci95": [0.0, 0.0]},
    "aggregate_pass_calibrated": 0.0,
    "aggregate_pass_inherit_xhigh": 0.0,
    "noninferior_agg": true
  }
}
```
(Numeric zeros are placeholders filled by `analyze` from real cell data — this document fabricates no results.)

### 7.2 Guarded refit rule (runtime `effort.py calibrate`)
Adopts the **guarded-refit pattern** (engram's FSRS scheduler: sample-gated, clamped, single-step, human-readable). Refitting from accumulated real-usage receipts (JSONL), a class's `recommended_tier` may change **only if all hold**:
1. **Min-N gate:** ≥ **9** graded outcomes exist for *both* the current tier and the candidate tier in that class.
2. **Single-step:** moves are one tier at a time along `low↔medium↔high↔xhigh↔max`; no jumps.
3. **Clamp:** never below `low` or above `max`.
4. **Rule flip:** the Section 5.4 non-inferiority decision must actually change under the new pooled data.
5. **Human-readable diff:** print, e.g. `T2-simple-transform: medium → low  (n=14, pass 0.93 vs max 0.93, Δ=0.00 ≤ δ=0.10)  ✓`.
Guards prevent a noisy handful of receipts from thrashing the table; a real shift must clear the gate to move it, and only by one step.

---

## 8. Reporting — `RESULTS.md` (auto-generated by `effort.py report`)

Sections, in order:
1. **Run manifest** — model, CLI version, seed, dates, N per cell, completed/excluded counts.
2. **Matrix table** — pass rate + median output tokens for every (task, tier); `api_error`/`parse_fail` footnotes.
3. **Per-class curves** — pass rate vs tier and output tokens vs tier (data tables + ASCII/gnuplot-free text sparklines), with Wilson CIs.
4. **Calibration table** — the RQ2 result: recommended tier per class, confidence, Δ-vs-max, cost.
5. **Policy headline (RQ3)** — the A/B: "calibrated policy used **X%** (95% CI a–b) fewer output tokens than inheritance-at-`xhigh` at aggregate pass **P_cal vs P_inh** (difference CI, non-inferior: yes/no)", plus the uniform-high comparison and the bookends.
6. **Threats to validity** — the honest Section 5.6 list, instantiated with what actually happened (wide CIs, any aborted cells, any mis-classed task per the re-labeling check below).

**Task re-labeling check (descriptive):** if a task's pooled `low`-tier pass rate ≥ **0.8**, flag it as *possibly mis-classed* (too easy for its class). It is surfaced in the report, not silently moved; a mis-classed task weakens that class's difficulty signal and the reader must know.

---

## 9. Harness spec (for the Software Engineer)

`bench/effort.py`, Python 3.14 **stdlib only** (`json`, `subprocess`, `random`, `statistics`, `argparse`, `concurrent.futures`, `urllib` not needed). Task files are JSON (stdlib-parseable — deliberately not YAML, to avoid a PyYAML dependency).

### 9.1 Subcommands
| cmd | does |
|---|---|
| `validate` | Phase 0 (Section 4); writes `bench/phase0-report.json`; **gates** `run`. |
| `run` | Executes the matrix or a subset. Seeded shuffle, concurrency (default 3), backoff, 300s timeout, env sanitization. Writes raw answers to `bench/raw/<task>/<tier>/<rep>.txt` and appends one JSONL record per run to `bench/results.jsonl`. **Resumable:** skips (task,tier,rep) already present & non-error in `results.jsonl`. |
| `grade` | Reads ungraded records, applies the task's checker (exact / pytest-asserts; regex supported but unused in pilot), writes `pass` + `failure_class` to `bench/graded.jsonl`. pytest runs in the Section 9.4 sandbox. |
| `analyze` | Cell pass rates, Wilson CIs, class pooling, NI decisions (5.4), bootstrap CIs, policy composition (5.5). Writes `bench/analysis.json` + `bench/calibration.json`. |
| `report` | Renders `bench/RESULTS.md` from `analysis.json` (Section 8). |
| `calibrate` | Runtime guarded refit (7.2) from accumulated receipts; prints the human-readable diff. |

### 9.2 Task-file schema (as shipped in `bench/tasks/`)
`id, class, title, prompt (array of lines, harness joins with "\n"), answer_convention ("sentinel-tags"|"python-code-block"), checker{type, ...}, max_output_tokens, difficulty_rationale`.
- `checker.type=="exact"`: `expected` (array of lines, joined then canonicalized `strip_outer_ws;rstrip_each_line`).
- `checker.type=="pytest-asserts"`: `entrypoint` (required fn name, for diagnostics), `asserts` (array of Python assert lines), `timeout_s`.

### 9.3 `results.jsonl` record schema
```json
{"task_id":"T2a","class":"T2-simple-transform","tier":"high","rep":1,
 "seed":20260706,"nonce":"<uuid4>","ts_start":"...","ts_end":"...","duration_ms":0,
 "session_id":"...","tokens_in":0,"tokens_out":0,"tokens_total":0,
 "cache_read":0,"cache_creation":0,"cost_usd":0.0,
 "raw_answer_path":"bench/raw/T2a/high/1.txt","exit_status":0,"api_error":false,"retries":0}
```
`grade` adds: `{"pass":true,"checker_type":"pytest-asserts","failure_class":"none","checker_detail":"6/6 asserts"}`.
`max_output_tokens` is an **anomaly threshold** (flag runaway/looping runs whose `tokens_out` grossly exceeds it for a low tier), **not** a CLI cap — see 4.4.

### 9.4 pytest sandbox (best-effort, documented)
Run the assembled program (`extracted code + asserts`) as `python3 -I -S <tmpfile>` in a fresh temp dir, with an explicitly minimal env, `resource` limits (CPU seconds ≈ `timeout_s`, address-space cap), and a wall-clock `subprocess` timeout. Network is not hard-blocked on macOS without a sandbox profile; residual risk is low (benign coding tasks, model-generated), and is documented in RESULTS.md. If run on Linux/CI, wrap in `unshare -n` or a seccomp/nsjail profile for true network isolation.

### 9.5 Telemetry alignment
Each record mirrors the receipt-protocol `effort{}` convention (files/tool counts → here tokens/duration/cost) so benchmark spend rolls into the same cost dashboard the orchestrator reads. The JSONL *is* the accumulation substrate the runtime `calibrate` refits from.

---

## 10. Patterns adopted (provenance)

| Pattern | Source (user's own repos / suite) | Where used here |
|---|---|---|
| **Blind grader** — grader payload has *no field* naming the tier/agent that produced the output; skeptic-first, round-down; grader runs at one FIXED cheap effort (medium) to avoid grader-effort confounds | engram `engram-assessor` agent ("deliberately blind… returns receipt JSON") | Section 2 keeps blind-grader count at **0** for the pilot by preferring deterministic checkers; the blind-grader path is specced (fixed medium effort, tier-blind payload) for future non-deterministic tasks. |
| **Oracle hierarchy** — executable > adversarial/blind > self-check (self never terminates); prefer deterministic checkers | production-grade `loop-protocol.md` (Rule 1) | All 12 tasks use Tier-1 executable oracles (exact-match, unit-test-pass). No loop terminates on model self-judgment. |
| **Receipt / effort telemetry** — every unit writes a JSONL/JSON record; align `effort{}` fields | production-grade `receipt-protocol.md` | `results.jsonl` schema (9.3); this task's own receipt at `.orchestrator/receipts/R4-methodology.json`. |
| **Guarded refit** — sample-gated, clamped, single-step, human-readable update | engram FSRS scheduler | Runtime `calibrate` rule (7.2). |

---

## Appendix A — Reference solutions (NOT shown to the model; oracle-integrity proof)

These prove the six pytest oracles are satisfiable and non-contradictory; all shipped asserts pass against them (validated end-to-end, 12/12 tasks). Exact-answer tasks were validated by direct computation, and T3b's uniqueness and T4b's count were brute-forced.

```python
# T2a
def normalize_phone(s):
    d = ''.join(c for c in s if c.isdigit())
    if len(d) < 10: return 'INVALID'
    d = d[-10:]
    return f'({d[0:3]}) {d[3:6]}-{d[6:10]}'

# T2b
def rle(s):
    if not s: return ''
    out, c, n = [], s[0], 1
    for ch in s[1:]:
        if ch == c: n += 1
        else: out.append(c + (str(n) if n > 1 else '')); c, n = ch, 1
    out.append(c + (str(n) if n > 1 else ''))
    return ''.join(out)

# T2c
import datetime
def business_days(a, b):
    s = datetime.date.fromisoformat(a); e = datetime.date.fromisoformat(b); n = 0; d = s
    while d <= e:
        if d.weekday() < 5: n += 1
        d += datetime.timedelta(days=1)
    return n

# T3a
def median(nums):
    s = sorted(nums); n = len(s)
    return s[n//2] if n % 2 else (s[n//2 - 1] + s[n//2]) / 2

# T4a
def final_balance(events):
    bal = h = 0
    for k, a in events:
        if k == 'deposit': bal += a
        elif k == 'withdraw':
            if bal - h >= a: bal -= a
        elif k == 'hold': h += a
        elif k == 'release': h = max(0, h - a)
    return bal - h

# T4c
def resolve(deps):
    done, ds, rem = [], set(), set(deps)
    while True:
        ready = sorted(t for t in rem if all(p in ds for p in deps[t]))
        if not ready: break
        p = ready[0]; done.append(p); ds.add(p); rem.discard(p)
    return done
```

Verified facts baked into oracles: `2026-07-06` is a **Monday**, `2026-07-04` a **Saturday**; July 2026 has **23** weekdays; T3b has exactly **one** consistent assignment; there are exactly **26** length-6 H/T strings with no 3-in-a-row.

## Appendix B — Pre-registered constants (fixed before any data)

| Constant | Value |
|---|---|
| Effort tiers | low, medium, high, xhigh, max |
| Model | claude-opus-4-8 |
| Prices | $5 / M input, $25 / M output |
| Pilot replicates n | 3 (→ 9 trials per class×tier) |
| NI margin δ (per-class) | 0.10 (10 pp) |
| NI margin δ_agg (policy aggregate) | 0.05 (5 pp) |
| Pass-rate CI | Wilson 95% |
| Difference / token CI | Newcombe (diff) & stratified bootstrap 95%, 10,000 resamples |
| Status-quo baseline | inheritance @ `xhigh` |
| Secondary baseline | uniform `high` |
| Cheapest-tier tie-break | median output tokens → total tokens → wall time |
| Run-order seed | 20260706 |
| Per-run timeout | 300 s |
| pytest checker timeout | 5 s/task |
| Refit min-N gate | 9 graded outcomes per cell |
| Refit move size | single tier step |
| Mis-classed-task flag | pooled low-tier pass ≥ 0.80 |
| Effort-modulation pass (Phase 0.3) | median(max out) ≥ 2× median(low out) |

## Appendix C — Non-inferiority decision, in pseudocode

```
for class in classes:
    p_max, n_max = pooled_pass_rate(class, "max")          # 3 tasks x n reps
    candidates = []
    for tier in ["low","medium","high","xhigh","max"]:
        p_t, n_t = pooled_pass_rate(class, tier)
        point_ok   = p_t >= p_max - DELTA                   # DELTA = 0.10
        diff_lo, _ = newcombe_diff_ci(p_t, n_t, p_max, n_max, 0.95)
        interval_ok = diff_lo >= -DELTA
        if point_ok and interval_ok:
            candidates.append((median_out_tokens(class, tier), tier))
    recommended = min(candidates)[1]                        # cheapest non-inferior
    confidence  = "low" if ambiguous_margin(class) else "high"
```
```
# RQ3 policy composition (no new runs)
for policy in [inherit_xhigh, uniform_high, calibrated, uniform_max, uniform_low]:
    tok  = sum(cell_mean_out_tokens(task.class, policy.tier_for(task)) for task in suite)
    pass = mean(cell_mean_pass(task.class, policy.tier_for(task)) for task in suite)
savings_vs_inherit = (tok[inherit_xhigh] - tok[calibrated]) / tok[inherit_xhigh] * 100
# bootstrap over within-cell replicates for the 95% CI on savings and on (pass_cal - pass_inherit)
```
