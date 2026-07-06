# Pipeline Settings
Engagement: standard
Parallelism: maximum
Worktrees: enabled

# Mode
Custom — research-first plugin build (effortmining)

# Skills in plan
polymath (mechanism investigation, pattern mining), data-scientist (literature review, benchmark methodology),
skill-maker (plugin scaffold), software-engineer (bench harness), qa-engineer (pilot benchmark execution),
code-reviewer (polish), technical-writer (README/docs)

# Gates
Gate A — after RESEARCH: niche verdict + benchmark methodology + benchmark scale/cost approval
Gate B — after PROVE/POLISH: results + repo review before push to private nagisanzenin/effortmining

# Project classification
Greenfield — creating from scratch at ~/Documents/Github/effortmining

# User decisions (binding)
- 2026-07-06: A/B benchmark model = claude-opus-4-8 (user: "opus instead of fable"). Full effort range low|medium|high|xhigh|max supported. $5/$25 per MTok for cost math.
- Benchmark instrument: headless `claude -p` on existing Claude Code auth (no ANTHROPIC_API_KEY, no ant CLI on this machine).
- 2026-07-06 GATE A PASSED: research verdict + methodology approved; benchmark scale = Pilot n=3 (180 runs, 12 tasks x 5 tiers x 3 reps).
- 2026-07-06 BENCH v2 APPROVED (user): full scope — R-research + C-coding + X-composite; ~135 tier runs + ~27 composite sessions; envelope $30-90 API-equiv; model claude-opus-4-8.
- 2026-07-07 OVERNIGHT AUTONOMY (user: "do this all by yourself and wrap things up"): run v2 end-to-end unattended. Decision rules: stay inside the $30-90 equiv envelope — if Phase 0 sizing busts it, SCALE DOWN (reps 3->2, then defer live-web/extras) rather than stop; grader must pass self-agreement gate before its verdicts count; ship 0.4.0 + push + final report file for the morning. No user gates until the final report.
