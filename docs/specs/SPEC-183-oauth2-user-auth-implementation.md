---
id: SPEC-183
title: OAuth2 user authentication — implementation
repo: maistro-engine
kind: spec
status: In Progress
created: 2026-05-29
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-059
implements:
  - maistro-engine#ADR-059
related:
  - maistro-engine#ADR-020
  - maistro-engine#ADR-024
  - maistro-engine#SPEC-014
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/auth/test_oauth.py
layer: Identity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Implemented
    date: 2026-07-02
  - status: In Progress
    date: 2026-07-29
    reason: >-
      Status corrected from Implemented (D2/#290): phases 1-2 (OAuth2 client +
      identity linking, maistro/auth/oauth.py) are real and tested, but no
      /v1/auth/oauth/{provider}/start-or-callback route exists anywhere in the
      tree (phase 3) and no audit-event wiring (phase 4).
---

# SPEC-183: OAuth2 user authentication — implementation

Implements [ADR-059](../adr/ADR-059-oauth2-user-authentication.md). Replaces the fabricating `security/oauth.py` stub with a real Authorization-Code-+-PKCE flow whose output is a standard Hive session.

## Context

`OAuth2Provider` fakes tokens and authenticates everyone as `user_{provider}`. The live user model is Hive's `HiveUser` + `hive_session` cookie + Argon2id password login + task-scoped elevation. ADR-059 keeps that authZ model and makes OAuth strictly an authN front-door that resolves to an existing `HiveUser`.

## Decision (target)

Phased PRs to `integration`, TDD throughout. Negative tests (no token on bad input) are first-class.

### Phase 1 — real OAuth2 client (core)
- New `maistro.auth.oauth`: `OAuthProviderConfig`, `OAuth2Client.authorize_url` (state + PKCE S256), `exchange_code` (real token POST + OIDC `id_token` JWKS validation + userinfo), `refresh`. Server-side `state→(provider, code_verifier, redirect_uri, ttl)` store (protocol + in-memory default).
- Delete `maistro.security.oauth` stub (re-home any used type); update the medium-finding note.
- Client secrets + provider tokens resolved/stored via `vault.py`; redaction patterns confirmed (ADR-044).
- Tests: valid `(code,state,verifier)` → identity; bad/replayed `code` or `state` → raises, **no token**; OIDC id_token signature/issuer/aud/exp validated; refresh works.

### Phase 2 — identity linking
- `IdentityLinkStore` protocol (`resolve(provider, sub)`, `link(...)`) with in-memory default; map `(provider, sub) → HiveUser.id`.
- Linking rules: known link → that user; no link → explicit account-link while logged in, OR `role="user"` empty-permissions creation **only** if open registration enabled; never auto-create admin.
- Tests: first-time identity gets no admin/no privileged auto-provision; explicit link resolves to existing user; email is not used as the join key.

### Phase 3 — hive-conductor routes + middleware
- Add `/v1/auth/oauth/{provider}/start` and `/v1/auth/oauth/{provider}/callback` (public prefixes); callback exchanges code, resolves/links identity, and issues the **existing** `hive_session` via the current `_issue_session` path.
- `AuthMiddleware` unchanged for protected routes (OAuth output is a normal session).
- Tests (TestClient): full start→callback→authenticated-request happy path with a stubbed provider; stubbed provider error → 401, no session.

### Phase 4 — audit + observability
- `auth.oauth.login|link|refresh|failed` events; tokens never logged (ADR-044). No `org_id` anywhere (ADR-019 CI grep).

## Implementation status (2026-07-02, status corrected 2026-07-29)

Phases 1 and 2 are implemented in `packages/maistro-core/src/maistro/auth/oauth.py`
with tests in `packages/maistro-core/tests/auth/test_oauth.py`. **Phase 3
(hive-conductor start/callback routes + middleware public prefixes) and Phase 4
(audit-event wiring into the product event bus) are follow-up work.** Front matter
was corrected from `Implemented` to `In Progress` (D2/#290): there is no
`/v1/auth/oauth/{provider}/start`-or-`/callback` route anywhere in the tree, so
this spec's own two-phase gap makes the feature unreachable end-to-end today,
which `Implemented` did not convey.

Deviations from the phase text above:

- id_token verification uses PyJWT (`JWKSIdTokenVerifier`) behind an
  `IdTokenVerifier` protocol; PyJWT arrives transitively (no new pyproject
  dependency). If PyJWT is absent, `default_id_token_verifier()` falls back to
  `UnverifiedJWTClaimsValidator` (claims-only, loud warning) — inject the JWKS
  verifier in production.
- Vault integration is via injection, not direct import: client secrets are
  resolved through a `SecretResolver` callable and audit events through an
  `EventEmitter` callable (payloads never carry tokens, ADR-044). The product
  wires these to `vault.py` and its event bus in Phase 3/4.
- Unknown identity with open registration is provisioned via an injected
  `UserProvisioner` (product creates the `role="user"`, empty-permissions
  record); core never creates users or grants admin.

## Out of scope (this spec)
- Provider-credential OAuth for LLM providers (SPEC-014).
- SAML / enterprise SSO / SCIM (Stronghold).
- Group→permission mapping from IdP claims.
- Session VCs in the audit log (after ADR-024 implementation).
- Multi-tenant `org_id` identity mapping.

## Test strategy
- `PYTHONPATH=packages/maistro-core/src python -m pytest packages/maistro-core/tests/auth -q` (client/linking) and `pytest packages/hive-conductor/backend/tests` (routes).
- Security invariant: there exists **no** path that yields a session without a verified provider response (explicit negative test + `run-formal` if it touches a pinned invariant).

## References
- [ADR-059](../adr/ADR-059-oauth2-user-authentication.md)
- [ADR-020](../adr/ADR-020-setup-wizard.md), [ADR-024](../adr/ADR-024-agent-identity-did-vc.md), [SPEC-014](SPEC-014-litellm-freetier.md)
