---
id: ADR-070426-e8a3
title: Session Trust Floor — monotonically descending runtime trust primitive
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-073
related:
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-058
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-e8a3: Session Trust Floor

## Context

`ADR-068` gives maistro-engine a rigorous **upward** elevation ladder: a principal's authority can
be raised for a specific action — `self-elevation`, `delegated-approval`, `admin-elevation` — and
the `Tier` gating enum (`packages/maistro-core/src/maistro/security/sentinel/authz_types.py:10-16`)
resolves exactly which of those gates an action needs. What the engine has **no** primitive for is
the descending direction: once a session has been exposed to something untrusted — an
unverified tool result, a low-confidence Warden scan, a skill imported at `t3`
(`packages/maistro-core/src/maistro/skills/import_pipeline.py:37`) — nothing tracks that the
session as a whole is now less trustworthy than it was a turn ago, and nothing stops a later turn
from taking a privileged action as if the session were still clean.

This is a live gap, not a hypothetical one. `maistro.types.security.TrustTier`
(`packages/maistro-core/src/maistro/types/security.py:11-18`, `SKULL < T4 < T3 < T2 < T1 < T0`)
already exists and is attached to individual agents and skills, but nothing computes a
*session-wide* floor across every contributor a session has touched, and nothing prevents
"trust laundering": summarizing, redacting, or compacting a poisoned context could otherwise make
a session look clean again to a downstream check that only inspects the current context window
rather than the session's history. `WardenVerdict` (`types/security.py:32-40`) already carries a
`confidence: float = 1.0` field, but nothing today reads it as a signal that should drag a
session's effective trust down when confidence is low.

`ADR-073` (Warden + Sentinel) establishes the scan/decision substrate this ADR's signals flow
through; `ADR-050`/`ADR-051` (tool reversibility taxonomy and approval gates) are the primary
consumers that need to know "is this session still trustworthy enough for this tool call," in
addition to (not instead of) the existing reversibility/impact checks. `ADR-058` (A2A delegation)
is the mechanism by which a session's work forks into sub-tasks; this ADR requires those forks to
inherit the parent's trust state rather than starting clean.

## Decision

**We introduce the Session Trust Floor (STF): a monotonically non-increasing, per-session
trust-tier floor, computed as the minimum over every contributor that has touched the session.**
STF is the descending counterpart of ADR-068's elevation ladder — elevation raises what a
principal is *permitted* to do for one action; STF lowers what a *session* is permitted to do
until a new session starts.

### Computation

```
STF = min(
    agent.trust_tier,        # TrustTier of every agent that has acted in this session
    recipe.trust_tier,       # TrustTier of every recipe/flow node invoked
    node.trust_tier,         # TrustTier of every graph node (ADR-062) executed
    tool.trust_tier,         # TrustTier of every tool/skill invoked (ADR-050/051 gates)
    input_source.trust_tier, # TrustTier of every external input source (user upload, MCP result, A2A peer)
    user.trust_score_tier,   # the acting user's own trust standing
    warden_confidence_tier,  # derived from WardenVerdict.confidence — see below
    ...
)
```

`TrustTier` (`SKULL < T4 < T3 < T2 < T1 < T0`, existing enum) is reused as-is; STF does not
introduce a second tier taxonomy. `min()` uses the enum's existing ascending-trust ordering, so STF
is always the *least* trusted contributor seen so far.

### Monotonicity — the anti-laundering property

**STF is monotonically non-increasing within a session.** Once a contributor drags the floor down
to `T3`, no later event can raise it back — not within the same session. Concretely:

- **Redaction, compaction, and summarization do NOT heal STF.** Compacting a poisoned context
  window changes what's *visible* in the prompt; it does not undo the fact that the session
  ingested untrusted content. If compaction could heal STF, compaction becomes a trust-laundering
  vector: scan input → get flagged → summarize the flagged turn away → floor silently recovers.
  STF is tracked as session-state metadata (independent of context-window contents), not derived
  by re-scanning whatever currently happens to be in the window.
