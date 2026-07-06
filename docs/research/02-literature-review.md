# 02 — Literature Review & Prior-Art Scan

**Task:** R2 (data-scientist) · **Date:** 2026-07-06 · **Status:** complete

> Scope: (a) what research says about matching test-time compute / reasoning effort to task
> difficulty, (b) what effort/thinking knobs vendors ship, (c) whether anyone has already
> productized closed-loop per-subagent effort calibration in an agent harness.
>
> **Citation discipline:** every source below was fetched and verified (arxiv abstract page or
> official docs/blog). Numbers are quoted from the source, not memory. Claims I could not verify
> against a primary source were dropped or downgraded and are listed in §10.

---

## 1. TL;DR + Niche Verdict

**The niche is real, but narrower than "nobody thought of this," and we must say so honestly.**

Three things are established by the evidence:

1. **Difficulty-adaptive test-time compute is settled science.** Spending more inference compute
   helps *hard* problems and is wasted on *easy* ones; allocating compute *by difficulty* beats
   uniform allocation. This is shown from foundational adaptive-computation work (Graves 2016;
   PonderNet 2021) through the modern reasoning-model era (Snell et al. 2024: compute-optimal
   scaling beats a 14× larger model; s1 2025; and a large "efficient reasoning" / "overthinking"
   literature with two dedicated 2025 surveys). Overthinking on easy inputs is quantified: o1-like
   models burn **1,953% more tokens** than conventional models to answer "2+3" (Chen et al. 2024).

2. **Vendors ship *static* effort knobs — plus one class of partial exception.** Anthropic
   (`effort`: low/medium/high/xhigh/max), OpenAI (`reasoning.effort`: none…xhigh), Google Gemini
   (`thinkingBudget`, `thinking_level`), Qwen3 (`thinking_budget`), and DeepSeek (`reasoning_effort`)
   all expose a **manually-set** dial. The partial exception is **model-internal auto-calibration**:
   Gemini's dynamic thinking (`thinkingBudget = -1`) and Anthropic's adaptive thinking
   (`thinking: {type:"adaptive"}`) let a *single model* decide its own thinking depth *per request*.
   That is auto-calibration, but it is (i) single-model, (ii) per-request, (iii) internal/opaque —
   **not** an outer loop that assigns effort **per subagent** in a multi-agent harness based on
   measured outcomes.

3. **No shipped system closes the loop per-subagent in an agent harness.** The per-subagent effort
   *knob* already exists in Claude Code (Agent SDK `AgentDefinition.effort`, overriding session
   effort; subagent frontmatter), and Anthropic's own docs say to use `low` effort "like subagents"
   and to "adjust effort based on task complexity" — but leave that calibration to the developer.
   Automatic effort selection is an **open, recurring feature request** across at least three
   harnesses (Claude Code #43083 open, #37783 closed-as-duplicate; OpenAI Codex #8649; OpenCode
   #21483). The closest *research* is **Ares** (Mar 2026): an outcome-labeled router that picks
   effort **per decision-step within one agent's loop** (up to 52.7% token cut), and **DART**
   (Jun 2026): per-query draft-agreement thinking budgets. Both are unshipped prototypes and
   neither operates **per-subagent** as a calibration layer in a production harness.

**Verdict for effortmining:** the defensible, unfilled niche is *"a shipped, benchmark-calibrated,
per-subagent effort-assignment layer for a production agent harness (Claude Code)."* We should
**not** claim to have invented difficulty-adaptive compute (Snell/Ares/DART did the science) or the
knob (Anthropic ships it). We *should* claim: (i) nobody has empirically measured effort-vs-quality
per subagent role and baked the winning setting into configs; (ii) the demand is proven by
duplicate feature requests; (iii) the economics are large (Anthropic: multi-agent systems use ~15×
the tokens of chat; token usage explains ~80% of performance variance). **Ares is our nearest
neighbor and the honest baseline to cite and differentiate against.**

---

## 2. Test-Time Compute Scaling

**Snell, Lee, Xu, Kumar (2024) — "Scaling LLM Test-Time Compute Optimally can be More Effective than
Scaling Model Parameters"** · arXiv **2408.03314** (6 Aug 2024).
The foundational modern result. Proposes a *compute-optimal* strategy that **allocates test-time
compute per prompt by difficulty**. Headline numbers (from abstract): improves test-time-compute
efficiency by **more than 4×** vs a best-of-N baseline; in a FLOPs-matched comparison, test-time
compute lets a model **outperform a 14× larger model** on problems where the smaller model already
has a reasonable success rate. *Relevance:* this is the scientific spine of effortmining — the
optimal amount of inference compute is a **function of task difficulty**, not a constant. Directly
motivates per-task (and by extension per-subagent) effort assignment.

**Muennighoff et al. (2025) — "s1: Simple test-time scaling"** · arXiv **2501.19393** (31 Jan 2025).
Introduces **budget forcing**: control test-time compute by forcibly terminating or extending the
model's thinking. Trained on only **1,000 curated reasoning samples** (Qwen2.5-32B-Instruct →
s1-32B). Numbers: exceeds o1-preview on competition math by **up to 27%** (MATH, AIME24); budget
forcing scales AIME24 accuracy **from 50% to 57%**. *Relevance:* demonstrates that a *simple,
external* control over thinking length moves quality monotonically on hard tasks — the exact lever
effortmining tunes, and evidence that the lever is cheap to operate.

