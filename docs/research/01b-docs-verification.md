# R1b — Docs-Only Verification: How Reasoning Effort Is Determined for Claude Code Subagents

> Provenance: independent docs-verification agent (general-purpose, official sources only, fetched live 2026-07-06).
> Method: docs.claude.com / code.claude.com / platform.claude.com pages + `anthropics/claude-code` CHANGELOG.md (raw, `main`). No local-machine inspection (that is R1's separate job — see `01-mechanism-investigation.md`).
> Sources: effort API doc, Claude Code model-config / sub-agents / cli-reference, Agent SDK typescript/python/subagents pages, orchestration example, CHANGELOG.md.

## 1. The `/effort` command

Sources: https://code.claude.com/docs/en/model-config ("Adjust effort level"); https://platform.claude.com/docs/en/build-with-claude/effort

- **Levels:** `low, medium, high, xhigh, max`, plus two Claude-Code-only pseudo-levels `auto` and `ultracode`.
- **Per-model support** (model-config table): Fable 5 / Sonnet 5 / Opus 4.8 / Opus 4.7 → `low, medium, high, xhigh, max`; Opus 4.6 / Sonnet 4.6 → `low, medium, high, max` (**no xhigh**). "Models not listed here do not support effort." Unsupported level → "falls back to the highest supported level at or below the one you set" (`xhigh`→`high` on Opus 4.6).
- **Defaults:** "`high` on Fable 5, Sonnet 5, Opus 4.8, Opus 4.6, and Sonnet 4.6, and `xhigh` on Opus 4.7."
- **Scope/persistence:** "`low, medium, high, and xhigh` persist across sessions. `max` ... applies to the current session only, except when set through `CLAUDE_CODE_EFFORT_LEVEL`." `/effort auto` = "reset to the model default" (a STATIC default level, not per-request selection). `ultracode` = session-only.
- **Set via:** `/effort` (slider or `/effort <level>`), the `/model` slider, `--effort` flag, `CLAUDE_CODE_EFFORT_LEVEL` env, `effortLevel` setting, or skill/subagent `effort:` frontmatter. **Precedence (verbatim):** "The environment variable takes precedence over all other methods, then your configured level, then the model default. Frontmatter effort applies when that skill or subagent is active, overriding the session level but not the environment variable."
- **ultracode (verbatim):** "a Claude Code setting rather than a model effort level: it sends `xhigh` to the model and additionally has Claude orchestrate dynamic workflows for substantive tasks... It is not part of the `effortLevel` setting, the `--effort` flag, or `CLAUDE_CODE_EFFORT_LEVEL`."
- **ultrathink keyword:** in-context only — "The effort level sent to the API is unchanged."

## 2. Custom agent frontmatter (`.claude/agents/*.md`)

Source: https://code.claude.com/docs/en/sub-agents ("Supported frontmatter fields")

- **Full documented field list** (only `name` + `description` required): `name, description, tools, disallowedTools, model, permissionMode, maxTurns, skills, mcpServers, hooks, memory, background, effort, isolation, color, initialPrompt`. (The `--agents`/SDK JSON form adds `prompt` = the markdown body.)
- **Yes, there is an `effort` key.** Exact spelling `effort`. **Verbatim:** "Effort level when this subagent is active. Overrides the session effort level. **Default: inherits from session.** Options: `low, medium, high, xhigh, max`; available levels depend on the model."
- `model` field **"Defaults to `inherit`"** (main conversation's model).

## 3. Headless `claude -p`

Sources: https://code.claude.com/docs/en/cli-reference; model-config

- **CLI flag:** `--effort` — "Set the effort level for the current session. Options: `low, medium, high, xhigh, max`... Overrides the `effortLevel` setting for this session and does not persist." Combinable with `-p`/`--print` (`claude -p --effort <level> "…"`).
- **settings.json key:** `effortLevel` — accepts `low, medium, high, xhigh`; "`max` and `ultracode` are session-only and are not accepted here."
- **Env var:** `CLAUDE_CODE_EFFORT_LEVEL` — "a level name or `auto`"; highest precedence. Related: `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT`; `CLAUDE_CODE_EXTRA_BODY` can inject `output_config.effort`. Hooks receive `effort.level` JSON / `$CLAUDE_EFFORT`.

## 4. Claude Agent SDK (TS + Python)

Sources: https://code.claude.com/docs/en/agent-sdk/typescript ; .../python ; .../subagents

- **`AgentDefinition.effort` exists in both.**
  - TS: `effort?: "low" | "medium" | "high" | "xhigh" | "max" | number;` — "Reasoning effort level for this agent."
  - Python: `effort: EffortLevel | int | None = None`, `EffortLevel = Literal["low","medium","high","xhigh","max"]`. Default `None` (inherit).
- **Query/options level:** TS `Options` has `effort`, `thinking` (`ThinkingConfig`, default `{type:'adaptive'}`), deprecated `maxThinkingTokens`. Python `ClaudeAgentOptions` has `effort`, `thinking`, deprecated `max_thinking_tokens`. `ThinkingConfig` = `adaptive | enabled{budget_tokens} | disabled`.
- SDK "Dynamic agent configuration" example builds agents via a developer **factory function** keyed on a runtime string — varies `model`/`prompt`, developer-controlled, NOT difficulty-automatic.

## 5. THE CRITICAL QUESTION — is effort auto-calibrated to task difficulty for subagents?

**NO documented mechanism auto-calibrates the effort LEVEL to task difficulty when spawning subagents. Effort is static.**

- Subagent effort **default = "inherits from session"** (sub-agents effort row). Only override is a **static** `effort:` frontmatter value (or the session/env level).
- Model has a documented **per-invocation `model` parameter** (Claude can choose a subagent's model per call); there is **no analogous per-invocation effort parameter** — effort is not selected per delegation. **NOT DOCUMENTED / does not exist.**
- **What subagents inherit by default:** model = `inherit` (main model); effort = session level; extended-thinking config = the session's (`v2.1.198`: "Subagents and context compaction now inherit the session's extended thinking configuration"; sub-agents page: "**There is no per-subagent thinking setting**"). Context otherwise starts fresh (no parent history/system prompt).
- The **only** difficulty-adaptive behavior is **adaptive reasoning/thinking WITHIN a fixed effort level** — a model capability ("lets the model decide whether and how much to think on each step based on task complexity"; `adaptive_thinking` = "dynamically allocates thinking based on task complexity"). It operates under the ceiling set by the static effort level; Claude Code does not raise/lower the effort level per subagent.
- **Advisory only** (not a feature): effort doc lists `low`'s typical use case as "Simpler tasks... **like subagents**," and best-practice #4 "**Consider dynamic effort:** Adjust effort based on task complexity" — guidance to the developer.
- **Orchestration/ultracode is not calibration:** the orchestration example (https://platform.claude.com/docs/en/build-with-claude/mid-conversation-effort-example) uses a fixed `EFFORT = "xhigh"` constant applied uniformly; "The mode is not an API parameter. It is built entirely from documented pieces." ultracode = `xhigh` + dynamic-workflow orchestration, applied session-wide.
- Supporting changelog: `2.1.198` subagents inherit session thinking config; `2.1.0` "Fixed subagents sometimes not inheriting the parent's model by default"; `2.1.149` status-bar bug re "the effort level applied by skill/agent `effort:` frontmatter" (confirms frontmatter is the override path, not auto-selection).

## 6. API parameter mapping

Claude Code's effort → **`output_config.effort`**. Confirmed. effort doc examples all use `"output_config": {"effort": "medium"}` (cURL/Python/TS/Go/Java/C#/PHP/Ruby). Corroborated in CHANGELOG: `2.1.122` "...those ARNs not receiving `output_config.effort`"; `2.1.113` "`CLAUDE_CODE_EXTRA_BODY` `output_config.effort` causing 400 errors on subagent calls."

---

## Every CHANGELOG.md entry mentioning "effort" (with versions, verbatim)

Source: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md (raw, `main`). **Bold** = load-bearing for the subagent-effort question.

- **2.1.186** — "Fixed agent teams: teammates spawned via tmux/pane backends now inherit the leader's `--effort` level"
- 2.1.181 — "Fixed settings changes (such as `/effort` or `/model`) failing with ENOENT when `~/.claude/settings.json` is a relative symlink..."
- 2.1.162 — "`/effort` now confirms when your chosen level will persist as the default for new sessions"
- 2.1.161 — "Fixed the `/effort` dialog, workflow animations, and prompt keyword shimmer not honoring the 'Reduce motion' setting"
- 2.1.160 — "Fixed `/effort ultracode` incorrectly blaming the dynamic workflows setting when the model cannot run xhigh; ultracode is no longer offered on models that do not support it"
- 2.1.154 — "Opus 4.8 is here! Now defaults to high effort · /effort xhigh for your hardest tasks"; "Renamed the `/effort` slider labels from 'Speed'/'Intelligence' to 'Faster'/'Smarter'"; "Fixed API 400 errors on models that don't support the effort parameter when `CLAUDE_CODE_ALWAYS_ENABLE_EFFORT` is set"
- 2.1.152 — "Fixed the effort-change confirmation dialog appearing when the conversation has no messages or when switching between effort levels that resolve to the same underlying value"
- **2.1.149** — "Fixed the status bar showing the user's baseline `/effort` setting instead of the effort level applied by skill/agent `effort:` frontmatter"
- 2.1.147 — "Fixed `/effort` opening with the slider on the wrong level — it now starts at your current effort"
- 2.1.143 — "Background sessions now preserve the model and effort level you set after waking from idle"; "`claude agents` accepts `--permission-mode`, `--model`, `--effort`, and `--dangerously-skip-permissions`..."
- 2.1.142 — "Added new `claude agents` flags: ... `--effort` ..."
- **2.1.133** — "Hooks now receive the active effort level via the `effort.level` JSON input field and the `$CLAUDE_EFFORT` environment variable, and Bash tool commands can read `$CLAUDE_EFFORT`"; "Fixed `/effort` in one session unexpectedly changing the effort level of other concurrent sessions..."
- 2.1.132 — "Fixed `/effort` picker not reflecting the `CLAUDE_CODE_EFFORT_LEVEL` env var override"
- 2.1.129 — "Fixed cache-miss warning appearing spuriously after `/clear` or compaction when changing `/effort` or `/model`"
- 2.1.128 — "Fixed banner showing 'with X effort' on models that don't support effort"
- **2.1.122** — "Fixed `/model` not showing the Effort option for Bedrock application inference profile ARNs, and those ARNs not receiving `output_config.effort`"
- 2.1.120 — "Skills can now reference the current effort level with `${CLAUDE_EFFORT}` in their content"
- 2.1.119 — "Status line: stdin JSON now includes `effort.level` and `thinking.enabled`"
- 2.1.117 — "...`cost.usage`, `token.usage`, `api_request`, and `api_error` now include an `effort` attribute when the model supports effort levels..."; "Default effort for Pro/Max subscribers on Opus 4.6 and Sonnet 4.6 is now `high` (was `medium`)"
- **2.1.113** — "Fixed `/effort auto` confirmation — now says 'Effort level set to max' to match the status bar label"; "Fixed `CLAUDE_CODE_EXTRA_BODY` `output_config.effort` causing 400 errors on subagent calls to models that don't support effort and on Vertex AI"
- 2.1.111 — "Claude Opus 4.7 xhigh is now available!..."; "Added `xhigh` effort level for Opus 4.7, sitting between `high` and `max`. Available via `/effort`, `--effort`, and the model picker; other models fall back to `high`"; "`/effort` now opens an interactive slider when called without arguments..."
- 2.1.98 — "Fixed `/effort max` being denied for unknown or future model IDs"
- 2.1.94 — "Changed default effort level from medium to high for API-key, Bedrock/Vertex/Foundry, Team, and Enterprise users (control this with `/effort`)"
- 2.1.84 — "Added `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL_SUPPORTS` env vars to override effort/thinking capability detection for pinned default models for 3p..."
- **2.1.80** — "Added `effort` frontmatter support for skills and slash commands to override the model effort level when invoked"; "Improved `/effort` to show what auto currently resolves to..."
- **2.1.78** — "Added `effort`, `maxTurns`, and `disallowedTools` frontmatter support for plugin-shipped agents"
- 2.1.76 — "Added `/effort` slash command to set model effort level" (origin of `/effort`)
- 2.1.73 — "Improved `/effort` to work while Claude is responding, matching `/model` behavior"
- 2.1.72 — "Simplified effort levels to low/medium/high (removed max) with new symbols (○ ◐ ●)... Use `/effort auto` to reset to default"; "Fixed `--effort` CLI flag being reset by unrelated settings writes on startup"; "VSCode: Added effort level indicator on the input border"
- 2.1.70 — "Fixed `API Error: 400 This model does not support the effort parameter`..."
- 2.1.69 — "Added effort level display (e.g., 'with low effort') to the logo and spinner..."
- 2.1.68 — "Opus 4.6 now defaults to medium effort for Max and Team subscribers..."; "Re-introduced the 'ultrathink' keyword to enable high effort for the next turn"
- **2.1.49** — "SDK model info now includes `supportsEffort`, `supportedEffortLevels`, and `supportsAdaptiveThinking` fields so consumers can discover model capabilities."
- 2.1.42 — "Added one-time Opus 4.6 effort callout for eligible users"

Arc: `/effort` introduced `2.1.76`; agent/skill `effort:` frontmatter added `2.1.78`–`2.1.80`; `xhigh` added `2.1.111`. **No entry anywhere adds difficulty-based auto-selection of effort for subagents.**

## What the docs never say (NOT DOCUMENTED)

- **No automatic selection of effort level by task difficulty** for subagents (or the main session). Effort is inherited-from-session or a static frontmatter/env/flag/setting value.
- **No per-invocation / per-Agent-tool effort parameter** — unlike `model`, which does have a documented per-invocation parameter. When Claude spawns a subagent it cannot pass a difficulty-tuned effort.
- `auto` and `ultracode` are **not API effort levels** (effort doc: "The values documented on this page are the complete set the API accepts"). `auto` = revert to the model's static default; `ultracode` = `xhigh` + workflow orchestration.
- **No documented "escalation"** where a hard subagent task bumps effort above the inherited session level.
- The distinction between the **static effort level** (a behavioral ceiling) and **adaptive thinking within it** (model decides per-step) is real but the docs never frame it as "effort calibration"; the only calibration that exists is the model's, within a fixed level — not Claude Code's, per subagent.