- **Forks inherit parent STF.** When a session forks — an A2A delegation (`ADR-058`), a sub-agent
  spawn, a graph-node fan-out (`ADR-062`) — the child session's initial STF is the parent's STF at
  fork time, never `T0`/clean. A child cannot be used to bypass a floor its parent already earned.
- **A new session is required to reset the floor.** There is no in-session "clear" operation. This
  is intentional: it makes STF a one-way ratchet, matching the "wisdom/regrets" asymmetry the
  engine already applies to memory (CLAUDE.md's "memory must forget... weight floors" principle,
  inverted — here the floor only ever tightens).

### Unknown sources default to lowest tier

A contributor with no established `TrustTier` — an unrecognized input source, an agent/skill
with no trust-tier metadata — defaults to `SKULL`, the lowest tier, not a neutral middle tier.
This mirrors the existing convention in `skills/parser.py`/`agents/factory.py` of defaulting
unspecified `trust_tier` to a cautious value, tightened here to the floor of the enum specifically
because STF's job is exactly to catch the "we don't know what this is" case.

### `TrustSignal` — how contributors report in

Every contributor emits a `TrustSignal`:

```python
@dataclass(frozen=True)
class TrustSignal:
    source: str           # which contributor emitted this (agent id, tool name, input_source id, ...)
    tier: TrustTier
    confidence: float     # [0, 1] — how sure the emitter is of `tier`
    rationale: str
    trace_ref: str        # link to the audit/trace entry this signal came from
```

The session's STF is `min(signal.tier for signal in session.trust_signals)`, folded in as each
signal arrives (an online reduction, not a recomputation from full history each time) — full
detail in `SPEC-279`.

### Warden confidence drags tier

`WardenVerdict.confidence` (already `[0, 1]` in shipped code, `types/security.py:39`) is read as an
additional `TrustSignal` source: a low-confidence clean verdict does not get the same tier weight
as a high-confidence one. A verdict with `clean=True` but `confidence=0.3` contributes a lower
`TrustSignal.tier` than a `confidence=0.99` verdict — the exact confidence-to-tier mapping is a
`SPEC-279` acceptance criterion, not decided here.

### Read-down semantics

**A lowered STF blocks NEW privileged actions; it does not retroactively block reading context
already present in the session.** If STF drops to `T3` mid-session, the session can still read
everything already in its context window (poisoned or not) — the model needs to be able to reason
about what happened, including about the thing that lowered the floor. What STF blocks is the
session *initiating* any action that requires a tier higher than the current floor: a tool call
gated `T1` by `ADR-051`, a delegated-approval action per `ADR-068` §B, etc. This is the same
distinction ADR-068 draws between "who may see" and "who may act" — STF adds a session-scoped act
gate on top of the existing principal-scoped one.

### Relationship to ADR-068

ADR-068 and STF are counterparts, not competitors, and both must pass for a privileged action to
proceed:

| | ADR-068 elevation ladder | Session Trust Floor |
|---|---|---|
| Direction | Upward (raise permitted authority) | Downward (lower permitted authority) |
| Scope | One action, one principal | Whole session, every contributor |
| Mechanism | Sudo/delegated-approval/admin gates | `min()` reduction over `TrustSignal`s |
| Can it be undone? | Yes — elevation is per-call, expires | No — monotonic within a session |
| Resets by | Gate re-evaluated per action | New session only |

An action proceeds only if the principal clears the ADR-068 gate tier **and** the session's
current STF is at or above whatever tier the action requires.

## Alternatives considered

**A) Per-turn trust check only (no session-wide floor).** Rejected — this is closest to the status
quo and is exactly what permits laundering: a poisoned turn gets summarized away, the next
per-turn check sees only the summary and passes clean.