**OpenAI o1/o3 deliberation scaling.** Widely reported that o-series accuracy rises with
inference-time "thinking." I did **not** find a single canonical OpenAI page stating a clean
train-vs-test scaling figure to quote verbatim, so I do not assign a number here; the vendor-side
manifestation of this idea is the `reasoning.effort` knob documented in §6. (Downgraded rather than
cite an unverifiable figure.)

---

## 3. Overthinking / Reasoning Economy

**Chen et al. (2024) — "Do NOT Think That Much for 2+3=? On the Overthinking of o1-Like LLMs"** ·
arXiv **2412.21187** (30 Dec 2024; v2 1 Feb 2025).
Quantifies wasted compute on easy inputs. On "what is 2 plus 3?", o1-like models consumed
**1,953% more tokens** than conventional models for the same answer (one model emitted 13 solutions
= 901 tokens when 39 sufficed). Introduces **outcome efficiency** (fraction of tokens that help
accuracy): QwQ-32B scores only **41.9%** on ASDIV (easiest), **50.7%** on GSM8K, **52.3%** on
MATH500 — i.e. roughly half of tokens add no accuracy. Their mitigation cuts MATH500 tokens by
**48.6%** at maintained accuracy; on GSM8K, **772.8 → 416.6 tokens (~46%)** *with accuracy rising
94.8% → 96.0%*. *Relevance:* the empirical core of "flat quality on easy tasks" — the predicted
shape of effortmining's easy-task benchmark curve.

**Han et al. (2024) — "Token-Budget-Aware LLM Reasoning" (TALE)** · arXiv **2412.18547** (24 Dec 2024).
Dynamically sets a token budget per problem by estimated complexity. Reduces output token cost by
**68.64% on average** with only slight accuracy loss; on GSM8K-Zero, **252.96 → 22.67 tokens** while
holding **98.72% accuracy**. *Relevance:* a difficulty-conditioned budget yields ~2/3 token savings
at matched quality — a concrete effect size to expect on easy/medium subagent tasks.

**Aggarwal & Welleck (2025) — "L1: Controlling How Long A Reasoning Model Thinks With RL" (LCPO)** ·
arXiv **2503.04697** (6 Mar 2025).
RL that makes a model obey a user-specified CoT length, enabling a smooth cost/accuracy trade.
Numbers: L1 beats s1's length control by **over 100–150% relative and 20–25% absolute** at 512/1024
token budgets; a **1.5B** L1-Max **surpasses GPT-4o at matched generation length** (~2% avg). *Relevance:*
shows the effort/length axis is a controllable, near-monotone quality dial — the axis we benchmark.

**Zhang et al. (2025) — "AdaptThink: Reasoning Models Can Learn When to Think"** · arXiv **2505.13417**
(19 May 2025; EMNLP 2025).
RL that lets a model choose **Thinking vs NoThinking** by difficulty. Reduces average response length
of DeepSeek-R1-Distill-Qwen-1.5B by **53%** *and improves accuracy by 2.4%*; the model selects
NoThinking predominantly on easy sets and shifts to Thinking as difficulty rises. *Relevance:* the
binary "should this subagent think at all?" decision, learned — the coarsest version of our knob.

**Surveys (umbrella citations):**
- **Sui et al. (2025) — "Stop Overthinking: A Survey on Efficient Reasoning for LLMs"** ·
  arXiv **2503.16419** (20 Mar 2025; TMLR 2025). Names the **"overthinking phenomenon"** (verbose,
  redundant outputs) and taxonomizes efficient-reasoning methods (model optimization, dynamic step
  reduction, prompt-based). Establishes that overthinking is a recognized, surveyed problem.
