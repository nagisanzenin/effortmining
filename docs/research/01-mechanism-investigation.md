# R1 — Mechanism Investigation: Is Per-Subagent Reasoning Effort Calibrated in Claude Code?

**Task:** R1-mechanism · **Agent:** polymath · **Date:** 2026-07-06
**Subject under test:** Claude Code `2.1.201` (native build, commit `5bb45156`, built 2026-07-03), macOS arm64.
**Method:** read-only forensics of the installed native binary (`strings` + grep), official docs (docs.claude.com), changelog, one live headless smoke probe, one live transcript inspection, and GitHub issue survey. Every claim below is tagged **[VERIFIED]** (with command output / URL / binary excerpt) or **[INFERRED]**.

---

## 1. Executive Verdict

**Per-subagent reasoning effort in Claude Code is CRUDE, not calibrated. Confidence: HIGH.**

Effort selection today is exactly the three-part "crude" mechanism the effortmining thesis predicts, with **zero** difficulty-aware calibration:

1. **Session inheritance** — a subagent with no explicit effort **inherits the session's effort level** (blanket copy). Verified in official docs, the changelog, and the binary. A one-line file lookup and a multi-file refactor spawned in the same session get the *same* effort.
2. **Static config** — effort can be *pinned* on a named agent via a frontmatter `effort:` field (or SDK `AgentDefinition.effort`), but this is a hand-authored constant, not a function of the task. The plain **Agent/Task tool exposes no effort parameter** — you cannot set effort at the spawn site the way you can set `model`.
3. **The model's own unguided judgment** — the only "automatic" path is effort `auto`/`unset`, which sends *no* effort param so the API applies the model's static default; and API-side `thinking:{type:"adaptive"}`, where the *model* (not the harness) decides thinking depth per turn. Neither is Claude-Code-side, task-difficulty-driven, per-subagent calibration.

**Nowhere in the harness is there a task classifier, an adaptive effort budget, or a feedback loop from outcomes to effort choice.** The only classifier that exists (`auto-mode`) governs *permission/safety* decisions, not effort. Demand for the missing capability is real and unmet: **7+ open feature requests** on `anthropics/claude-code` ask for exactly per-subagent effort control (see §Evidence).

Hypothesis scorecard: **H1 VERIFIED · H2 VERIFIED · H3 VERIFIED · H4 VERIFIED** (one sub-nuance PARTIAL — the Workflow `agent()` path, see §4).

---

## 2. Evidence Table

