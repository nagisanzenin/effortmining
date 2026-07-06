# Freshness Protocol — Temporal Sensitivity for Volatile Data

**Core principle: Never trust your training data for things that change frequently. Verify before you implement.**

LLMs confidently produce outdated model IDs, wrong pricing, deprecated APIs, old package versions, and stale configuration syntax. This protocol makes you aware of what data decays and when to verify it.

---

## Volatility Tiers

### Tier 1 — Critical (changes in days to weeks) → MUST WebSearch before using

- **LLM/AI model IDs and capabilities** — model names, context windows, pricing, rate limits, feature support (e.g., `gpt-4o`, `claude-sonnet-4-20250514`, `gemini-2.0-flash`)
- **API pricing** — any cloud service, SaaS, or API provider pricing (changes without notice)
- **Security advisories** — active CVEs, vulnerability disclosures, compromised packages
- **SDK breaking changes** — major version releases that change API surface (e.g., OpenAI SDK v4→v5, LangChain 0.1→0.2)
- **Deprecated features** — APIs, services, or flags marked for removal

**Action:** Stop. WebSearch for the current state. Cite what you found. Then implement.

### Tier 2 — High (changes in weeks to months) → WebSearch when writing config or dependencies

- **Package/library versions** — latest stable versions of frameworks, libraries, tools (npm, pip, cargo, go)
- **Framework APIs** — Next.js, React, Vue, Svelte, NestJS, FastAPI major version APIs
- **Docker base image tags** — current LTS/stable tags (e.g., `node:22-alpine`, `python:3.13-slim`)
- **Cloud provider services** — AWS/GCP/Azure service names, SKUs, regions, feature availability
- **Terraform/Pulumi provider schemas** — resource names, required fields, new features
- **CI/CD platform syntax** — GitHub Actions, GitLab CI, CircleCI workflow syntax and available actions
- **OAuth/auth provider flows** — provider-specific endpoints, scopes, token formats
- **CLI tool flags** — flags and subcommands for tools like `docker`, `kubectl`, `terraform`, `gh`

**Action:** WebSearch when you're about to write a version number, config block, or integration code. Use the verified version/syntax.

### Tier 3 — Medium (changes in months to quarters) → WebSearch if uncertain

- **Browser APIs and compatibility** — Web APIs, CSS features, browser support
- **Recommended crypto algorithms** — current best practices for hashing, encryption, key derivation
- **Compliance frameworks** — SOC2, HIPAA, GDPR requirement updates
- **Infrastructure best practices** — recommended instance types, scaling patterns, cost optimization

**Action:** If you feel uncertain or the recommendation is version-specific, search. If you're confident and the guidance is fundamental, proceed.

### Tier 4 — Stable (changes over years) → Trust training data

- Language fundamentals (syntax, type systems, standard libraries)
- Protocols (HTTP, TCP/IP, WebSocket, gRPC)
- SQL and database fundamentals
- Algorithms and data structures
- Design patterns and architecture principles
- Git operations

**Action:** Proceed without searching. These rarely change in ways that break code.

---

## When to Search — Decision Flow

```
Am I about to write a version number, model ID, or pricing figure?
  → YES → WebSearch (Tier 1-2)

Am I writing integration code for an external API or service?
  → YES → WebSearch for current SDK/API docs (Tier 2)

Am I recommending a specific tool, library, or service version?
  → YES → WebSearch for latest stable version (Tier 2)

Am I writing Dockerfile FROM, package.json versions, or dependency configs?
  → YES → WebSearch for current LTS/stable versions (Tier 2)

Am I referencing a security practice, CVE, or vulnerability?
  → YES → WebSearch for current advisories (Tier 1)

Am I writing language fundamentals, algorithms, or standard patterns?
  → NO search needed → Proceed (Tier 4)
```

---

## Search-Then-Implement Pattern

When a verification search is triggered:

1. **Identify** what needs verification (model ID, version, API syntax, pricing)
2. **Search** using WebSearch with a specific query (e.g., "anthropic claude api model IDs 2026", "next.js 15 app router API")
3. **Extract** the verified current value from search results
4. **Cite briefly** in your output what you found:
   ```
   ✓ Verified: Claude model ID is `claude-sonnet-4-20250514` (Anthropic docs, March 2026)
   ✓ Verified: Next.js stable is 15.2.x — using App Router API
   ✓ Verified: node:22-alpine is current LTS
   ```
5. **Implement** using the verified data

---

## Skill-Specific Sensitivity

Different agents encounter different volatile data:

| Agent | High-Sensitivity Areas |
|-------|----------------------|
| **Software Engineer** | Package versions, SDK APIs, framework patterns, database driver syntax |
| **Frontend Engineer** | Framework APIs (React/Next.js/Vue), CSS features, browser compatibility, UI library versions |
| **DevOps** | Docker base images, Terraform providers, CI/CD action versions, cloud CLI syntax |
| **SRE** | Monitoring tool APIs (Datadog/Grafana/PagerDuty), cloud service quotas, Kubernetes versions |
| **Security Engineer** | CVEs, deprecated crypto, OWASP updates, auth provider changes, supply chain advisories |
| **Data Scientist** | LLM model IDs/pricing/context windows, ML framework APIs, vector DB APIs, embedding model specs |
| **Solution Architect** | Cloud service capabilities, managed service pricing, regional availability, compliance updates |
| **Code Reviewer** | Linting rule changes, language version features, framework deprecations |
| **QA Engineer** | Testing framework APIs, browser driver versions, CI runner environments |
| **Technical Writer** | API docs accuracy, version-specific feature references |
| **Product Manager** | Market/competitive data, pricing benchmarks, regulatory changes |
| **Polymath** | Broad research — always verify factual claims about current state of technology |

---

## Anti-Patterns

| Wrong | Right |
|-------|-------|
| Writing `"gpt-4-turbo"` from memory | WebSearch "openai models API current" → use verified ID |
| `FROM node:20-alpine` because you saw it once | WebSearch "node.js current LTS version" → use verified tag |
| Recommending `bcrypt` rounds from training data | WebSearch "bcrypt recommended rounds 2026" → verify |
| Writing `provider "aws" { version = "~> 5.0" }` | WebSearch "terraform aws provider latest version" → use verified |
| Citing a CVE number without checking | WebSearch the CVE → confirm it exists and is current |
| Assuming pricing for a cloud service | WebSearch "{service} pricing" → use current numbers |
| Writing SDK code from memory for fast-moving APIs | WebSearch "{sdk} latest version API reference" → verify syntax |

---

## Key Principle

**The cost of a 10-second web search is near zero. The cost of shipping code with a wrong model ID, deprecated API, or vulnerable dependency is high.** When in doubt, search.