- **Alomrani et al. (2025) — "Reasoning on a Budget: A Survey of Adaptive and Controllable
  Test-Time Compute in LLMs"** · arXiv **2507.02076** (2 Jul 2025). Proposes a two-tier taxonomy —
  **L1-controllability** (methods under a *fixed* budget) vs **L2-adaptiveness** (dynamically scale
  inference by *input difficulty or model confidence*) — and states current models "apply uniform
  inference-time compute regardless of task complexity" as the gap. *This survey frames exactly
  effortmining's field; L2-adaptiveness is our target quadrant.*

---

## 4. Difficulty Estimation & Adaptive Computation

**Graves (2016) — "Adaptive Computation Time for Recurrent Neural Networks"** · arXiv **1603.08983**.
The origin of learned, input-dependent compute: a differentiable **halting** mechanism (with a
"ponder cost") lets an RNN spend more steps on harder-to-predict transitions. *Relevance:* the
15-year-old intellectual ancestor of "spend effort proportional to difficulty."

**Banino, Balaguer, Blundell (2021) — "PonderNet: Learning to Ponder"** · arXiv **2107.05407**.
Learns to **adapt computation to problem complexity** end-to-end via a learned halting distribution,
improving the accuracy/compute trade and generalization. *Relevance:* formalizes difficulty→compute
as a learned policy — the research template our benchmark approximates empirically (offline) rather
than via gradient learning.

**Lee et al. (2026) — "DART: Draft-Agreement Routing for Training-Free Adaptive Thinking Budgets in
Hybrid Reasoning Models"** · arXiv **2606.23181** (22 Jun 2026).
A **training-free**, per-query difficulty estimator: sample two cheap no-think drafts; if they
agree, answer directly; if they disagree, predict a thinking budget from **draft entropy**. Numbers:
math **+9.0 points** accuracy at **15–69% fewer** thinking tokens; code **+22.5 points** at
**51–63% fewer** thinking tokens; generalizes across 0.6B–32B. *Relevance:* a lightweight,
model-agnostic difficulty signal (draft agreement) — a candidate *runtime* estimator effortmining
could layer on top of its offline per-role calibration. Adjacent prior art (see §8).

*(AdaptThink §3 and Ares §8 also belong to this category — difficulty-conditioned compute.)*

---

## 5. Model Routing & Cascades (adjacent axis — routes *models*, not *effort*)

**Chen, Zaharia, Zou (2023) — "FrugalGPT"** · arXiv **2305.05176**.
LLM **cascade**: try cheap models first, escalate on low confidence. Up to **98% cost reduction**
while matching GPT-4, or **+4% accuracy** over GPT-4 at equal cost; notes API prices differ by two
orders of magnitude. *Relevance:* proves cost-vs-quality is huge and controllable — but the control
variable is **which model**, not **how much effort per model**. effortmining is orthogonal/complementary.

**Ong et al. (2024) — "RouteLLM: Learning to Route LLMs with Preference Data"** · arXiv **2406.18665**
(26 Jun 2024; ICLR 2025).
Trains routers to send queries to a strong vs weak model. Per the LMSYS RouteLLM release, routers
achieve **>85% cost reduction on MT-Bench** (also ~45% MMLU, ~35% GSM8K) while retaining **95% of
GPT-4 performance** (matrix-factorization router sends only ~14% of queries to GPT-4). *(Note: the
arxiv abstract states only "cost reductions of over 2 times"; the 85%/95% figures are from the
LMSYS blog/framework, cited as such.)* *Relevance:* same as FrugalGPT — a **model** dial, not an
**effort** dial. We cite these as the well-known neighbors to *contrast* effortmining against, not
as our niche.

---

## 6. Vendor Effort / Thinking Knobs (official docs — Tier-1 verified 2026-07-06)

**Anthropic — `effort` (current primary control).** Source: platform.claude.com `.../build-with-claude/effort`.
Parameter `output_config.effort`; levels **`low` · `medium` · `high` (default) · `xhigh` · `max`**
(availability is model-dependent). Supported on **Claude Fable 5, Mythos 5, Opus 4.8, Opus 4.7,
Opus 4.6, Sonnet 5, Sonnet 4.6, and Opus 4.5**. Key facts: `high` == omitting the parameter;
effort is "a **behavioral signal, not a strict token budget**"; it affects **all** output tokens
including tool calls (lower effort ⇒ fewer tool calls). The docs table lists **`low`** use-case as
*"Simpler tasks that need the best speed and lowest costs, **like subagents**,"* and Best-Practice #4
says *"**Consider dynamic effort:** Adjust effort based on task complexity."* — i.e. Anthropic
explicitly recommends per-task/dynamic effort **but ships no calibrator**.

