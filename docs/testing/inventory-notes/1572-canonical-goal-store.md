---
inventory-delta:
  packages/maistro-core/tests: +51
---

# 1572-canonical-goal-store

Issue #1572 ships the canonical Goal store (`maistro.goals`): `Goal`,
append-only `GoalRevision` chain, Subgoal lineage, recorded lifecycle and
ownership transitions, one protocol over in-memory/SQLite/PostgreSQL
backends, Workspace-seam authorization, and immutable Run-admission binding.
Fifty-one node IDs arrive with it, all in
`packages/maistro-core/tests/goals/` except two gained legs of an existing
suite, described last.

`test_goal_store_conformance.py` (+14, parametrized ×3) is one suite over all
three backends — the in-memory reference and the SQLite and PostgreSQL
durable twins — because "the durable stores behave like the reference" is a
comparison only when the same bodies run over all three. It holds every
backend to the issue's acceptance pairs: Goal/revision/transition round-trip
through a reopen; append-only revisions with a stale CAS refused and a
concurrent append leaving exactly one winner; lifecycle CAS with every
transition out of every terminal state refused; Subgoal lineage preserving
parent Goal and Project (and refusing a parent in another Workspace or
Project); agent reassignment as a recorded, attributed, both-sides-carrying
transition with the no-op refused; and the authorization seam driven over
each backend so two principals in two Workspaces cannot read or mutate each
other's Goals and a foreign Goal raises byte-identical
`GoalNotVisible` to a missing one. The PostgreSQL leg needs a migrated
server (`MAISTRO_TEST_PG_DSN`) and skips loudly tracked-by
`MAISTRO_REQUIRE_PG_LEGS` otherwise — it was run green against a PG18
database at `alembic upgrade head` before this note was written, and it is
the leg that caught the one real bug the suite now pins: a transition does
not move `current_revision`, so the PostgreSQL CAS carries a
`status = 'active'` arm as well (the state half of "compare-and-set on
revision and state"), without which the second of two concurrent transitions
silently overwrote the first.

`test_run_goal_binding.py` (+8) proves the spine half: `admit_direct_work`
binds `goal_id`/`goal_revision` over the in-memory and SQLite Run stores,
the binding survives storage, every subsequent transition to terminal leaves
it untouched (a historical Run keeps the revision it used), unbound admission
stays unbound, a half binding is refused at the model, and a terminal Run
never moves its Goal's state — the Goal moves only through the one explicit
writer, with no transition record appearing on the Run's account.

`test_goal_wiring.py` (+6) proves composition rather than library:
`create_container` — the one composition both shipped products call — exposes
`goal_store` and a `goal_reader` that wraps the container's own stores;
`wire_goal_store` selects SQLite over a SQLite pool, PostgreSQL over a
migrated pool, refuses an *unmigrated* PostgreSQL pool with a loud in-memory
fallback instead of a store querying tables that do not exist, and falls
back to memory with a warning naming #1572 when no database exists; and a
Goal created through the container's seam is readable by its principal and
`GoalNotVisible` to everyone else.

`test_goal_restart_readback.py` (+1) is the closure leg: one SQLite file
carrying the Goal tables and the canonical Runs together — the supported
durable composition at this tier — written, every connection closed, and
read back through fresh stores with the same Goal, the same two revisions,
both recorded mutations (agent reassign and status move, each with both
sides), and the Run still carrying the goal revision it was admitted
against rather than the Goal's current one.

`test_goal_model.py` (+9) pins the record guards the stores can only be as
strict as: frozen revisions, pointer numbering from 1, no self-parenting,
required identity fields, the terminal-set and legality table (only `active`
has outgoing moves; no state moves to itself), and transition records that
must carry both sides of their kind.

Finally, the existing
`workspaces/test_sqlite_alembic_schema_parity.py` (+0 node IDs) now walks
the three Goal tables too: SQLite's own DDL and migration 053 are held to
one dialect-neutral spec (column sets, nullability, integer/timestamptz/doc
types, keys, the self-referential lineage cascade, and the project index),
so the two descriptions of the same tables cannot drift the way the scope
tables once did (#1135).
