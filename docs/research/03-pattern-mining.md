# 03 — Pattern Mining: engram + production-grade → effortmining

**Task:** R3 (Polymath engineering-research). **Date:** 2026-07-06.
**Sources (shallow clones, read-only):**
- `engram` — https://github.com/nagisanzenin/engram @ v0.3.0 (learning plugin: FSRS scheduler, blind assessor, curriculum DAG).
- `claude-code-production-grade-plugin` ("pg") — https://github.com/nagisanzenin/claude-code-production-grade-plugin @ v5.5.x (14-agent build orchestrator).

Both by the same author (nagisanzenin / Quan Duong). engram's README explicitly states its verification patterns (oracle loops, receipts, re-anchoring) were "inherited from claude-code-production-grade-plugin, transposed from software verification to learning verification" (engram `README.md:255`). effortmining is the third repo in that lineage: **transpose the same discipline to effort calibration** — pick the cheapest agent configuration that still passes a blind grader.

**Files analyzed:** 34 across both repos (full reads of the load-bearing files; frontmatter/grep sweeps of the rest).

---

## ★ HEADLINE FINDING — the reasoning-effort frontmatter cross-check (extraction item 11)

This is the single most decision-relevant fact for effortmining's mechanism investigation, so it leads.

**On the Claude Code side, no agent anywhere sets a reasoning-effort key. The only keys used in `agents/*.md` frontmatter are `name`, `description`, and (optionally) `tools`.** There is no `model`, no `reasoning_effort`, no `thinking`, no budget key on any Claude Code agent in either repo.

Exact keys found, per surface:

| Surface | File(s) | Frontmatter keys actually present |
|---|---|---|
| engram Claude Code agents | `agents/engram-assessor.md`, `-curriculum-architect.md`, `-artifact-smith.md` | `name`, `description`, `tools` (assessor omits `tools` → inherits all) |
| engram Claude Code skills | `skills/{learn,review,coach}/SKILL.md` | `name`, `description`, `argument-hint` |
| pg skills (pg has **no** `agents/` dir — every worker is a `SKILL.md`) | `skills/*/SKILL.md` ×15 | `name`, `description`; `data-scientist` additionally: `version`, `author`, `tags` |
| **engram Codex ports** | `codex/agents/*.toml` | `name`, `description`, **`model_reasoning_effort`**, `sandbox_mode`, `developer_instructions` |

**The reasoning-effort key exists only on the Codex (TOML) side, and it is Codex-native: `model_reasoning_effort`.** The author reached for it exactly when they wanted to tier reasoning per agent — and the assignment is itself a calibration signal (`codex/agents/*.toml:7-9`):

| Agent | Task nature | `model_reasoning_effort` |
|---|---|---|
| `engram-curriculum-architect` | Decompose topic into a first-principles DAG (generative, high-stakes structure) | `high` |
| `engram-artifact-smith` | Build an interactive explorable (generative, creative) | `high` |
| `engram-assessor` | Grade productions against a fixed rubric (bounded, checklist-driven) | `medium` |

Read that last row carefully: **the blind grader is deliberately set one tier *below* the generative agents.** Grading against an explicit rubric is a more constrained task than open-ended generation, so it earns less reasoning budget. That is precisely the effort/task-difficulty mapping effortmining aims to *measure and automate* rather than hand-set.

**Consequences for effortmining's mechanism investigation:**
1. If effortmining wants per-agent effort tiers **on Claude Code today**, the frontmatter does not offer a knob — neither repo found one. The author's own precedent is: (a) use Codex's `model_reasoning_effort` where the platform exposes it, and (b) on Claude Code, tier *effort behaviorally* — via prompt-encoded depth, loop budgets, and engagement modes (see items 7 & 8). Our investigation should confirm whether the current Claude Code `Agent`/subagent frontmatter now supports a `model:` or effort key; these repos are evidence it did **not** at their versions, and the workaround they chose is the fallback design effortmining should be ready to ship.
2. The Claude Code `Agent()` dispatch these repos use carries **no** per-call model/effort override — only `subagent_type`, `mode`, `run_in_background` (pg `SKILL.md:871-877`). So "effort" on Claude Code is currently a property of *the prompt and the loop*, not a dial. effortmining's calibration table therefore selects among **prompt/loop configurations** (a "tier" = a named bundle of depth + loop budget + optional model), and — where Codex is a target — maps cleanly onto `model_reasoning_effort`.

---

## PART A — Patterns mined from `engram`

### A1. Plugin packaging & dual-runtime manifest (item 1) — **ADOPT**

**What:** A plugin is a directory with a `.claude-plugin/plugin.json` manifest plus a sibling `.claude-plugin/marketplace.json` that lists the plugin(s) the repo publishes. engram ships the *same* engine to two runtimes (Claude Code + Codex) from one tree.

**Where:**
- `.claude-plugin/plugin.json` — `name`, `version` (`0.3.0`), `description`, `author.name`, `homepage`, `keywords[]`, plus wiring keys `skills: "./skills/"`, `hooks: "./hooks/hooks.json"`, `interface: {displayName, category}` (the `.codex-plugin/plugin.json` mirror adds `skills`/`hooks`/`interface`; the `.claude-plugin` copy is leaner).
- `.claude-plugin/marketplace.json` — `name`, `description`, `owner.name`, `plugins: [{name, source:"./", description}]`.
- Install UX (`README.md:15-18`): `claude plugin marketplace add nagisanzenin/engram` then `claude plugin install engram@engram` — note the `plugin@marketplace` addressing.
- Versioning discipline (pg `docs/PUBLISHING.md:82`, `:253`): `plugin.json` on `main` is "the single source of truth for what version is this," enforced by a pre-publish assertion that `plugin.json.version == marketplace.plugins[0].version`. Cross-manifest version drift is the failure mode this guards.