**Anthropic — `effort` (launch numbers).** Source: anthropic.com/news/claude-opus-4-5 (Opus 4.5,
model `claude-opus-4-5-20251101`, 24 Nov 2025). At **medium** effort, Opus 4.5 **matches Sonnet 4.5's
best SWE-bench Verified score using 76% fewer output tokens**; at **highest** effort it **exceeds
Sonnet 4.5 by 4.3 percentage points while using 48% fewer tokens**. This is the cleanest published
proof that the effort dial buys large token savings at held-or-better quality — the exact win
effortmining industrializes per subagent.

**Anthropic — extended thinking `budget_tokens` (legacy / being deprecated).** Source:
platform.claude.com `.../extended-thinking`. `thinking: {type:"enabled", budget_tokens: N}` sets the
**maximum** internal reasoning tokens (Claude may use fewer; must be **< `max_tokens`**). On Opus
4.6 / Sonnet 4.6 `budget_tokens` is **deprecated in favor of `effort` + adaptive thinking**; on Opus
4.7 / Sonnet 5 / Opus 4.8 / Fable 5 manual `budget_tokens` is unsupported (400 error). *(I could not
verify a "minimum 1024" from the live doc, so I do not state one — see §10.)*

**Anthropic — adaptive thinking (`thinking: {type:"adaptive"}`).** The model decides *when and how
much* to think per request; always-on for Fable 5 / Mythos 5 / Sonnet 5. **This is Anthropic's
single-model auto-calibration** — the partial exception, analogous to Gemini dynamic thinking.

**OpenAI — `reasoning.effort`.** Source: developers.openai.com `/api/docs/guides/reasoning`. Values
**`none` · `minimal` · `low` · `medium` · `high` · `xhigh`** (subset per model). GPT-5.5 defaults to
`medium`. "Lower effort favors speed and token usage; higher effort thinks more completely." Static,
developer-set.

**Google Gemini — `thinkingBudget` + dynamic thinking (the key partial exception).** Source:
ai.google.dev/gemini-api/docs/thinking + Google Cloud docs. `thinkingConfig.thinkingBudget` is an
integer token cap (Gemini 2.5 Flash: **0–24,576**, `0` disables where allowed). **`thinkingBudget = -1`
enables *dynamic thinking*: the model automatically sizes its thinking budget to the request's
complexity**, and dynamic is the default when unspecified. *This is genuine auto-calibration — but
single-model, per-request, internal.* **Freshness note:** as of 2026-07, Gemini docs also expose a
newer `thinking_level` enum (`minimal/low/medium/high`) alongside `thinkingBudget` (the two can
conflict), mirroring the industry move toward semantic effort levels.

**Qwen3 — `thinking_budget` + `enable_thinking`.** Source: qwenlm.github.io/blog/qwen3 + Alibaba
Model Studio docs. `extra_body={"enable_thinking": True, "thinking_budget": N}` caps reasoning
tokens (on hitting the cap the model stops thinking and answers); soft switches `/think` and
`/no_think` per turn; defaults to the model's max CoT length. Static, developer-set.

**DeepSeek — hybrid thinking (`enable_thinking`, `reasoning_effort`).** Source: api-docs.deepseek.com
+ Alibaba Model Studio. V3.1 is a hybrid thinking/non-thinking model; `enable_thinking` toggles
mode; `reasoning_effort` accepts **`high` / `max`** (default `high`). Static, developer-set.

> **Cross-vendor pattern:** every vendor now ships a *semantic effort level* and/or a *token budget*,
> almost all **manually set**. The only auto-calibration shipped is **model-internal, single-model,
> per-request** (Gemini dynamic thinking, Anthropic adaptive thinking). None decides effort **per
> subagent** from **measured task outcomes**.

---

## 7. Agent-Harness Economics

