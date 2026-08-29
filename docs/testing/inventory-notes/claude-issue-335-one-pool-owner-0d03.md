---
inventory-delta:
  packages/maistro-core/tests: +20
---
# claude-issue-335-one-pool-owner-0d03

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_container_pool_ownership.py` — 20 tests for SPEC-082926-730d (#335).

They count pools. That is the whole design: the leak was invisible because
nothing counted, and `get_pool` was a process singleton that ignored its
argument, so in one process the "second" pool was usually the same object and
the double-open looked like a no-op.

Nine of the eighteen need a migrated PostgreSQL (`MAISTRO_TEST_PG_DSN`) and skip
without one. That is not laziness about mocking: "how many pools did building a
container open" is only answerable when the container actually builds, and the
first draft of this file tried a fake pool and got as far as
`ProjectNotFound: Root Project for Workspace 'default'` — a fake deep enough to
reach the answer would have been a second implementation of PostgreSQL, which is
a thing that agrees with whatever the code does. `asyncpg.create_pool` is
*wrapped* rather than replaced for those, so the pools are real and the count is
still exact. The wrapper is captured at import, before any fixture patches the
name, because a test that builds its own pool through the patched name gets
counted as the container's — which is exactly the confusion under test, and it
did happen on the first run.

The other eleven are about a dict and a method and run anywhere: the per-DSN
registry, and `aclose` over a fake pool that counts its own closes. Those use a
real `Container` built on `memory://` rather than a hand-rolled stand-in, so they
cannot drift from a constructor that takes a dozen collaborators.

Two of them fail on the pre-#335 code and pass on it — verified by reverting the
one line in `_wire_postgres_backend` and re-running, not by assertion:
`test_a_supplied_pool_prevents_a_second_pool_for_the_same_database` and
`test_the_stores_and_the_events_hold_the_same_pool`. That is the issue's
definition of done ("resource-leak tests fail on the current double-pool path").

Nothing was removed. `tests/persistence/test_init.py`'s three references to the
`_pool` global became `_pools`, the registry that replaces it — same tests, same
claims, one scope narrower.

Two of the eleven exist because the branch-arc half of the diff-coverage gate
found them: closing a DSN the registry does not hold, and forgetting a pool it
never held. Both are paths a real shutdown takes — a container that already
closed its own pool, and one holding a pool the caller supplied.