**Why for effortmining:** We are a plugin. Copy this manifest layout verbatim; keep a single-source version and (if we ever target Codex) the same one-tree-two-manifests split. The `keywords`/`interface.category` fields are cheap legibility wins.

**Verdict: ADOPT** — it is the canonical, working plugin skeleton by the same author; no reason to reinvent.

---

### A2. SessionStart hook that surfaces state in one ambient line (item 2) — **ADOPT**

**What:** A `SessionStart` hook prints at most two lines about pending state, and **stays completely silent when there is nothing to say**. It never blocks or errors a session.

**Where:**
- `hooks/hooks.json` — event `SessionStart`, `matcher: "startup|resume|clear"`, runs a `command`-type hook `"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"` with `timeout: 10`.
- `hooks/session-start.sh` — `set -u`; bails to `exit 0` if `python3` missing; resolves `$ROOT` from `CLAUDE_PLUGIN_ROOT`/`CODEX_PLUGIN_ROOT` else self-locates relative to the script; then `python3 engram.py session-start 2>/dev/null || true`. **Degrade-to-silence on every failure path.**
- The actual line is computed in Python, not shell (`scripts/engram.py:956` `cmd_session_start`): if `not due and not pending: return` (silence). Otherwise prints e.g. `[engram] 6 reviews due (transformers: 6) · ~4 min · /review to clear, /learn to continue.` It also emits a "productions awaiting grading" line and a ">7 days since coach" nudge.
- **Security note worth stealing** (`engram.py:967-971`): before echoing a topic name into hook output it re-checks `slug_ok(t)` because "this text is injected into the agent's context; a free-form topic name would be a prompt-injection vector." Hook output is untrusted-by-construction.

**Why for effortmining:** Our telemetry hook should do exactly this — one ambient line like `[effort] 3 tasks miscalibrated last run · /calibrate to retune` and silence otherwise. The self-resolving `$ROOT` and degrade-to-silence contract are the reliability bar. The slug-guard-before-echo is a free prompt-injection defense we must copy since our hook will surface task/agent names.

**Verdict: ADOPT** — mechanism (hooks.json → thin shell → python one-liner), silence discipline, and injection guard all transfer directly.

**pg's two-hook variant (item 12, related) — ADAPT:** pg uses `SessionStart` (`session-guard.sh`) **and** `PostToolUse` (`oracle-gate.sh`) (`pg/hooks/hooks.json`). Two ideas worth lifting:
- **Gate-on-state SessionStart:** `session-guard.sh` fires only if `Claude-Production-Grade-Suite/` exists in cwd, counts artifacts, and emits a markdown block instructing Claude to run `AskUserQuestion`. The hook *shapes the agent's next move* rather than just informing.
- **"Arm after first green" PostToolUse gate:** `oracle-gate.sh` runs the fast oracle after source edits but **does not block while the tree has never been green** (greenfield is red by construction); it writes an `oracle.armed` sentinel on first green and only enforces thereafter. It skips non-source edits, walks *up from the edited file* to find the workspace (worktree-safe), and uses `exit 2` to surface stderr to the agent as feedback. This is the cleanest "don't nag until it matters" hook pattern I found — directly reusable if effortmining ever gates on a per-edit check.

---

### A3. The deterministic Python CLI as the source of truth (item 3) — **ADOPT**

**What:** A single stdlib-only `engram.py` (1742 lines) owns **all** state, math, and evidence. The LLM never computes a date or a grade for scheduling — it shells out. Docstring states the law: *"The LLM never computes dates or stability values; it calls this CLI"* (`engram.py:6`).

**Subcommand design** (argparse subparsers, `engram.py:1670-1725`): `init`, `add-topic`, `topics`, `topic-status`, `next`, `due`, `rate`, `receipt`, `stash {add,list,count,clear}`, `model`, `misconception`, `experiment`, `log-session`, `session-start`, `path`, `refit`, `doctor`, `report`, `stats`, `selftest`. Verb-first, JSON in / JSON out (`emit()` at `:320`).

**Storage format** — a hybrid that is worth copying exactly:
- **State = JSON** (mutable, whole-object): per-topic concept graphs via `load_graph(topic)`; one `learner-model.json` via `load_model()`.
- **Event streams = JSONL append-logs** (immutable, appended): receipts at `receipts/<topic>.jsonl` (`engram.py:650`), the crash-safe stash `pending-verify.jsonl` (`STASH_FILE`, `:323`), `sessions.jsonl`.
- **Atomic writes** (`write_json`, `:197-205`): `tempfile.mkstemp` in the target dir → write → `os.replace(tmp, path)`. A crash never leaves a half-written state file.
- **Corruption quarantine** (`read_json`, `:171-178`): a malformed file is `os.replace`'d to `<path>.corrupt.<date>` and never silently discarded; `doctor` points at it; sibling topics keep working.
- **Untrusted-input guards** (`:53-67`): `slug_ok()` / `require_slug()` reject slashes, `..`, leading-dot, nulls — every filename component is validated before it touches the filesystem. Numeric leaves clamp to bounds (`MODEL_NUMERIC_BOUNDS`, `:713`) so a typo can't wreck the scheduler.
- **Self-test** (`selftest`, `:1250`): README claims 63 checks over "the FSRS math, state machine, and every hardened boundary," each run in a tempdir. Boundary tests include traversal rejection, batch atomicity, corrupt-state survival.

