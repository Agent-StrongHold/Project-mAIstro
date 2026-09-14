"""Machine checks for parity between the Learning SQL twins (#1156)."""

from __future__ import annotations

from maistro.persistence.learning_contract import (
    LEARNING_FIELD_DISPOSITIONS,
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
    declared = set(Learning.__dataclass_fields__)

    assert set(LEARNING_FIELD_DISPOSITIONS) == declared
    assert declared == (LEARNING_PERSISTED_FIELDS | LEARNING_GENERATED_FIELDS)
    assert LEARNING_PERSISTED_FIELDS.isdisjoint(LEARNING_GENERATED_FIELDS)
    assert {"id"} == LEARNING_GENERATED_FIELDS


def test_sql_twins_declare_the_same_complete_persistence_contract() -> None:
    declared = set(Learning.__dataclass_fields__)
    persisted = declared - LEARNING_GENERATED_FIELDS

    assert _SQLITE_PERSISTED_FIELDS == _PG_PERSISTED_FIELDS == persisted
    assert _SQLITE_GENERATED_FIELDS == _PG_GENERATED_FIELDS == LEARNING_GENERATED_FIELDS
    assert set(_SQLITE_INSERT_FIELDS) == set(_PG_INSERT_FIELDS) == persisted
    assert persisted <= _sqlite_columns()
