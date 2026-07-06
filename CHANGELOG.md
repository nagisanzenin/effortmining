# Changelog

All notable changes to effortmining are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-06

Pilot benchmark completed; its measured numbers are folded into the shipped docs and the calibration table.

### Added

- **Fitted calibration table (`version: 1`).** `bench/state/calibration.json` now carries the pilot's measured recommendations — T1-mechanical → `low`, T2-simple-transform → `low`, T3-moderate-reasoning → `high`, T4-hard-reasoning → `low` (T4 flagged; its pilot tasks tested too easy — see caveats) — replacing the a-priori `version: 0` ladder.
- **Measured results in `README.md`.** New "Measured results (pilot, 2026-07-06)" section: 180/180 runs on `claude-opus-4-8` (0 API errors, 0 fidelity violations, 175 pass / 5 wrong_answer / 0 parse_fail), a per-class pass-rate table, the token-per-tier ladder (low 101 → max 696, ≈ 6.9x), and the confirmed overthinking finding.

### Changed

- **README headline resolved to its `HELD` form.** The pre-registered RQ3 claim tested and held: the calibrated policy used **64.7% fewer output tokens** (bootstrap 95% CI [60.9, 67.7]) than inheritance@`xhigh` at **equal** aggregate pass (1.000 vs 1.000); 20.5% [12.3, 27.8] fewer than uniform-`high`; +8.3 pp over uniform-`low`. Pareto verdict: **un-dominated**. Full report in `bench/RESULTS.md`.
- **README status badge** `pre-pilot scaffold` → `pilot-proven`.
- **`miner-*` agent descriptions** now name the class each tier is calibrated for under v1 (miner-low: T1/T2, plus T4-with-caveat; miner-high: T3) and, for tiers no class currently maps to (medium/xhigh/max), when a caller should still choose them. Frontmatter `effort:`/`name:` unchanged; the five agent bodies remain byte-identical.
- **`/effortmine` skill** — the embedded no-file fallback table now mirrors the fitted pilot v1 values (was an a-priori ladder), labeled as the fitted pilot v1 snapshot (2026-07-06).

### Notes

- **Pilot caveats travel with the numbers.** n = 3 reps/cell, so per-class confidence is `low` by design (wide pre-registered intervals). **T4's** `low` recommendation rests on tasks the misclassification check flagged as too easy for Opus 4.8 — not proof that hard reasoning needs no effort; harder T4 tasks are queued. **T3** is the class with the genuine quality gradient (low 6/9, high 9/9). The overthinking tail (H3) is confirmed at `max` in all four classes. Single model, one machine; re-fit per model.
- **Version note:** this entry documents 0.2.0, but `.claude-plugin/plugin.json` still reads `0.1.0` (owned outside these docs). Bump the manifest to `0.2.0` to reconcile.

[0.2.0]: https://github.com/nagisanzenin/effortmining/releases/tag/v0.2.0

## [0.1.0] — 2026-07-06

Initial scaffold: the plugin skeleton and the per-subagent effort mechanism, released ahead of the pilot benchmark (which landed in 0.2.0 with the measured numbers).

### Added

- **Tiered worker agents** `miner-low`, `miner-medium`, `miner-high`, `miner-xhigh`, `miner-max` — five generic delegate workers, byte-identical except for their frontmatter `effort:` level. This is the mechanism that makes per-subagent effort selection possible today: Claude Code has no per-spawn effort parameter, so a tier is applied by choosing which agent to spawn.
- **`effort-grader`** — a blind grader (pinned `effort: medium`) whose input payload deliberately omits any field naming the tier/agent/model that produced an artifact, so grades cannot be biased by effort. Skeptic-first, rounds down, emits strict JSON. For non-deterministic benchmark tasks and runtime audit.
- **`/effortmine`** skill — the calibrated dispatch orchestrator: decompose, classify (T1 through T4), look up the calibration table, dispatch each subtask to the matching `miner-<tier>`, and log the dispatch. At this release it shipped an a-priori difficulty-to-effort default table (`version: 0`); the fitted `version: 1` table replaced it in 0.2.0.
- **`/effort-bench`** skill — a thin driver over the `bench/effort.py` harness (built separately): `validate → run → grade → analyze → report`, plus runtime `calibrate`.
- **Hooks** — a silent-unless-useful `SessionStart` ambient line, and a fail-open `PostToolUse(Task)` dispatch logger that appends to `bench/state/dispatch-log.jsonl`.
- **Docs** — `README.md`, `docs/architecture.md`, and the research reports under `docs/research/` (mechanism investigation, docs verification, literature review, pattern mining, benchmark methodology).

### Notes

- At this release the calibration numbers had not yet been measured (`docs/research/04-benchmark-methodology.md`); the shipped default table was an a-priori difficulty-to-effort ladder marked `version: 0`. The pilot benchmark in 0.2.0 replaced it with the fitted `version: 1` table.

[0.1.0]: https://github.com/nagisanzenin/effortmining/releases/tag/v0.1.0
