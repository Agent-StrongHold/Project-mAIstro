---
id: ADR-090726-9a4e
title: "The Hybrid — crypto-bound approvals: WebAuthn presence, Biscuit delegation, hash-chained evidence"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-07
accepted: 2026-09-07
substrate:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-022
  - maistro-engine#ADR-024
implements: []
related:
  - maistro-engine#ADR-077
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-083026-6c72
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/nodes/test_human_verdict_fail_closed.py
  - packages/maistro-core/tests/capabilities/test_durable_approval.py
  - packages/hive-conductor/backend/tests/test_hitl_door.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-07
    reason: "Operator chose among pure-WebAuthn, pure-Biscuit, and hybrid designs for crypto-bound approvals."
  - status: Accepted
    date: 2026-09-07
    reason: "Operator ratified the full Hybrid for M2 (decision d5, 2026-09-07): WebAuthn + Biscuit + hash-chained log, all phases 0-4."
ac-modules:
  AC-1: maistro.capabilities.approval_store
  AC-2: maistro.graph.nodes.human_approve_draft
  AC-3: maistro.graph.nodes.human_delegate_to_role
  AC-4: maistro.graph.nodes.human_review_and_edit
  AC-5: backend.routes.hitl
---

# ADR-090726-9a4e: The Hybrid — crypto-bound approvals: WebAuthn presence, Biscuit delegation, hash-chained evidence

## Context

Human approvals in this system are currently *recorded* but not *bound*: a
HITL answer, an `ApprovalStore.resolve`, or an RSI promotion decision is
settled by whoever reached the write seam, and the durable record says only
what that caller claimed about itself — in several places, literally the
string `"system"`. Nothing in the record proves that a human was present for
the decision, that the deciding principal held the authority the decision
exercised, or that the record was not edited after the fact.

