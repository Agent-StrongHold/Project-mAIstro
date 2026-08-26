---
inventory-delta:
  packages/maistro-core/tests: +13
---
# claude-issue-297-agent-record-import

Thirteen new node IDs. Eight in
`packages/maistro-core/tests/persistence/test_pg_agents_real_schema.py` (six in
`TestABuiltinAgentReachesTheRegistry`, two in `TestTheRowCarriesNoTenancy`); five
net in `packages/maistro-core/tests/agents/test_factory.py`, where
`TestPersistAgentRecord`'s two cases became four and `TestTheBuiltinRow` adds
three. The two replaced cases are described below — they are part of the
finding, not incidental churn.

## The import was half of it

#297 reports that `factory.py` imports `maistro.models.agent`, a module that
exists nowhere — not in `maistro-core`, not in the Conductor app, and not
contributable from outside `maistro-core` at all, because `maistro` is a regular
package rather than a namespace one. So `_persist_agent_record` raised
`ModuleNotFoundError` on its first statement on every deployment, and the
`except Exception` logged it at WARNING as *"Failed to persist agent ... to DB"* —
a message indistinguishable from a transient database problem.

Fixing only that would have changed the exception and nothing else. The registry
could not have taken the row either.

## Three columns the registry could never write to

Measured against a real PostgreSQL 18, migrated with the shipped chain:

| Column | Migration 005 | What the registry sends | Result |
|---|---|---|---|
| `priority_tier` | `Integer` | `Literal["P0".."P5"]`, defaulting to `"P2"` | asyncpg: *'str' object cannot be interpreted as an integer* |
| `rules` | `JSONB` | newline-joined text | *invalid input syntax for type json* |
| `provenance` | `JSONB` | `"builtin"` / `"user"` | *invalid input syntax for type json* |

`priority_tier` fails at bind time, before PostgreSQL sees the statement, so it
is the one that masks the other two. `trust_tier` — the same kind of value, a
tier label — was already `Text`, which is what makes this a transcription slip
in one migration rather than a design decision.

So `PgAgentRegistry.upsert` had never once succeeded against a real deployment,
for any agent from any caller. Migration `018` corrects the three types; with
them corrected an identity upserts, `count()` and `souls()` answer, and `get()`
returns every field unchanged.

## Why the existing round-trip test did not catch it

`test_pg_agents_roundtrip.py` passes, and has all along. It builds its **own**
`agents` table in SQLite with every column `TEXT`, so the schema under test is
not the schema that ships and a type mismatch is invisible to it by
construction.

Its docstring also claimed *"a real PostgreSQL instance is not available in
CI"*, which stopped being true when the `postgres` job gained a service
container. Both are corrected in this change: the file now says what it pins
(the registry's serialization) and what it cannot (the schema), and points at
the new file for the other half.

The conftest in that directory had already written down the exact gap, before
any of this was measured:

> "That proves the query was composed; it cannot prove the query runs, that the
> table exists, or that the column types accept what the store writes."

## `TestABuiltinAgentReachesTheRegistry`

Every case drives `_builtin_agent_row` — the mapping `factory.py` itself
builds — rather than a row written for the test. A test that hand-writes the
row can pass while the factory sends something else, which is the shape of
failure this issue is about.

`test_the_tier_label_is_stored_as_the_label` asserts `"P1"` comes back rather
than merely that the write succeeded: an integer column that silently accepted a
coerced `1` would be a different kind of wrong, and "it didn't raise" is not the
claim worth pinning.

`test_reseeding_updates_rather_than_duplicates` covers the operation that
actually runs: seeding happens on every start, so the second start must not
double the roster.

## `TestTheRowCarriesNoTenancy`

The dead `AgentRecord(...)` call passed `org_id=""` and `preamble=True`. Neither
is a column in `agents`, and `org_id` must not become one — multi-tenancy
belongs to the importing product, never to `maistro-core` (ADR-019, ADR-068).
These two are the only cases here that need no server, because they are about
the row's shape rather than the database's answer.

## The handler

`except Exception` became `except SQLAlchemyError`. A database that is down or
that rejects the row is still a tolerable outcome — the agents load from the
filesystem, only the write-back is lost — but a `TypeError` or an
`AttributeError` from the row this module builds is a defect and is now raised.
The log line says which of the two happened rather than reusing one message for
both.


## The test that manufactured the missing module

`test_factory.py::TestPersistAgentRecord` had two cases, and between them they
are why this survived:

    fake_models_agent.AgentRecord = _FakeAgentRecord
    sys.modules["maistro.models"] = fake_models
    sys.modules["maistro.models.agent"] = fake_models_agent

`test_success_path_builds_record_and_upserts` **injected the missing module into
`sys.modules`** and then asserted the success path worked. Its docstring said
the module "lives in hive-conductor, not installed in core's test env" — the
same claim the production comment made, and false for the same reason. The test
did not discover the module was missing; it supplied it.

Its neighbour, `test_swallows_exceptions_and_logs`, asserted the failure was
swallowed and logged. That was true, and was the defect.

What replaces them asserts the row reaches the registry, that a database error
is tolerated *and named as one*, and — the direction that matters — that
anything which is not a database error is raised.

## Three incomplete test doubles, surfaced by the narrowing

`_EmptyRegistry` and `_BrokenRegistry` in `TestCreateAgentsFilesystem` had no
`upsert` method at all. They never needed one: the import raised before the call
could reach it, so an incomplete double was indistinguishable from a complete
one. Narrowing the handler turned both into `AttributeError` immediately, which
is the behaviour the issue asked for working on its first run.

`test_a_missing_upsert_is_raised_too` pins that, so the next incomplete double
fails rather than being absorbed.
