---
id: ADR-028
title: "Admin / User Privilege Separation — Mandatory two-tier model"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-024
implements: []
related:
  - maistro-engine#ADR-020
  - maistro-engine#ADR-022
  - maistro-engine#ADR-023
  - maistro-engine#ADR-029
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-028: Admin / User Privilege Separation — Mandatory two-tier model

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed), ADR-024 (DID/VC Identity)

---

## Context

The dominant pattern in personal-AI-agent platforms is single-user-as-root. Cisco found a third-party skill performed undisclosed data exfiltration because the agent ran with full privilege. The defense must be structural, not behavioral — asking the model to enforce its own constraints fails under prompt injection.

**Source:** `Project_mAIstro/specs/security/S-142-privilege-separation.md` (155 lines)

## Decision

**Two-tier privilege model, mandatory at install time:**

- **`admin`** — holds the Conductor Seed (ADR-021), signs elevation approvals, edits capability whitelists, rotates secrets, promotes plugin trust tiers. Annoying for daily use; that's the point.
- **`users`** (1..N) — day-to-day interaction. Cannot construct privileged AgentSpecs. Cannot read/modify vault. Cannot promote skills past `untrusted`. Privileged operations route through admin via HITL signing.

The wizard (ADR-020) does **not** produce a working install with fewer than two users (admin + at least one named user). Step 4 is structurally required. No CLI flag, env var, or headless workaround exists.

### Capability envelope

- `AgentSpec` constructed with verified identity (admin OR user, never both, never neither)
- Tool whitelist keyed on user role; admin-only tools rejected in user-keyed envelopes
- Background tasks run as specific user, not admin
- Federation messages carry issuing user identity (ADR-024)

### Elevation flow

When a user needs an admin-only operation:

1. User request → conductor detects privilege requirement → elevation request queued
2. Dashboard/push shows admin structured prompt with risk assessment
3. Admin signs via wallet app (ADR-022, ADR-023) — same UX for "send 1000 sats" and "delete directory"
4. Signature recorded as VC (ADR-024), operation proceeds

> **Amended by ADR-068:** this flow models a *human admin* signing. ADR-068 generalises it:
> (a) **self-elevation (sudo)** — a user clears a *within-authority* gate with their **own**
> password/passkey, not by asking admin; (b) the **agent principal** cannot self-elevate and
> instead sends its owning human a **scoped 2FA** request; (c) `admin`/`user` become the base
> of a **configurable role system + approver graph** in core (retiring "Full RBAC out of
> scope" below). Authorization (this ADR) is the *authorize* step preceding the ADR-051
> *approve* step; both are enforced by Sentinel (Warden supplies the trust-boundary risk).

Three elevation modes:
- **Inline ask** (default) — admin signs each operation individually
- **Time-boxed delegation** — admin grants scope for duration (15 min, 1 hour), auto-revokes
- **Pre-approved by policy** — admin signs standing policy VC ("user1 may delete files <1GB in own home")

### Identity attestation

Users identified via substrate (ADR-029):
- Tailscale/Headscale: ACL group membership → admin/user
- NetBird/Cloudflare: OIDC email → user identity
- ZeroTier/LAN/localhost: S-149 keypair challenge (`m/44'/9000'/<user-index>'`)

### `users.toml`

```toml
[admin]
pubkey = "<m/0' hex>"
email = "blake@example.com"

[[user]]
name = "lilly"
pubkey = "<m/44'/9000'/1' hex>"
role = "user"
```

Admin-signed; conductor refuses to load unsigned or invalid-signature versions.

## Interface (spec)

```python
class PrivilegeLevel(Enum):
    ADMIN = "admin"
    USER = "user"

@dataclass
class ElevationRequest:
    user: str
    operation: str
    args: dict
    risk: str
    reason: str

class PrivilegeService:
    def get_level(self, user: str) -> PrivilegeLevel: ...
    def can_perform(self, user: str, operation: str) -> bool: ...
    def request_elevation(self, user: str, operation: str, args: dict) -> str: ...
    def approve_elevation(self, request_id: str, admin_signature: bytes) -> None: ...
    def grant_delegation(self, user: str, scope: str, duration_minutes: int) -> None: ...
    def check_policy_vc(self, user: str, operation: str) -> bool: ...
```

## Acceptance criteria

- [ ] Setup wizard structurally incapable of completing with <2 users
- [ ] No CLI flag/env var produces single-user install
- [ ] `users.toml` admin-signed; conductor refuses invalid signature
- [ ] AgentSpec construction validates user identity; admin-only tools reject user-keyed envelopes
- [ ] Elevation round-trip under 30s on typical mobile push
- [ ] Time-boxed delegation: 15-min scope, auto-revoke at expiry
- [ ] Policy VCs: admin signs standing policy, auditable + revocable
- [ ] Audit log records every elevation (granted/declined/expired/revoked) as signed VC
- [ ] Background tasks run as specific user, not admin
- [ ] Federation peers cannot impersonate admin

## Out of scope

- ~~Full RBAC (roles beyond admin/user)~~ — **now in scope per ADR-068**: configurable roles +
  a policy-matrix approver graph live in core. `admin`/`user` here are the base roles.
- Custom AgentSpec role definitions (Medley plugin territory)
- Multi-tenant `tenant` isolation (Stronghold concern; `org`/`team` scope axes are core per ADR-068)

## Source references

- `~/maistro-engine/specs/security/S-142-privilege-separation.md` — full 155-line spec

## Links

- Source spec: S-142
- Related ADRs: ADR-020 (Setup Wizard), ADR-021 (Conductor Seed), ADR-022 (Hardware Signing), ADR-023 (Agent Crypto Ops), ADR-024 (DID/VC), ADR-029 (Networking Substrate)
