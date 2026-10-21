"""Machine checks for parity between the Learning SQL twins (#1156)."""

from __future__ import annotations

from maistro.persistence.learning_contract import (
    LEARNING_GENERATED_FIELDS,
    LEARNING_PERSISTED_FIELDS,
)
from maistro.persistence.pg_learnings import (
    _PG_GENERATED_FIELDS,
    _PG_INSERT_FIELDS,
    _PG_PERSISTED_FIELDS,
)
from maistro.persistence.sqlite_learnings import (
    _SCHEMA,
    _SQLITE_GENERATED_FIELDS,
    _SQLITE_INSERT_FIELDS,
    _SQLITE_PERSISTED_FIELDS,
)
from maistro.types.memory import Learning


def _sqlite_columns() -> set[str]:
    columns: set[str] = set()
    for line in _SCHEMA.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.startswith(("CREATE", ")")):
            continue
        columns.add(stripped.split(maxsplit=1)[0])
    return columns


def test_every_declared_learning_field_has_an_explicit_disposition() -> None:
    """The disposition sets form a complete partition of the dataclass.

    A Learning field outside the partition has no disposition and fails here,
    so a future field cannot land in one persistence twin only (#1156). The
    partition itself is the disposition map; there is deliberately no derived
    dict in ``learning_contract`` because vulture's src-only scan cannot see
    this test consumer and would bank it as dead (exact-debt-ledger).
    """
    declared = set(Learning.__dataclass_fields__)

    assert declared == (LEARNING_PERSISTED_FIELDS | LEARNING_GENERATED_FIELDS)
    assert LEARNING_PERSISTED_FIELDS.isdisjoint(LEARNING_GENERATED_FIELDS)
    assert {"id"} == LEARNING_GENERATED_FIELDS
    # Every persisted field is named verbatim in the shared insert contract of
    # both twins; nothing durable is silently synthesized or dropped.
    assert not (declared - LEARNING_GENERATED_FIELDS) - LEARNING_PERSISTED_FIELDS


def test_sql_twins_declare_the_same_complete_persistence_contract() -> None:
    declared = set(Learning.__dataclass_fields__)
    persisted = declared - LEARNING_GENERATED_FIELDS

    assert _SQLITE_PERSISTED_FIELDS == _PG_PERSISTED_FIELDS == persisted
    assert _SQLITE_GENERATED_FIELDS == _PG_GENERATED_FIELDS == LEARNING_GENERATED_FIELDS
    assert set(_SQLITE_INSERT_FIELDS) == set(_PG_INSERT_FIELDS) == persisted
    assert persisted <= _sqlite_columns()
