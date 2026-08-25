---
id: ADR-082326-5386
title: "Outbound HTTP policy at the shared-client seam"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-23
accepted: 2026-08-25
substrate: []
implements: []
related:
  - maistro-engine#ADR-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/security/test_outbound_policy.py
ac-modules:
  AC-1: maistro.http
  AC-2: maistro.security.outbound
  AC-3: maistro.security.outbound
  AC-4: maistro.security.outbound
  AC-5: maistro.security.outbound
  AC-6: maistro.security.outbound
history:
  - status: Proposed
    date: 2026-08-23
  - status: Accepted
    date: 2026-08-25
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082326-5386: Outbound HTTP policy at the shared-client seam

## Context

`CLAUDE.md`'s sixth decision is that all input is untrusted and the Warden scans
at every trust boundary. An outbound URL is one: a URL an agent decided to
fetch, a skill manifest someone asked to import, a webhook a caller registered.

#154 gave the engine one SSRF validator, `security/ssrf.py`, and it is
effective. It is also a *function*, which every call site has to remember to
call. Counted: of the twenty-five modules in `maistro-core` that issue an
outbound HTTP request, **three call it**. Twenty-two do not, including the two
whose destination is most likely to be attacker-influenced rather than
configured — `tasks/progress_webhook`, which posts to a registered webhook URL,
and `agents/strategies/tool_http`, which fetches whatever a tool call names.

Nearly all of those modules already route through `maistro.http.shared_client`.
There is one seam that reaches them.

The reason it could not simply be switched on: **the engine legitimately calls
internal endpoints.** `agents/conductor`, `agents/pm_llm_call`,
`graph/nodes/llm_summarize` and `orchestrator/hierarchy` talk to a
LiteLLM/Ollama gateway that is routinely `http://127.0.0.1:4000` or a LAN host,
and `integrations/home_assistant` is that shape by definition. A blanket guard
at that seam refuses the engine's own traffic on the first request.

## Decision

**The policy lives at the transport, and it is on by default.**
`maistro.http` wraps every pooled client's transport in a `GuardedTransport`
that applies the policy to each request.

**It cannot distinguish caller-influenced URLs from configured ones, and that
is why it guards everything.** The tempting policy — validate what a caller
chose, leave what an operator configured — is not implementable here: a
transport sees a URL and nothing about its provenance. By the time a request
arrives, "the operator configured this" and "a tool call named this" are the
same string. Any policy that depends on telling them apart has to live at the
call sites, which is precisely the arrangement that produced three out of
twenty-five.

**Configured destinations are named, not inferred.** An origin the deployment
actually configured is reached without validation; everything else is
validated. That inverts the failure mode: forgetting to allow a real endpoint
is a refusal on the first request, loud and immediate, while forgetting to
guard a call site is a hole nobody sees. Only one of those is safe to get
wrong.

**Allowances are seeded from settings.** `configured_endpoints()` reads the
LiteLLM base, the Ollama base, the ntfy base and the server base off the
settings objects, and a client handed its own endpoint (Home Assistant) can
register that origin. No hand-maintained list, so moving a gateway moves its
allowance with it rather than leaving a stale entry behind and a working
deployment broken.

**An allowance is an origin, compared exactly.** Scheme, host and port, with
the default port normalised. `http://127.0.0.1:4000` allows that gateway and
nothing else — not port 8080 on the same host, not another RFC1918 address, not
`https://` to the same name. It is not "allow private addresses"; it is "allow
this endpoint", which is the narrowest thing that still lets the engine talk to
its own LLM.

**Redirect hops are covered by construction.** httpx re-enters the transport for
every hop, so a chain that starts public and lands private is validated at the
hop that matters, with no call-site change. This is the main reason the policy
is at the transport rather than in `shared_client`'s wrapper.

**A transport that fabricates responses is not wrapped.** `httpx.MockTransport`
opens no socket, and it is how the entire test suite avoids the network;
guarding it would make thousands of fake hosts unreachable while protecting
nothing. Nothing in production can install one. This is deliberately *not* an
"off" switch — there is none.

