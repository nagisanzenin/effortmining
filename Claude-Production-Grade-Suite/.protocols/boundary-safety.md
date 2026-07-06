# Boundary Safety Protocol

Six structural patterns that cause silent failures at system boundaries. These are framework-agnostic and apply to any stack. All agents must check for these as structural rules.

---

## Pattern 1 — Framework Abstractions Break at System Boundaries

Every framework has convenience abstractions (client-side router, ORM, state manager). These abstractions assume you stay within their domain. When you cross a boundary — client to server, app to API, internal to external — the abstraction silently fails or behaves unexpectedly.

**Rule:** Before using a framework abstraction, verify it works for the target's domain. If the target is outside the framework's routing/rendering layer (API endpoints, external URLs, file downloads, auth flows), fall back to the platform primitive (raw `<a href>`, raw `fetch`, raw redirect).

**Detection:** Scan for framework navigation/routing components that target API routes, external URLs, or non-page endpoints.

**Examples:**
- Next.js `<Link>` used for API routes (`/api/auth/login`) — silently does client-side navigation instead of full request
- React Router `navigate()` used for external OAuth URLs — breaks the auth flow
- ORM `.save()` used across database boundaries — silently fails or creates in wrong schema

---

## Pattern 2 — Delegate to the Framework's Control Flow

Frameworks with middleware, interceptors, or guards already handle cross-cutting concerns (auth, redirects, logging). Manually implementing the same logic in the UI layer creates a parallel control flow that conflicts with the framework's own.

**Rule:** Identify the framework's intended control flow for auth, routing, and error handling. Wire the UI to the happy path (the protected destination). Let middleware/guards handle the unhappy path (redirecting to login, showing errors). Never bypass or duplicate the framework's control flow.

**Detection:** If the UI links directly to auth/error/middleware endpoints instead of to the protected resource, flag it.

**Examples:**
- Login button links to `/api/auth/signin` instead of `/dashboard` (with middleware redirecting unauthenticated users to login)
- Component manually checks auth state and redirects, duplicating what the auth middleware already does
- Error handling in both the API client interceptor AND the component — conflicting behaviors

---

## Pattern 3 — Self-Referencing Configuration Creates Infinite Loops

When a system lets you override default behavior with a custom handler, pointing that override back to the default handler creates an infinite loop. The system says "use X instead of default" then X IS the default — infinite redirect/recursion.

**Rule:** Any configuration that overrides a default path/handler MUST point to a genuinely different implementation. If the override target equals the default, remove the override entirely.

**Detection:** Compare override values against the system's known default paths/handlers. Flag if they match.

**Examples:**
- NextAuth `signIn` page override pointing to `/api/auth/signin` (which IS the default) — infinite redirect
- Custom error page that redirects to the default error handler — infinite loop
- Proxy rule that forwards to itself — infinite request loop

---

## Pattern 4 — Global Interceptors Must Be Conditional

Global callbacks, middleware, and interceptors fire for ALL matching events, not just the one you're thinking about. An unconditional override in a global interceptor breaks every other flow that passes through it.

**Rule:** Every global interceptor (redirect callbacks, request middleware, error handlers, event hooks) must include conditional logic that distinguishes the target case from pass-through cases. The default behavior for unmatched cases must preserve the original intent (pass through the URL, request, or event unchanged).

**Detection:** Any global interceptor that returns a hardcoded value without branching on its input parameters is a bug.

**Examples:**
- Auth callback that always redirects to `/dashboard` — breaks the "redirect back to original page after login" flow
- API interceptor that always retries on 401 — retries the login request itself, creating a loop
- Error handler that always shows a toast — shows toasts for expected/handled errors too

---

## Pattern 5 — Test Full User Journeys Across System Boundaries

Unit tests verify individual components. Integration tests verify API contracts. But actual user journeys cross multiple systems (browser to OAuth provider to callback to redirect to authenticated page). Testing only within system boundaries misses the transitions.

**Rule:** For every multi-system flow (auth, payment, email, webhook), the test plan MUST include at least one end-to-end scenario that traces the complete journey from user action to final state. The test must verify the user lands in the correct final state, not just that each hop returns 200.

**Detection:** If the test plan has auth tests that only check "returns token" but never check "user ends up on the dashboard," it's incomplete.

**Examples:**
- Auth test checks token is issued but never checks that the callback redirects to the right page
- Payment test checks Stripe returns success but never checks that the order status updates and the user sees confirmation
- Webhook test checks the endpoint returns 200 but never checks that the side effect (email sent, status changed) actually happened

---

## Pattern 6 — Identity Must Be Consistent Across Integrated Systems

When system A triggers system B (git push to CI/CD, commit to deploy, API call to webhook), system B validates the actor's identity. If A uses a different identity format than B expects, the action silently fails or is rejected.

**Rule:** Before wiring two systems together, verify the identity chain: what identity does system A send, and what does system B expect? Map usernames, emails, tokens, and API keys across all integrated systems. Mismatches at any hop break the pipeline.

**Detection:** At integration setup time, extract identity fields from both systems and compare formats. Flag mismatches (local hostname email vs GitHub email, test token vs production token, etc.).

**Examples:**
- Git commits use local hostname email, but CI/CD requires GitHub-verified email — deployments fail silently
- OAuth provider returns email as identifier, but the app expects username — user creation fails
- API key for staging environment used in production webhook config — all webhooks rejected

---

## Quick Reference

| # | Pattern | One-Liner |
|---|---------|-----------|
| 1 | Abstractions break at boundaries | Use platform primitives when crossing domains |
| 2 | Don't duplicate framework control flow | Wire UI to the destination, let middleware handle the rest |
| 3 | Self-referencing config = infinite loop | Overrides must point to something different than the default |
| 4 | Global interceptors must branch | Never return a hardcoded value from a global hook |
| 5 | Test full journeys, not just hops | Verify the user's final state, not intermediate responses |
| 6 | Identity must match across systems | Verify identity format compatibility at every integration point |
