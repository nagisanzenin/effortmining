# Changelog

All notable changes to effortmining are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.3] — 2026-07-10

### Fixed

- **Dispatch-hook telemetry on plugin installs** ([#1](https://github.com/nagisanzenin/effortmining/issues/1), reported by [@yuzushi-dev](https://github.com/yuzushi-dev)): a plugin-loaded agent is addressed as `<plugin>:<agent>` (`effortmining:miner-low`), and the hook's slug validator rejected the `:`, so `agent_type` was written as `null` for **every** real dispatch — the 0.5.2 fallback scan (`startswith("miner-")`) missed the namespaced name too. The hook now logs the namespaced name verbatim, and `normalize_dispatch_record()` strips the `<plugin>:` prefix when deriving the tier. **Calibration output is unchanged** — tier-only hook records were already class-unresolved and skipped by `calibrate`, so `calibration.json` never saw this field. What returns is the audit trail.

### Added

- **`tests/test_hooks.py` — 27 tests, the first coverage `hooks/*.sh` has ever had.** The hook is deterministic core, but no oracle executed it: `unittest` imported `bench/effort.py` and `selftest` ran the mock pipeline, so a payload assumption could rot silently. It did, for three releases. The suite replays real payload shapes through the actual shell script and asserts the writer/reader seam — what the hook writes, `normalize_dispatch_record()` must resolve a tier from. 11 of the 27 fail against 0.5.2's code.
- **`RELEASE_PROTOCOL.md`** — the shipping checklist, with the two gates this repo turned out to need: a guard that a mock refit never overwrites the tracked `calibration.json`, and a dogfood against a real plugin-loaded session. The dogfood earned its place immediately by falsifying a claim in the protocol's own first draft.

### Changed

- `bench/effort.py`: `normalize_dispatch_record()` strips a `<plugin>:` prefix before deriving the tier, so namespaced and bare agent names resolve identically. Two selftest checks cover both spellings (58 v1 checks).

## [0.5.2] — 2026-07-07

### Fixed

- **Dispatch-hook telemetry**: `agent_type` came back null on a live Agent-tool dispatch (payload field spelling varies by surface); the hook now tries known spellings and falls back to scanning input values for a `miner-*` worker name. Found during the real-install user-test round; dispatch itself was unaffected.

## [0.5.1] — 2026-07-07

### Fixed

- **Install-blocking manifest bug**: `plugin.json` declared `skills`/`agents`/`hooks` path fields that fail Claude Code's plugin validation (`agents: Invalid input`); components live in the standard directories and are auto-discovered, so the fields are removed. Caught by a real `claude plugin install` from the public marketplace — the plugin now installs cleanly.

## [0.5.0] — 2026-07-07

The refit: the calibration loop proven end-to-end on deliberately harder fitting tasks.

### Added

- **Six hard fitting tasks** (R4-R6 research chains, C4-C6 adversarial coding; 90 more real runs; validator now 163 checks incl. 12 naive-implementation failure proofs) under pre-registered Amendment A.
- **First data-driven tier move: C-coding `low` → `medium`** (C6 invariant task breaks `low` 16/18; `medium` at ceiling; guarded single-step refit; ambient policy self-updated; stale warning shed automatically).
- **Contextual-difficulty finding**: X1.3-recipe research saturates at `low` in isolation but defeats `low` inside composite jobs — isolated fitting cannot price context; R-research keeps its warning + route-hard-to-`xhigh` mechanism by design.
- **Fabrication failure mode on record**: the one remaining composite failure invented a ticket ID absent from its documents — low effort fabricates, not just skims.

### Changed

- Post-refit composite re-test (pre-registered confirmation): verdict remains `calibrated_wins=false` (44/45 vs 45/45) — reported honestly; caveat-aware routing holds 45/45 at equal-or-lower cost than inheritance across draws.
- Refit warning semantics: warnings for refitted classes are recomputed (earned, not inherited); non-refit classes keep theirs.
- README v2 section rewritten to the post-refit truth (draw-noise range replaces the single −15.6% exploratory figure).

## [0.4.0] — 2026-07-07

Benchmark v2: the no-regression proof on real work (research, coding, composite jobs).

### Added

- **Suite v2** (`bench/tasks-v2/`, 9 tasks): document-grounded research with invented facts, real coding vs hidden adversarial pytest, composite multi-part jobs; `--suite v2` across the harness; blind-grader path live (H6 reliability 12/12); `run-composite` three-policy A/B.
- **225 more real runs.** Isolated R/C saturate at `low` (90/90). Composite pre-registered verdict: as-fitted table LOST (42/45 vs 45/45) — kept honestly. `X1.3` is the first tier-discriminating research task (`low` 0/3, `high` 1/6, `xhigh` 3/3).
- **Caveat-aware policy (exploratory): 100% quality at −15.6% tokens vs inheritance** — the policy the ambient hook already injects (table + its own warnings).
- **Machine-readable fit-blindness warnings** in `calibration.json` for every non-easy class whose fitting tasks all saturate (R-research, C-coding, T4); ambient policy line marks them with `*` automatically.

### Fixed

- Composite calibrated arm silently fell back to `high` for all subtasks (class-vocabulary mismatch) — alias normalization + loud fallback + regression tests; the buggy arm pass was archived and re-run.
- Grader score-scale reconciliation (unit fraction vs rubric points) — accepts both, normalizes, records which.

## [0.3.0] — 2026-07-06

Ambient mode: the plugin now works with zero commands — install it and calibrated dispatch happens on its own.

### Added

- **Ambient dispatch policy (SessionStart).** The SessionStart hook now injects a second, model-facing line derived live from `calibration.json`: whenever Claude delegates a subtask to a subagent, it is nudged to pick the tier-pinned `miner-<tier>` worker for that subtask's difficulty class instead of a default agent at inherited effort. A refit automatically changes the injected policy; class slugs and tier names are allowlist-sanitized before echo; an explicit user effort request always overrides the policy. `/effortmine` remains the deliberate, full-pipeline path.
- **`LICENSE` (MIT)** — the README badge finally has the file to back it.
- **README "Using it" section** — ambient / precise (`/effortmine`) / measured (`/effort-bench`), in that order.

### Notes

- First public release.

## [0.2.0] — 2026-07-06

Pilot benchmark completed; its measured numbers are folded into the shipped docs and the calibration table.

### Added

- **Fitted calibration table (`version: 1`).** `bench/state/calibration.json` now carries the pilot's measured recommendations — T1-mechanical → `low`, T2-simple-transform → `low`, T3-moderate-reasoning → `high`, T4-hard-reasoning → `low` (T4 flagged; its pilot tasks tested too easy — see caveats) — replacing the a-priori `version: 0` ladder.
- **Measured results in `README.md`.** New "Measured results (pilot, 2026-07-06)" section: 180/180 runs on `claude-opus-4-8` (0 API errors, 0 fidelity violations, 175 pass / 5 wrong_answer / 0 parse_fail), a per-class pass-rate table, the token-per-tier ladder (low 101 → max 696, ≈ 6.9x), and the confirmed saturation finding at `max`.

### Changed

- **README headline resolved to its `HELD` form.** The pre-registered RQ3 claim tested and held: the calibrated policy used **64.7% fewer output tokens** (bootstrap 95% CI [60.8, 67.8]) than inheritance@`xhigh` at **equal** aggregate pass (1.000 vs 1.000); 20.5% [12.3, 27.7] fewer than uniform-`high`; +8.3 pp over uniform-`low`. Pareto verdict: **un-dominated**. Full report in `bench/RESULTS.md`.
- **README status badge** `pre-pilot scaffold` → `pilot-proven`.
- **`miner-*` agent descriptions** now name the class each tier is calibrated for under v1 (miner-low: T1/T2, plus T4-with-caveat; miner-high: T3) and, for tiers no class currently maps to (medium/xhigh/max), when a caller should still choose them. Frontmatter `effort:`/`name:` unchanged; the five agent bodies remain byte-identical.
- **`/effortmine` skill** — the embedded no-file fallback table now mirrors the fitted pilot v1 values (was an a-priori ladder), labeled as the fitted pilot v1 snapshot (2026-07-06).

### Notes

- **Pilot caveats travel with the numbers.** n = 3 reps/cell, so per-class confidence is `low` by design (wide pre-registered intervals). **T4's** `low` recommendation rests on tasks the misclassification check flagged as too easy for Opus 4.8 — not proof that hard reasoning needs no effort; harder T4 tasks are queued. **T3** is the class with the genuine quality gradient (low 6/9, high 9/9). H3 is confirmed at `max` in all four classes as **saturation, not regression**: `max` never improved quality over `xhigh` and always cost more (no strict regressions observed). Single model, one machine; re-fit per model.
- **Version:** `.claude-plugin/plugin.json` and the README version badge are bumped to `0.2.0` in step with this entry.
- **Refit scope (0.2.0):** `effort.py calibrate` refits the table from graded **benchmark** receipts only. Dispatch-log telemetry is collected today (hooks + `/effortmine`), but folding it into the refit is roadmap — the live-usage closed loop is not yet shipped.

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