**B) Allow STF to heal after N clean turns (decay upward, mirroring memory decay).** Rejected —
memory decay-without-reinforcement (CLAUDE.md design decision 5) is about forgetting weak signal
over time to avoid unbounded accumulation; trust floors are the opposite case, where the risk is
under-caution, not over-accumulation. Healing on a timer creates a wait-it-out laundering vector.

**C) Recompute STF by re-scanning current context window instead of tracking signals as
metadata.** Rejected — this is what compaction/redaction would defeat; a floor derived only from
what's currently visible cannot survive a compaction pass that removes the flagged content.

**D) A single scalar trust score instead of the existing `TrustTier` enum.** Rejected — `TrustTier`
already exists and is attached to agents/skills throughout the codebase
(`skills/parser.py`, `agents/factory.py`, `agents/catalog.py`); introducing a second, incompatible
scale for sessions would require a conversion layer everywhere STF meets an existing trust-tier
check.

## Consequences

**Positive:**
- Closes the trust-laundering gap: summarization/compaction can no longer be used to make a
  poisoned session look clean to a downstream tool-approval gate.
- Reuses the existing `TrustTier` enum and `WardenVerdict.confidence` field — no new tier
  taxonomy, and the confidence field this ADR depends on already ships in `types/security.py`.
- Gives `ADR-051`'s tool approval gates and `ADR-058`'s A2A delegation a session-scoped signal they
  currently lack.

**Negative / risks:**
- **Over-conservative floors can freeze a session.** A single low-confidence Warden false-positive
  early in a long session permanently caps what that session can do. Mitigation: `SPEC-279`'s
  acceptance criteria include a HITL path (mirroring Stronghold's `stf_ratchet_decision` review
  item) so a human can explicitly ratify a floor back up in a *new* session that inherits the
  reviewed context, rather than silently unsticking the old one.
- **`TrustSignal` volume.** Every tool call, node execution, and input ingestion now emits a
  signal; this is bookkeeping overhead on every trust boundary Warden already scans. Mitigation:
  the reduction is online (`min()` fold, not history replay), so cost is O(1) per signal.
- **Unknown-source-defaults-to-SKULL is aggressive.** A legitimate new input source with no
  trust-tier metadata yet will floor every session that touches it until it's classified.
  Mitigation: this is the intended fail-closed behavior — an operator classifies the source once,
  not per session.

**Trade-offs accepted:**
- We accept that STF can never be healed in-session, trading session flexibility for a hard
  guarantee against laundering.
- We accept read-down (not read-and-write-down) semantics, trading some caution (a poisoned
  session can still reason about poisoned context) for keeping the model able to function at all
  after a floor drop — a fully retroactive block would make recovery from a false-positive
  effectively require abandoning the session anyway.

## References

- [ADR-068: Unified Authorization & Elevation](ADR-068-unified-authorization-and-elevation.md)
- [ADR-073: Warden + Sentinel](ADR-073-warden-sentinel.md)
- [ADR-050: Tool reversibility taxonomy and compensator contract](ADR-050-tool-reversibility-taxonomy.md)
- [ADR-051: Tool approval gates](ADR-051-tool-approval-gates.md)
- [ADR-058: Agent-to-agent (A2A) delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [SPEC-279: Session Trust Floor](../specs/SPEC-279-session-trust-floor.md)
- Stronghold `BACKLOG.md` CFM-2 ("Session Trust Floor (STF) + Trust Ledger") — origin of the STF
  concept; the Trust Ledger / copper-value economy half of CFM-2 is Stronghold-owned and out of
  scope here (no `org_id`/tenancy-scoped currency in core).
- Seams: `types/security.py:11-40` (`TrustTier`, `WardenVerdict.confidence`),
  `security/sentinel/authz_types.py:10-16` (`Tier` gating ladder), `skills/import_pipeline.py:37`,
  `a2a/delegate.py`.