**How skills shell out** (`skills/learn/SKILL.md:11-20`): the skill resolves `ENGRAM="${CLAUDE_PLUGIN_ROOT:-${CODEX_PLUGIN_ROOT:-$ENGRAM_ROOT}}/scripts/engram.py"` then does everything via `python3 "$ENGRAM" …`. **Critical shell-safety rule** (`learn/SKILL.md:20`): *"Never put learner text on a shell command line."* Free text reaches the engine only via `--file` (written with the Write tool) or piped to `--json -` / `--production-file -`, because "a stray `'` or `$(…)` in what they typed … would execute." This is command-injection defense at the orchestration layer.

**Why for effortmining:** Our benchmark harness and calibration table are the exact analog of engram.py — deterministic code that the model must not fake. Copy: verb-first JSON CLI, JSON-state + JSONL-events split, atomic writes, corruption quarantine, slug guards, a `selftest` subcommand, and the "free text only via `--file`/stdin" rule (our harness will pass task prompts and agent outputs around — same injection surface).

**Verdict: ADOPT** — this is the reference implementation for "deterministic core the LLM defers to." It is the spine effortmining should copy structurally.

---

### A4. ★ The INDEPENDENT ASSESSOR — blind grading with a receipt contract (item 4) — **ADOPT (highest priority)**

This is the crown jewel and the pattern effortmining's benchmark is built around. Full contract below.

**What:** A separate agent, `engram-assessor`, grades learner productions against rubrics **while deliberately blind to the tutoring dialogue**. It receives only the items + rubrics + productions and returns strict JSON receipts consumable by `engram.py receipt`. The design intent, verbatim: *"the separation of powers made real. The tutor teaches and roots for the learner; you grade like the exam is real, because an inflated grade poisons a schedule the learner is trusting with their memory"* (`agents/engram-assessor.md:6`).

**Where:** `agents/engram-assessor.md` (Claude Code) + `codex/agents/engram-assessor.toml` (Codex, `model_reasoning_effort="medium"`, `sandbox_mode="read-only"`).

**How blindness is enforced — three structural mechanisms (not a promise):**
1. **Fresh context by construction.** It is a *separate agent*, spawned with only the stash contents. The orchestrating skill is instructed (`learn/SKILL.md:91`): *"Spawn engram-assessor with the pending items — only the stash contents … Never include your tutoring dialogue or your opinion of how it went."* The tutor cannot leak because it is a different process with a curated payload.
2. **The input schema physically excludes the lesson.** The assessor's input carries `claim`, `rubric`, `probe`, `production`, `confidence`, `kind` — there is no field for the dialogue. Blindness is the shape of the data, not the grader's willpower.
3. **Bracket-note discipline.** `production` may contain the tutor's factual observations in brackets (e.g. `[omitted the mechanism when asked]`). The contract (`assessor.md:35`): treat brackets as *the tutor's* words not the learner's, grade only what the learner produced, and treat factual omission-notes as confirmation of absence, never presence.

**Input contract** (`assessor.md:27-28`):
```json
{"items": [{"topic":"…","node":"…","claim":"…","rubric":["…"],"probe":"…","production":"…","confidence":72,"kind":"encode"}]}
```
- `confidence` may be **null** — pass through untouched; *"NEVER invent, infer, or reasonably estimate a confidence"* (`:34`). Null items don't count toward calibration.
- An `audit` request additionally carries the tutor's proposed rating — judge independently first, *then* compare.

**Grading stance — the rubric that makes grades trustworthy** (`assessor.md:8-16`):
- **Skeptic first:** list what's missing/wrong against the rubric *before* crediting what's present.
- **Meaning over wording:** a paraphrase preserving the mechanism scores as recalled; recitation missing the mechanism does not.
- **Derivable nodes owe a why:** if the rubric has a why/derivation criterion and the production states only the what, cap at `partial`.
- **Confidence is not evidence:** high confidence + wrong content is still `lapsed` — *"precisely the case most valuable to catch — flag it."*
- **When torn, round down and say why**, quoting the failed rubric criterion.
- Empty/"no idea" → `lapsed`, kindly. Never infer unproduced knowledge.

**Grade → rating map** (`assessor.md:19-23`) — a fixed table, not vibes:

| grade | when | rating |
|---|---|---|
| `recalled` | all rubric criteria met | `easy` if complete+precise+confidence ≥70, else `good` |
| `partial` | core present, criteria missing | `hard` |
| `lapsed` | core absent or wrong | `again` |

