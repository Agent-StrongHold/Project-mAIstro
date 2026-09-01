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
  - packages/hive-conductor/backend/tests/test_oauth_product_wiring.py
layer: Identity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Implemented
    date: 2026-07-02
  - status: In Progress
    date: 2026-08-31
    reason: >-
      Status corrected from Implemented (D2/#290): phases 1-2 (OAuth2 client +
      identity linking, maistro/auth/oauth.py) are real and tested, but phase 3
      routes and phase 4 audit wiring were missing when the earlier Implemented
      claim was made. As of 2026-08-31, phase 3 start/callback/session wiring
      and the canonical product auth.oauth.login/link/failed audit subset are
      implemented and tested. Status remains In Progress because provider-token
      vault persistence, product refresh/token lifecycle and
      auth.oauth.refresh audit semantics, and an authenticated
      account-link/provisioning product flow remain unmet; the shipped login
      path accepts only pre-linked active users and intentionally discards
      provider tokens.
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
- Add exact `/v1/auth/oauth/{provider}/start` and `/v1/auth/oauth/{provider}/callback`
  `GET` routes; only validated configured providers are public. Callback exchanges
  code, resolves/links identity, and issues the **existing** `hive_session` via
  the current `_issue_session` path.
- `AuthMiddleware` remains unchanged for protected-route session handling
  (OAuth output is a normal session); only the exact start/callback public-route
  decision is added.
- Tests (TestClient): full start→callback→authenticated-request happy path with a stubbed provider; stubbed provider error → 401, no session.

### Phase 4 — audit + observability
- `auth.oauth.login|link|refresh|failed` events; tokens never logged (ADR-044). No **hard tenant**
  boundary anywhere — that is Stronghold's. This criterion used to read *"No `org_id` anywhere
  (ADR-019 CI grep)"*; ADR-068 **supersedes** it and ADR-019 §"Scope vs. tenancy" records the
  correction, so `org` is a soft scope axis core may carry and there is no such grep (#386).

## Implementation status (updated 2026-08-31)

Phases 1 and 2 are implemented in `packages/maistro-core/src/maistro/auth/oauth.py`
with tests in `packages/maistro-core/tests/auth/test_oauth.py`. Phase 3 is now
implemented in Hive Conductor: exact configured-provider `GET` start/callback
routes use Authorization Code + PKCE, a browser-bound and server-side single-use
state, durable conflict-safe `(provider, sub) → HiveUser.id` links, and the
existing `_issue_session`/`hive_session` path. The end-to-end and negative
coverage is in
`packages/hive-conductor/backend/tests/test_oauth_product_wiring.py`.

Phase 4 is **partial**, not complete. Product `log_audit` records normalized
`auth.oauth.login` only after local session issuance, `auth.oauth.link` when a
new durable link wins, and sanitized `auth.oauth.failed` outcomes. Provider
access/id/refresh tokens are intentionally discarded after identity resolution,
so there is no provider-token vault persistence, product refresh/token lifecycle,
or canonical product `auth.oauth.refresh` event. The product also exposes no
authenticated account-link or OAuth provisioning route; login is limited to
pre-linked active users. Those gaps keep front matter `status: In Progress`.

Deviations from the phase text above:

- `PyJWT[crypto]` is a direct `maistro-core` dependency.
  `default_id_token_verifier()` always returns `JWKSIdTokenVerifier`; there is
  no claims-only fallback and production injection is unnecessary.
  `UnverifiedJWTClaimsValidator` remains only as an explicitly selected
  compatibility/test seam and is not selected by the product.
- Client-secret resolution remains protocol-driven in core. Hive resolves the
  configured vault key through its canonical vault-first secrets service at
  exchange time; no secret is a provider-config value. Provider tokens are not
  stored at all in the current product wiring, which is an acknowledged unmet
  criterion rather than evidence of vault persistence.
- Core retains open-registration and explicit-link seams, but the shipped Hive
  route wires `open_registration=False` and accepts pre-linked active users
  only. It never auto-provisions an admin.
- Core's pre-resolution `auth.oauth.login` event is not treated as product
  success. Hive emits canonical login audit only after `_issue_session`
  succeeds, and emits the implemented link/failed subset with normalized,
  non-secret fields.

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
