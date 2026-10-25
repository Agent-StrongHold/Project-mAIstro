"""Bridge Hive ``log_audit`` rows into the maistro-core Sentinel ``AuditLog`` (#53 / #325).

Hive routes and services call the synchronous ``routes.audit.log_audit`` helper.
The core store is async and owned by the bound Container. These helpers complete
the write before ``log_audit`` returns so convergence tests and sync auth paths
observe the row immediately.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from maistro.types.security import AuditEntry as CoreAuditEntry

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None


def bind_audit_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Remember the ASGI loop so sync routes on worker threads can reach the core store."""
    global _main_loop
    _main_loop = loop


def _engine_container() -> Any | None:
    try:
        from services.engine import get_engine

        engine = get_engine()
    except RuntimeError:
        return None
    return getattr(getattr(engine, "_agent_port", None), "container", None)


def _core_audit_log() -> Any | None:
    container = _engine_container()
    if container is None:
        return None
    return getattr(container, "audit_log", None)


def hive_entry_to_core(
    *,
    entry_id: str,
    action: str,
    actor: str,
    target: str | None,
    detail: dict[str, Any] | None,
    severity: Literal["info", "warning", "critical"],
    created_at: datetime,
) -> CoreAuditEntry:
    """Map Hive's JsonStore audit shape onto the core Sentinel ``AuditEntry``."""
    payload = detail or {}
    verdict = "denied" if severity in {"warning", "critical"} else "allowed"
    return CoreAuditEntry(
        timestamp=created_at,
        boundary=action,
        user_id=actor,
        verdict=verdict,
        detail=json.dumps(payload, sort_keys=True),
        request_id=entry_id,
        tool_name=target,
    )


def _sqlite_audit_path(container: Any) -> str | None:
    url = str(getattr(getattr(container, "config", None), "database_url", ""))
    if not url.startswith("sqlite:"):
        return None
    path = url.removeprefix("sqlite:///").removeprefix("sqlite://")
    return path or None


def _sync_sqlite_audit_insert(container: Any, entry: CoreAuditEntry) -> None:
    path = _sqlite_audit_path(container)
    if path is None:
        return
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, boundary, user_id, org_id, team_id, agent_id,
                tool_name, verdict, detail, trace_id, request_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.timestamp.isoformat(),
                entry.boundary,
                entry.user_id,
                getattr(entry, "org_id", "") or "",
                getattr(entry, "team_id", ""),
                entry.agent_id,
                getattr(entry, "tool_name", "") or "",
                entry.verdict,
                entry.detail,
                entry.trace_id,
                entry.request_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _sync_in_memory_audit_insert(audit_log: Any, entry: CoreAuditEntry) -> None:
    audit_log._entries.append(entry)


def write_core_audit_sync(entry: CoreAuditEntry) -> None:
    """Persist one row to the core audit store from Hive's sync ``log_audit`` seam."""
    audit_log = _core_audit_log()
    if audit_log is None:
        return
    container = _engine_container()
    class_name = type(audit_log).__name__
    try:
        if class_name == "SqliteAuditLog" and container is not None:
            _sync_sqlite_audit_insert(container, entry)
            return
        if class_name == "InMemoryAuditLog":
            _sync_in_memory_audit_insert(audit_log, entry)
            return
        loop = _main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(audit_log.log(entry), loop)
            future.result(timeout=10)
        else:
            loop.run_until_complete(audit_log.log(entry))
    except Exception:
        logger.exception("core audit write failed for boundary=%s", entry.boundary)


def core_entry_to_hive(entry: CoreAuditEntry) -> dict[str, Any]:
    """Project a core audit row into Hive's HTTP ``/v1/audit`` response shape."""
    detail_raw = entry.detail or ""
    try:
        detail = json.loads(detail_raw) if detail_raw else {}
        if not isinstance(detail, dict):
            detail = {"message": detail_raw}
    except json.JSONDecodeError:
        detail = {"message": detail_raw}
    severity = "warning" if entry.verdict == "denied" else "info"
    return {
        "id": entry.request_id or uuid4().hex,
        "action": entry.boundary,
        "actor": entry.user_id,
        "target": entry.tool_name,
        "detail": detail,
        "severity": severity,
        "created_at": entry.timestamp.astimezone(UTC).isoformat(),
    }


async def list_core_audit_entries(
    *,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
    limit: int = 10_000,
) -> list[dict[str, Any]] | None:
    """Read the core audit store when the Container exposes one."""
    audit_log = _core_audit_log()
    if audit_log is None or not hasattr(audit_log, "get_entries"):
        return None
    rows: list[CoreAuditEntry] = await audit_log.get_entries(limit=limit)
    entries = [core_entry_to_hive(row) for row in rows]
    if action is not None:
        entries = [entry for entry in entries if entry.get("action") == action]
    if severity is not None:
        entries = [entry for entry in entries if entry.get("severity") == severity]
    if actor is not None:
        entries = [entry for entry in entries if entry.get("actor") == actor]
    return entries
