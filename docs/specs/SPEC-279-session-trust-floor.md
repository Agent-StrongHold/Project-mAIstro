---
id: SPEC-279
title: "Session Trust Floor — TrustSignal, floor computation, and gate integration"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-070426-e8a3
related:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-246
  - maistro-engine#SPEC-247
implements:
  - maistro-engine#ADR-070426-e8a3
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_session_trust_floor.py
  - formal/models/test_session_trust_floor.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-279: Session Trust Floor

## Finding addressed

`ADR-070426-e8a3` decides that maistro-engine needs a monotonically non-increasing, per-session
trust floor (STF) to close a trust-laundering gap: nothing today tracks that a session as a whole
has been exposed to untrusted content, so summarizing or compacting a poisoned turn out of the
context window currently makes the session look clean to any downstream check. This SPEC defines
the concrete `TrustSignal` type, the floor-computation reduction, where it is stored, and the
integration points — conduit ingest, `ADR-051` tool-approval gates, `ADR-058` A2A delegation, and
the compaction path — that must consult it. It also folds in the existing
`WardenVerdict.confidence` field (`maistro.types.security.WardenVerdict`, already `float = 1.0` in
shipped code) as an input to the floor rather than treating it as a field this SPEC needs to add.

## Design

### 1. `TrustSignal` type

New dataclass in `maistro.types.security` (alongside `TrustTier`/`WardenVerdict`):

```python
@dataclass(frozen=True)
class TrustSignal:
    """One contributor's trust report, folded into a session's STF."""

    source: str            # contributor id: agent id, tool name, input_source id, recipe id, ...
    tier: TrustTier         # SKULL < T4 < T3 < T2 < T1 < T0 (existing enum, reused as-is)
    confidence: float = 1.0  # [0, 1] — emitter's confidence in `tier`
    rationale: str = ""
    trace_ref: str = ""     # audit/trace entry this signal originated from
```

`source` categories at minimum: `agent`, `recipe`, `node` (ADR-062 graph node), `tool`,
`input_source`, `user`, `warden`. Unknown/unclassified sources emit `TrustSignal(tier=TrustTier.SKULL, confidence=1.0, rationale="unclassified source")` — the fail-closed default from
`ADR-070426-e8a3`, not a neutral tier.

### 2. Floor computation and storage

`SessionTrustState` — new session-scoped state, stored alongside `SessionConfig`
(`maistro.types.session`), not derived from context-window contents:

```python
@dataclass
class SessionTrustState:
    """Session-scoped STF tracking. Independent of context-window contents —
    compaction/redaction of the window must not affect this state (anti-laundering)."""

    floor: TrustTier = TrustTier.T0   # starts clean; only ever moves toward SKULL
    signals: list[TrustSignal] = field(default_factory=list)

    def observe(self, signal: TrustSignal) -> TrustTier:
        """Fold in one signal. Returns the (possibly unchanged) floor.

        Monotonic: `self.floor = min(self.floor, effective_tier(signal))` using
        TrustTier's existing ascending-trust ordering — never assigns upward.
        """
```

`effective_tier(signal)` maps a `(tier, confidence)` pair to the tier actually folded into the
floor: a low-confidence signal is treated as one tier lower than reported (see AC-4 for the exact
threshold table) — this is where `WardenVerdict.confidence` enters: every `Warden.scan()` call
site additionally emits a `TrustSignal(source="warden", tier=<mapped from verdict.clean/flags>, confidence=verdict.confidence, ...)`.

Storage: `SessionTrustState` is keyed by `session_id` in the same store that holds
`InMemorySessionStore`'s history (`maistro.sessions.store`), as a sibling structure — not a field
derived from `get_history()`'s message list, specifically so a compaction pass that shortens or
summarizes history cannot touch it. Persistence backends (future Postgres session store) must
carry `SessionTrustState` as its own row/column, not reconstruct it from message content.

### 3. Integration points

**Conduit ingest** (`maistro.conduit`) — every request entering `determine_execution_tier`'s
pipeline first resolves the session's current `SessionTrustState.floor` and attaches it to the
`Intent` (new `Intent.session_trust_floor: TrustTier` field) so downstream agents/strategies can
read it without a second lookup.

**Tool-approval gates (`ADR-051`)** — `Sentinel`'s gate resolution (`resolve_tier` per
`ADR-068` §D) gains a second check: an action proceeds only if
`session_trust_floor >= action_required_tier` **in addition to** the existing ADR-068
principal-authority gate. A session whose floor has dropped below a tool's required tier gets a
`stf_insufficient` event (not an exception — mirrors Stronghold's CFM-2 pattern of a typed,
reviewable event rather than a hard failure) routed to a HITL surface for a ratchet decision in a
new session.