Three designs were on the table (#329):

1. **Pure WebAuthn** — every human decision is a ceremony (resident key,
   user verification). Maximal presence proof; unusable for runtime
   delegation, because a hardware-bound key cannot attenuate an agent's
   authority to a scoped, expiring capability.
2. **Pure Biscuit** — offline-capable ed25519 tokens carry every grant.
   Maximal delegation expressiveness; proves nothing about human presence,
   because possession of a key is not liveness of a person.
3. **The Hybrid** — each primitive does the half it is uniquely good at.

The operator ratified the full Hybrid on 2026-09-07 (decision d5), choosing
to carry all phases 0–4 in M2.

## Decision

Approvals become **crypto-bound**: every durable human decision carries
cryptographic evidence of *who* decided, *what* they decided, and *that the
record is intact*. Three legs, one decision:

### Leg 1 — WebAuthn binds human presence

Any approval that exists to prove a *person* was present (self-elevation,
delegated/admin approval, irreversible-action gates) is finalized by a
WebAuthn assertion over the canonical approval payload: challenge =
`request_digest` of the exact effect, authenticator response recorded with
the settlement. This is ADR-068 §D's "local human factor = password/passkey"
made structural: the passkey assertion is the human's signature, not a
password check that happens to sit in front of the write.

### Leg 2 — Biscuit binds runtime delegation

Any approval that exists to prove *authority* — an agent acting on a
principal's behalf, an attenuation of a broader grant — is a Biscuit token
(ed25519 per ADR-024's `did:key`/Ed25519VerificationKey2020 substrate).
Biscuits are chosen over a bespoke format because attenuation and
caveats-first-then-authority are exactly the delegation lattice ADR-068 §D
describes ("agent → scoped 2FA": single action, concrete args, short TTL),
with offline verification at the enforcement point. Agents never hold the
human factor (ADR-068 §D); they hold attenuated, expiring authority that a
human signed.

### Leg 3 — a hash-chained append-only event log binds the record

Settlements append to a per-workspace hash-chained log (each entry commits
the previous entry's digest), giving tamper evidence without a third-party
notary. This extends the existing event spine (ADR-037 audit events;
ADR-024 signed VCs for grant/denial records): the chain makes *reordering,
deletion, or post-hoc editing* of the approval record detectable, which a
mutable row cannot.

### Implemented as an extension of existing seams, not a parallel system

The Hybrid does not introduce a second approval path. It binds evidence to
the seams that already own the decisions:

- **Durable `ApprovalStore`** (`maistro.capabilities.approval_store`) — the
  resolved actor becomes the verified principal, threaded explicitly, never
  defaulted; the resolution event joins the hash chain.
- **HITL answer canonical settlement** (ADR-083026-6c72) — the one canonical
  write that settles a pause stamps the verified session principal into the
  audit record; a missing verdict never counts as approval (fail closed).
- **`GovernedInvocation` boundary** (ADR-081226-6b46) — REQUIRE_APPROVAL
  enforcement consumes the crypto-bound decision; policy still re-evaluates
  on resume, so a signed approval authorizes an effect, it does not exempt it.
- **RSI promotion** — the promotion decision is a delegated-approval shape:
  principal presence or Biscuit-delegated authority, plus chain evidence.

### Conformance with the standing record

- **ADR-068 §D** — human factor + VC records: WebAuthn is the local human
  factor; every grant/denial remains a recordable VC-style audit fact, now
  chain-committed. RLPHD auto-acting stays governed by ADR-068 §E's hard
  limits: nothing here lets a predictor mint presence.
- **ADR-024** — `did:key`/ed25519 + VC: Biscuit's ed25519 keys derive from
  the same DID substrate; approval attestations remain expressible as VCs.
- **ADR-022** — hardware signers: a hardware-backed authenticator or seed
  source plugs in as the WebAuthn/Biscuit key holder where the operator
  selects one; software keys remain the default floor, not the ceiling.
- **ADR-081226-6b46** — the Invocation boundary stays the single place
  capability effects cross into provider execution; binding happens behind it.
- **ADR-083026-6c72** — answer/timeout/cancel remain one canonical
  serialized settlement; the Hybrid adds evidence *to* that write.
- **ADR-077** — live revocation is honored: a Biscuit is an *assertion of
  attenuated authority*, not a session. Every use re-checks against host
  state (session store, ADR-068 resolver, revocation flags) exactly as
  ADR-077 requires of every token; a revoked or withdrawn delegation fails
  the re-check on its next use regardless of unexpired caveats.

## Interface

No new execution authority. Public surface deltas, all additive:

- `ApprovalStore.resolve` requires an explicit `actor` (verified principal)
  — the default is removed; callers cannot settle an approval without
  naming who settled it.
- HITL route audit records carry the resolved session principal rather than
  the literal `"system"`.
- Human verdict nodes treat a missing/empty `verdict` as *pending* (re-pause),
  never as approval.

Later phases add the WebAuthn ceremony endpoints, Biscuit minting/attenuation
at the delegation seams, and chain verification tooling; those specifications
land as their own SPECs under this ADR's authority.

## Acceptance criteria

Behavioral contracts (per [`engine#ADR-032`](ADR-032-contracts-as-acceptance-criteria.md)).
Phase 0/1 installment criteria — proven by the tests below and bound via
`@pytest.mark.ac`; the Biscuit/ADR-077 criterion lands with Phase 3.

- **AC-1**: `ApprovalStore.resolve` refuses calls that do not thread a
  verified actor; the persisted `DurableApproval.actor` is the value the
  caller supplied, never a default.
- **AC-2**: `human_approve_draft` treats a resumed answer lacking an
  explicit, non-blank, string verdict as pending — never `approved` — and
  re-pauses awaiting one; explicit verdicts still resume.
- **AC-3**: `human_delegate_to_role` never routes a payload on a missing or
  blank verdict; explicit verdicts still route.
- **AC-4**: `human_review_and_edit` treats a missing or blank verdict as
  pending — never approved; explicit verdicts with edits still resume.
- **AC-5**: the HITL door stamps the verified session principal into answer
  and cancel audit records; an answer with no verified principal is never
  recorded as the literal `"system"`.

## Test plan

| Test | Type | Covers |
|---|---|---|
| `packages/maistro-core/tests/graph/nodes/test_human_verdict_fail_closed.py` | behavioral / unit | AC-2/AC-3/AC-4: missing verdict re-pauses, never approves, across the three verdict nodes |
| `packages/maistro-core/tests/capabilities/test_durable_approval.py` | behavioral / unit | AC-1: resolve without an actor is refused; actor is persisted |
| `packages/hive-conductor/backend/tests/test_hitl_door.py` | behavioral / integration | AC-5: answer/cancel audit entries name the session principal |

## Dependencies

- ADR-068 (authorization tiers/elevation) — accepted; the Hybrid binds §D's
  elevation legs rather than replacing them.
- ADR-024 / ADR-022 — accepted; key substrates already decided there.

## Out of scope

- Changing the Goal → Graph → Run → NodeRun → Attempt execution spine or the
  canonical settlement rules of ADR-083026-6c72.
- Replacing sessions (ADR-077) — Biscuits delegate authority alongside
  sessions, not instead of them.
- Federation/multi-conductor verification of a foreign chain (deferred; the
  chain is per-workspace evidence first).
- The builders' model-populated `requires_human_approval` flag semantics
  (tracked as a residual risk until the approval gate itself is bound).

## Source references

- `packages/maistro-core/src/maistro/capabilities/approval_store.py` — durable approval seam.
- `packages/hive-conductor/backend/routes/hitl.py` — HITL door audit seam.
- `packages/maistro-core/src/maistro/graph/nodes/human_approve_draft.py` — verdict seam.
- Biscuit authorization format — attenuation tokens, offline verification.

## Links

- Issue: #329
- Phase 0/1 installment (this ADR + seam fixes): PR TBD
- Follow-up SPECs: WebAuthn ceremony, Biscuit delegation, chain verification (phases 2–4).

