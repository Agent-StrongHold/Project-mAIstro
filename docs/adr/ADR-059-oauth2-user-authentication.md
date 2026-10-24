---
id: ADR-059
title: OAuth2 user authentication — real provider flow, layered over service-key authz
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-29
substrate:
  - maistro-engine#ADR-024
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-020
  - maistro-engine#ADR-064
  - maistro-engine#SPEC-014
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Identity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
---

# ADR-059: OAuth2 user authentication — real provider flow, layered over service-key authz

## Context

`maistro.security.oauth.OAuth2Provider` is a **fabricating stub**: `exchange_code_for_token()` ignores the `code`, makes no HTTP call to the provider, and returns a deterministic token whose `user_id` is literally `f"user_{provider}"` with `roles=["user"]` — i.e. everyone authenticates as the same user. It has **zero external references** (unwired), so it is not a live vuln today, but it is a total auth bypass if ever imported (the "dangerous-looking stub" medium finding).

What already exists and works:

- **B2B service-key auth** (`maistro.auth`): `ServiceKeyRegistry.authenticate(key)`, `ServiceIdentity{name, key_hash, scopes}`, a 27-value `Scope` StrEnum across 12 categories with `category:*` wildcard expansion, constant-time key compare, and FastAPI deps `require_scope` / `require_any_scope`. This is **service-to-service authZ**, not user authN.
- **Hive-conductor user auth**: `HiveUser{username, password_hash (Argon2id), role, permissions[], did}`, session cookies (`hive_session`, HttpOnly), `/v1/auth/{login,register,logout,whoami,elevate}`, and task-scoped permission **elevation**. This is the live user-auth model.

Direction already set by prior art: **ADR-020** ("LLM providers — OAuth-first where possible, API-key-paste fallback"), **SPEC-014** (in-browser OAuth for free-tier LLM providers, `PROVIDER_AUTH_EXPIRED` re-auth), **ADR-024** (DID/VC; `HiveUser.did` reserved), **ADR-044** (redaction of `gho_*` / JWT / OAuth-callback secrets). **ADR-019** governance: maistro-core stays product-agnostic and **org-id-free**; multi-tenant mapping is Stronghold's.

Note: SPEC-014's OAuth is about authenticating the Conductor **to an LLM provider** (provider credential acquisition). This ADR is about authenticating a **human user to the Conductor** via an IdP (Google/GitHub/OIDC). They share a provider-config shape but are different flows; this ADR covers user login and explicitly defers provider-credential OAuth to SPEC-014.

## Problem

There is no real way for a human to log in with an external identity provider. The stub must be replaced with a spec-compliant Authorization-Code-with-PKCE flow that (a) actually verifies the provider, (b) maps the external identity onto an existing `HiveUser` (authZ stays local), and (c) cannot silently authenticate anyone. We must decide the authN/authZ split, identity mapping, token storage, and where the flow plugs into the existing middleware.

## Decision

**OAuth2 provides authentication (who you are); the existing `HiveUser`/`Scope` model provides authorization (what you may do).** The IdP never grants permissions directly.

### 1. Flow: Authorization Code + PKCE + state (OIDC where available)

Replace `OAuth2Provider` with a real client:

- `authorize_url(provider, redirect_uri)` → builds the IdP authorization URL with a CSRF `state` and PKCE `code_challenge` (S256); persists `{state → (provider, code_verifier, redirect_uri, expiry)}` server-side (short TTL).
- `exchange_code_for_token(provider, code, state, redirect_uri)` → validates `state`, performs the **real** token POST to the provider's `token_url` with the `code_verifier`, validates the OIDC `id_token` (issuer, audience, expiry, signature via JWKS) when present, and fetches `userinfo`. No fabrication; unknown/invalid `code` or `state` → raise, never mint a token.
- `refresh(provider, refresh_token)` → real refresh against the provider.

### 2. Identity mapping (authN → local user)

The provider's stable subject is `(provider, sub)` (never email alone — emails are mutable/reassignable). Maintain an `identity_links` mapping `(provider, sub) → HiveUser.id`:

