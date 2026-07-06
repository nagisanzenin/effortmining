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
  It audits env sanitization (`CLAUDE_CODE_EFFORT_LEVEL` must be unset — a hard error
  that fails the gate, since a per-run level that can be overridden cannot be trusted)
  and sizes latency. Writes `state/phase0.json` and **gates `run`**. `--mock` exercises
  the plumbing with fabricated probes. Exit 0 iff the gate passes.

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
  Wilson 95% score intervals; per-`(class, tier)` pooling (9 trials/cell at n=3);
  the non-inferiority decision (point guard **and** Newcombe difference-CI guard at
  δ=10pp); the cheapest non-inferior tier per class; seeded stratified-bootstrap CIs
  for the RQ3 policy comparison (calibrated vs inherit@`xhigh` vs uniform-high vs the
  bookends); and the possibly-mis-classed-task flag. Writes `state/analysis.json` and
  the v1 `state/calibration.json`.

- **`report`** — Renders `bench/RESULTS.md` from `analysis.json` (methodology §8):
  run manifest, the full matrix table, per-class pass/token curves (ASCII sparklines
  with Wilson CIs), the calibration table, the RQ3 policy headline, and an honest
  threats-to-validity section. Unicode-box style, no emoji.

- **`calibrate`** — Guarded runtime refit (methodology §7.2). Reads `analysis.json`,
  and for each class may move the recommended tier only if all guards hold: ≥ 9 graded
  outcomes exist for both the current and candidate cells (min-N gate), moves are a
  **single tier step** along `low↔medium↔high↔xhigh↔max`, clamped to `low..max`, and
  the non-inferiority decision must actually change. Prints a human-readable diff and
  writes the updated `state/calibration.json`. Guards keep a noisy handful of receipts
  from thrashing the table.

- **`selftest`** — Runs the mock pipeline end-to-end (`validate --mock` → `run --mock`
  → `grade` → `analyze` → `report` → `calibrate`) in a throwaway temp dir and asserts
  the invariants (files written, schemas valid, resumability, pass/fail spread, valid
  tiers, CIs in `[0,1]`, no emoji, no leftover temp files). Exit 0/1. This is the fast,
  offline confidence check — no login or API spend.

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
| `state/calibration.json` | `analyze`, `calibrate` | **yes** | the calibration table (the deliverable) |
| `RESULTS.md` | `report` | yes | human-readable results |

`raw/` and `state/*` are gitignored; `state/calibration.json` is force-tracked
(`!bench/state/calibration.json`) because it is the shipped artifact.

## `results.jsonl` record schema

One JSON object per line (methodology §9.3), for example:

```json
{"run_id":"T2a__high__r1","task_id":"T2a","class":"T2-simple-transform","tier":"high",
 "requested_effort":"high","effective_effort":"high","rep":1,"scale":"pilot",
 "seed":20260706,"nonce":"…","model":"claude-opus-4-8","cli_version":"2.1.201",
 "ts_start":"…","ts_end":"…","duration_ms":0,"session_id":"…","tokens_in":0,
 "tokens_out":0,"tokens_total":0,"cache_read":0,"cache_creation":0,"cost_usd":0.0,
 "raw_answer_path":"raw/answers/T2a__high__r1.txt","exit_status":0,"api_error":false,
 "retries":0}
```

`grade` adds `{"pass":true,"checker_type":"pytest-asserts","failure_class":"none",
"checker_detail":"6/6 asserts"}`.

`requested_effort` is the tier passed via `--effort`. `effective_effort` is read from
the envelope if a future CLI exposes it, else it defaults to the requested tier —
headless JSON does not currently report per-run effort (see
[`01-mechanism-investigation.md`](../docs/research/01-mechanism-investigation.md) §6);
the Phase 0.3 modulation check is what validates that effort is actually live.

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
python3 -m unittest discover -s tests    # 47 unit tests
python3 bench/effort.py selftest         # offline end-to-end invariants
```

The unit suite covers the Wilson interval against textbook values, the Newcombe
difference CI against the published worked example, the non-inferiority rule and its
edge cases, resumability, seeded-shuffle and bootstrap determinism, atomic-write
crash-safety, env sanitization, answer parsing, and both graders.
