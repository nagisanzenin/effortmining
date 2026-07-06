# effortmining benchmark harness (`bench/`)

`effort.py` is the single-file, stdlib-only (Python 3.14) harness that runs the
pre-registered A/B benchmark in [`docs/research/04-benchmark-methodology.md`](../docs/research/04-benchmark-methodology.md)
and produces effortmining's default **calibration table**: the cheapest reasoning-effort
tier per class of subagent task that is not measurably worse than `max`.

Everything is deterministic where it can be (seeded shuffle, seeded bootstrap),
every write is atomic (tempfile + `os.replace`), `raw/results.jsonl` is append-only
and resumable, and model-generated code is executed **only** inside the `grade`
sandbox. The only network call is the `claude` subprocess — and `--mock` removes
even that, running the whole pipeline offline.

## Quick start

```bash
# 0. Prove the oracles are correct (read-only, no generation)
python3 bench/tools/validate_oracles.py

# 1. Phase 0 instrument gate — MUST pass before spending on the matrix
python3 bench/effort.py validate --model claude-opus-4-8

# 2. Run the pilot matrix (12 tasks x 5 tiers x 3 reps = 180 runs), 3-way concurrency
python3 bench/effort.py run --scale pilot --parallel 3

# 3. Grade, analyze, report
python3 bench/effort.py grade
python3 bench/effort.py analyze
python3 bench/effort.py report            # writes bench/RESULTS.md

# Offline dry-run of the entire pipeline (no API spend, no login needed):
python3 bench/effort.py selftest
```

