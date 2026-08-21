---
id: ADR-077
title: "Web and Session Security"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-068
implements: []
related:
  - maistro-engine#ADR-059
  - maistro-engine#ADR-026
  - maistro-engine#ADR-073
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-077: Web and Session Security

**Status:** Proposed
**Date:** 2026-05-30
**Formalises the existing `hive_session`** mechanism and binds the web edge to the ADR-068
authorization model, which is dynamic and therefore cannot be carried in a self-contained token.

---

## Context

The web edge currently issues a `hive_session` cookie, but the session model, cookie hardening,
CSRF posture, rate-limiting, and WebSocket authentication are unspecified and live only in code. At
the same time, ADR-068 made authority **dynamic**: short-TTL privilege elevation, revocable
delegation, device revocation, and adaptive RLPHD weights all change a principal's effective
authority between one request and the next. A self-contained token (stateless JWT) freezes authority
at mint time and would assert stale claims until it expires — exactly the wrong property for a system
whose whole point is live revocation and elevation. This ADR specifies how a browser client
authenticates and how each request resolves authority.

## Decision

Sessions are **opaque and server-side**. We do **not** use JWT for sessions.

### Opaque server-side sessions

A successful login mints a high-entropy random token (the opaque cookie value) and stores the
associated session record server-side (the formalised `hive_session` store). The cookie carries
**no claims** — only the lookup key. On every request the middleware loads the session, identifies
the principal, and then **re-resolves privileges live** through the ADR-068 resolver. Authority is
never frozen in the token, so a revocation, a delegation withdrawal, a device revocation, an
elevation expiry, or an RLPHD weight change takes effect on the **next request** with no token churn.

This is the deciding reason over stateless JWT:

- ADR-068 authority is **dynamic** — a self-contained token would assert stale authority until
  expiry.
- Opaque sessions give **instant revocation** (delete/flag the server record).
- They avoid JWT footguns — algorithm confusion (`alg: none`, HS/RS swap), secret-rotation breakage,
  and oversized claim payloads.

### Cookie hardening

The session cookie is set with:

- `HttpOnly` — not readable by page JavaScript.
- `Secure` — HTTPS only.
- `SameSite` — `Lax` for the top-level session cookie (`Strict` where the route allows).
- **Idle expiry** (sliding inactivity timeout) **and absolute expiry** (hard cap regardless of
  activity).
- **Rotation on privilege change** — the session identifier is regenerated on login and on any
  elevation/de-elevation, so a fixated or leaked pre-elevation value cannot ride an elevated session.

### CSRF

State-changing routes (`POST`/`PUT`/`PATCH`/`DELETE`) require a CSRF token that is validated against
the session (double-submit or synchroniser-token pattern). Safe methods do not. The CSRF check is
independent of the authority resolution and runs before it.

### Rate-limiting and brute-force backoff

Per-IP and per-user rate limits guard the login and other sensitive endpoints, with escalating
backoff on repeated failures. This is a first-class part of the web edge, not an afterthought.

### WebSocket authentication — same resolver

`BaseHTTPMiddleware` does **not** run for the WebSocket scope, so a WS connection that relied on
middleware would be unauthenticated. WebSocket handlers therefore authenticate **explicitly**, using
the **same** opaque-session lookup and the **same** ADR-068 `authorize()` resolver as HTTP requests.
The connection is rejected at handshake if resolution fails, and long-lived connections must tolerate
mid-connection revocation (re-check on privileged actions).

```python
# HTTP path: middleware resolves authority live, per request.
async def session_middleware(request, call_next):
    sess = await session_store.load(request.cookies.get("hive_session"))
    if sess is None:
        return unauthorized()
    if request.method in MUTATING_METHODS and not csrf_ok(request, sess):
        return forbidden()
    request.state.principal = await resolver.resolve(sess.principal_id)  # ADR-068, live
    return await call_next(request)

# WebSocket path: middleware does NOT run — authorize() in the handler.
async def ws_handler(ws):
    sess = await session_store.load(ws.cookies.get("hive_session"))
    decision = await authorize(sess, ws_action) if sess else DENY  # same resolver as HTTP
    if not decision.allowed:
        await ws.close(code=4401)
        return
    ...
```

## Acceptance criteria

- [ ] The session cookie is an opaque random value mapping to a server-side `hive_session` record and
      carries no authority claims; no JWT is used for sessions.
- [ ] Privileges are re-resolved live via the ADR-068 resolver on **every** request — a revocation or
      elevation change is reflected on the next request with no re-login (property test: revoke
      mid-session → next request denied).
- [ ] The cookie sets `HttpOnly`, `Secure`, `SameSite`, both idle and absolute expiry, and the
      session identifier rotates on login and on any privilege change.
- [ ] State-changing routes reject requests lacking a valid CSRF token; safe methods do not require
      one.
- [ ] Login and sensitive endpoints enforce per-IP and per-user rate limits with brute-force backoff.
- [ ] WebSocket connections authenticate in the handler via the same opaque-session lookup and the
      same `authorize()` resolver, and reject at handshake on failure.

## Consequences

- Authority is always current: ADR-068 elevation, delegation, device revocation, and RLPHD changes
  take effect immediately without token reissue.
- Sessions require a server-side store lookup per request (a cost JWT avoids) — acceptable for
  instant revocation and the dynamic authority model, and cacheable for the session record.
- The session store becomes a security-critical, admin-scoped component; its compromise is equivalent
  to compromising authentication, so it is hardened and audited (ADR-073).
- The WebSocket path no longer silently bypasses authentication.

## Out of scope

- The authority resolution algorithm itself — ADR-068 owns it; this ADR only binds the web edge to it.
- The session-store backend schema and eviction policy (a follow-up SPEC).
- Federated / external IdP login flows (OIDC, SSO) — a separate ADR if adopted.
- Multi-tenant session partitioning — Stronghold (ADR-019).
