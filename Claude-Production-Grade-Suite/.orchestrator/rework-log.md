## BUILD — Rework 1 (B2 analyze)
Concerns: analyze implemented ORIGINAL §5 (NI reference hard-coded to max; missing uniform-low baseline, TOST, overthinking flag). Orchestrator repro: perfect-tie mock pilot -> all classes recommend max (degenerate; RQ3 negative in best case).
Oracle: repro scenario must yield low-everywhere; unittest+selftest green; ratchet degenerate-classes 4 -> 0.
Changes: landed on wave-b/B2-specrev (49ff978+6c4dbfc), merged to main 6c4dbfc.
Converged: orchestrator re-verified — Scenario A perfect-tie -> low x4 (ratchet 4->0),
Scenario B gradient -> low/medium/xhigh/xhigh with overthinking flag + 3-baseline
Pareto + TOST computed. 61/61 tests, selftest green. Cycle CLOSED (1 iteration).

## BENCH v2 — Rework 2 (composite arm mapping)
Concerns: calibrated arm silently fell back to 'high' for all 45 subtasks — X subtask classes (mechanical/research-lite/...) did not match calibration-table keys; first composite pass compared high-vs-high-vs-xhigh.
Found by: orchestrator diagnosis of composite failures (tier column uniform 'high' in calibrated arm).
Fix: SUBTASK_CLASS_ALIASES normalization + loud stderr fallback + 2 regression tests (119/119). Buggy arm records archived (results-composite-mapping-bug.jsonl.bak) and stripped; calibrated arm re-run.
Bonus finding preserved: X1.3 is genuinely tier-discriminating (xhigh 3/3 vs high 1/6, fair prompt) — oracle unchanged.
