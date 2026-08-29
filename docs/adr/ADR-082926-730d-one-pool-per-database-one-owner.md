---
id: ADR-082926-730d
title: "One asyncpg pool per database, owned by the registry"
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
substrate:
  - maistro-engine#ADR-082226-5104
implements: []
related:
  - maistro-engine#ADR-087
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/test_container_pool_ownership.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082926-730d: One asyncpg pool per database, owned by the registry

## Context

`create_container` accepts a `pg_pool` and a `database_url`. Given both, it took
the URL branch anyway: `_wire_postgres_backend` called `get_pool()`, opened a
pool, and built the learnings, outcome, session and quota stores against it.
`_resolve_pg_pool` then preferred the *supplied* pool for everything downstream —
prompt manager, audit log, strike tracker, execution spine, durable events.

So two pools existed against one database, with the stores split across them, and
neither had an owner: nothing in the container closes a pool, and the caller who
supplied one had no way to know a second had been opened on its behalf.

Two things hid this. `maistro.persistence.get_pool` was a **process singleton
that ignored its argument** after the first call — so in a single process the
"second" pool was usually the same object, and a `get_pool("…/db_a")` followed by
`get_pool("…/db_b")` silently returned db_a's pool. And nothing closes pools at
all, so a leak has no symptom until connection slots run out.

## Decision

**One pool per database.** `get_pool(dsn)` keeps a registry keyed by DSN rather
than one global. Asking for a database that is already open returns that pool;
asking for a different one opens a different pool instead of handing back a
connection to the wrong server. `close_pool(dsn)` closes one; `close_pool()` with
no argument closes every pool this process opened, which is what every existing
caller meant.

**A supplied pool is the pool.** `create_container(pg_pool=…)` threads it into
`_wire_postgres_backend`, so the PostgreSQL branch uses it for the stores it
builds and never calls `get_pool`. Precedence is no longer a post-hoc preference
applied after both pools exist; the second pool is not created.

**The registry owns the pool; a container is a holder.** `Container.holds_pg_pool`
is true only when the container took the pool from the registry.
`Container.aclose()` *releases* what it holds and leaves a supplied pool alone —
closing a caller's pool out from under it is the mirror-image bug of leaking one.
`aclose()` is idempotent, and a release that raises does not stop the rest of the
shutdown.

The first version of this decision said "one owner", meaning the container that
opened the pool. Review showed that is unsound for the same reason the registry
exists: `get_pool` returns the *same* object to every caller of a DSN, so two
containers built from one URL would both be owners, and whichever closed first
would take the pool out from under the other — the failure surfacing later, as a
query error, far from the close (Codex, #335). So `get_pool` records a user,
`release_pool` drops one, and the pool closes when the count reaches zero.
`close_pool` remains unconditional: teardown and a failed preflight need the pool
gone regardless of who still holds a reference, and it now attempts every close
before raising, because it empties the registry first and an early return would
leave the remainder open *and* unreachable.

## Consequences

### Positive
- Every store that shares a transaction boundary shares one pool, because there
  is only one to share.
- A caller that hands in a pool keeps it: the container neither duplicates nor
  closes it.
- `get_pool` for a second database stops being a silent wrong answer.
- Container construction has a countable number of pools, which is what makes the
  leak testable rather than a thing you notice in production connection counts.

### Negative / Trade-offs
- `get_pool`'s sizing arguments still apply only to the first call *per DSN*
  rather than per process. The same surprise, one scope smaller, and now stated
  in the docstring.
- `close_pool()` closing every pool is a bigger hammer than it used to be, since
  there can now be more than one. Every current caller wants exactly that — test
  teardown and preflight failure — and the per-DSN form exists for anyone who
  does not.
- Reference counting is state that can be wrong. A caller that takes a pool and
  never releases it leaks the pool exactly as before; what changed is that the
  opposite mistake — releasing a pool someone else is using — is no longer
  possible. That is the right way round: a leak is bounded by process lifetime
  and visible in connection counts, while a close under a live user is an error
  in unrelated code, later.
- `close_pool()` now raises an `ExceptionGroup` rather than the first failure.
  A caller that caught a specific exception type from it will not match the
  group; there are no such callers today, and hiding the second failure to keep
  the old shape would defeat the reason the loop continues.

### Neutral
- The pool registry is process-global, like the singleton it replaces. Making it
  container-scoped would change every call site for a property nothing has needed.