**A2A delegation (`ADR-058`)** — `GuestPeerManager.delegate()` and any in-process sub-agent spawn
copy the parent session's `SessionTrustState.floor` into the child's initial state
(`SessionTrustState(floor=parent.floor, signals=[])` — the child starts its own signal list but
never above the inherited floor). A federated peer that cannot represent `SessionTrustState` treats
the inherited floor as an opaque "do not exceed this tier" ceiling on any action it takes on the
parent's behalf.

**Compaction path** — wherever session history is summarized/compacted/redacted (any future
`maistro.sessions` compaction routine), the routine MUST NOT read from or write to
`SessionTrustState`. This is enforced structurally (compaction operates only on the message-history
store) and is exercised by AC-2's test.

**`WardenVerdict.confidence`** — already shipping (`types/security.py:39`, `float = 1.0` default).
This SPEC's only change to it is behavioral: every call site of `Warden.scan()` now also produces
a `TrustSignal` derived from the returned verdict, per the mapping in AC-4. No schema change to
`WardenVerdict` itself.

### 4. Read-down enforcement

Enforcement checks (`session_trust_floor >= required_tier`) gate **new action initiation** only.
Nothing added by this SPEC filters, redacts, or blocks read access to session history/context —
that would contradict `ADR-070426-e8a3`'s read-down semantics and would break a session's ability
to reason about what happened. Reviewers should reject any patch that adds a context-window read
filter keyed off STF.

## Acceptance criteria

- **AC-1**: `TrustSignal` and `SessionTrustState` are added to `maistro.types.security`;
  `SessionTrustState.observe()` is a pure `min()` fold — property-tested (Hypothesis) that for any
  sequence of signals, `floor` after N observations is `<=` `floor` after any prefix of N-1
  observations (monotonicity). Lives in `formal/models/test_session_trust_floor.py` alongside the
  existing `test_trust_boundary.py`/`test_warden_detector.py` invariant suite.
- **AC-2**: A compaction/summarization pass on session history (simulated in the test — replace
  the message list, leave `SessionTrustState` untouched) does not change `SessionTrustState.floor`.
  Property test: floor before compaction == floor after compaction, for any compaction that only
  mutates message history.
- **AC-3**: Fork inheritance — spawning a child session (A2A delegation or sub-agent spawn) sets
  the child's initial floor equal to the parent's floor at fork time; the child's floor can
  subsequently drop further but never rise above the inherited value. Property test parameterized
  over parent floors `T0`..`SKULL`.
- **AC-4**: Confidence-to-tier mapping is a documented, tested table (e.g., `confidence < 0.5`
  drags the signal's effective tier down by one step; `confidence < 0.2` by two steps — exact
  thresholds fixed at implementation time and captured as a unit test table, not left as prose).
- **AC-5**: Unknown/unclassified `TrustSignal.source` folds in at `TrustTier.SKULL` — unit test
  with a synthetic unregistered source id.
- **AC-6**: `Sentinel`'s tool-approval gate (`ADR-051`) integration: a tool call requiring tier
  `T1` is denied with a `stf_insufficient` event (not an exception) when
  `session_trust_floor < T1`, and allowed when `session_trust_floor >= T1`, independent of the
  ADR-068 principal-authority result (both must pass).
- **AC-7**: `Intent.session_trust_floor` is populated by conduit ingest before dispatch; a session
  with no prior signals defaults to `TrustTier.T0` (clean start), not `SKULL` (that default is for
  unclassified *contributors*, not fresh sessions).
- **AC-8**: No code path reads `SessionTrustState` to filter, hide, or block *reading* existing
  session content — verified by an integration test asserting `get_history()` output is unaffected
  by floor value.

## Test plan

1. **Unit** — `packages/maistro-core/tests/security/test_session_trust_floor.py`:
   `TrustSignal` construction, `SessionTrustState.observe()` monotonicity (direct assertions),
   confidence-to-tier mapping table (AC-4), unknown-source default (AC-5), fork inheritance (AC-3).
2. **Property-based** — `formal/models/test_session_trust_floor.py` (Hypothesis, same house style
   as `test_trust_boundary.py`/`test_session_store.py`): random sequences of `TrustSignal`s ->
   floor never increases (AC-1); random compaction interleaved with signals -> compaction never
   changes floor (AC-2); random fork points -> child floor never exceeds parent floor at fork time
   (AC-3).
3. **Integration** — `Sentinel` gate resolution with a fake `SessionTrustState` fixture in
   `tests/fakes.py`-equivalent for maistro-core, asserting `stf_insufficient` fires correctly
   (AC-6) and that conduit ingest populates `Intent.session_trust_floor` (AC-7).
4. **Regression guard** — a test explicitly asserting `get_history()` is called with no
   `SessionTrustState` argument and its output is independent of floor value (AC-8), to catch any
   future patch that couples read access to STF.
