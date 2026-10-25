"""Workspace-scoped conversation session index + SessionStore transcripts (#1822).

Metadata (owner, Workspace, title, timestamps) lives in a service-owned
JsonStore — the same durability wiring as Home layouts (#1048), not a new
row in the retiring `stores.py` ledger. Transcript bodies go through the
maistro SessionStore (container.session_store when the engine is up; an
in-memory twin when tests run without a Container).

Unscoped legacy `stores.chat_sessions` rows are not migrated and remain
unreachable through these APIs (AC-6).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import stores
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from maistro.sessions.search import SessionSummary, search_sessions
from maistro.sessions.store import InMemorySessionStore
from services.model_store import JsonStore

logger = logging.getLogger("hive.conversation_sessions")

STORE_NAME = "conversation_sessions"
_SESSION_MISSING = "session not found"

session_meta_store: JsonStore = stores.register_json_store(JsonStore(STORE_NAME))

#: Module-level twin so unit tests without an engine Container still exercise
#: append/get/idempotence against a real SessionStore implementation.
_fallback_session_store = InMemorySessionStore()


class ConversationSessionRecord(BaseModel):
    """Durable index row. Transcript body is not stored here."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    user_id: str
    workspace_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _now() -> datetime:
    return datetime.now(UTC)


def _session_store() -> Any:
    """Prefer the Container's SessionStore; fall back to the in-memory twin."""
    try:
        from services import chat_runs

        container = chat_runs._container()
    except Exception:
        container = None
    store = getattr(container, "session_store", None) if container is not None else None
    if store is not None:
        return store
    return _fallback_session_store


def _load(session_id: str) -> ConversationSessionRecord | None:
    raw = session_meta_store.get(session_id)
    if not isinstance(raw, dict):
        return None
    try:
        return ConversationSessionRecord.model_validate(raw)
    except Exception:
        logger.warning("conversation session %r metadata was unreadable", session_id)
        return None


def _write(record: ConversationSessionRecord) -> ConversationSessionRecord:
    session_meta_store[record.session_id] = record.model_dump(mode="json")
    return record


async def _require_member(user_id: str, workspace_id: str) -> None:
    from services import workspace_authority

    if await workspace_authority.visible_view(user_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")


def require_owned(
    user_id: str,
    session_id: str,
    workspace_id: str | None = None,
) -> ConversationSessionRecord:
    """The caller's session, or the same 404 for missing / foreign / wrong Workspace."""
    record = _load(session_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=404, detail=_SESSION_MISSING)
    if workspace_id is not None and record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=_SESSION_MISSING)
    return record


async def create(user_id: str, workspace_id: str, title: str) -> ConversationSessionRecord:
    await _require_member(user_id, workspace_id)
    t = _now()
    record = ConversationSessionRecord(
        session_id=str(uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        title=title or "New chat",
        created_at=t,
        updated_at=t,
    )
    return _write(record)


async def list_for(
    user_id: str,
    workspace_id: str,
    *,
    query: str = "",
) -> list[ConversationSessionRecord]:
    """List this caller's Workspace sessions, optionally filtered by ADR-048 search.

    Empty ``query`` keeps the product ``updated_at`` descending order. A
    non-empty ``query`` filters title + transcript body through
    ``maistro.sessions.search.search_sessions`` (snippet/cursor pagination
    stay available to callers that map the page themselves).
    """
    await _require_member(user_id, workspace_id)
    out: list[ConversationSessionRecord] = []
    for key in list(session_meta_store.keys()):
        record = _load(key)
        if record is None:
            continue
        if record.user_id == user_id and record.workspace_id == workspace_id:
            out.append(record)

    # Always route through search_sessions so ADR-048 stays on the product
    # list path (disposition root: conversation_sessions / routes.chat).
    summaries: list[SessionSummary] = []
    store = _session_store()
    for record in out:
        history: list[dict[str, str]] = []
        if query:
            history = list(await store.get_history(record.session_id))
        body_parts = [record.title, *(str(m.get("content", "")) for m in history)]
        summaries.append(
            SessionSummary(
                session_id=record.session_id,
                started_at=record.created_at,
                message_count=len(history),
                title=record.title,
                body="\n".join(body_parts),
            )
        )
    page = search_sessions(
        summaries,
        query=query,
        limit=max(len(summaries), 1),
    )
    by_id = {record.session_id: record for record in out}
    matched = [by_id[item.session_id] for item in page.items if item.session_id in by_id]
    if query:
        return matched
    return sorted(matched, key=lambda record: record.updated_at, reverse=True)


async def get(
    user_id: str, session_id: str
) -> tuple[ConversationSessionRecord, list[dict[str, str]]]:
    record = require_owned(user_id, session_id)
    history = await _session_store().get_history(session_id)
    return record, list(history)


async def delete(user_id: str, session_id: str) -> bool:
    """Remove one of this owner's sessions; silent for missing/foreign (no oracle)."""
    record = _load(session_id)
    if record is None or record.user_id != user_id:
        return False
    session_meta_store.pop(session_id, None)
    await _session_store().delete_session(session_id)
    return True


async def append_turn(
    session_id: str,
    messages: list[dict[str, str]],
    turn_id: str | None = None,
) -> None:
    """Append a turn to the SessionStore and bump the metadata timestamp.

    `turn_id` is the SessionStore idempotence key (ADR-083026-5fab): a retry
    with the same identity is a no-op at the transcript layer.
    """
    store = _session_store()
    already = False
    if turn_id is not None:
        provenance = getattr(store, "turn_provenance", None)
        if callable(provenance) and provenance(session_id, turn_id) is not None:
            already = True
    await store.append_messages(session_id, messages, turn_id=turn_id)
    if already:
        return
    record = _load(session_id)
    if record is None:
        return
    _write(record.model_copy(update={"updated_at": _now()}))


def reset_for_tests() -> None:
    """Clear metadata and the fallback transcript twin between tests."""
    for key in list(session_meta_store.keys()):
        session_meta_store.pop(key, None)
    global _fallback_session_store
    _fallback_session_store = InMemorySessionStore()