**Anthropic (2025) — "How we built our multi-agent research system"** (anthropic.com/engineering).
The economic case for caring about per-subagent spend. Verified figures: *"agents typically use
about **4× more tokens** than chat interactions, and multi-agent systems use about **15× more
tokens** than chats."* In their BrowseComp analysis, *"token usage by itself explains **80% of the
variance**,"* with tool calls and model choice as the other factors (three factors ≈ 95% of variance).
Anthropic hand-codes effort heuristics into prompts: *"Simple fact-finding requires just 1 agent
with 3–10 tool calls, direct comparisons might need 2–4 subagents with 10–15 calls each, and complex
research might use more than 10 subagents."* Parallelization *"cut research time by up to 90%."*
*Relevance:* (i) the 15× multiplier makes per-subagent effort the single biggest cost lever; (ii)
token usage dominates performance variance — so any effort A/B **must control for tokens**; (iii)
Anthropic's own effort allocation is **static prompt guidance**, precisely the manual step
effortmining replaces with measurement.

**SWE-Effi / "Effectiveness under Token Budget" (EuTB)** · arXiv **2509.09853** (and related SWE-agent
evaluations). Re-evaluates coding agents by **token efficiency**, not just resolution rate (e.g.
OpenHands ~34% resolution with Qwen3-32B at EuTB ~22.7%); notes SWE-agent/OpenHands are typically run
at **medium reasoning effort** to balance cost and accuracy. *Relevance:* prior art for **how to
score** effort experiments — an efficiency-under-budget metric effortmining's benchmark should adopt.

---

## 8. Prior-Art Scan (the critical section)

Search trail (WebSearch/WebFetch, 2026-07-06): "claude code subagent reasoning effort thinking
budget plugin"; "'adaptive thinking budget' OR 'dynamic reasoning effort' router middleware github";
"automatically calibrate reasoning effort per subagent agent harness closed loop 2026"; "CrewAI
LangGraph AutoGen per-agent thinking budget reasoning effort"; "OpenHands SWE-agent reasoning effort
budget compute policy"; "reasoning effort optimizer npm pypi auto select task difficulty";
"AdaptThink…"; "Ares adaptive reasoning effort"; "DART draft-agreement thinking budget"; plus direct
fetches of Claude Code docs, the Agent SDK reference, and GitHub issues #37783 / #43083.

**Closest research prototypes:**

- **Ares — "Adaptive Reasoning Effort Selection for Efficient LLM Agents"** (Yang et al.) ·
  arXiv **2603.07915** (9 Mar 2026). **CLOSEST prior art.** A lightweight router predicts the *lowest
  appropriate reasoning level for each decision step* within **one agent's multi-turn loop** (levels
  high/medium/low), trained via a **data pipeline that identifies the minimum effort for successful
  step completion** — i.e. **outcome-labeled, closed-loop** calibration. Up to **52.7% token
  reduction** vs fixed high-effort with "minimal degradation" on TAU-Bench, BrowseComp-Plus,
  WebArena. **What it lacks vs effortmining:** it is **per-step within a single agent**, not
  **per-subagent across a multi-agent harness**; it is a **research prototype** (fine-tuned router
  model), not a shipped Claude Code plugin operating the vendor's black-box `effort` knob; and it
  calibrates online per-step rather than deriving a reusable per-role effort setting from offline
  A/B benchmarks. *Overlap: HIGH on concept; our differentiation is granularity (subagent-role),
  productization (shipped harness plugin), and method (black-box benchmark calibration).*

- **DART** · arXiv **2606.23181** (22 Jun 2026). Training-free **per-query** thinking-budget predictor
  via draft agreement/entropy (§4). **Adjacent** — per-query, not per-subagent; a runtime estimator,
  not a harness calibration layer.

**Shipped / mechanism-level tools (all fall short of closed-loop per-subagent calibration):**

- **Claude Code / Agent SDK — the knob itself.** `AgentDefinition.effort`
  (`"low"|"medium"|"high"|"xhigh"|"max"|number`) **overrides session effort per subagent** (SDK
  `agents` param); subagent frontmatter supports `effort`; docs recommend `low` for subagents. **This
  validates effortmining's premise (the per-subagent knob exists) — but the *value* is a manual human
  choice; there is no calibrator.** OVERLAP on mechanism, **zero** on calibration.
- **Pydantic AI harness** — exposes `get_reasoning_effort_router()`, a hook where a capability can
  supply a router (e.g. "force HIGH during planning"). **ADJACENT:** a *mechanism* for effort routing,
  but the policy is user-written and **rule/phase-based**, not benchmarked or outcome-calibrated.
- **`@howaboua/pi-auto-reasoning-tool` (npm)** — gives the agent a `change_reasoning` tool to pick its
  own `low/medium/high`. **ADJACENT:** **self-selection** by the agent, not an outer measured
  calibration; no benchmarking, no per-subagent policy.
- **Model routers (RouteLLM, FrugalGPT, and 2026 gateways)** — route **models**, not **effort** (§5).
  FAR from niche on the control variable.
