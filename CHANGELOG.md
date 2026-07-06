# Changelog

All notable changes to effortmining are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-07-06

Initial scaffold: the plugin skeleton and the per-subagent effort mechanism, ahead of the pilot benchmark that fills in measured numbers.

### Added

- **Tiered worker agents** `miner-low`, `miner-medium`, `miner-high`, `miner-xhigh`, `miner-max` — five generic delegate workers, byte-identical except for their frontmatter `effort:` level. This is the mechanism that makes per-subagent effort selection possible today: Claude Code has no per-spawn effort parameter, so a tier is applied by choosing which agent to spawn.
- **`effort-grader`** — a blind grader (pinned `effort: medium`) whose input payload deliberately omits any field naming the tier/agent/model that produced an artifact, so grades cannot be biased by effort. Skeptic-first, rounds down, emits strict JSON. For non-deterministic benchmark tasks and runtime audit.
- **`/effortmine`** skill — the calibrated dispatch orchestrator: decompose, classify (T1 through T4), look up the calibration table, dispatch each subtask to the matching `miner-<tier>`, and log the dispatch. Ships a pre-pilot default table (unproven, `version: 0`).
- **`/effort-bench`** skill — a thin driver over the `bench/effort.py` harness (built separately): `validate → run → grade → analyze → report`, plus runtime `calibrate`.
- **Hooks** — a silent-unless-useful `SessionStart` ambient line, and a fail-open `PostToolUse(Task)` dispatch logger that appends to `bench/state/dispatch-log.jsonl`.
- **Docs** — `README.md`, `docs/architecture.md`, and the research reports under `docs/research/` (mechanism investigation, docs verification, literature review, pattern mining, benchmark methodology).

### Notes

- Calibration numbers are **pending the pilot benchmark** (`docs/research/04-benchmark-methodology.md`). The shipped default table is an a-priori difficulty-to-effort ladder, not measured evidence, and is marked `version: 0` / `proven: false`.

[0.1.0]: https://github.com/nagisanzenin/effortmining/releases/tag/v0.1.0
