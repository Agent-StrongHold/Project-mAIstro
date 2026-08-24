"""`PgRunStore`'s two internal guards, tested where they are reachable (#132).

Both are unreachable through the public API by construction, which is the point
of them — and which is why the conformance suite cannot cover them. They are
tested here as the pure functions they are, with no server involved.

`_integrity_failure` is the one that matters. asyncpg raises `UniqueViolationError`
for both "another Attempt is already active" and "two writers allocated the same
ordinal", and those are opposite answers: the first is a refusal a caller
handles, the second is a bug in this store's locking. The mapping lives in a
constraint *name*, so a migration that renames an index turns a handled refusal
into a generic failure silently — with nothing to notice unless the names are
asserted somewhere.
"""

from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.pg_store import OCCURRENCE_INDEX, PgRunStore, _integrity_failure
from maistro.runs.sources import (
    ADMISSION_SOURCE,
    SCHEDULE_ID_KEY,
    SCHEDULE_SOURCE,
    SCHEDULED_FOR_KEY,
)
from maistro.runs.store import ActiveAttemptExists, DuplicateOccurrence, RunIntegrityError


def _asyncpg_integrity_base() -> type[Exception]:
    """asyncpg's own integrity-violation base, resolved at import.

    The store catches this class and nothing else, so a stand-in that does not
    inherit from it would never reach the code under test.
    """
    import asyncpg

    return asyncpg.exceptions.IntegrityConstraintViolationError


class _Violation(Exception):
    """Stands in for asyncpg's constraint error, which carries the name."""

    def __init__(self, constraint_name: str | None) -> None:
        super().__init__("violates")
        self.constraint_name = constraint_name


class TestIntegrityFailureMapping:
    def test_the_active_attempt_index_maps_to_a_handled_refusal(self) -> None:
        """The name is the migration's. If `012` renames this index, the
        caller that catches `ActiveAttemptExists` stops seeing it."""
        mapped = _integrity_failure(_Violation("ix_canonical_attempts_one_active"), "nr-1")

        assert isinstance(mapped, ActiveAttemptExists)
        assert "nr-1" in str(mapped)

    def test_the_ordinal_constraint_maps_to_a_store_bug_not_a_refusal(self) -> None:
        """A caller must not retry this one: it means the NodeRun row lock did
        not hold, and retrying races the same way again."""
        mapped = _integrity_failure(_Violation("uq_canonical_attempts_node_run_ordinal"), "nr-1")

        assert isinstance(mapped, RunIntegrityError)
        assert not isinstance(mapped, ActiveAttemptExists)
        assert "row lock" in str(mapped)

    @pytest.mark.parametrize("constraint", [None, "", "some_other_constraint"])
    def test_an_unrecognised_constraint_is_not_silently_a_refusal(self, constraint) -> None:
        """Defaulting to `ActiveAttemptExists` would tell a caller to back off
        and retry over a constraint nobody has reasoned about."""
        mapped = _integrity_failure(_Violation(constraint), "nr-1")

        assert isinstance(mapped, RunIntegrityError)
        assert not isinstance(mapped, ActiveAttemptExists)


class TestThePayloadTableGuard:
    """`_locked` and `_write` interpolate the table name into SQL.

    The guard is what makes that safe: only the three canonical tables, each
    paired with its own identity column, reach the f-string. A caller passing a
    mismatched pair is a programming error and refused before any SQL is built,
    which is also why the `# nosec B608` on those lines is honest.
    """

    async def test_an_unknown_table_is_refused_before_any_sql(self) -> None:
        with pytest.raises(ValueError, match="unsupported canonical execution table"):
            await PgRunStore._write(None, "users", "user_id", "u-1", object())

    async def test_the_right_table_with_the_wrong_column_is_refused(self) -> None:
        """The pair is checked, not just the table: `canonical_runs` keyed by
        `node_run_id` would build valid SQL against the wrong column."""
        with pytest.raises(ValueError, match="unsupported canonical execution table"):
            await PgRunStore._write(None, "canonical_runs", "node_run_id", "r-1", object())


class TestTheOccurrenceClaimIsMatchedByName:
    """A unique violation on some *other* constraint is not a duplicate firing.

    The same argument `_integrity_failure` above rests on, one table over.
    asyncpg raises the same exception class for every unique index, so the only
    thing separating "this occurrence already fired" from any other constraint
    refusing the insert is the name — and reporting the wrong one would tell
    the admitter to carry the cursor past a firing that never happened.

    These use a subclass of asyncpg's **real** base class rather than a
    stand-in. `create_run` catches `_integrity_errors()`, which resolves that
    class at call time, so a plain `Exception` would sail past the guard
    untouched and the test would pass without ever entering it.
    """

    async def test_a_violation_on_another_constraint_is_re_raised(self) -> None:
        store, graph = await _store_raising(_violation("some_other_index"))

        with pytest.raises(_AsyncpgViolation):
            await store.create_run(graph, provenance=_occurrence_provenance())

    async def test_the_occurrence_index_becomes_a_duplicate_occurrence(self) -> None:
        """The positive half, so the two tests together pin the discrimination
        rather than just one side of it."""
        store, graph = await _store_raising(_violation(OCCURRENCE_INDEX))

        with pytest.raises(DuplicateOccurrence) as caught:
            await store.create_run(graph, provenance=_occurrence_provenance())

        assert caught.value.schedule_id == "sched-1"

    async def test_a_run_claiming_no_occurrence_re_raises_even_on_that_index(self) -> None:
        """A Run with no claim cannot have violated the occurrence index, so
        matching the name alone is not enough to call it a duplicate firing."""
        store, graph = await _store_raising(_violation(OCCURRENCE_INDEX))

        with pytest.raises(_AsyncpgViolation):
            await store.create_run(graph, provenance={ADMISSION_SOURCE: "task_queue"})


class _AsyncpgViolation(_asyncpg_integrity_base()):  # type: ignore[misc]
    """A real asyncpg integrity error carrying the constraint name.

    Subclassed rather than constructed because asyncpg builds its exceptions
    from a server message; the name is all this store reads.
    """

    def __init__(self, constraint_name: str) -> None:
        super().__init__("violates")
        self.constraint_name = constraint_name


def _violation(constraint_name: str) -> _AsyncpgViolation:
    return _AsyncpgViolation(constraint_name)


def _occurrence_provenance() -> dict[str, str]:
    return {
        ADMISSION_SOURCE: SCHEDULE_SOURCE,
        SCHEDULE_ID_KEY: "sched-1",
        SCHEDULED_FOR_KEY: "2026-08-24T12:00:00+00:00",
    }


async def _store_raising(exc: Exception) -> tuple[PgRunStore, Graph]:
    """A store whose every statement fails with `exc`, on a real Project.

    The Project is real so `_validate_graph_scope` passes on its own terms —
    these tests are about what happens at the insert, and stubbing the check
    before it would leave the path under test reachable only by the stub.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    store = PgRunStore(_PoolRaising(exc), project_store=projects)
    graph = Graph(
        workspace_id="w1",
        project_id=root.project_id,
        name="g",
        nodes=[Node(node_id="n1", node_type="agent", name="a")],
    )
    return store, graph


class _PoolRaising:
    """A pool whose only connection fails every statement with `exc`."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def acquire(self) -> _PoolRaising:
        return self

    async def __aenter__(self) -> _PoolRaising:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    async def execute(self, *_args: object) -> None:
        raise self._exc