- **Gemini dynamic thinking / Anthropic adaptive thinking** — **single-model, per-request**
  auto-calibration (§6). ADJACENT but not per-subagent and not harness-level.

**Demand signal (the niche is wanted and unshipped):** auto-effort is an **open, recurring** request.
- Claude Code **#43083 "configurable reasoning effort level for subagents"** — **OPEN**
  (`area:agents`, `enhancement`): today only *model* is configurable per subagent via the Agent tool;
  effort is controllable only at the parent level. Requester's use case: a **28-agent** orchestration
  where code-writing / review / lookup agents each need different effort.
- Claude Code **#37783 "Auto-effort: dynamically adjust reasoning effort based on prompt complexity"**
  — **CLOSED as duplicate** (a Haiku-tier classifier picks effort before the main model runs).
  Closed-as-dup = the ask recurs.
- Claude Code **#25669** (effort/thinking for Task-tool subagents), **OpenAI Codex #8649** ("Auto"
  reasoning tiering), **OpenCode #21483** (auto-select effort by task complexity) — same request,
  three more harnesses.

**Conclusion of the scan:** the **knob** is shipped and the **science** exists (Snell, Ares, DART),
but **no shipped product/plugin performs closed-loop, benchmark-calibrated, per-subagent effort
assignment inside a production agent harness.** Ares is the one system doing outcome-labeled adaptive
effort for agents, and it is (a) per-step not per-subagent, (b) an unshipped research prototype. That
is the honest boundary of our niche.

---

## 9. Synthesis — The Evidence-Backed Case

**(i) Difficulty-adaptive compute is established science.** Compute-optimal test-time scaling beats a
14× larger model and is >4× more efficient than best-of-N (Snell 2024); the field has two 2025
surveys and an explicit **L2-adaptiveness** category (Alomrani 2025). Overthinking on easy inputs is
quantified at up to **1,953% wasted tokens** (Chen 2024) with ~50% "outcome efficiency," and multiple
methods recover **53–69% of tokens at held/better accuracy** (AdaptThink 53%; TALE 68.64%; DART
15–69%). → *Adaptive effort is real and the effect sizes are large.*

**(ii) Vendors ship static knobs, with model-internal auto-thinking as the only shipped exception.**
Anthropic `effort` (5 levels), OpenAI `reasoning.effort` (6 levels), Gemini `thinkingBudget`/
`thinking_level`, Qwen3 `thinking_budget`, DeepSeek `reasoning_effort` — all **manually set**. The
one auto-calibration shipped is **single-model, per-request** (Gemini `-1` dynamic thinking;
Anthropic adaptive thinking). Anthropic's docs even *recommend* dynamic, per-task, subagent-aware
effort — and leave the decision to the developer. → *The dial exists; the policy for setting it does
not ship.*

**(iii) No shipped system closes the loop per-subagent in a harness.** The per-subagent knob exists
(Claude Code SDK), auto-selection is an open feature request in ≥3 harnesses, and the nearest
research (Ares) is per-step and unshipped. → *effortmining's niche — a shipped, benchmark-calibrated,
per-subagent effort layer — is genuinely unoccupied, provided we position honestly against Ares and
against model-internal adaptive thinking.*

**Honest caveats we must carry forward:** (1) Ares already demonstrates outcome-labeled adaptive
effort for agents — we are not first to the *idea*, only to the *per-subagent, shipped, black-box-knob*
instantiation. (2) Model-internal adaptive thinking may erode part of the win: if the model already
self-regulates thinking per request, the *marginal* value of an outer effort setting is an empirical
question our benchmark must measure (not assume). (3) Because token usage explains ~80% of
performance variance (Anthropic), effort A/Bs must report **quality at matched token budgets**, or
the result is confounded.

---

## 10. Verified-Citation List

*All entries fetched & confirmed on 2026-07-06. Numbers quoted from source.*

