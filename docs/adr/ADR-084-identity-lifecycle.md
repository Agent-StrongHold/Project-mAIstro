---
id: ADR-084
title: "Identity Lifecycle — DID method, agent-authority tokens, recovery, offboarding, peer trust"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-024
  - maistro-engine#ADR-068
implements: []
related:
  - maistro-engine#ADR-022
  - maistro-engine#ADR-026
  - maistro-engine#ADR-058
  - maistro-engine#ADR-063
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Identity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-084: Identity Lifecycle

**Status:** Proposed
**Date:** 2026-05-30
**Specifies the full lifecycle** of an identity — birth (DID), delegation (authority tokens),
loss (recovery), death (offboarding), and cross-boundary trust (federation peers) — that ADR-021
(identity) and ADR-068 (authz) assume but never lay out end to end.

---

## Context

ADR-021 establishes identities and ADR-068 establishes the authz model, but the *lifecycle* is
undocumented: what DID method a local identity uses, how an agent comes to hold "a subset of its
owner's authority" (ADR-068's open phrase), what happens when a user loses their keys, what happens
when a user is removed, and how a federation peer becomes trusted. This ADR decides all five, with
deliberate consequences attached to weaker choices so the secure path is the default path.

## Decision

### 1. DID method

- **Local identities (users, agents) default to `did:key`** — self-contained, no infrastructure,
  no registry. The DID *is* the key material.
- **An identity that must be discoverable or federated publishes `did:web`** — federation is
  **opt-in**; you only take on a hosted DID document when you need to be found across a boundary.

### 2. Agent authority (resolves ADR-068)

ADR-068 says an agent "holds a SUBSET of its owner's authority" without saying how. Resolution:
the owner mints a **signed, expiring capability token** (a VC, ADR-024) **per task / per
delegation**.

- `scope <= owner's own authority` — an agent can never exceed its owner. The mint clamps it.
- The token carries a **TTL** and **auto-expires**; there is no standing agent authority.
- The agent **presents the token**; its authority **is exactly the token's scope** — nothing
  implicit, nothing ambient. Least-privilege per task.

```python
class CapabilityToken(BaseModel):           # a VC, ADR-024
    issuer: DID                             # the owner
    subject: DID                            # the agent
    scope: AuthzScope                       # clamped: scope <= issuer's authority
    task_id: str                            # per-task / per-delegation
    expires_at: datetime                    # TTL; auto-expires, no renewal-by-default
```

### 3. Account / key recovery — a capability-graded ladder

Recovery is **not one mechanism** but a ladder, **conditional on what was installed and the user's
role**, where a **better option preempts a lesser one** and choosing a **less-secure method carries
consequences**.

Availability is conditioned:

- **No HD-crypto installed → no seed-phrase option.**
- **The user is the admin → no admin-assisted recovery** (no one above them to assist).
- Method set also depends on **role** and **team-vs-solo** install.
- **M-of-N 2FA (SLIP39-style) is a backup**, offered only when the better options are unavailable.

Graded outcomes (a better method preempts a worse one):

| Method (best→worst) | Condition | Outcome |
|---|---|---|
| seed-phrase **+** admin confirm | both available | full access restored **instantly** |
| seed-phrase only | team context | restored, but the user **loses super-secure team capabilities** until a team admin re-approves |
| seed-phrase only | solo install | restored **immediately** |
| M-of-N 2FA (SLIP39) | seed unavailable | restored after an **X-hour lockout** of anything requiring escalation |
| restore-from-backup | solo, final fallback | restored, but **anything encrypted with the seed is lost** without it |

### 4. Offboarding (user removal)

On user removal, **immediately**:

- **Revoke** sessions, VCs, and device leaf certs (ADR-026).
- **Running tasks** are **cancelled or reassigned** — admin's choice.
- The user's **agents and memory are archived per retention** (audit kept), **not hard-deleted**.

Hard-delete / right-to-be-forgotten is a **Stronghold** concern (ADR-019), not handled here.

### 5. Federation peer trust

- The **preferred onboarding** is an **invite / handshake exchange with mutual DID pinning**.
- That handshake **requires explicit admin approval (a trust VC)** before the peer is active —
  pinning establishes identity, but not trust.
- **Manual admin-add** is the fallback.
- **An admin trust grant is ALWAYS required** before a peer can be used, regardless of path.

## Acceptance criteria

- [ ] Local users and agents default to `did:key`; `did:web` is used only when discoverability /
      federation is opted into.
- [ ] An agent's authority comes from a signed, expiring capability VC (ADR-024) minted per task;
      its scope is clamped to `<= owner's authority` and it auto-expires.
- [ ] An agent presenting no valid token has no authority; an expired token grants nothing.
- [ ] Recovery options offered depend on the install (no HD-crypto → no seed-phrase) and on
      role / team-vs-solo; a better method preempts a lesser one.
- [ ] Recovery outcomes are graded as specified: seed+admin → instant full; seed-only (team) →
      restored minus super-secure team caps pending admin re-approval; seed-only (solo) → instant;
      M-of-N 2FA → restored after an X-hour escalation lockout; backup fallback → seed-encrypted
      data lost.
- [ ] On user removal, sessions + VCs + device leaf certs (ADR-026) are revoked immediately; running
      tasks are cancelled or reassigned by admin choice; agents/memory are archived (audit kept),
      not hard-deleted.
- [ ] A federation peer is inactive until an admin trust grant (trust VC); mutual DID pinning alone
      does not activate it; manual admin-add is available as a fallback.

## Consequences

- ADR-068's "subset of owner's authority" is now concrete: a clamped, expiring, per-task VC, so a
  compromised agent leaks only one task's scope for one TTL.
- `did:key`-by-default keeps the common case infra-free; `did:web` is the price of being federated.
- Recovery is honest about tradeoffs — the secure path is instant, the weak paths carry lockouts,
  capability loss, or data loss, so users are steered toward installing the good options.
- Offboarding preserves audit and reversibility (archive, not delete), keeping the engine's
  records intact while cutting the user's live access at once.
- Federation stays admin-gated: no peer is ever trusted by handshake alone.

## Out of scope

- **Break-glass / emergency access** (when all approvers are unreachable) is deliberately
  **deferred** pending deeper design.
- Hard-delete / right-to-be-forgotten — Stronghold (ADR-019).
- The DID-document hosting / rotation mechanics for `did:web`.
- The exact `X` lockout duration and the M-of-N parameters (tuning detail; follow-up SPEC).