**Output contract** — strict JSON array, *no prose*, directly consumable by `engram.py receipt` (`assessor.md:39-52`):
```json
[{"topic":"…","node":"…","kind":"encode",
  "grade":"recalled|partial|lapsed","rating":"again|hard|good|easy",
  "confidence":72,"production":"<verbatim, ≤600 chars>","probe":"<probe>",
  "misconceptions":["one line per distinct wrong model, learner's framing"],
  "rubric_notes":"criterion-by-criterion: met/missed, quoting the rubric",
  "feedback_line":"ONE specific actionable sentence — no praise-padding",
  "source":"assessor"}]
```
- Audits add `"audit":{"tutor_rating":"…","agree":true|false,"note":"…"}` and are **advisory** — they inform, they do not reschedule.
- **Appeals:** one appeal per item (learner's argument + original production); re-judge on merits; changing a grade is honorable if the argument shows the rubric was actually met — *"Sympathy is not a criterion."*

**The receipt-consumer side is defensively atomic** (`engram.py:671-682`, `cmd_receipt`): it validates **every** item and confirms **every** node exists **before applying any**, so one hallucinated node id can't half-apply a batch. Grades only become schedule state through this deterministic gate — the model's JSON is a *proposal*, the CLI is the *authority*.

**Why for effortmining — this is our benchmark's core:** Our benchmark grades subagent outputs produced at different effort tiers. It MUST be blind to *which tier produced which output*, or the grade is contaminated by exactly the bias this pattern was built to kill (the "tutor was convinced the session went great" while the blind assessor found 1 recalled / 4 partial / 1 lapsed — `README.md:132`). Transpose the contract:
- **Input to our grader:** `{task_id, prompt, rubric[], artifact}` — and crucially **no `tier`/`agent`/`model` field**. Blindness = the tier label is absent from the payload (mechanism 2 above).
- **Rubric per task** authored up front (like the curriculum-architect writes rubrics as "the grading contract" — A6).
- **Output:** per-artifact `{task_id, grade, score, rubric_notes, failure_modes[], source:"grader"}` consumed by a deterministic `bench.py record` that owns the pass/fail and the calibration update.
- **Steal the stance verbatim:** skeptic-first, meaning-over-wording, round-down-and-say-why, flag confident-wrong. Set the grader's `model_reasoning_effort` to `medium` (one below the workers) per the author's own precedent.

**Verdict: ADOPT — top priority.** Replicate the full contract (blind-by-payload-shape, skeptic-first rubric, strict-JSON-consumed-by-CLI, atomic apply, appeals). It is the difference between a benchmark and a vibe.

---

### A5. FSRS scheduler + the `refit` loop = the calibration-table analog (item 5) — **ADAPT**

**What:** A quantitative model (memory stability) drives every decision (next review date), and a guarded fitting loop nudges the model from the user's *measured* outcomes. This is structurally identical to "a calibration table drives effort choices, fitted from measured benchmark outcomes."

**The model** (`engram.py:36-156`): FSRS-4.5 with a 17-element weight vector `W`, `DECAY=-0.5`, `FACTOR=19/81` (chosen so R(t=S)=0.9). Pure functions: `retrievability(elapsed,S)`, `interval_for(S,retention,mult)`, `init_stability/difficulty`, `next_difficulty` (mean-reverts toward D0(Good)), `next_stability_recall/forget`, and `apply_rating(fsrs,rating,date)` — a **pure transition** returning `(new_fsrs, receipt_fields)`. Every path is defensively clamped so a corrupt/hand-edited model can never divide-by-zero or explode the schedule (`interval_for:96-102`).

**The fitting loop** (`engram.py:991-1026`, `cmd_refit`) — the part effortmining should copy conceptually:
- Collects review receipts that recorded a predicted `retrievability`.
- **Guarded:** returns `{ok:false}` with a helpful `reason` if there are 0 such receipts, or `<50` and not `--force` — *"refit is meaningful only with real evidence."* Don't fit on noise.
- Computes `observed` recall vs `predicted` recall, inverts along the power forgetting curve, and derives a **single interval multiplier**, clamped to `[0.5, 1.5]`.
- Writes `interval_multiplier` + `last_refit` back to `learner-model.json`, and returns a plain-language `read` ("intervals shortened — memory decays faster than the default model").
- Honesty about scope: v1 fits one scalar; full FSRS parameter optimization is explicitly deferred (documented, not hidden).

**Why for effortmining:** Replace "memory stability → next review date" with "task features → effort tier," and "observed vs predicted recall → interval multiplier" with "observed pass-rate at tier T vs predicted → adjust the tier-selection threshold." The transferable discipline is: **(1)** a deterministic table/model makes the decision, never the LLM; **(2)** the table is *fitted from receipts*, closing the loop; **(3)** the fit is **guarded by a minimum-N** and **clamped**, and refuses to run on thin evidence with a helpful message; **(4)** it emits a human-readable interpretation of what changed. effortmining's `calibrate` subcommand is engram's `refit` with the nouns swapped.

**Verdict: ADAPT** — don't ship FSRS (wrong domain), but ship its *shape*: guarded, clamped, receipt-fed fitting of a small deterministic model that drives the decision, with an honest v1 scope. This is the second-most-important pattern after the assessor.

---

### A6. Curriculum architect: rubrics as the grading contract (supporting A4) — **ADAPT**

**What:** The `engram-curriculum-architect` agent decomposes a topic into a DAG where **each node ships its own `rubric` (2-4 criteria) and a non-leaking `probe`**, written "as an exam grader would" (`agents/engram-curriculum-architect.md:22`). The rubric is authored *by a different agent, up front*, so the grader (A4) has an objective contract to grade against and never invents its own bar.

**Where:** `agents/engram-curriculum-architect.md`; output is strict JSON for `engram.py add-topic`. Node quality bar (`:19-25`): `claim` is one testable sentence; `probe` is free-recall that "does NOT leak the answer"; `rubric` criteria are checkable ("names both terms", "explains why normalization is needed"); slugs must match `^[A-Za-z0-9][A-Za-z0-9._-]*$` (`codex` port `:` adds this — engine rejects traversal).

**Why for effortmining:** Our benchmark tasks need the same separation: **an author agent (or fixtures) writes each task's rubric before any tier runs**, so the blind grader grades against a pre-committed bar, not a post-hoc one. This kills a second contamination path (grader inventing an easier/harder rubric to match the output it sees). It also mirrors loop-protocol Rule 4 (oracle immutability): the rubric is the oracle; the producer of the output must not author it.

**Verdict: ADAPT** — adopt "rubric authored up front by a non-producer" as a benchmark fixtures rule; the DAG/threshold machinery itself is engram-specific (SKIP that part).

---

### A7. README / marketing structure that makes the repo legible (item 6) — **ADAPT**

**What:** engram's `README.md` (272 lines) is a template for a legible plugin repo. Structure: centered banner + shields (version, license, `selftest 33/33`, scheduler, `100% local`) → one-line thesis → 2-line install → "Wait — what is this?" with an **is/is-not table** → an ASCII **loop diagram** → a **condensed real transcript** (the money shot: the assessor caught what the tutor missed) → 3-command table → "why it works (the science)" with a collapsible citations `<details>` → FAQ → collapsible CLI reference / troubleshooting / repo-layout `<details>`.

**Why for effortmining:** The reusable moves: (1) shields that assert *verifiable* facts (`selftest N/N`, `100% local`) — trust signals, not decoration; (2) an **is/is-not table** to position against the obvious alternative ("isn't this just X?"); (3) an ASCII pipeline diagram; (4) a **real transcript proving the core claim** — for us, a transcript showing a low-effort tier passing the grader on an easy task and failing on a hard one, i.e. calibration earning its keep; (5) collapsible `<details>` to keep the top scannable while housing the CLI reference.

**Verdict: ADAPT** — copy the skeleton and the trust-signal discipline; content is ours.

---

## PART B — Patterns mined from `production-grade`

### B1. Orchestrator SKILL.md: mode-classification + lazy phase dispatch + engagement modes (item 7) — **ADOPT**

**What:** One `production-grade/SKILL.md` (1168 lines) is a meta-orchestrator that classifies the request, runs only the relevant workers, and scales depth by an engagement mode.

**Mode classification table** (`SKILL.md:81-93`): a `Mode | Trigger Signals | Skills Involved` table with 11 rows (Full Build, Feature, Harden, Ship, Test, Review, Architect, Document, Explore, Optimize, Custom). Classify → then **single-skill modes skip the plan and invoke immediately; multi-skill modes present an `AskUserQuestion` plan** (`:95-119`). "The overhead of invoking unnecessarily is near zero" — bias toward acting.

**Lazy phase dispatch:** workers keep their steps in `phases/NN-*.md` (e.g. `software-engineer/phases/02-service-implementation.md`) and the dispatch prompt tells the agent *which phase file to follow* rather than inlining it — the orchestrator stays small and the detail loads just-in-time. polymath uses `modes/*.md` the same way. This is the "load detail on demand" structure that keeps the top-level skill legible.

**Context-preload via bash frontmatter injection** (`SKILL.md:20-27`): the skill body opens with `` !`git status` ``, `` !`cat CLAUDE.md` ``, `` !`cat …/visual-identity.md` `` etc. — command substitutions that inline live repo + protocol state into the skill at load time. Clever way to re-anchor without spending an agent turn.

**Engagement modes = the behavioral effort dial** (`SKILL.md:462-489`): `Express | Standard | Thorough | Meticulous`, written to `.orchestrator/settings.md`, and **every skill reads it to scale its own depth**: PM interview 2-3 / 3-5 / 5-8 / 8-12 questions; architect auto-derive → full walkthrough + per-ADR approval; Thorough/Meticulous add phase summaries and per-agent gate review. Loop budgets scale on the same axis (B2, Rule 10).

**Why for effortmining:** This *is* effort tiering on Claude Code, achieved without any model knob — through prompt-encoded depth + loop budgets selected by one named mode. effortmining's tier selector should mirror `settings.md`: a single written setting the workers read to scale behavior. Adopt: (1) the classification-table → skip-or-confirm-plan router; (2) lazy `phases/`/`modes/` dispatch to keep our top skill small; (3) the bash-injection context preload; (4) engagement-mode-as-effort-dial as the *fallback* mechanism if per-agent effort frontmatter is unavailable.

**Verdict: ADOPT** — the whole orchestration skeleton (classify → route → mode-scaled depth → lazy phase files) is directly reusable and is the proven Claude-Code way to express "effort tiers."

---

### B2. ★ loop-protocol.md — oracle-driven iteration, in full (item 8) — **ADOPT**

**What:** The discipline that makes iteration safe. Core law (`loop-protocol.md:3`): *"NO ORACLE, NO LOOP. A loop is defined by its exit condition, not its participants. Never iterate without an executable check that decides 'done'; never let the producer of work also control the check that judges it."* This is the doctrine our benchmark loop must inherit.

**The ten rules (`skills/_shared/protocols/loop-protocol.md`, mirrored into the worktree at `.protocols/loop-protocol.md`):**
1. **Oracle hierarchy** (`:9-22`): Tier 1 Executable (compile/test/lint/contract/e2e/diff) — gold, may terminate; Tier 2 Adversarial judgment (independent critic told to REFUTE) — may terminate *only if the critic didn't produce the work*; Tier 3 Self-check — **never** terminates a loop. No Tier 1-2 oracle? Build one first or escalate. An oracle you can't execute is **UNVERIFIED**, not green.
2. **Loop contract** (`:23-36`): before looping, state `goal / producer / oracle / delta / ratchet / budget / exit`.
3. **Convergence guards** (`:38-45`): **Ratchet** vs a *baseline* snapshot (a real fix may transiently raise the count — fixing an import error reveals hidden failures = progress); **Plateau** = 2 no-progress iterations → stop; **Oscillation** = a fixed failure signature reappears → stop, escalate up; **Hard caps** (inner 5, review 3, remediation 3) are backstops, not targets.
4. **Oracle immutability / anti-gaming** (`:47-55`): the producer must not modify the oracle it loops against. QA owns the `tests/` tree; producers may never skip/weaken it. Both directions are violations — weakening the test **and** overfitting the impl (hardcoding expected output, stubbing to return the fixture). Defend with held-out checks the producer doesn't see + an adversarial reviewer hunting overfit code.
5. **Delta-only feedback** (`:57-59`): each iteration carries forward only the failing oracle output + pointers; **re-read artifacts from disk (re-anchor), don't accumulate conversation history.**
6. **Escalation ladder** (`:61-70`): escalate **strategy, not effort** — same producer next iter → fresh agent, different approach → re-plan one altitude up → user. *"Try harder fails the same way twice."*
7. **Premade loops** (`:72-82`): inner red-green, TDD pair, review, integration, remediation, functional-drive, debug-JIT — each with producer→oracle→exit.
8. **JIT composer** (`:84-86`): any agent may compose a new loop by instantiating the Rule 2 contract, iff oracle is Tier 1-2 and it's registered in the ledger.
9. **Loop ledger** (`:88-96`): every loop writes `.orchestrator/loops/{id}.md` (contract + one line per iteration + exit reason); receipts include a `loops[]` entry `{id, iterations, ratchet:"9→4→1→0 failing", exit}`. A `plateau|oscillation|budget` exit must be surfaced at the next gate.
10. **Loop budgets by engagement mode** (`:98-107`): Express/Standard/Thorough/Meticulous scale review rounds (1/2/3/3) and remediation cycles (2/3/3/4). **This is the effort dial applied to iteration.**

**Why for effortmining:** Our benchmark harness *is* a loop: run tier T → blind grader (the oracle) → did it pass? → if calibrating, adjust. Every rule transfers:
- The **blind grader is our Tier-2 adversarial oracle** — and it satisfies Rule 1's "critic that did not produce the work" by construction (A4). Where a task has an executable check (tests/compile), that's a Tier-1 oracle we should prefer.
- **Ratchet vs baseline / plateau / oscillation** give our calibration loop principled stop conditions instead of a fixed iteration count.
- **Oracle immutability** = the grader's rubric is fixed and the worker tiers can't touch it; **anti-gaming (impl-side)** = defend against a cheap tier that overfits to a visible rubric — hold rubric details back or use held-out checks.
- **Delta-only + re-anchor from disk** = don't feed a tier the full history; re-read the task fresh each attempt (also keeps effort measurement clean).
- **Loop ledger + receipt `loops[]`** = exactly how we record each calibration run's trajectory.

**Verdict: ADOPT — second-highest priority after the assessor.** This protocol is the rulebook for effortmining's iteration and convergence; copy it near-verbatim, swapping "code oracle" for "blind grader + optional executable check."

---

### B3. receipt-protocol.md — verifiable gates with an `effort` field (item 8) — **ADOPT**

**What:** *"Every completed task must have proof it actually ran. No receipt = not done."* (`.protocols/receipt-protocol.md:3`). Every agent writes a JSON receipt as its **last** action.

**Schema** (worktree `.protocols/receipt-protocol.md`): required `task`, `agent`, `phase`, `status:"complete"`, `artifacts[]` (**each path must exist on disk when written**), `metrics{}` (≥1 concrete number, no empty objects), **`effort{files_read, files_written, tool_calls}`**, `verification` (one line of *what was checked*), and `loops[]` (one entry per loop, per B2 Rule 9). Anti-patterns are enumerated: receipt-before-work, empty artifacts, `metrics:{}`, `verification:"done"`, missing `effort`, unregistered loops, and — pointedly — *"Receipt lists a report/doc file the Write tool couldn't create → persist it via Bash heredoc, verify it exists, THEN write the receipt."*

**Orchestrator verification** (`:` "Orchestrator Verification"): at every phase transition the orchestrator lists expected receipts, reads each, **confirms every `artifacts` path exists on disk**, recovers missing artifacts, and extracts `metrics` for the gate display so *"users see verified data, not agent claims."* Remediation is a 3-receipt chain (finding → fix → original agent re-scan verification).

**Why for effortmining:** The **`effort` field is quite literally our subject matter** — `files_read / files_written / tool_calls` per agent is the raw cost signal our calibration correlates against pass/fail. Adopt the receipt protocol wholesale as the telemetry substrate: every tiered agent emits a receipt with `effort` + the grader verdict, and our `bench.py` reads receipts (not agent prose) to compute cost-vs-quality per tier. The "artifacts must exist on disk" and "metrics must be concrete numbers" rules are the anti-hallucination floor for our benchmark data.

**Verdict: ADOPT** — it is already the receipt format we were told to emit; make it the canonical telemetry record and mine `effort` as the primary cost metric.

---

### B4. Agent dispatch, wave announcements, visual identity (item 9) — **ADOPT (visual) / ADAPT (waves)**

**Agent dispatch prompt formula** (`SKILL.md:871-877`):
```python
Agent(prompt="You are the {Role}. {task}. Read {inputs on disk}. Follow {phase file}. Write output to {path}.",
      subagent_type="general-purpose", mode="bypassPermissions", run_in_background=True)
```
Formula = **role + task + inputs-to-re-anchor-from-disk + phase-file-to-follow + output-path**. Note again: **no model/effort key on the dispatch** (reinforces item 11). Dependencies are expressed with `TaskCreate` + `TaskUpdate` (blocked-by), and work fans out one Agent per unit (per service/page).

**Two-wave parallelism** (`SKILL.md:720-820`): Wave A = build + all analysis that needs only the architecture (up to 7+ concurrent); Wave B = execution against the written code; worktree isolation per agent (`:498`, `:515`) — *"parallel execution is both faster AND cheaper in total tokens because each agent carries minimal context instead of accumulating prior work."*

**Visual identity** (`.protocols/visual-identity.md`, 384 lines) — mission-control aesthetic, adopt as-is:
- **No emoji** (breaks monospace, renders inconsistently); a fixed **Unicode icon vocabulary** with exactly one meaning each: `◆` brand, `●` active, `○` pending, `✓` done, `✗` failed, `⧖` in-progress, `→` transition, `·` separator.
- **Three container tiers:** `╔═╗` (reserved, 3-5 uses/run: header, gates, final summary), `┌─┐` (wave/status boards), `━━━` (section headers).
- **"Information is the aesthetic"** / **"Concrete over vague":** *never* `✓ Analysis complete` — always `✓ Analyzed 247 files, found 12 issues`. Every completion line MUST contain a number.
- **Before/after `→` deltas** as proof of work (`12 findings → 0 Critical`); streaming-as-animation (dashboard reprints are the progress bar).

**Why for effortmining:** Our benchmark runs are inherently parallel (N tiers × M tasks) — the wave-announcement + checkmark-cascade + concrete-metrics completion lines are the right UX. The dispatch formula (re-anchor from disk, follow a phase file, write to a path) is exactly how we should launch tiered workers. Adopt the visual-identity protocol verbatim (it's already in our `.protocols/`).

**Verdict: ADOPT** the visual identity + dispatch formula; **ADAPT** two-wave → "N-tier fan-out" for our benchmark matrix.

---

### B5. Auto-update check (local vs remote plugin.json) (item 10) — **ADOPT**

**What:** On start, compare the installed version to `main` and prompt once if newer (`SKILL.md:307-341`): (1) read local version from `~/.claude/plugins/installed_plugins.json`; (2) `WebFetch https://raw.githubusercontent.com/<owner>/<repo>/main/.claude-plugin/plugin.json` → remote `version`; (3) **WebFetch fails → silently continue, never block**; (4) remote ≤ local → silent; (5) remote > local → one `AskUserQuestion`; on accept: `git clone --depth 1` to `/tmp`, read new SHA, `mkdir` a versioned cache dir, `rm -rf .git && cp -r` the **full** plugin (a prior bug copied only some dirs and dropped `hooks/` — `pg/CHANGELOG.md:60`), update `installed_plugins.json` (`version`/`installPath`/`gitCommitSha`/`lastUpdated`). The SessionStart hook in `hooks.json` self-resolves the newest cached version via `for d in …/*/; sort -V | tail -1`.

**Why for effortmining:** Cheap, self-contained freshness for a marketplace plugin; the offline-degrades-silently and copy-the-*full*-plugin lessons are pre-paid bug fixes. Guard `raw.githubusercontent` version-comparison is the whole mechanism.

**Verdict: ADOPT** — lift the routine; swap owner/repo. Low effort, real UX payoff.

---

### B6. Boundary-safety & other clever bits (item 12) — **ADAPT / reference**

- **boundary-safety.md** (`.protocols/boundary-safety.md`): 6 structural silent-failure patterns at system boundaries (framework abstractions break at boundaries; don't duplicate framework control flow; self-referencing config = infinite loop; global interceptors must branch; **test full journeys not just hops**; identity must match across systems). Mostly web/framework-flavored, but Pattern 5 ("verify the user's final state, not intermediate 200s") is the right instinct for benchmark isolation: grade the *final artifact against the rubric*, not intermediate tool successes. **ADAPT** the "check full journey / final state" idea; the rest is reference.
- **oracle-gate "arm after first green"** (A2) — the single cleverest hook; reusable anywhere effortmining gates on a per-edit check.
- **Corruption quarantine + slug guards + atomic writes + selftest boundary tests** (A3) — the resilience kit; adopt with the CLI.
- **Bash-frontmatter context preload** (B1) — re-anchor the orchestrator cheaply.
- **Codex/Claude one-tree-two-manifests** (A1) — only if we target Codex; note that Codex is where `model_reasoning_effort` lives, so a Codex port is the *natural home* for real per-agent effort tiers.

---

## ADOPT / ADAPT / SKIP summary

| # | Pattern | Source | Verdict | One-line reason |
|---|---|---|---|---|
| A1 | Plugin manifest + single-source versioning | engram | **ADOPT** | Canonical working plugin skeleton by same author |
| A2 | Ambient SessionStart hook (silent-unless-due) + injection guard | engram | **ADOPT** | Exactly our telemetry-nudge mechanism, incl. prompt-injection defense |
| A2′ | Gate-on-state + "arm after first green" PostToolUse | pg | **ADAPT** | Best "don't nag until it matters" hook if we gate on checks |
| A3 | Deterministic stdlib CLI (JSON state + JSONL events, atomic, quarantine, slug guards, selftest) | engram | **ADOPT** | The spine: LLM defers to code for all math/state/evidence |
| **A4** | **INDEPENDENT ASSESSOR — blind grading contract** | engram | **ADOPT ★** | Our benchmark's core; blind-by-payload-shape + skeptic rubric + strict-JSON→CLI |
| A5 | FSRS + guarded `refit` fitting loop | engram | **ADAPT** | Shape of our calibration table: guarded, clamped, receipt-fed model that decides |
| A6 | Rubrics authored up front by a non-producer | engram | **ADAPT** | Grader grades against a pre-committed bar (second contamination path killed) |
| A7 | README structure (is/is-not table, real transcript, `<details>`) | engram | **ADAPT** | Legibility template + verifiable trust signals |
| B1 | Orchestrator: classify→route + lazy phase files + engagement-mode depth dial | pg | **ADOPT** | Effort tiering on Claude Code *without* a model knob |
| **B2** | **loop-protocol (oracle hierarchy, ratchet/plateau/oscillation, anti-gaming, ledger)** | pg | **ADOPT ★** | Rulebook for our benchmark/calibration loop |
| B3 | receipt-protocol with **`effort` field** | pg | **ADOPT** | `effort{files_read,written,tool_calls}` IS our cost signal |
| B4 | Dispatch formula + waves + visual identity (no-emoji, Unicode tiers, concrete counts) | pg | **ADOPT**/ADAPT | Right UX + launch pattern for a parallel benchmark matrix |
| B5 | Auto-update (local vs `raw.githubusercontent` plugin.json) | pg | **ADOPT** | Cheap freshness; offline-degrades-silent; copy full plugin |
| B6 | boundary-safety (Pattern 5: final-state grading) | pg | **ADAPT** | Grade final artifact vs rubric, not intermediate 200s |
| — | FSRS math itself; curriculum DAG/threshold machinery; pg's 14-agent SDLC roster | both | **SKIP** | Domain-specific to learning/SDLC; not effortmining's problem |

---

## PROPOSED effortmining REPO STRUCTURE

Synthesizes A1 (manifest), A3 (CLI spine), A4 (blind grader), A5 (calibration fit), B1 (orchestrator), B2/B3 (loop+receipt), B4 (visual/dispatch). Every piece is annotated with the pattern it descends from.

```
effortmining/
├── .claude-plugin/
│   ├── plugin.json                 # A1 — name, version (single source), skills, hooks, agents, keywords
│   └── marketplace.json            # A1 — {plugins:[{name, source:"./"}]}; version asserted == plugin.json
├── (.codex-plugin/plugin.json)     # A1/B6 — OPTIONAL Codex port; the natural home for real
│                                   #          per-agent model_reasoning_effort tiers (item 11)
├── README.md                       # A7 — banner+shields(selftest N/N), is/is-not table,
│                                   #      ASCII pipeline, real transcript (cheap tier passes easy /
│                                   #      fails hard task), collapsible CLI ref
├── CHANGELOG.md                    # A1 — versioning discipline
│
├── skills/
│   ├── calibrate/SKILL.md          # B1 — orchestrator: classify task → pick tier via calibration table →
│   │                               #      dispatch tiered agent → blind grade → (optional) refit.
│   │                               #      Resolves $BENCH="…/bench/effort.py"; all state via python3 "$BENCH".
│   │                               #      Shell-safety: task text/artifacts only via --file/stdin (A3).
│   │   └── phases/                 # B1 — lazy-loaded steps (01-classify, 02-dispatch, 03-grade, 04-fit)
│   ├── bench/SKILL.md              # B1 — run the benchmark matrix (N tiers × M tasks), emit receipts+report
│   └── _shared/
│       └── protocols/              # B2/B3/B4 — copied near-verbatim from pg (already proven)
│           ├── loop-protocol.md    # B2 ★ — oracle hierarchy, ratchet/plateau/oscillation, anti-gaming, ledger
│           ├── receipt-protocol.md # B3 — receipt schema incl. effort{} + loops[]
│           ├── visual-identity.md  # B4 — no-emoji, Unicode tiers, concrete-count completion lines
│           └── grading-contract.md # A4 — the blind-grader contract as a shared, versioned document
│
├── agents/
│   ├── effort-grader.md            # A4 ★ — BLIND grader. Input {task_id,prompt,rubric[],artifact} with NO
│   │                               #      tier/agent field. Skeptic-first, round-down, strict-JSON→bench record.
│   │                               #      (frontmatter: name/description/tools — Codex port sets
│   │                               #       model_reasoning_effort="medium", one tier below workers — item 11)
│   ├── task-author.md              # A6 — writes each task's rubric up front (non-producer of the answers)
│   └── worker-{low,med,high}.md    # B1/item 11 — effort-tiered worker VARIANTS. On Claude Code a "tier" is a
│                                   #      named bundle of prompt-depth + loop-budget (+ optional model); on
│                                   #      Codex each maps to model_reasoning_effort low/medium/high.
│
├── hooks/
│   ├── hooks.json                  # A2 — SessionStart (startup|resume|clear) → thin shell → python one-liner
│   └── session-start.sh            # A2 — self-resolving $ROOT, degrade-to-silence, slug-guard before echo
│                                   #      Ambient line: "[effort] 3 tasks miscalibrated · /calibrate" else silent
│
├── bench/                          # A3/A5 — the DETERMINISTIC CORE (stdlib-only python; LLM never computes)
│   ├── effort.py                   # A3 — verb-first JSON CLI: init | classify | dispatch-plan | record |
│   │                               #      calibrate | report | stats | doctor | selftest
│   │                               #      A5 — `calibrate` = engram's refit: guarded (min-N), clamped,
│   │                               #      receipt-fed fit of the tier-selection table; human-readable "read"
│   ├── tasks/                      # A6 — benchmark fixtures: one JSON per task {id, prompt, rubric[], checks?}
│   └── state/ (gitignored)         # A3 — JSON tables (calibration.json) + JSONL event logs
│                                   #      (receipts/<run>.jsonl, runs.jsonl); atomic writes, corrupt→quarantine
│
├── .orchestrator/
│   ├── receipts/                   # B3 — per-agent receipts (effort{} + grader verdict + loops[])
│   └── loops/                      # B2 — loop ledger: one file per calibration/benchmark loop
│
└── docs/
    ├── research/03-pattern-mining.md   # this file
    └── architecture.md                 # calibration-table design, tier definitions, oracle wiring
```

**Data-flow (how the pieces compose):**
`calibrate` skill classifies a task → reads `calibration.json` → picks the cheapest tier predicted to pass → dispatches `worker-<tier>` (dispatch formula B4, re-anchor from disk) → worker writes an artifact + a receipt with `effort{}` (B3) → **`effort-grader` (A4) grades blind** (payload has no tier label) → `bench/effort.py record` applies the verdict atomically (A4 consumer) → if a run is in `calibrate` mode, `effort.py calibrate` (A5) refits the tier table from accumulated receipts, guarded + clamped → loop governed by loop-protocol (B2: grader is the Tier-2 oracle; ratchet/plateau/oscillation decide stop). The whole thing is a benchmark whose oracle is a blind grader and whose product is a fitted effort-selection table.

**Why this shape:** it is engram's architecture (deterministic CLI + blind assessor + guarded fitting loop) wearing production-grade's clothes (mode-scaled orchestration + oracle-loop + receipt/effort telemetry + mission-control UX) — the exact synthesis the two source repos were already converging toward, retargeted from "keep what you learned" / "ship production code" to "spend the least effort that still passes."
