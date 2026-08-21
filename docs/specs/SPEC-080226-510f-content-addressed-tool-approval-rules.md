---
id: SPEC-080226-510f
title: "Content-addressed standing approval rules for tool calls"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-08-02
substrate:
  - maistro-engine#SPEC-253
  - maistro-engine#ADR-051
  - maistro-engine#ADR-083
  - maistro-engine#ADR-069
implements: []
related:
  - maistro-engine#SPEC-257
  - maistro-engine#ADR-062
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-080226-510f: Content-addressed standing approval rules for tool calls

## Context

`maistro.tools.approval.gate` (SPEC-253/ADR-051) currently makes per-call approval decisions
(`needs_plan_approval`, `needs_escalation`, `collapse_window`) but has no concept of a durable
"don't ask again" rule — every risky call is re-evaluated from the declared plan or an escalation
threshold, with nothing persisted across turns or sessions. Grepping `maistro-engine` for
`always_approve`, `ApprovalRule`, `dont_ask_again`, or any standing-rule concept returns zero
matches.

Microsoft's Agent Framework harness (`_harness/_tool_approval.py`) solves this with a
`ToolApprovalRule(tool_name, args, server_label)` persisted in session state, matched by **name**.
Its own docstring flags the resulting footgun: "a rule provided for one feature ... may auto-approve
*any* local tool whose name matches, not just the tool the rule was designed for" — a collision that
is avoided only by caller discipline, not by the data model.

We can do better by construction. This codebase already has two proven, unrelated instances of
content-addressed identity that solve the same underlying problem:

- `maistro.code_registry` (SPEC-257/ADR-069): `CodeEntry(name, version, kind, code_sha256, signature)`
  — dynamically-registered graph-node code (compensators, impact estimators, dynamic gates) is
  identified and signature-verified by the hash of its content, not by name+version alone.
- `maistro.skills.import_pipeline` (ADR-083): `PolicyAttachment(skill_name, content_hash,
  policy="rescan_on_use")` — every imported/forged skill is bound to a SHA-256 of its content at
  registration, and every use re-hashes the payload and compares. A mismatch is reported explicitly
  as `"content_hash mismatch: payload mutated since import (rug-pull)"`. This is rug-pull defense for
  security scanning; the same primitive generalizes to approval caching.

The one tool source with no content-addressed identity today is native/built-in tools —
`CapabilityRegistry.register(provider)` resolves providers by logical identity rather than a hash
of the implementation that will execute.

## Goals

- A `ToolApprovalRule` that grants "don't ask again" only for the exact code that was approved —
  reinstalling or updating a tool under the same name must NOT inherit its predecessor's approvals.
- One `ToolIdentity` shape usable across all three tool sources: marketplace-imported skills,
  Forge-created skills, and native Python tools/capability providers.
- Reuse of existing content-hash infrastructure (`import_pipeline.PolicyAttachment`,
  `code_registry.CodeEntry`) rather than a parallel hashing scheme.
- Two-tier rule granularity, matching MS's usable distinction: approve this tool for any arguments,
  or approve only this exact argument set.
- Rules scoped along the existing scope axes (session → user → team), not a new axis.

## Non-goals

- Not building a UI/approval-prompt flow — this spec covers the rule data model, identity
  resolution, and matching logic only. Surfacing "always approve?" to a human is a separate concern
  (existing `ApprovalDecision`/`decided_by` in `tools/approval/types.py` already covers the prompt
  outcome).
- Not changing Sentinel's per-call `pre_call()`/`post_call()` validation — standing rules sit
  *before* that gate (skip re-prompting), they do not replace policy validation.
- Not retrofitting `code_registry`'s signature-verification (`SignatureVerifier`) onto tool
  approval in this pass — native tools are first-party code in this repo, not third-party payloads
  like graph-node plugins. Revisit if/when third-party native tool plugins are supported.
- No changes to `maistro.graph.compaction` (tracked separately).

## Decision

### `ToolIdentity`

```python
@dataclass(frozen=True)
class ToolIdentity:
    name: str            # human label, e.g. "file_access_write" or a skill name
    version: str
    code_sha256: str      # content hash — the actual matching key
```

Resolution differs by source, computed once and cached, never per-call:

