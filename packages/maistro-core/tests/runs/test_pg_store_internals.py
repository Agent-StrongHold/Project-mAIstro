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

from maistro.runs.pg_store import PgRunStore, _integrity_failure
from maistro.runs.store import ActiveAttemptExists, RunIntegrityError


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
