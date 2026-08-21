---
id: ADR-070426-e9da
title: Header-based CSRF defense for hive-conductor's cookie-authenticated mutations
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate: []
implements: []
related:
  - maistro-engine#ADR-058
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-e9da: Header-based CSRF defense for hive-conductor's cookie-authenticated mutations

## Context

The repo-mining sweep of `stronghold` (tracked in the Wave-2 candidate list) flagged that
`hive-conductor` — the only cookie-authenticated app in the monorepo — has no CSRF defense on its
state-changing routes, while stronghold's BFF auth layer does.

`stronghold/src/stronghold/api/routes/auth.py:43-53`'s `_check_csrf()` unconditionally requires an
`X-Stronghold-Request` header on every mutating request reaching that router. The more
defense-in-depth variant, `stronghold/src/stronghold/api/routes/sessions.py:19-36`, only enforces
the header when it actually matters: method is mutating (`POST`/`PUT`/`DELETE`) **and** no
`Authorization` bearer header is present **and** a session cookie is present. Bearer-token callers
and unauthenticated requests are left alone — they aren't CSRF-vulnerable in the first place, since
a cross-origin form POST can't attach an `Authorization` header or a cookie that belongs to a
different site.

`hive-conductor`'s own `AuthMiddleware`
(`packages/hive-conductor/backend/middleware/auth.py`) already has the shape this check would slot
into. `dispatch()` (lines ~90-131) resolves the caller via `_get_user()` (lines ~133-146), which
reads `request.cookies.get("hive_session")` first and falls back to a `Bearer ` `Authorization`
header — i.e. it already knows, per request, which of the two auth modes was used. It does this
*after* the `_PUBLIC_EXACT` / `_PUBLIC_PREFIXES` allowlist check (lines ~18-43) and *before*
`_required_permission()`/`_check_permission()` gate protected ops. There is currently no CSRF check
anywhere in this pipeline.

The highest-value target for this gap is
`packages/hive-conductor/backend/routes/auth.py`'s `POST /elevate` endpoint (lines ~266-300): it is
authenticated (requires a valid `hive_session` cookie), cookie-bearing (the whole point of the
session model), and permission-escalating (grants `elevated_permissions` for a `task_id`, logged at
`severity="warning"`). A forged cross-site POST to `/v1/auth/elevate` from a page the victim has
open, riding their session cookie, would be a textbook CSRF privilege-escalation attack if the
browser will attach the cookie automatically and the request needs nothing else the attacker
doesn't already know (the request body is attacker-controlled; only the cookie is missing from the
attacker's own origin).

`maistro-server` (`packages/maistro-server/`) is out of scope entirely: it is bearer-token-only
(no session cookie surface), so it has no CSRF attack surface to begin with — this ADR does not
touch it.

## Decision

Add a header-based CSRF check directly inside `AuthMiddleware.dispatch()`
(`packages/hive-conductor/backend/middleware/auth.py`), gated on the same three-way condition as
stronghold's `sessions.py` variant (not the blanket `auth.py` variant, which would needlessly break
bearer-token API clients):

1. `request.method` is mutating (`POST`, `PUT`, `PATCH`, `DELETE`) — hive-conductor's
   `_PROTECTED_OPS` table already enumerates `PATCH` as a first-class mutating verb, so the check
   covers one more verb than stronghold's two ported variants did.
2. A `hive_session` cookie is present on the request (mirrors `_get_user()`'s own cookie-first
   read).
3. No `Authorization: Bearer ...` header is present (mirrors `_get_user()`'s own fallback order —
   if a bearer token was used, this wasn't a cookie-riding browser request).

When all three hold, and the path isn't already public
(`_PUBLIC_EXACT`/`_PUBLIC_PREFIXES`/`_PUBLIC_PREFIXES_LOOSE`, lines ~18-43 — those routes,
`/v1/auth/login` and `/v1/auth/register` in particular, are pre-session and must remain reachable
without the header), the request must carry a custom header or the middleware returns `403` before
`call_next()` is invoked — same rejection point as the existing 401/403 branches in `dispatch()`.

The header name follows the engine's `Maistro*`-prefixed convention (see repo-root `CLAUDE.md`'s
naming-convention section) rather than porting stronghold's own `X-Stronghold-Request` name
verbatim: **`X-Maistro-Request`**. Its value is not checked — only presence, exactly like
stronghold's `_check_csrf()` — because the defense is structural: a custom header triggers a CORS
preflight, and a cross-origin form POST cannot attach custom headers at all. Same-origin requests
issued by the SPA's own `fetch()`/`axios` calls attach it trivially, the same way any legitimate
client would attach any other outbound header.

### Prerequisite (acceptance-blocking): update the `authed_client`/`admin_client` test fixtures

`packages/hive-conductor/backend/tests/conftest.py`'s `authed_client` and `admin_client` fixtures
(lines ~97-116) log in via `client.post("/v1/auth/login", ...)` and hand back a `TestClient` that
carries the resulting `hive_session` cookie for every subsequent call in the test. Once this
middleware change lands, every existing authenticated `POST`/`PUT`/`PATCH`/`DELETE` test that uses
either fixture will start failing with `403 Missing X-Maistro-Request header` — the fixture has no
reason today to attach a header nothing currently checks.

