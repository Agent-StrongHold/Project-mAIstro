"""Phase 5 — Signal #2 edit-lock service.

When a user manually edits a DAG field, the optimizer must NOT
auto-apply mutations to that field for `EDIT_LOCK_DAYS` (default 30).
This service exposes:

  mark_edited(dag_id, field_paths, *, user_id, now=None)
      Record a manual edit on these field paths; refreshes the TTL.

  is_locked(dag_id, field_path, *, now=None) -> bool
      Returns True if the optimizer must respect a manual override.

  locked_fields(dag_id, *, now=None) -> list[str]
      Snapshot view for the optimizer's pre-mutation check.

The store is in-memory (matches the rest of stores.py); the lock TTL
walks back from now() so a process restart re-uses persisted timestamps
when a future persistent backing lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

EDIT_LOCK_DAYS = 30


@dataclass
class _LockRecord:
    locked_until: datetime
    user_id: str = ""
    last_field: str = ""


# {dag_id: {field_path: _LockRecord}}
_locks: dict[str, dict[str, _LockRecord]] = {}


def _now(override: datetime | None = None) -> datetime:
    return override if override is not None else datetime.now(UTC)


def mark_edited(
    dag_id: str,
    field_paths: list[str],
    *,
    user_id: str = "",
    now: datetime | None = None,
    lock_days: int = EDIT_LOCK_DAYS,
) -> None:
    """Record manual edits on the given field paths; resets the TTL.

    field_paths is a list of dotted/bracketed strings e.g.
    "nodes[abc].config.temperature" or "edges[xyz].condition". The
    optimizer compares its proposed mutation path against this list
    via is_locked() before applying.
    """
    if not dag_id:
        raise ValueError("dag_id is required")
    if not field_paths:
        return
    expires = _now(now) + timedelta(days=lock_days)
    by_field = _locks.setdefault(dag_id, {})
    for path in field_paths:
        by_field[path] = _LockRecord(
            locked_until=expires,
            user_id=user_id,
            last_field=path,
        )


def is_locked(
    dag_id: str,
    field_path: str,
    *,
    now: datetime | None = None,
) -> bool:
    """True if `field_path` (or any prefix of it) has an active manual
    edit on this DAG."""
    by_field = _locks.get(dag_id, {})
    if not by_field:
        return False
    cutoff = _now(now)
    # Prefix match: if the user edited `nodes[abc].config`, an optimizer
    # mutation on `nodes[abc].config.temperature` is also locked.
    for locked_path, rec in by_field.items():
        if rec.locked_until <= cutoff:
            continue
        if field_path == locked_path or field_path.startswith(locked_path + "."):
            return True
    return False


def locked_fields(
    dag_id: str,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return the active locked field paths for a DAG (sorted, ascending)."""
    by_field = _locks.get(dag_id, {})
    cutoff = _now(now)
    return sorted(path for path, rec in by_field.items() if rec.locked_until > cutoff)


def clear(dag_id: str | None = None) -> None:
    """Drop locks. With no arg → drop all (test helper). With a dag_id →
    drop that DAG's locks. Production callers should NOT use this except
    in dag-deletion paths."""
    if dag_id is None:
        _locks.clear()
        return
    _locks.pop(dag_id, None)


def diff_dag_snapshots(
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[str]:
    """Compute the list of changed field paths between two DAG snapshots.

    Paths are dotted with [<id>] index keys for node + edge lists so a
    change to node `abc`'s config doesn't collide with node `xyz`'s.
    """
    changed: list[str] = []
    _diff_top_level(old, new, changed)
    _diff_node_list(old, new, changed)
    _diff_edge_list(old, new, changed)
    return changed


def _diff_top_level(old: dict[str, Any], new: dict[str, Any], changed: list[str]) -> None:
    for key in ("name", "description", "entry_node", "max_cycles", "run_scout", "status"):
        old_v = old.get(key)
        new_v = new.get(key)
        if old_v != new_v:
            changed.append(key)


def _diff_node_list(old: dict[str, Any], new: dict[str, Any], changed: list[str]) -> None:
    old_by_id = {n["id"]: n for n in (old.get("nodes") or [])}
    new_by_id = {n["id"]: n for n in (new.get("nodes") or [])}
    # Added + removed nodes
    for added_id in new_by_id.keys() - old_by_id.keys():
        changed.append(f"nodes[{added_id}]")
    for removed_id in old_by_id.keys() - new_by_id.keys():
        changed.append(f"nodes[{removed_id}]")
    # Modified nodes — per-field
    for shared_id in old_by_id.keys() & new_by_id.keys():
        for fld in ("role", "name", "agent_id", "model", "strategy", "prompt", "config"):
            if old_by_id[shared_id].get(fld) != new_by_id[shared_id].get(fld):
                changed.append(f"nodes[{shared_id}].{fld}")


def _diff_edge_list(old: dict[str, Any], new: dict[str, Any], changed: list[str]) -> None:
    old_by_id = {e["id"]: e for e in (old.get("edges") or [])}
    new_by_id = {e["id"]: e for e in (new.get("edges") or [])}
    for added_id in new_by_id.keys() - old_by_id.keys():
        changed.append(f"edges[{added_id}]")
    for removed_id in old_by_id.keys() - new_by_id.keys():
        changed.append(f"edges[{removed_id}]")
    for shared_id in old_by_id.keys() & new_by_id.keys():
        for fld in ("from_node", "to_node", "condition"):
            if old_by_id[shared_id].get(fld) != new_by_id[shared_id].get(fld):
                changed.append(f"edges[{shared_id}].{fld}")
