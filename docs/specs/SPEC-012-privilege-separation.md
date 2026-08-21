---
id: SPEC-012
title: "Admin / user1 privilege separation — mandatory two-tier model"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-021
implements:
  - maistro-engine#ADR-028
related: []
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
    date: 2026-04-25
---

# SPEC-012: Admin / user1 Privilege Separation

See `blakematthews-dev/project_maistro` specs/security/S-142-privilege-separation.md for full spec.

## Acceptance Criteria

- [ ] Setup wizard (SPEC-009) is structurally incapable of completing with fewer than two users (admin + at least one named user)
- [ ] No CLI flag, environment variable, or undocumented path produces a single-user install
- [ ] `users.toml` is admin-signed; conductor refuses to start with an invalid signature
- [ ] AgentSpec construction validates the user identity against `users.toml`; admin-only tools reject user-keyed envelopes
- [ ] Elevation flow: user proposes → admin signs in wallet → operation proceeds; round-trip latency under 30s on a typical mobile push
- [ ] Time-boxed delegation: admin grants a 15-min scope; user operates without prompts within scope; auto-revokes at expiry
- [ ] Policy VCs: admin signs a standing policy; auditable + revocable; user operates within policy without per-call prompts
- [ ] Audit log records every elevation (granted, declined, expired, revoked) as a signed VC
- [ ] Heartbeat / reactor-spawned tasks (SPEC-013) run as a specific user, not as admin; verified by trace inspection
- [ ] Admin key rotation invalidates all active elevation grants: when the admin rotates their `m/0'` keypair, all active time-boxed delegation scopes and policy VCs are revoked atomically; subsequent requests citing a grant signed by the previous key are rejected with `GRANT_KEY_MISMATCH`; no manual per-grant revocation is required after rotation