For the v2 suite (R-research / C-coding / X-composite), see
[Suite v2](#suite-v2--r-research--c-coding--x-composite) below.

`--scale` is one of `pilot` (n=3, 180 runs, recommended), `fallback` (n=2, 120),
`reduced` (T1+T2 only, n=3, 90 — good for shaking out the harness), or `extended`
(n=5, 300 — for undecided classes). `run` is **resumable**: re-invoking it skips
cells already recorded with a non-error result, so an interrupted sweep never
re-bills completed work.

## Subcommands

- **`validate`** — Phase 0 instrument gate (methodology §4). For each tier it probes
  `claude -p --effort <tier> --model claude-opus-4-8 --output-format json`, confirms
  the flag is accepted and the JSON envelope parses, and enumerates the envelope's
  field names. It runs the **effort-modulation check** (a fixed novel reasoning probe
  ×3 per tier) and **aborts** unless median `max`-tier output tokens ≥ 2× median `low`.
  It runs the **Phase 0.6 effort-fidelity check** (§4.6): a temporary Stop-hook
  captures each probe's effective `effort.level`, and the gate aborts unless
  requested == effective for all five tiers (proving Opus 4.8 honors each level with
  no silent downgrade). It audits env sanitization (`CLAUDE_CODE_EFFORT_LEVEL` must be
  unset — a hard error) and sizes latency. Writes `state/phase0.json` and **gates
  `run`** (a real `run` refuses to start unless `gate_passed`, or `--force`). `--mock`
  exercises the plumbing with fabricated probes. Exit 0 iff the gate passes.

- **`run`** — Executes the matrix. Builds the `(task, tier, rep)` cell list for the
  chosen scale, shuffles it with a fixed seed (`--seed`, default `20260706`, recorded
  in every record) to de-correlate tier from wall-clock position, and runs cells via a
  thread pool (`--parallel`, default 3). Each run wraps its prompt in an inert per-run
  nonce (defeats prompt-cache reuse of a prior answer), enforces a 300s hard timeout,
  and retries transient (rate-limit / 5xx / timeout) failures with exponential backoff.
  It appends one JSONL record per run to `raw/results.jsonl` (append-only) and writes
  the raw answer text to `raw/answers/<run_id>.txt`. Resumable by default; `--rerun-failed`
  also re-runs cells whose graded verdict was a quality fail. `--mock` fabricates
  deterministic envelopes (per seed) so the pipeline is fully testable offline.

- **`grade`** — Applies each task's checker to the latest non-error result per cell.
  Exact tasks: extract the first `<answer>…</answer>`, canonicalize (`strip_outer_ws`;
  `rstrip_each_line`), compare `==` to the shipped expected. pytest tasks: extract the
  last ```python block, append the hidden asserts, and run the assembled program in the
  sandbox (see below). Writes `state/graded.jsonl` (a derived, atomically-rewritten
  file) with `pass` and a `failure_class` from the taxonomy `none | wrong_answer |
  parse_fail | timeout | api_error`. Verdicts for unchanged answers (same nonce) are
  reused; `--regrade` forces a full recompute.

- **`analyze`** — Computes the statistics (methodology §5): per-cell pass rates with
  Wilson 95% score intervals; per-`(class, tier)` pooling (9 trials/cell at n=3). The
  non-inferiority **reference is the empirical quality-ceiling tier** (arg-max pooled
  pass, ties → cheaper) — not mechanically `max`, so an overthinking `max` cannot
  lower the bar (H3). It applies the non-inferiority rule (point guard **and** Newcombe
  difference-CI guard at δ=10pp) to pick the cheapest non-inferior tier per class;
  adds a **TOST equivalence test** for easy classes T1/T2 (H1, upgrading confidence to
  `high(equiv)` when `low` is provably within ±10pp of the ceiling) and an
  **overthinking flag** (H3). The RQ3 policy comparison scores calibrated against
  **three** baselines — inherit@`xhigh`, uniform-`high`, uniform-`low` — with seeded
  stratified-bootstrap CIs and a **Pareto un-dominated** victory verdict. Writes
  `state/analysis.json` and the v1 `state/calibration.json`.

- **`report`** — Renders `bench/RESULTS.md` from `analysis.json` (methodology §8):
  run manifest, the full matrix table, per-class pass/token curves (ASCII sparklines
  with Wilson CIs), the calibration table, the RQ3 policy headline, and an honest
  threats-to-validity section. Unicode-box style, no emoji.

- **`calibrate`** — Guarded runtime refit (methodology §7.2). Reads `analysis.json`,
  and for each class may move the recommended tier only if all guards hold: ≥ 9 graded
  outcomes exist for both the current and candidate cells (min-N gate), moves are a
  **single tier step** along `low↔medium↔high↔xhigh↔max`, clamped to `low..max`, and
  the non-inferiority decision must actually change. It also folds B1's runtime
  `state/dispatch-log.jsonl` into the min-N count, tolerating both writer shapes: an
  `effortmine` record carries `task_class`; a `posttooluse-hook` record carries only
  `agent_type` (a `miner-<tier>` worker) from which the class is not derivable, so it
  is **skipped and counted**. Prints a human-readable diff and writes the updated
  `state/calibration.json`.

- **`selftest`** — Runs the mock pipeline end-to-end (`validate --mock` → `run --mock`
  → `grade` → `analyze` → `report` → `calibrate`) in a throwaway temp dir and asserts
  the invariants (files written, schemas valid, resumability, pass/fail spread, valid
  tiers, CIs in `[0,1]`, no emoji, no leftover temp files). Exit 0/1. This is the fast,
  offline confidence check — no login or API spend. `--suite v2` runs the v2 pipeline
  (skips gracefully if `tasks-v2/` is empty).

## Suite v2 — R-research / C-coding / X-composite

`--suite v2` (default `v1`) adds three high-value task classes to prove effort
right-sizing does not regress quality on serious work. **v1 behavior is byte-for-byte
unchanged**: every v2 path is additive, and v2 uses its own `-v2`-suffixed state files
(`results-v2.jsonl`, `graded-v2.jsonl`, `analysis-v2.json`, `phase0-v2.json`,
`RESULTS-v2.md`). `state/calibration.json` is **shared** — v2 extends its class table;
the composite arms consume it. Tasks come from `tasks-v2/` (override with `--tasks-dir`).

- **Task schema (v2):** `{id, class: "R-research"|"C-coding"|"X-composite", prompt,
  documents?: [{title, content}], checker, max_output_guardrail, timeout_s}`.
  `documents[]` are prepended to the prompt as clearly-delimited context blocks and
  their (estimated) tokens are counted in input accounting (recorded as
  `document_tokens`). `prompt` may be an array of lines (v1 style) or a plain string.

- **R-research** — long provided documents; checker is `exact` **or** `blind-grader`.
  The **blind grader** (`checker.type=="blind-grader"`, payload
  `{rubric, pass_threshold, max_score}`) grades non-deterministic prose by invoking
  `claude -p --model claude-opus-4-8 --effort medium --output-format json` with a fixed
  template implementing the [effort-grader contract](../agents/effort-grader.md). Its
  payload names **only** `{task_prompt, rubric, artifact}` — there is structurally no
  tier/agent/effort/rep field, so the grade cannot be biased by effort level. Output is
  parsed defensively (first balanced JSON object); a parse failure is retried once, then
  flagged `grading_error` — **excluded from quality, never counted as a task fail**.
  Grader tokens/cost are recorded under separate `grading_*` keys so grading spend never
  pollutes the measured run cost. `grade --grade-mock` gives deterministic offline
  verdicts keyed by artifact hash.

- **C-coding** — hidden adversarial `pytest-asserts`, run in the same §9.4 sandbox as v1.

- **X-composite** — multi-subtask jobs (`subtasks: [{id, class, prompt, checker}]`, each
  checker `exact` or `pytest-asserts`, never blind). `run-composite` executes each
  X-task × arm × rep, running the subtasks **sequentially** (each an independent
  `claude -p` call), grading inline, and appending one record per subtask
  (`+ {composite_id, arm, subtask_id}`) to `raw/results-composite.jsonl`, resumable by
  `(composite, arm, rep, subtask)`. Three **policy arms** set each subtask's tier:
  `calibrated` (read `calibration.json` for the subtask's class; R-research/C-coding
  fall back to `high` until fitted), `inherit_xhigh` (`xhigh` everywhere, the status
  quo), and `uniform_high` (`high` everywhere, the model default).

- **`analyze --suite v2`** runs R/C through the existing per-class machinery (pooling,
  Wilson, ceiling-referenced NI) and adds the **composite arm analysis**: summed output
  tokens per arm (mean over reps ± bootstrap CI) and aggregate subtask pass per arm, with
  the pre-registered verdict — *calibrated wins iff its summed tokens are below both
  baselines (bootstrap CI of the saving excludes 0) **and** its aggregate pass is
  non-inferior to both at δ=5pp (Newcombe)*. Writes `analysis-v2.json` only.

- **`validate --suite v2`** adds a **grader-reliability smoke test** (grade one fixed
  artifact twice; the verdicts must agree — this gates the v2 matrix) and a
  **long-context probe** (~10k-token input at `low`/`max`, to size cost) to
  `phase0-v2.json`. **`calibrate --suite v2`** merges R-research/C-coding entries into
  the shared `calibration.json` (same guarded rules; each stamped `suite:"v2"`),
  **preserving** existing classes; X-composite never enters the table. **`report
  --suite v2`** renders `RESULTS-v2.md` (R/C curves, composite arm table + verdict,
  grader-reliability line, v2 threats).

```bash
# v2 pipeline (offline dry-run: append --mock / --grade-mock to each spending step)
python3 bench/effort.py validate      --suite v2 --model claude-opus-4-8
python3 bench/effort.py run            --suite v2 --parallel 3
python3 bench/effort.py run-composite  --suite v2 --arms calibrated,inherit_xhigh,uniform_high --reps 3 --parallel 3
python3 bench/effort.py grade          --suite v2
python3 bench/effort.py analyze        --suite v2
python3 bench/effort.py calibrate      --suite v2      # merges R/C into calibration.json
python3 bench/effort.py report         --suite v2      # writes bench/RESULTS-v2.md
```

## State-file map

Paths are relative to `--root` (default: this directory, `bench/`). Tasks are read
from `--tasks-dir` (default `<root>/tasks`).

| Path | Written by | Committed? | Contents |
|---|---|---|---|
| `raw/results.jsonl` | `run` | no (gitignored) | append-only, one record per run |
| `raw/answers/<run_id>.txt` | `run` | no (gitignored) | raw model answer text |
| `state/phase0.json` | `validate` | no (gitignored) | Phase 0 instrument report + gate verdict |
| `state/graded.jsonl` | `grade` | no (gitignored) | graded outcomes, one per cell |
| `state/analysis.json` | `analyze` | no (gitignored) | full statistical analysis |
| `state/calibration.json` | `analyze`, `calibrate` (both suites) | **yes** | the calibration table (the deliverable; shared v1+v2) |
| `state/capture/` | `run`, `validate` (real) | no (gitignored) | effort-fidelity Stop-hook + sidecar |
| `state/dispatch-log.jsonl` | B1 skill/hook (runtime) | no (gitignored) | dual-source dispatch receipts read by `calibrate` |
| `RESULTS.md` | `report` | yes | human-readable results |
| `raw/results-v2.jsonl` | `run --suite v2` | no (gitignored) | v2 R/C runs (append-only) |
| `raw/results-composite.jsonl` | `run-composite` | no (gitignored) | v2 composite subtask runs (graded inline) |
| `state/graded-v2.jsonl` | `grade --suite v2` | no (gitignored) | v2 graded outcomes (incl. blind grader) |
| `state/phase0-v2.json` | `validate --suite v2` | no (gitignored) | Phase 0 + grader-smoke + long-context probe |
| `state/analysis-v2.json` | `analyze --suite v2` | no (gitignored) | v2 per-class + composite arm analysis |
| `RESULTS-v2.md` | `report --suite v2` | yes | v2 human-readable results |

`raw/` and `state/*` are gitignored; `state/calibration.json` is force-tracked
(`!bench/state/calibration.json`) because it is the shipped artifact.

## `results.jsonl` record schema

One JSON object per line, with token/cost/duration keys bound verbatim to the
R1-confirmed envelope (methodology §9.3), for example:

```json
{"run_id":"T2a__high__r1","task_id":"T2a","class":"T2-simple-transform","tier":"high",
 "effort_requested":"high","effort_effective":"high","effort_effective_source":"hook",
 "fidelity_ok":true,"rep":1,"scale":"pilot","seed":20260706,"nonce":"…",
 "model":"claude-opus-4-8","cli_version":"2.1.201","ts_start":"…","ts_end":"…",
 "duration_ms":0,"session_id":"…","input_tokens":0,"output_tokens":0,"total_tokens":0,
 "cache_creation_input_tokens":0,"cache_read_input_tokens":0,"total_cost_usd":0.0,
 "model_usage":{},"raw_answer_path":"raw/answers/T2a__high__r1.txt","exit_status":0,
 "api_error":false,"retries":0}
```

`grade` adds `{"pass":true,"checker_type":"pytest-asserts","failure_class":"none",
"checker_detail":"6/6 asserts"}`.

**Effort fidelity.** `effort_requested` is the tier passed via `--effort`.
`effort_effective` is the tier that actually ran, read out-of-band from a Stop-hook
capture (`effort_effective_source:"hook"`) and joined to the run by `session_id` —
headless JSON carries no effort field (see
[`01-mechanism-investigation.md`](../docs/research/01-mechanism-investigation.md) §6).
A run counts toward its cell only if `fidelity_ok` (requested == effective, verified);
a downgrade or an unverified capture is excluded and re-attempted (§4.6). Phase 0.6
gates the whole matrix on requested == effective for all five tiers.

## The grade sandbox — honest scope

pytest checks run the assembled `extracted code + hidden asserts` as
`python3 -I -S <tmpfile>` in a fresh temp CWD, with a minimal env, POSIX resource
limits (CPU seconds, address space), and a wall-clock timeout. This is **subprocess
isolation, not a jail**: on macOS, network is not hard-blocked without a sandbox
profile. The residual risk is low (benign, model-generated coding tasks) and is
documented in `RESULTS.md`. On Linux/CI, wrap the interpreter in `unshare -n`
(or an nsjail/seccomp profile) for true network isolation. Model-generated code is
executed **only** here — never elsewhere in the harness.

## Tests

```bash
python3 -m unittest discover -s tests    # 117 unit tests (80 v1 + 37 v2)
python3 bench/effort.py selftest              # offline end-to-end invariants (v1)
python3 bench/effort.py selftest --suite v2   # offline end-to-end invariants (v2)
```

The v1 suite (`tests/test_effort.py`, 80 tests) covers the Wilson interval against
textbook values, the Newcombe difference CI against the published worked example, the
non-inferiority rule and its edge cases, the ceiling-referenced calibration and
overthinking flag, TOST equivalence, the dual-source dispatch-log normalization,
effort-fidelity validity, resumability, seeded-shuffle and bootstrap determinism,
atomic-write crash-safety, env sanitization, answer parsing, and both graders.

The v2 suite (`tests/test_effort_v2.py`, 37 tests, over tiny fixtures in
`tests/fixtures-v2/`) covers `--suite` path isolation (v1 files untouched), document
prepending + token accounting, the blind-grader payload's structural blindness
(asserted on the constructed prompt), the grader parse-failure taxonomy, composite
resumability, arm-policy tier mapping (incl. the calibrated-table fallback), the
composite arm-analysis math on synthetic data, and a mock end-to-end v2 pipeline.
