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

**One owner: `services/profile_store.py`.** The HTTP route and all five
chat-tool paths call the same module; none of them touches a dict of its own.
It stores through `PersistedStore` under the namespace `user_profiles` —
the Conductor's own SQLite state, needing no service this repo does not
provision.

It follows `settings_store` (#334) rather than the `stores.py` registry that
#340 used for dashboard layouts, and the reason is the read-back below: the
`JsonStore` wrapper exposes no way to read a raw document back, so a store in
that registry can only acknowledge a write it has not confirmed. Layouts can
live with that; a profile the user is told was saved cannot.

**No cache.** Every read decodes from the store. A process cache is what let
the panel and the tools disagree without either noticing, and it is what makes
a second replica serve a profile its owner has already changed. A profile read
is one row.

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

**One field at a time, where the caller holds one fact.** `PUT` replaces the
whole document, so a client that read the profile at page load and later sends
it back deletes whatever changed in between — a fact the user set in chat, or a
second tab. `PATCH /v1/profile` sets one field, and the identity panel uses it.
That removes the lost update rather than detecting it; a revision is carried on
the record for a future caller that genuinely does replace the document.

**The handlers are synchronous, and the chat tools offload.** A write reads
SQLite and then waits in `State.flush()` — up to ten seconds with a backed-up
writer queue. In an `async` handler that blocks the event loop and stalls every
other request; Starlette runs a plain `def` handler in its threadpool instead,
which is why `routes/settings.py` is sync too. The chat tools are genuinely
async, so their writes go through `asyncio.to_thread`.

**Reads fail the way writes do.** A reader can fail for reasons that have
nothing to do with the record — I/O, permissions, a malformed database,
exhausted descriptors. Those were escaping unclassified, so `GET` answered 500
where the `PUT` beside it answered the documented 503. They are wrapped at the
same seam as the write.

**No automatic import from PostgREST, and no silence about it.** Nothing here
creates `user_profiles`, so no deployment this repo provisions can hold a row
there. An operator who created the table by hand is the one case where rows
exist — and its column shapes are whatever that operator chose, so reading them
back would be guessing and writing the guess into the durable record. Startup
logs `PROFILE_STORE_CUTOVER` when PostgREST is configured, naming what is no
longer read.

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
