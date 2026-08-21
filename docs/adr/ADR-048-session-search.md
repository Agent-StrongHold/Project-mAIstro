---
id: ADR-048
title: Session Search — Episodic memory inspector endpoint
repo: maistro-engine
kind: adr
status: Implemented
created: 2026-05-13
substrate:
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Implemented
---

# ADR-048: Session Search — Episodic memory inspector endpoint

## Context

Maistro has rich episodic memory (`src/maistro/memory/episodic/`) but no way for an integrating product to *list and search past sessions*. Project_mAIstro's UI, AgentTuring's reflection loop, and the hermes-style Sessions screen all want the same thing: paginated session list, full-text search over message bodies, snippet highlights, and a resume hook.

Hermes-desktop ships this as `src/renderer/src/screens/Sessions/Sessions.tsx` + `src/main/session-cache.ts` + `src/main/sessions.ts` — cached-then-synced list, debounced search returning snippets with `<<…>>` markers, date grouping, resume-into-chat. That's the user-facing capability we should make a substrate primitive so product repos don't each build it against the raw episodic store.

## Problem

No HTTP surface over episodic memory. Products would have to query Postgres directly, duplicate snippet-highlighting, and risk inconsistent privacy/scoping behavior.

## Solution sketch

One read-only endpoint, `GET /v1/sessions`, backed by Postgres `pg_trgm` over message bodies plus a covering index on `(profile_id, started_at DESC)`. Snippets generated server-side with `ts_headline` so all clients render the same highlight format (`<<term>>`). No new storage — reads through the existing episodic store interface (ADR-016). Auth/scoping enforced via the existing profile middleware so a tenant only sees its own sessions.

## Endpoint

```
GET /v1/sessions?q=<query>&profile_id=<id>&since=<iso>&limit=50&cursor=<opaque>
→ 200
{
  "items": [
    {
      "session_id": "uuid",
      "started_at": "2026-05-12T14:03:00Z",
      "ended_at": "2026-05-12T14:18:42Z",
      "message_count": 24,
      "model": "claude-opus-4-7",
      "title": "morning briefing",      // first-message-derived, cached on session row
      "snippet": "... and the <<weather>> looks ...",
      "tokens": { "in": 12034, "out": 4421 }
    }
  ],
  "next_cursor": "opaque-or-null"
}
```

`q` omitted → plain reverse-chronological list (no FTS cost, used by the "recent sessions" view).
`q` present → pg_trgm rank against message bodies, `ts_headline` snippet.

## Data path

1. Request hits `api/sessions.py` router.
2. Profile middleware injects `profile_id` from the auth context; any client-supplied `profile_id` must match or 403.
3. Repository call against `EpisodicStore.search(query, profile_id, since, limit, cursor)`.
4. Adapter implementations: Postgres (production) + in-memory (tests). Sqlite path uses FTS5; Postgres path uses pg_trgm + GIN.

## Acceptance criteria

- [ ] `GET /v1/sessions` without `q` returns sessions reverse-chronologically in <100ms p95 for a profile with 10k sessions.
- [ ] `GET /v1/sessions?q=foo` returns ranked results with `snippet` containing `<<foo>>` markers, p95 <300ms at 100k messages.
- [ ] Cross-tenant leak test: profile A's auth token never returns profile B's `session_id` even on identical `q`.
- [ ] Cursor pagination is stable under concurrent writes (uses `(started_at, session_id)` tuple, not offset).
- [ ] OTel span `sessions.search` records `q.length`, `hit_count`, `cursor_used` attributes.

## Open questions

1. **Title derivation.** Compute lazily on first read, or write at session end via a hook in the conductor? Recommend write-at-end (cheap, makes search response deterministic).
2. **Snippet width.** Hermes uses ~80 chars on either side of the hit. Make it a query param (`snippet_chars=80`) with a server cap?
3. **Soft-deleted sessions.** Should `GET /v1/sessions` include them with a flag, or always exclude? Recommend exclude by default; add `?include_deleted=true` admin-only.
4. **Resume action.** This ADR is read-only — "resume into a new task carrying this session as context" is a separate `POST /v1/tasks` shape and lives in a follow-up ADR.
5. **Cross-session vector search.** Episodic store has embeddings; do we expose a `mode=semantic` switch here, or keep that on a separate `/v1/memory/search` endpoint? Recommend separate endpoint to keep this one simple and lexical.

## Source references

- `hermes-desktop:src/renderer/src/screens/Sessions/Sessions.tsx` — UX target (debounced search, snippet markers, date grouping)
- `hermes-desktop:src/main/session-cache.ts` — cached-then-synced list pattern
- `hermes-desktop:src/main/sessions.ts` — server-side search shape
- `maistro-engine:src/maistro/memory/episodic/` — underlying store (ADR-016)
- `maistro-engine:src/maistro/api/ws.py` — existing session-scoped streaming, defines `session_id` semantics

## Out of scope

- Resume / fork-from-session endpoint (separate ADR).
- Semantic / vector search mode.
- Full message-by-message session detail endpoint — `GET /v1/sessions/{id}/messages` is implied but specced separately.
- UI — substrate exposes API only.