| # | Source (command / file+line / URL) | Finding | H |
|---|---|---|---|
| E1 | `claude --help` | `--effort <level>  Effort level for the current session (low, medium, high, xhigh, max)` — first-class CLI flag, session-scoped | **H1** |
| E2 | binary str. L329731 (`/effort` help builder) | Levels rendered as `low..max` + pseudo-levels `ultracode` ("xhigh + dynamic workflow orchestration (this session only)") and `auto` ("Use the default effort level for your model") | **H1** |
| E3 | binary str. L173430-440 (`tengu_effort_command`) | `/effort` saves "as your default for new sessions" **or** "(this session only)"; when `CLAUDE_CODE_EFFORT_LEVEL` env is set, `/effort` shows "Not applied … takes over" | **H1** |
| E4 | CHANGELOG **2.1.154** | "Opus 4.8 is here! Now defaults to **high effort** · `/effort xhigh` for your hardest tasks" — confirms `/effort`, model-dependent default | **H1** |
| E5 | binary str. L317975 (config-key list) | Persisted settings key is **`effortLevel`** (sits beside `outputStyle`, `language`, `fastMode`, `alwaysThinkingEnabled`) | **H1** |
| E6 | Agent-tool description, binary str. L148978 & L148988 | "Each agent type's **model, reasoning effort, and tool access** are set in its definition (`.claude/agents/*.md` frontmatter, or the SDK `agents` option); **the `model` parameter here overrides the definition for this** [call]" — model is per-call overridable, **effort is not** | **H2/H3** |
| E7 | Agent-tool input schema (this session's own tool def) | Agent tool params = `description, prompt, subagent_type, model, isolation, mode, name, run_in_background, team_name` — **no `effort`** | **H2** |
| E8 | Docs `code.claude.com/docs/en/sub-agents` L281 | `effort \| No \| Effort level when this subagent is active. **Overrides the session effort level. Default: inherits from session.** Options: low, medium, high, xhigh, max; available levels depend on the model` | **H2/H3** |
| E9 | CHANGELOG **2.1.172** | "**Subagents and context compaction now inherit the session's extended thinking configuration**, improving output quality" — blanket session→subagent inheritance (dated behavior change) | **H2** |
| E10 | Docs sub-agents L306 (min-version 2.1.198) | "subagents also **inherit the main conversation's extended thinking** configuration: if thinking is on in your session, it's on for the subagent…" | **H2** |
| E11 | binary str. L349729 (Zod **agent-definition** schema) | `effort: E.union([E.enum(["low","medium","high","xhigh","max"]), E.number().int()]).optional().describe("Reasoning effort level for this agent. Either a named level or an integer")` — exact frontmatter key = **`effort`**; optional; named level **or integer** | **H3** |
| E12 | Docs sub-agents L222 / L271-281 | `--agents` JSON + file frontmatter accept: `description, prompt, tools, disallowedTools, model, permissionMode, mcpServers, hooks, maxTurns, skills, initialPrompt, memory, effort, background, isolation, color`. `model` default = `inherit` | **H3** |
| E13 | `claude auto-mode config` / `defaults` | The only classifier in CC is **auto-mode = permission/safety** (allow / soft_deny / hard_deny rules over agent *actions*). It never touches effort | **H4** |
| E14 | binary str. — `reasoningEffort`=0, `reasoning_effort`=0 hits; effort "picker" hits = only `modelPicker:increaseEffort` / `decreaseEffort` (manual UI) | No automatic effort-selection code path; effort changes only by explicit user/config action | **H4** |
| E15 | binary str. — `difficulty`(11)=unrelated (`forceCadetDifficulty`, wordlist noise); `calibrat`(26)=`RecalibrationFunction`, `calibrateStartTime`, + 1 prompt string "so workers can calibrate depth" | No task-difficulty→effort logic anywhere | **H4** |
| E16 | binary str. L318235-250 (`thinking` settings) | API `thinking` modes: `adaptive` = "**Claude decides when and how much to think** (Opus 4.6+)", `enabled`, `disabled`. This is *model-side* adaptivity, not harness per-subagent calibration | **H4** |
| E17 | GitHub issues #43083, #25669, #25591, #47156, #39220, #31536, #64033 | 7+ **open** feature requests for per-subagent/per-call effort. #25591: "effort level is only configurable at the session level via /model, the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, or settings files" | **H2/H4** |
| E18 | live smoke probe `claude -p … --output-format json` | Result reports `total_cost_usd`, `duration_ms`, `ttft_ms`, `num_turns`, full `usage{…}` + `modelUsage{…}` — but **no effort field** | Telemetry |
| E19 | live transcript `~/.claude/projects/*/*.jsonl` | Per-message `message.usage{input_tokens, output_tokens, cache_*}`, `message.model`, **`isSidechain`** (marks subagent turns) — **no effort field** | Telemetry |
| E20 | binary str. L318320-326 + L349729 (hook schema) | Hooks (PreToolUse/PostToolUse/Stop/**SubagentStop**) receive `effort.level` ("Active effort level for the current turn … after any silent downgrade"), `agent_id`, `agent_type`, `prompt.id` (OTel join key). Also exported as **`CLAUDE_EFFORT`** env var to Bash/hooks | Telemetry |

---

## 3. Mechanism Map — Every Place Effort CAN Be Set Today

Exact key names / levels / flags, ordered from most global to most local:

| Surface | Exact name | Scope | Levels accepted | Source |
|---|---|---|---|---|
| CLI flag | `--effort <level>` | current session | low, medium, high, xhigh, max | E1 [VERIFIED] |
| Slash command | `/effort <level>` | session; savable as new-session default **or** session-only | low, medium, high, xhigh, max, `auto`, `ultracode` | E2,E3 [VERIFIED] |
| Env var (input) | **`CLAUDE_CODE_EFFORT_LEVEL`** | session; **overrides `/effort`** ("takes over") | low, medium, high, xhigh (max/ultracode noted as not reaching remote procs) | E3,E17 [VERIFIED] |
| Settings.json key | **`effortLevel`** | persisted per-user default | low..max | E5 [VERIFIED] |
| Settings.json key | **`ultracode`** (bool) | session-only; xhigh + dynamic workflows | — | binary L319195 [VERIFIED] |
| Agent frontmatter / SDK | **`effort`** | per named agent; overrides session; default = inherit | low, medium, high, xhigh, max **or integer** | E8,E11,E12 [VERIFIED] |
| API param it maps to | `output_config.effort` (Anthropic); `reasoning_effort` (OpenAI-compat endpoints) | per request | low, medium, high, xhigh, max | embedded claude-api doc L346430+, bug #65863 [VERIFIED] |
| Legacy / deprecated | `maxThinkingTokens` (settings), `MAX_THINKING_TOKENS` env, `thinking:{type:"enabled",budget_tokens:N}` | superseded by `effort` on Opus 4.6+ (400 on 4.7+) | token integer | binary L318249, L346430 [VERIFIED] |

**Pseudo-levels:** `auto`/`unset` → resolver `TTf` returns `{value: void 0}` = send no effort → **model's static default** (E2, binary L329731). `ultracode` → resolves to `xhigh` + standing dynamic-workflow orchestration (E2).

**Claude Code default effort:** model-dependent. Opus 4.8 defaults to **high** (E4); the embedded API guide states **xhigh** is "used as the default in Claude Code" for coding/agentic models (Opus 4.7). [VERIFIED, model-specific.]

**Does NOT exist:** a per-call effort parameter on the Agent/Task tool (E6, E7); any auto/adaptive effort selection by task difficulty (E14–E16).

---

## 4. What Propagates to Subagents by Default

- **Effort:** resolution order is **frontmatter `effort` → else inherit session effort**. There is **no per-invocation override slot** (unlike `model`, which the Agent tool *can* override per call). [VERIFIED E6, E8]
- **Extended thinking config:** inherited by subagents (and by context compaction) since **2.1.172** / docs note 2.1.198. [VERIFIED E9, E10]
- **Model:** default `inherit` (same model as main conversation); overridable via Agent `model` param or `CLAUDE_CODE_SUBAGENT_MODEL` env (min-version 2.1.196). [VERIFIED docs L273, L302]
- **Active effort is exported downward as env var `CLAUDE_EFFORT`** to child processes / Bash / hooks (`if(e.effortLevel!==void 0) t.CLAUDE_EFFORT=e.effortLevel`, binary L322028). [VERIFIED]
- **Net effect:** every ad-hoc subagent (`general-purpose` via the Task tool) runs at the **session effort**, full stop. Only a *pre-defined named agent* can carry a different (still static) effort.

**PARTIAL nuance (flag for benchmark):** GitHub **#64033** — "Workflow tool: honor `effort` on custom subagents + add an `effort` option to `agent()`" — indicates the dynamic-workflow `agent()` path may **not** honor a custom subagent's frontmatter `effort`, and lacks its own per-`agent()` effort option. So even the one programmatic multi-agent surface has an effort gap. [VERIFIED issue exists; exact current behavior INFERRED from title/summary — worth a direct workflow test in the benchmark phase.]

---

## 5. Gap Analysis — effortmining's Niche

Precisely what is missing today (each is a place effortmining can add value):

1. **No spawn-site effort control.** The Agent/Task tool takes `model` but not `effort` (E6, E7). You cannot say "do this lookup at low effort" without authoring a whole named agent. [VERIFIED]
2. **No task→effort mapping.** Effort is a hand-set constant or a blanket inherit. Nothing in the harness reads task shape/complexity and picks effort. [VERIFIED — H4]
3. **No feedback loop.** Outcomes (success, retries, cost, token spend) never inform subsequent effort choices. No adaptive budget. [VERIFIED — H4]
4. **Uniform-effort swarms.** A fan-out of N subagents at one session effort spends the same reasoning on trivial and hard sub-tasks alike — the core inefficiency the thesis targets. [VERIFIED via E8/E9 inheritance semantics]
5. **Effort is invisible in cost telemetry.** Neither headless JSON nor transcript usage records the effort level used (E18, E19); it's only observable via hooks / `CLAUDE_EFFORT` (E20). Auditing "what effort did each subagent actually use, and did it pay off?" requires custom instrumentation — which effortmining can provide.
6. **Workflow `agent()` effort gap** (#64033) — even the programmatic path doesn't cleanly honor per-agent effort. [PARTIAL]

---

## 6. Telemetry Availability (for the benchmark designer)

**A. Headless `claude -p … --output-format json` — result object [VERIFIED, live probe]:**
```
type, subtype, is_error, duration_ms, duration_api_ms, ttft_ms, ttft_stream_ms,
time_to_request_ms, num_turns, result, stop_reason, session_id,
total_cost_usd,
usage: { input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
         output_tokens, server_tool_use{web_search_requests,web_fetch_requests},
         service_tier, cache_creation{ephemeral_1h_input_tokens,ephemeral_5m_input_tokens},
         inference_geo, iterations[], speed },
modelUsage: { "<model-id>": { inputTokens, outputTokens, cacheReadInputTokens,
              cacheCreationInputTokens, webSearchRequests, costUSD,
              contextWindow, maxOutputTokens } },
permission_denials[], terminal_reason, fast_mode_state, uuid
```
→ **cost + tokens + duration are all present; effort level is NOT.** (Sample run: haiku "reply ok" → `total_cost_usd:0.0180629`, `duration_ms:1770`, `output_tokens:36`.)

**B. Transcript JSONL `~/.claude/projects/<proj>/<session>.jsonl` — per message [VERIFIED, live]:**
```
parentUuid, isSidechain (bool ← marks SUBAGENT turns), message.model,
message.usage{input_tokens, cache_creation_input_tokens, cache_read_input_tokens,
              output_tokens, server_tool_use, service_tier, cache_creation,
              inference_geo, iterations[], speed},
requestId, type, uuid, timestamp, cwd, sessionId, version, gitBranch, entrypoint
```
→ **`isSidechain:true` is the subagent-attribution key.** No effort field in usage.

**C. Hooks — the ONLY per-turn effort observability [VERIFIED, binary schema]:**
- Fired for `PreToolUse`, `PostToolUse`, `Stop`, **`SubagentStop`** (models that support the effort param).
- Payload includes: `effort.level` ("Active effort level for the current turn … after any silent downgrade for the selected model"), **`agent_id`** ("present only when the hook fires from within a subagent"), `agent_type` (e.g. "general-purpose", "code-reviewer"), `prompt.id` (== OTel `prompt.id`, joins hook output to OTel at prompt grain).
- **`CLAUDE_EFFORT`** env var exposes active effort to Bash/hooks/statusline.

→ **Benchmark implication:** to correlate effort ↔ cost/quality per subagent, instrument a `SubagentStop`/`PostToolUse` hook to capture `{agent_id, agent_type, effort.level}` and join to transcript `isSidechain` usage rows (or OTel via `prompt.id`). Effort must be *injected* (via frontmatter/config) and *observed* (via hooks) separately — it is never in the cost payload itself.

---

## 7. Open Questions for the Benchmark Phase

1. **Silent downgrade behavior:** `effort.level` is reported "after any silent downgrade for the selected model", and a `supportsEffortLevels` capability flag exists (binary L318467). Which models honor `max`/`xhigh`, and does setting `max` on an unsupported model silently become something lower? Benchmark must record *effective* effort, not requested.
2. **Integer effort:** the agent-def schema accepts `effort` as a named level **or an integer** (E11). What does an integer mean (token budget? ordinal?) and how does it map to `output_config.effort`? Untested.
3. **Workflow `agent()` effort (#64033):** does the dynamic-workflow path actually honor frontmatter `effort` or the H2-observed per-call override? Needs a direct A/B run.
4. **Does inherited vs. pinned effort actually change cost/quality measurably** across representative sub-task tiers (lookup / edit / multi-file reasoning)? This is the empirical core the benchmark must establish.
5. **`auto` vs explicit:** how does effort `auto` (model default) compare on cost/quality to an explicitly-tuned per-task effort — i.e., how much headroom does calibration actually unlock?
6. **`CLAUDE_CODE_EFFORT_LEVEL` remote caveat:** binary says it "is session-scoped and won't reach the remote process" for some values — verify effort propagation to `isolation:"remote"` / background subagents.

---

### Provenance notes
- Binary is a 221 MB native Mach-O arm64 executable at `~/.local/share/claude/versions/2.1.201` (no `cli.js`); JS is embedded as readable strings (362,286 lines extracted). All "binary str. L####" cite that dump.
- Live probes touched only: one haiku headless generation (`ok`), read-only `auto-mode config/defaults`, and read-only inspection of this session's own transcript. No writes outside the worktree.
- Every fabricated-risk item is marked INFERRED; unresolved items are listed in §7 rather than guessed.