- **Marketplace-imported / Forge-created skills**: `code_sha256` = the skill's existing
  `PolicyAttachment.content_hash` (ADR-083). No new hashing — read the attachment already bound at
  import/forge time.
- **Native Python tools / capability providers**: new one-time hash at registration through
  MAIstro's capability/tool registry — SHA-256 of the executor's resolved source (module file
  content or serialized `__code__`, mirroring `code_registry`'s `code_sha256` derivation), cached
  on the registry entry.

### `ToolApprovalRule`

```python
@dataclass(frozen=True)
class ToolApprovalRule:
    tool: ToolIdentity
    args: dict[str, Any] | None   # None = any-args; else exact-match, MS's two-tier scope
    scope: Literal["session", "user", "team"]  # reuses existing scope axes, not tenant
```

Stored in session/user/team-scoped state (mirrors existing scope-store patterns — no new storage
layer). Matching: `_matches_rule(call, rule)` compares `call.tool_identity.code_sha256 ==
rule.tool.code_sha256` first (never `name`), then args per rule's tier.

### Integration point

`gate.needs_escalation()` gains a rule-check step before its existing plan/threshold logic:

```
needs_escalation(call, impacts, thresholds, plan_state) →
    if a persisted ToolApprovalRule matches call.tool_identity + call.args: False
    else: existing needs_escalation logic (plan-declared vs. threshold-tripped)
```

A rule is created the same way MS creates one — from an approval response carrying an
"always approve this tool" / "always approve this tool with these args" scope — but the persisted
key is `code_sha256`, so updating the tool's code (new skill version, patched native tool) produces
a new hash and the old rule silently stops matching. No explicit revocation step is needed for the
common case of "the tool changed under me."

## Acceptance criteria

- Approving a tool call with "always approve" scope persists a `ToolApprovalRule` keyed on
  `code_sha256`, and a subsequent identical call skips escalation.
- Re-registering a tool under the same name with different content (different `code_sha256`)
  does NOT match an existing rule — the next call re-escalates.
- A rule with `args=None` matches any argument set for that exact tool version; a rule with
  concrete `args` matches only that exact call shape.
- Marketplace/Forge skill identity reuses `PolicyAttachment.content_hash` with no duplicate hash
  computation.
- Native tool identity hash is computed once at registration, not on the hot path of every call.

## Testing

- Unit tests for `ToolIdentity` resolution from each of the three sources (imported skill, forged
  skill, native provider), asserting the same content produces the same hash and different content
  produces a different hash.
- Unit tests for `_matches_rule` covering: exact-args match, any-args match, name-collision
  non-match (two tools with the same `name` but different `code_sha256` must not cross-match — the
  regression test for the exact footgun MS's docstring warns about).
- Integration test through `gate.needs_escalation()`: declared-plan path, threshold-trip path, and
  new standing-rule short-circuit path, confirmed against `maistro.testing.HarnessEnvironment`.
- Property-based test (candidate for `formal/`) asserting rule matching is never satisfied by
  name alone — i.e. for all `(rule, call)` pairs, `matches(rule, call) →
  rule.tool.code_sha256 == call.tool_identity.code_sha256`.

## Open questions

- Where should the native-tool hash be cached — on the capability/tool registry entry itself, or
  in a separate identity cache keyed by `(slot, provider_name)`? Affects invalidation when a
  provider is re-registered at runtime (hot-reload).
- Should tool identity be surfaced directly by the existing capability registry protocol, or stay
  in a wrapper to avoid widening an established interface before the unified capability work?
- Team-scoped rules: does a team-scoped "always approve" require a higher approval authority
  (e.g. team admin) than a session-scoped one? Not addressed here — may need an ADR if the answer
  is yes.

## References

- Microsoft Agent Framework harness, `_harness/_tool_approval.py`
  (github.com/microsoft/agent-framework) — `ToolApprovalRule`/`ToolApprovalMiddleware`, the
  name-collision footgun this spec avoids by construction.
- `maistro.code_registry` (SPEC-257/ADR-069) — `CodeEntry.code_sha256` precedent.
- `maistro.skills.import_pipeline` (ADR-083) — `PolicyAttachment.content_hash`, rug-pull defense.
- `maistro.tools.approval.gate` (SPEC-253/ADR-051) — existing per-call decision logic this extends.
