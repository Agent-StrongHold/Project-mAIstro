from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import stores
from fastapi import APIRouter, Request
from models.schemas import MemoryEntry, MemoryNamespace
from pydantic import BaseModel, ConfigDict
from services.owned_records import memory_entries_for

router = APIRouter(tags=["memory"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/namespaces", response_model=list[MemoryNamespace])
def list_namespaces() -> list[MemoryNamespace]:
    return list(stores.memory_namespaces.values())


@router.get("/entries", response_model=list[MemoryEntry])
def list_entries(request: Request, namespace: str | None = None) -> list[MemoryEntry]:
    entries = memory_entries_for(request).values()
    if namespace:
        entries = [e for e in entries if e.namespace == namespace]
    return entries


@router.get("/entries/{entry_id}", response_model=MemoryEntry)
def get_entry(entry_id: str, request: Request) -> MemoryEntry:
    return memory_entries_for(request).require(entry_id)


class PutEntryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    value: str
    namespace: str = "default"
    tags: list[str] = []


@router.post("/entries", response_model=MemoryEntry)
def create_entry(body: PutEntryBody, request: Request) -> MemoryEntry:
    eid = str(uuid4())
    t = _now()
    entry = MemoryEntry(
        id=eid,
        key=body.key,
        value=body.value,
        namespace=body.namespace,
        tags=body.tags,
        embedding=None,
        created_at=t,
        updated_at=t,
    )
    return memory_entries_for(request).create(eid, entry)


class UpdateEntryBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str | None = None
    value: str | None = None
    tags: list[str] | None = None


@router.put("/entries/{entry_id}", response_model=MemoryEntry)
def update_entry(entry_id: str, body: UpdateEntryBody, request: Request) -> MemoryEntry:
    owned = memory_entries_for(request)
    entry = owned.require(entry_id)
    updates = body.model_dump(exclude_none=True)
    updates["updated_at"] = _now()
    return owned.update(entry_id, entry.model_copy(update=updates))


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: str, request: Request) -> None:
    memory_entries_for(request).delete(entry_id)


@router.post("/entries/{entry_id}/reinforce", response_model=MemoryEntry)
def reinforce_entry(entry_id: str, request: Request) -> MemoryEntry:
    owned = memory_entries_for(request)
    entry = owned.require(entry_id)
    t = _now()
    return owned.update(
        entry_id,
        entry.model_copy(update={"accessed_count": entry.accessed_count + 1, "updated_at": t}),
    )


@router.post("/entries/{entry_id}/decay", response_model=MemoryEntry)
def decay_entry(entry_id: str, request: Request) -> MemoryEntry:
    owned = memory_entries_for(request)
    entry = owned.require(entry_id)
    t = _now()
    new_count = max(0, entry.accessed_count - 1)
    return owned.update(
        entry_id,
        entry.model_copy(update={"accessed_count": new_count, "updated_at": t}),
    )


@router.post("/entries/{entry_id}/contradict")
def contradict_entry(entry_id: str, request: Request) -> dict:
    memory_entries_for(request).require(entry_id)
    return {"status": "contradiction_registered"}


@router.get("/stats")
def memory_stats(request: Request) -> dict:
    entries = memory_entries_for(request).values()
    total = len(entries)
    ns_counts: dict[str, int] = {}
    for e in entries:
        ns_counts[e.namespace] = ns_counts.get(e.namespace, 0) + 1
    avg_accessed = sum(e.accessed_count for e in entries) / total if total else 0
    return {"total": total, "counts_by_namespace": ns_counts, "avg_accessed_count": avg_accessed}