| # | Citation | ID / URL | Verified numbers |
|---|----------|----------|------------------|
| 1 | Snell, Lee, Xu, Kumar (2024), *Scaling LLM Test-Time Compute Optimally…* | arXiv 2408.03314 | >4× vs best-of-N; beats 14× larger model (FLOPs-matched) |
| 2 | Muennighoff et al. (2025), *s1: Simple test-time scaling* | arXiv 2501.19393 | 1,000 samples; +27% vs o1-preview; AIME24 50%→57% |
| 3 | Chen et al. (2024), *Do NOT Think That Much for 2+3=?* | arXiv 2412.21187 | 1,953% more tokens on "2+3"; outcome-eff 41.9/50.7/52.3%; −48.6% MATH500 tokens |
| 4 | Han et al. (2024), *Token-Budget-Aware LLM Reasoning (TALE)* | arXiv 2412.18547 | −68.64% tokens avg; GSM8K-Zero 252.96→22.67 @ 98.72% |
| 5 | Aggarwal & Welleck (2025), *L1 / LCPO* | arXiv 2503.04697 | +100–150% rel / 20–25% abs over s1; 1.5B > GPT-4o at matched length |
| 6 | Zhang et al. (2025), *AdaptThink* (EMNLP 2025) | arXiv 2505.13417 | −53% length, +2.4% accuracy (R1-Distill-Qwen-1.5B) |
| 7 | Graves (2016), *Adaptive Computation Time for RNNs* | arXiv 1603.08983 | (foundational; differentiable halting / ponder cost) |
| 8 | Banino et al. (2021), *PonderNet: Learning to Ponder* | arXiv 2107.05407 | (learned halting; adapts compute to complexity) |
| 9 | Chen, Zaharia, Zou (2023), *FrugalGPT* | arXiv 2305.05176 | up to 98% cost cut @ GPT-4 parity; +4% acc at equal cost |
| 10 | Ong et al. (2024), *RouteLLM* (ICLR 2025) | arXiv 2406.18665 | LMSYS: >85% MT-Bench cost cut @ 95% GPT-4 perf (abstract: ">2×") |
| 11 | Yang et al. (2026), *Ares: Adaptive Reasoning Effort Selection* | arXiv 2603.07915 | up to −52.7% tokens vs fixed-high; per-step, outcome-labeled router |
| 12 | Lee et al. (2026), *DART: Draft-Agreement Routing…* | arXiv 2606.23181 | math +9.0pts/−15–69% tok; code +22.5pts/−51–63% tok; training-free |
| 13 | Sui et al. (2025), *Stop Overthinking* (survey, TMLR 2025) | arXiv 2503.16419 | names "overthinking phenomenon"; 3-way taxonomy |
| 14 | Alomrani et al. (2025), *Reasoning on a Budget* (survey) | arXiv 2507.02076 | L1-controllability vs L2-adaptiveness taxonomy |
| 15 | (context) *SWE-Effi / EuTB* | arXiv 2509.09853 | token-efficiency eval; OpenHands ~34% resolve / EuTB ~22.7% |
| V1 | Anthropic — Opus 4.5 announcement | anthropic.com/news/claude-opus-4-5 | medium: =Sonnet 4.5 SWE-bench @ −76% output tokens; high: +4.3pp @ −48% tokens; `claude-opus-4-5-20251101` |
| V2 | Anthropic — `effort` docs | platform.claude.com/docs/en/build-with-claude/effort | levels low/medium/high(default)/xhigh/max; `output_config.effort`; "low…like subagents"; behavioral signal not strict budget |
| V3 | Anthropic — extended thinking | platform.claude.com/docs/en/docs/build-with-claude/extended-thinking | `thinking:{type:enabled,budget_tokens}`; max not target; < `max_tokens`; deprecated for effort on 4.6+ |
| V4 | Anthropic — multi-agent research system | anthropic.com/engineering/multi-agent-research-system | agents ~4× / multi-agent ~15× chat tokens; token usage = 80% of variance; parallel −90% time |
| V5 | OpenAI — reasoning guide | developers.openai.com/api/docs/guides/reasoning | `reasoning.effort` none/minimal/low/medium/high/xhigh; GPT-5.5 default medium |
| V6 | Google — Gemini thinking | ai.google.dev/gemini-api/docs/thinking | `thinkingBudget` (2.5 Flash 0–24,576); **−1 = dynamic thinking**; newer `thinking_level` enum |
| V7 | Qwen3 — thinking budget | qwenlm.github.io/blog/qwen3 | `enable_thinking` + `thinking_budget`; `/think` `/no_think` |
| V8 | DeepSeek — V3.1 hybrid thinking | api-docs.deepseek.com | `enable_thinking`; `reasoning_effort` high/max (default high) |
| P1 | Claude Code — Agent SDK / subagents | code.claude.com/docs/en/agent-sdk/typescript; /sub-agents | `AgentDefinition.effort` overrides session effort per subagent |
| P2 | Claude Code issue #43083 (OPEN) | github.com/anthropics/claude-code/issues/43083 | requests configurable per-subagent effort; only model configurable today |
| P3 | Claude Code issue #37783 (CLOSED-dup) | github.com/anthropics/claude-code/issues/37783 | auto-effort by prompt complexity (Haiku classifier) |
| P4 | Pydantic AI harness #84 | github.com/pydantic/pydantic-ai-harness/issues/84 | `get_reasoning_effort_router()` hook; rule/phase-based |
| P5 | `@howaboua/pi-auto-reasoning-tool` (npm) | pi.dev package | agent self-selects effort via `change_reasoning` tool |

