---
id: ADR-082926-3b80
title: "A dashboard layout is saved to the Conductor's data boundary, or the save fails"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
substrate: []
implements: []
related:
  - maistro-engine#ADR-078
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_dashboard_layout.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-3b80: A dashboard layout is saved to the Conductor's data boundary, or the save fails

## Context

`routes/dashboard_layout.py` kept every user's layout in a module-level dict and
mirrored it to `backend/data/dashboard_layouts.json` — a path *inside the image*,
beside the code, not inside the volume the deployment documents as its data
boundary. A container recreate therefore lost every layout, and the loss was
silent: the write was wrapped in

```python
except Exception as e:
    logger.warning("Failed to save dashboard layouts: %s", e)
```

so a read-only filesystem, a full disk, or a root-owned directory produced a
warning in a log nobody reads and a `{"ok": true}` to the user who had just
rearranged their dashboard. The whole file was rewritten on every save, so a
crash mid-write could truncate every user's layout at once, not just the writer's.

A second copy lived in PostgREST under `user_service_state`. The read path
consulted it *before* the local file, and the write path mirrored to it through
`asyncio.ensure_future` with the result discarded — so the two could disagree,
and the one the user got back on the next GET was whichever the fallback ladder
reached first.

Everything else in the Conductor that must survive a restart already goes
through `stores.py`, whose `JsonStore` writes each key through the configured
`PersistedStore`: SQLite under `CONDUCTOR_STATE_DB` for a homelab install,
PostgreSQL where one is configured. One key per user, one upsert per save.

## Decision

Dashboard layouts are a `JsonStore` in `stores.py` like every other durable
Conductor collection, and `services/dashboard_layouts.py` owns the record shape.

- **One boundary.** The image-internal JSON file and the PostgREST mirror are
  both removed. There is one place a layout is written and one place it is read.
- **A failed write is a failed request.** `save()` writes, reads the record
  back, and raises `LayoutPersistenceError` if what came back is not what went
  in. `PUT /v1/dashboard/layout` answers **503** on that, never `{"ok": true}`.
  No `except Exception` stands between the write and the response.
- **Per user, per key.** The store key is the authenticated principal's id, so
  one user's failed or concurrent write cannot truncate another's layout. The
  route no longer falls back to a shared `"dev"` id when no principal is
  present: it answers **401**, because a shared bucket is not a default, it is
  a leak waiting for the middleware to change.
- **Conflicts are explicit.** Every record carries a `revision`. A `PUT` may
  carry `expectedRevision`; if it does and the stored revision has moved, the
  save is refused with **409** and the current record. A `PUT` without it is
  last-write-wins — the same behaviour the SPA has today, now with the revision
  in the response so a client can start checking.
- **A read does not write.** Seeding a preset used to persist from inside the
  `GET` handler, inside a bare `except`. The preset is now returned unsaved; it
  becomes durable when the user saves, which is the only moment they have said
  anything about it.

## Consequences

### Positive
- A successful `PUT` survives container recreation, because it went to the
  volume rather than to the image.
- A user whose save did not land is told so, in the response, at the moment it
  did not land.
- One writer's failure can no longer damage another's layout: SQLite upserts one
  row, where the old code rewrote the whole file.
- Layouts inherit whatever durability the deployment already configured,
  including the refusal behaviour a degraded store applies to every other write.

### Negative / Trade-offs
- Layouts written to the old `backend/data/dashboard_layouts.json` are not
  migrated. That file lives inside the image; on any deployment that has been
  recreated since it was written, it is already gone, and reading it back would
  re-introduce the boundary this removes. A user re-arranges a dashboard once.
- A deployment that was relying on the PostgREST `user_service_state` copy will
  not find layouts there any more.

### Neutral
- `expectedRevision` is optional, so the current SPA needs no change to keep
  working.