## Acceptance criteria

Retrofitted at acceptance, from the behaviour PR #202 already shipped and
`packages/maistro-core/tests/security/test_outbound_policy.py` already proves.
Each is bound to a test that existed before this record was accepted — the
criteria describe the decision, they do not extend it.

- [x] **AC-1** Every transport a pooled client is built with is guarded,
  including the proxy mounts httpx chose from the environment, and wrapping is
  idempotent.
- [x] **AC-2** A private, link-local, loopback or metadata destination is
  refused at the transport, in each of its usual spellings.
- [x] **AC-3** A redirect chain that starts public and lands private is refused
  at the hop that matters, with no call-site change.
- [x] **AC-4** A configured internal endpoint is reachable without disabling the
  guard, and the allowance is seeded from settings rather than listed in code.
- [x] **AC-5** An allowance is an exact origin: it does not widen to another
  port, another host, or another scheme.
- [x] **AC-6** The two caller-influenced call sites — the progress webhook and
  the HTTP tool executor — are refused a private target.

## Consequences

### Positive
- Twenty-two modules become guarded without twenty-two edits, and a
  twenty-sixth is guarded the day it is written.
- Redirect chains are validated per hop, which no call-site check achieved.
- The engine's own LLM traffic skips the resolver entirely: an allowed origin
  is a set lookup, so the hot path costs less than the guarded one.
- The allowlist cannot silently rot, because it is derived from the same
  settings the clients read.

### Negative / Trade-offs
- **The guard is applied to httpx's transports after the client is built,
  reaching into two private attributes** (`_transport`, `_mounts`). The obvious
  alternative — passing `transport=guarded(...)` — was the first draft of this
  ADR and was wrong in a way worth recording, because it looks harmless: httpx
  0.28 reads `allow_env_proxies = trust_env and transport is None`, so supplying
  any transport switches environment-proxy support off for the whole engine.
  The result on a deployment that egresses through `HTTPS_PROXY` is not a weaker
  guard but no egress at all. Rebuilding the proxy map here instead would mean
  reimplementing httpx's environment parsing — per-scheme variables, `ALL_PROXY`,
  `NO_PROXY` suffix matching — and drifting from it on the next release. So httpx
  builds what it always builds and each transport it chose is wrapped, guarded by
  a test that fails if those attributes move.
- **A refusal from inside a transport inherits from two hierarchies.**
  `OutboundBlockedError` is both an `SSRFBlockedError` (hence a `ToolError`) and
  an `httpx.TransportError`, because eleven call sites already catch the httpx
  contracts — the OAuth exchange, the HTTP harness's fallback, the quota CLI's
  exit code — and a transport that raises something a transport cannot raise
  walks straight past all of them. Multiple inheritance for an exception is a
  cost; asking every caller to learn a new exception, or leaving their handlers
  silently bypassed, is a larger one.
- **The rebinding window from #154 is unchanged.** This guard resolves the name
  and httpx resolves it again to connect. Pinning the resolved address into the
  connection is still not done.
- A non-allowlisted destination now costs a DNS resolution per request. That is
  the price of the control; the allowlist keeps it off the paths that matter.
- A deployment that adds an endpoint without adding it to settings will see a
  refusal. That is the intended direction of failure, but it is a failure, and
  the error names the URL so it is actionable.

### Neutral
- `security/ssrf.py` is unchanged. This ADR decides *where* and *when* it runs,
  not what it considers private.
- `agents/strategies/tool_http` — one of the two caller-influenced call sites —
  has no production entry point today; `quality/reachability-baseline.json`
  lists it as unreachable. Its guard is therefore proven by test rather than
  exercised in production, and AC-6 is annotated to the module that does the
  refusing rather than to the call site that would trigger it. That is a real
  gap in the *call site*, not in the policy, and it is stated here rather than
  implied by an annotation nobody would question.
- Call sites that already validate keep doing so. The duplicate check costs a
  cached lookup and means a call site that stops using the shared pool is still
  guarded.