**Rejected / downgraded claims (citation discipline):**
- *"budget_tokens minimum = 1024"* — **dropped**; not stated on the live extended-thinking doc I
  fetched. Not cited from memory.
- *AdaptThink NoThinking selection rates (86.9% GSM8K / 40.4% AIME24)* — **downgraded to qualitative**;
  these came from a secondary Substack, not the arxiv abstract (which confirms only −53% / +2.4%).
- *RouteLLM "85% cost @ 95% GPT-4"* — **re-sourced**: attributed to the LMSYS RouteLLM blog/framework,
  since the arxiv abstract states only "over 2 times" cost reduction. Not presented as an abstract claim.
- *OpenAI o1/o3 canonical train-vs-test scaling figure* — **not asserted**; no single official page
  found to quote a clean number.

---

## 11. Implications for Benchmark Design

The literature makes sharp, testable predictions for effortmining's A/B benchmark. Design to detect
these shapes:

1. **Expect a difficulty × effort interaction (the core hypothesis).** On **easy** subagent tasks,
   quality should be **flat across effort** while tokens fall steeply — the Pareto win is "same
   quality, far fewer tokens." Evidence for the magnitude: Opus 4.5 **medium = high quality at −76%
   output tokens** on SWE-bench (V1); TALE **−68.64%** at matched accuracy; AdaptThink **−53%** with
   *+2.4%* accuracy; DART **−15–69%**. → *Predicted easy-task effect: quality Δ ≈ 0, token Δ ≈
   −50% to −75%.* Power the benchmark to detect a **null quality effect** (equivalence test), not just
   a difference.

2. **Expect effort-sensitive quality on hard tasks, with diminishing returns and an overthinking
   plateau.** On **hard** tasks quality should **rise with effort** then flatten/regress: s1 AIME
   **50→57%** via budget forcing; Opus 4.5 high **+4.3pp** SWE-bench; DART code **+22.5pts**; but
   Anthropic warns `max` "can lead to overthinking" and Chen 2024 shows accuracy can *improve* when
   tokens are *cut*. → *Predicted hard-task effect: monotone-but-saturating quality gain of ~single
   digits to ~20 points, with a non-monotone tail at `max`.* Include a `max`-vs-`high` contrast to
   catch overthinking regressions.

3. **Control for tokens — token usage explains ~80% of performance variance** (V4). Report **quality
   at matched token budget** (or token-normalized quality / an EuTB-style efficiency-under-budget
   metric, §7) so effort effects aren't confounded by raw spend. Log tokens, tool-call count, and
   model as covariates (Anthropic's three variance factors).

4. **Difficulty must be an explicit, graded factor.** Every cited method conditions on difficulty
   (Snell bins by difficulty; L2-adaptiveness by definition). Build a **task-difficulty gradient**
   (e.g. trivial lookup → single-file edit → multi-file refactor → open-ended research) and measure
   the effort-response curve *within each rung*. The predicted signal is a **crossover**: low effort
   Pareto-dominates on the easy rungs; high/xhigh dominates on the hard rungs.

5. **Per-subagent, not per-prompt, is our unit — and the economic multiplier is large.** With
   multi-agent systems at **~15× chat tokens** (V4), calibrating a handful of recurring subagent
   *roles* (searcher, reviewer, implementer, summarizer) captures most of the savings. Design the
   benchmark around **subagent roles** (matching the Anthropic guidance and issue #43083's 28-agent
   use case), and express results as an **effort-per-role recommendation table** with measured
   quality/token trade-offs.

6. **Baseline against the real alternatives.** The benchmark's control arms should be: (a) session
   default (`high`) applied to all subagents; (b) Anthropic's static heuristic ("low for subagents");
   (c) model-internal adaptive thinking left to self-regulate; and, as the research ceiling, (d) an
   Ares-style per-step router if feasible. effortmining wins only if its **calibrated per-role
   settings** beat (a)–(c) on token-normalized quality — that is the number that proves the niche.

---

*End of 02-literature-review.md*
