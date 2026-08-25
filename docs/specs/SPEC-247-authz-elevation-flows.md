---
id: SPEC-247
title: "Elevation flows — self-elevation re-auth and agent scoped-2FA (ADR-068 §D)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-028
implements:
  - maistro-engine#ADR-068
related:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-246
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-245
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_elevation_grants.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-247: Elevation flows — self-elevation re-auth and agent scoped-2FA

## Context

ADR-068 §D distinguishes two elevation flavors: **self-elevation** (a human re-authenticates
with their own password/passkey for a within-authority, high-consequence action — proving
liveness + intent, not asking permission) and the **agent scoped-2FA leg** (an agent can never
self-elevate; it emits a scoped approval request — single action, concrete args, short TTL —
to its owning human, whose signature is the agent's second factor). SPEC-245's `authorize()`
surfaces `needs == "self_elevation"` or `"scoped_2fa"` but does nothing to clear either. This
SPEC adds the grant lifecycle.

## Goals

- Add `ElevationGrant` type (`principal_id`, `action_class`, `granted_at`, `ttl_seconds`,
  `kind: Literal["self_elevation", "scoped_2fa"]`, `signed_by`) and an `ElevationStore`
  protocol + `InMemoryElevationStore` (mirroring the `EpisodicStore`/`OutcomeStore` DI pattern).
- `request_self_elevation(principal, action_class) -> ElevationChallenge`: stub challenge
  object (no real password/passkey verification — that's an auth-substrate integration point,
  out of scope); `confirm_self_elevation(challenge, proof) -> ElevationGrant` records a
  short-TTL grant scoped to `action_class`.
- `request_scoped_2fa(agent_principal, action, args) -> ScopedApprovalRequest`: for `kind ==
  "agent"` principals only; raises if called with a human principal. Captures the single
  action + concrete args + short TTL per ADR-068 §D ("single action, concrete args, short
  TTL"). `confirm_scoped_2fa(request, owner_signature) -> ElevationGrant`: the owning
  human's signature clears it; the grant is scoped to that one action instance, not reusable
  for a different call.
- `Sentinel.authorize()` (SPEC-245) checks `ElevationStore` for an unexpired matching grant
  before falling through to `needs="self_elevation"/"scoped_2fa"` — i.e. a still-valid prior
  grant short-circuits the gate to `authorized=True, needs="none"`.
- Every grant/denial/expiry emits an audit event (`maistro.security._types.AuditLog`,
  ADR-037) — no VC/DID signing substrate in this SPEC (ADR-023/024 are a separate crypto
  layer, explicitly deferred per ADR-068's own out-of-scope list and CLAUDE.md's
  crypto/onboarding-is-Deferred note).

## Non-goals

- Real password/passkey verification or DID/wallet signature checking — `proof`/
  `owner_signature` are opaque tokens in this SPEC; the actual auth substrate integration
  is a follow-up once ADR-023/024 land.
- Notification channel for delivering the scoped-2FA request to the owning human (push,
  email, etc.) — product-level, ADR-051, explicitly out of scope there too.
- Persisting grants in Postgres — `InMemoryElevationStore` only, following the existing
  `InMemory*` store convention; persistence is a `maistro.persistence` follow-up.

## Decision

```python
@dataclass(frozen=True)
class ElevationGrant:
    principal_id: str
    action_class: str
    kind: Literal["self_elevation", "scoped_2fa"]
    granted_at: datetime
    ttl_seconds: int
    signed_by: str          # principal_id of self, or the owning human for scoped_2fa
    action_args_hash: str | None = None  # set for scoped_2fa; binds grant to one call

    def is_valid(self, *, now: datetime, action_class: str, args_hash: str | None = None) -> bool:
        if self.action_class != action_class:
            return False
        if (datetime.now(UTC) - self.granted_at... ) ...  # ttl check
        if self.kind == "scoped_2fa" and self.action_args_hash != args_hash:
            return False  # not reusable for different args
        return True

class ElevationStore(Protocol):
    async def store(self, grant: ElevationGrant) -> None: ...
    async def find_valid(self, principal_id: str, action_class: str, args_hash: str | None) -> ElevationGrant | None: ...
```

`request_scoped_2fa` raising on `kind == "human"` principals enforces ADR-068 §D's "an agent
NEVER holds a password and NEVER self-elevates" at the type/call level, not just by convention.

## Acceptance criteria

- [ ] A human principal clearing `self_elevation` records a grant with `kind ==
      "self_elevation"`, `signed_by == principal.id` (self-signed).
- [ ] An agent principal's `request_scoped_2fa` is rejected with a clear error if called for
      a `kind == "human"` principal.
- [ ] A scoped-2FA grant is bound to the specific action args (`action_args_hash`) — replaying
      the same grant for different args on the same `action_class` fails `is_valid`.
- [ ] An expired grant (`ttl_seconds` elapsed) fails `is_valid` and `authorize()` falls back
      to requiring a fresh elevation.
- [ ] Every grant, scoped-2FA request, and expiry produces an audit event.

## Testing

- `packages/maistro-core/tests/security/test_elevation_grants.py` (new) — grant TTL
  expiry, args-hash binding for scoped_2fa, the human-vs-agent self-elevation rejection,
  `Sentinel.authorize()` short-circuiting on a valid prior grant, audit event emission.

## Open questions

- Whether `action_args_hash` should be a hash of the canonicalized args dict or a caller-
  supplied opaque token — leaning hash (avoids caller mistakes), to confirm during
  implementation.

## References

- `packages/maistro-core/src/maistro/security/sentinel/audit.py`
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- [SPEC-245: Authorization tier ladder](SPEC-245-authz-tier-ladder.md)