- Known link → resolve to that `HiveUser`; issue the **existing Hive session** (same cookie, same `permissions`, same elevation model). OAuth changes only *how* the session is established.
- No link → **do not auto-provision an admin.** Either (a) link to the currently-logged-in user (account linking), or (b) create a `role="user"` with empty `permissions[]` **only if** open registration is enabled (mirrors `/v1/auth/register`'s "registration unavailable until setup complete" guard). First-run admin is never created via OAuth.

### 3. Token storage

Provider access/refresh tokens are **secrets** → stored via the engine's `vault.py` (age-encrypted), keyed by `HiveUser.id` + provider, **never** in the session cookie or client bundle, and redacted in logs (ADR-044). The browser holds only the opaque `hive_session` cookie, exactly as today. OAuth tokens are server-side only.

### 4. Middleware integration

No new auth path for normal requests: OAuth's *output* is a standard Hive session, so `AuthMiddleware` and `_PUBLIC_PREFIXES` are unchanged except for adding the callback route (`/v1/auth/oauth/{provider}/callback`) and start route to the public prefixes. Service-key auth (`maistro.auth`) is untouched and remains the path for machine-to-machine.

### 5. Scope/role mapping

IdP scopes (`openid profile email`) are used only to fetch identity; they do **not** map to Hive `Scope`/permissions. A user's capabilities come solely from their `HiveUser.permissions` + task elevation. (Optional, deferred: an admin-configured `group → permission` map for IdPs that expose groups.)

## Interface (sketch)

```python
@dataclass(frozen=True)
class OAuthProviderConfig:
    name: str
    authorization_url: str
    token_url: str
    jwks_url: str | None        # for OIDC id_token verification
    userinfo_url: str | None
    client_id: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    # client_secret resolved from vault, never stored here

class OAuth2Client:
    def authorize_url(self, provider: str, redirect_uri: str) -> tuple[str, str]:  # (url, state)
        ...
    async def exchange_code(self, provider: str, code: str, state: str,
                            redirect_uri: str) -> OAuthIdentity: ...  # validated; raises on bad code/state
    async def refresh(self, provider: str, refresh_token: str) -> OAuthToken: ...

@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    sub: str                    # stable provider subject
    email: str | None
    email_verified: bool
    display_name: str | None

class IdentityLinkStore(Protocol):
    async def resolve(self, provider: str, sub: str) -> str | None: ...      # → HiveUser.id
    async def link(self, provider: str, sub: str, user_id: str) -> None: ...
```

## Acceptance criteria

- [ ] `OAuth2Client.exchange_code` performs a **real** token request and returns an identity only for a valid `(code, state, code_verifier)`; an invalid/replayed `code` or mismatched `state` raises (no token minted). The old fabricating stub is deleted.
- [ ] PKCE `code_challenge=S256` and a single-use, TTL-bound `state` are enforced; reusing a `state` fails.
- [ ] OIDC `id_token` is signature/issuer/audience/expiry-validated against JWKS when the provider supplies one.
- [ ] A first-time external identity does **not** receive admin and does **not** auto-create a privileged user; linking resolves to an existing `HiveUser` or (if open registration) a `role="user"` with empty permissions.
- [ ] Provider access/refresh tokens are stored age-encrypted via `vault.py`, never placed in the session cookie or any client-visible surface, and are redacted in logs (ADR-044 patterns).
- [ ] Successful OAuth login issues the **same** `hive_session` cookie as password login; downstream `AuthMiddleware`, permissions, and elevation behave identically.
- [ ] Authn events audited (`auth.oauth.login|link|refresh|failed`); no event or stored record carries `org_id` (ADR-019 CI grep).
- [ ] No code path authenticates a user without a verified provider response (negative test: stubbed provider returning error → 401, not a session).

## Open questions

1. **Where does `OAuth2Client` live — `maistro.security.oauth` or `maistro.auth`?** Recommend **`maistro.auth`** (alongside the user/identity concern) and leave `security.oauth` only if a thin compatibility shim is needed; cleanest is to delete `security/oauth.py` and re-home. Decide during implementation.
2. **`IdentityLinkStore` backing.** In-memory + the existing `JsonStore`/SQLite pattern for Hive, or a maistro-core persistence store? Recommend a **protocol with an in-memory default**, Hive provides the persistent impl (keeps core product-agnostic).
3. **Account-linking UX.** Auto-link by verified email vs require an explicit "link this provider" action while logged in. Recommend **explicit link** (email auto-link is a known account-takeover vector if `email_verified` is trusted blindly).
4. **Which providers for v0.** Google + GitHub (both well-documented OIDC/OAuth2)? Recommend **generic OIDC + Google + GitHub**, configured via `OAuthProviderConfig` so others are config-only.
5. **Relationship to ADR-024 DID.** Should a successful OAuth login also issue/sign a session VC into the audit log? Recommend yes as a follow-up once ADR-024 lands; not a v0 blocker.
6. **Admin bootstrap.** Keep first-run admin strictly password-based (setup wizard), OAuth for daily users only? Recommend **yes** — never create the first admin via an external IdP.

## Source references

- `maistro-engine:packages/maistro-core/src/maistro/security/oauth.py` — the stub being replaced.
- `maistro-engine:packages/maistro-core/src/maistro/auth/{registry,provider,_types,middleware}.py` — service-key authZ + `Scope` model (untouched).
- `maistro-engine:packages/hive-conductor/backend/routes/auth.py`, `middleware/auth.py`, `models/schemas.py` — live user/session model OAuth must produce a session for.
- `maistro-engine:packages/maistro-core/src/maistro/security/passwords.py` — Argon2id (password path stays).
- `maistro-engine:packages/maistro-core/src/maistro/vault.py` — age-encrypted token storage.
- ADR-020 setup wizard ("OAuth-first where possible").
- ADR-024 DID/VC (`HiveUser.did`; future session VCs).
- ADR-064 secret redaction (`gho_*`, JWT, OAuth callback).
- SPEC-014 LiteLLM provider OAuth (distinct flow — provider credentials, not user login).
- ADR-019 governance — product-agnostic, no `org_id`.

## Out of scope

- OAuth to authenticate the Conductor **to LLM providers** (that is SPEC-014's provider-credential flow).
- SAML / enterprise SSO, SCIM provisioning (Stronghold concern).
- Multi-tenant / `org_id` identity mapping.
- Group→permission mapping from IdP claims (deferred; permissions remain locally assigned).
- Issuing audit-log session VCs (follow-up after ADR-024 implementation).
