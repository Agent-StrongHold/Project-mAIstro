---
id: ADR-083026-3d92
title: "Profile state has one durable owner, and no acknowledged write reaches nothing"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-082926-0b72
  - maistro-engine#ADR-082926-3b80
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_profile_durability.py
layer: Identity
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-3d92: Profile state has one durable owner, and no acknowledged write reaches nothing

## Context

The Conductor kept user profiles in a module global,
`services.chat_completion._PROFILE_CACHE`, and mirrored them to a PostgREST
table called `user_profiles`.

Three things were true of that arrangement at once.

**The durable half could not run.** `services/pg_store.py` reads
`DEPLOY_TARGET_POSTGREST_URL` / `POSTGREST_URL` at import. Unset — the default,
and what every tracked Compose profile produces — `pg_get` returns `[]` and
`pg_upsert` returns `None`, with no error and no log. And no `user_profiles`
table exists anywhere in this repository: no migration, no model, no DDL, and
`init-db.sql` contains no `CREATE TABLE` at all. The durability was not merely
unwired; it was not expressible against anything this repo ships.

**The two writers could not see each other.** `PUT /v1/profile` wrote the cache
and mirrored to PostgREST inside `contextlib.suppress(Exception)`. The chat
tools — `profile_get`, `profile_set`, `profile_delete`, `favorite_model`, and
the biographer path — read *only* PostgREST. So with PostgREST absent, every
tool read `{}` regardless of what the panel had saved, and `profile_set` wrote
that `{}` plus one field back over the cache: a save through the UI was erased
by the next field set in chat. Two owners of one fact is the defect; that they
disagreed silently is what made it invisible.

**Every surface acknowledged anyway.** The route returned the preferences it
had been sent, which reads as an acknowledgement. `KnowledgeBase.tsx`'s
`savePrompt` ended in `.catch(() => {})`. A swallow on the client, over a
swallow on the server, over a write that reached nothing.

#333 already settled the governing rule for this exact situation in the
Conductor: no silent ephemeral downgrade. #334 applied it to settings and #340
to dashboard layouts. This is the same shape, one family later.

## Decision

**One owner: `services/profile_store.py`, over `stores.user_profiles`.**
Profiles join the Conductor's own registry, the same `_all_json_stores` that
`configure_persistence` already wires to SQLite. This needs no service the repo
does not provision. The HTTP route and all five chat-tool paths call the same
module; none of them touches a dict of its own.

**`_PROFILE_CACHE` is deleted rather than wrapped.** Following ADR-082926-0b72:
removing the name makes a missed call site an `AttributeError` at import, where
a write-through wrapper would have made it a write that quietly does not land.
The four remaining readers were converted; nothing wraps.

**A write is acknowledged only after it is read back.** `PersistedStore.put_raw`
enqueues a closure for `State`'s writer thread and returns, and
`State._writer_loop` swallows what that closure raises. So a plain store write
is acknowledged before it is known to have landed — the same trap ADR-082926-0b72
documents. `profile_store.save` flushes the writer, reads the document back, and
compares it to what was sent; a disagreement raises
`ProfilePersistenceError` and the route answers 503. There is no
`contextlib.suppress` on any profile write path.

**The `user_profiles` PostgREST path is removed, not completed.** Completing it
would add an external service to the default deployment for one table, against
the precedent of #367. All nine `user_profiles` call sites go. `pg_store.py`
itself stays: `hive_memory_entries` still uses it behind `DEPLOY_TARGET_APP_ENV`,
which is a separate family and out of this record's scope.

**Deletion is a first-class operation.** A profile is user-identifying content,
so `DELETE /v1/profile` removes the record — not the fields one at a time, and
not "set it to empty". Retention is stated: a profile is kept until its owner
deletes it, because it is data the user authored about themselves and no
schedule the system picks would be the right one.

**A profile is addressed by its authenticated principal, with no fallback.**
`_user_id` used to fall back to the literal `"dev"` when the request carried a
principal with neither an id nor a username, which would have had unrelated
callers reading and writing one shared profile. It now refuses.

## Consequences

### Positive
- A profile written through the panel is readable after a restart, and is the
  same profile the chat tools read and write.
- A failed persist is a 503 to the caller and a visible error in the panel,
  rather than a 200 over a discarded write.
- The nine references to a table that does not exist are gone, so nothing
  reads as configured-but-unwired.

### Negative / Trade-offs
- `save` flushes the writer thread, so a profile write waits on the queue where
  the old one returned immediately. It returned immediately by not persisting.
- Without a state database the Conductor keeps profiles in-process. That is
  reported (`durable: false` on the record) rather than implied away.

### Neutral
- The stored envelope carries a `schema_version` and a `revision`. Neither is
  used for conflict refusal yet; they exist so a later build can add it without
  a migration, and so a forward-version record refuses to load rather than
  being coerced and re-written with its unknown fields dropped.