**This is not a footnote — it is an explicit prerequisite the implementing PR must ship in the same
change as the middleware, not as a follow-up.** Landing the middleware without updating the
fixtures breaks the hive-conductor test suite wholesale (every route test exercising a mutating
verb through `authed_client`/`admin_client`), and a PR that does that cannot be treated as green. The
concrete fix is for both fixtures to either (a) set `client.headers["X-Maistro-Request"] = "1"` once
after login, so every subsequent call on that client carries it automatically, or (b) wrap the
returned `TestClient` so mutating calls always attach the header. Login/register (`_PUBLIC_EXACT`)
themselves need no change since they're allowlisted before the CSRF check runs.

## Alternatives considered

**Double-submit cookie** (a second, JS-readable cookie whose value the client must echo back in a
header or body field, compared server-side). Rejected: it requires minting and validating a second
cookie value, plus wiring the SPA to read a cookie and re-attach its value — more moving parts than
a static header, for the same guarantee (a cross-origin form can't reproduce the client-side
echo step any more than it can attach a custom header). stronghold's own choice of the simpler
custom-header approach (documented directly in `stronghold/src/stronghold/api/routes/auth.py`'s
module docstring, lines 15-19) is the right one to port as-is, not to "improve" into double-submit.

**Blanket enforcement (stronghold's `auth.py::_check_csrf`, not the `sessions.py` variant).**
Rejected: it checks header presence on every mutating request regardless of auth mode, which would
also reject legitimate bearer-token API callers (e.g. the `maistro` CLI, or any future service
integration hitting hive-conductor's `/v1/` routes with a service key instead of a browser
session). The `sessions.py` variant's extra cookie-present / no-bearer-header conditions are exactly
the defense-in-depth refinement that makes this correct for an app that supports both auth modes.

**Do nothing / status quo (SameSite=Lax cookie alone).** `_issue_session()`
(`packages/hive-conductor/backend/routes/auth.py:158-164`) already sets `samesite="lax"` on the
session cookie, which blocks the cookie from riding along on cross-site POSTs from most modern
browsers. Rejected as the sole defense: `SameSite=Lax` is a browser-enforced mitigation with known
gaps (older browsers, some in-app browsers/webviews, and top-level GET-triggered navigations that
some implementations still treat as "safe" for Lax purposes) — defense-in-depth via an
application-level check that doesn't depend on browser compliance is the same judgment stronghold
already made, and there's no reason for hive-conductor to have a weaker posture on an
elevation-capable endpoint.

## Consequences

### Positive
- Closes a genuine CSRF gap on the one cookie-based app in the monorepo, specifically hardening the
  highest-value target (`POST /v1/auth/elevate`) along with every other mutating route.
- Reuses `AuthMiddleware`'s existing per-request auth-mode detection (`_get_user()`) instead of
  adding a parallel code path — the check is a few lines inside `dispatch()`, not a new middleware
  layer.
- Bearer-token callers (service integrations, the `maistro` CLI) are completely unaffected —  the
  gate only fires for cookie-riding, no-bearer-header requests.

### Negative / Trade-offs
- Every hive-conductor frontend call that mutates state must now attach `X-Maistro-Request` — a
  one-line addition to the SPA's shared `fetch`/`axios` wrapper, but a change that has to ship
  alongside the middleware, not after it, or the SPA itself starts getting 403s from its own UI.
- The test-fixture update in `conftest.py` (see Prerequisite above) is mandatory in the same PR;
  treating it as separate work risks a merge where CI is red until the follow-up lands.

### Neutral
- No change to `maistro-server`, which has no cookie-based auth surface and therefore no CSRF
  attack surface to defend.
- No change to the elevation model itself (ADR-068) — this only adds a transport-level guard in
  front of it, not a new permission or approval step.

## Non-goals

- **Implementing the code.** This ADR is docs-only, per the Wave-2 deferral decision — no change to
  `middleware/auth.py`, `routes/auth.py`, or `tests/conftest.py` ships with this record. A follow-up
  PR implements the middleware change and the fixture update together.
- Changing `maistro-server`'s auth model — it is bearer-only and out of scope.
- Double-submit-cookie or token-based CSRF schemes — explicitly rejected above in favor of the
  simpler header check.
- Revisiting `SameSite=Lax` cookie settings — those are unchanged; this ADR adds a second,
  independent layer on top.

## References

- [ADR-058: A2A delegation protocol](ADR-058-a2a-delegation-protocol.md)
- [ADR-068: Unified authorization and elevation](ADR-068-unified-authorization-and-elevation.md)
- Seams: `packages/hive-conductor/backend/middleware/auth.py` (`AuthMiddleware.dispatch`,
  `_get_user`, `_PUBLIC_EXACT`/`_PUBLIC_PREFIXES`),
  `packages/hive-conductor/backend/routes/auth.py` (`elevate`, `_issue_session`),
  `packages/hive-conductor/backend/tests/conftest.py` (`authed_client`, `admin_client`)
- Prior art: `stronghold/src/stronghold/api/routes/auth.py:43-53` (`_check_csrf`, blanket variant),
  `stronghold/src/stronghold/api/routes/sessions.py:19-36` (`_check_csrf`, defense-in-depth variant
  this ADR ports)
