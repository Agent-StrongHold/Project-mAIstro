"""Bounded cursor reads on the existing immutable audit authority (#358).

Row identity, not request_id (which may repeat or be empty), breaks timestamp
ties. Scope and filter predicates precede LIMIT. Each supported filter shape
has an ordered index; migrations build these before traffic is served.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any

from maistro.types.security import AuditEntry

MAX_PAGE_SIZE = 200

# The boolean expression matches Hive's projection of all non-denials to info.
_FILTERS = ("user_id", "boundary", "(verdict = 'denied')")
AUDIT_PAGE_INDEXES = {
    "ix_audit_page_" + str(mask): ("org_id", *fields, "timestamp DESC", "id DESC")
    for mask, fields in enumerate(
        fields for size in range(4) for fields in combinations(_FILTERS, size)
    )
}


@dataclass(frozen=True)
class AuditPage:
    records: list[tuple[int, AuditEntry]]
    next_cursor: str | None


def decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        if len(cursor) > 1024:
            raise ValueError
        payload = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        timestamp, row_id = payload
        if (
            not isinstance(timestamp, str)
            or type(row_id) is not int
            or not 1 <= row_id <= 2**63 - 1
        ):
            raise ValueError
        datetime.fromisoformat(timestamp)
        return timestamp, row_id
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("malformed audit cursor") from exc


def page_query(
    *,
    org_id: str,
    user_id: str | None,
    boundary: str | None,
    denied: bool | None,
    limit: int,
    cursor: str | None,
    postgres: bool = False,
) -> tuple[str, list[Any]]:
    if org_id is None:
        raise ValueError("org_id cannot be None; pass '' for an unscoped read")
    values: list[Any] = []

    def bind(value: Any) -> str:
        values.append(value)
        return f"${len(values)}" if postgres else "?"

    conditions = [f"org_id = {bind(org_id)}"]
    for column, value in zip(_FILTERS, (user_id, boundary, denied), strict=True):
        if value is not None:
            conditions.append(f"{column} = {bind(value)}")
    size = max(1, min(limit, MAX_PAGE_SIZE)) + 1
    if cursor is not None:
        timestamp, row_id = decode_cursor(cursor)
        if not postgres:
            # SQLite seeks only timestamp for tuple inequalities on these
            # indexes: deep ties otherwise scan every preceding tied row.
            # Merge two disjoint, individually limited index ranges instead.
            where = " AND ".join(conditions)
            prefix = f"SELECT * FROM audit_log WHERE {where} AND "
            suffix = " ORDER BY timestamp DESC, id DESC LIMIT ?"
            same = prefix + "timestamp = ? AND id < ?" + suffix
            older = prefix + "timestamp < ?" + suffix
            return (
                f"SELECT * FROM (SELECT * FROM ({same}) UNION ALL SELECT * FROM ({older}))"
                " ORDER BY timestamp DESC, id DESC LIMIT ?",
                [*values, timestamp, row_id, size, *values, timestamp, size, size],
            )
        stamp = datetime.fromisoformat(timestamp)
        if stamp.tzinfo is None:
            raise ValueError("malformed audit cursor: timezone required")
        conditions.append(f"(timestamp, id) < ({bind(stamp)}, {bind(row_id)})")
    ceiling = bind(size)
    return (
        "SELECT * FROM audit_log WHERE "
        + " AND ".join(conditions)
        + f" ORDER BY timestamp DESC, id DESC LIMIT {ceiling}",
        values,
    )


def make_page(rows: Sequence[Mapping[str, Any]], limit: int) -> AuditPage:
    size = max(1, min(limit, MAX_PAGE_SIZE))
    records = []
    for row in rows[:size]:
        timestamp = row["timestamp"]
        records.append(
            (
                int(row["id"]),
                AuditEntry(
                    timestamp=(
                        datetime.fromisoformat(timestamp)
                        if isinstance(timestamp, str)
                        else timestamp
                    ),
                    **{
                        key: row[key]
                        for key in (
                            "boundary",
                            "user_id",
                            "org_id",
                            "team_id",
                            "agent_id",
                            "tool_name",
                            "verdict",
                            "detail",
                            "trace_id",
                            "request_id",
                        )
                    },
                ),
            )
        )
    next_cursor = None
    if len(rows) > size:
        last = rows[size - 1]
        stamp = last["timestamp"]
        payload = [stamp if isinstance(stamp, str) else stamp.isoformat(), int(last["id"])]
        next_cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return AuditPage(records, next_cursor)
