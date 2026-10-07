from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Request
from models.schemas import MemoryEntry, MemoryNamespace
from pydantic import BaseModel, ConfigDict
from services.owned_records import memory_entries_for

router = APIRouter(tags=["memory"])


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/namespaces", response_model=list[MemoryNamespace])
def list_namespaces(request: Request) -> list[MemoryNamespace]:
    """The caller's namespaces, derived from their durable entries (#389).

    This used to return a hard-coded seed (`default`, one entry, 1024 bytes)
    no write could ever change. The canonical owner of namespace state is the
    memory entries themselves: the namespaces here are grouped from the
    entries the authenticated principal owns, with real counts and real
    sizes. Empty means the caller has no entries — empty-valid, distinct from
    unauthorized (a foreign entry is invisible, not an error) and from a
    failure (which raises).
    """
    counts: dict[str, tuple[int, int]] = {}
    for entry in memory_entries_for(request).values():
        n, size = counts.get(entry.namespace, (0, 0))
        counts[entry.namespace] = (
            n + 1,
            size + len(entry.value.encode("utf-8")),
        )
    return [
        MemoryNamespace(name=name, entry_count=n, size_bytes=size)
        for name, (n, size) in sorted(counts.items())
    ]


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


@router.post("/entries/{entry_id}/contradict", response_model=MemoryEntry)
def contradict_entry(entry_id: str, request: Request) -> MemoryEntry:
    """Record a contradiction against an entry — durably, on the entry (#389).

    This route used to check the entry existed and return
    `{"status": "contradiction_registered"}` without storing anything: a
    success for an operation that did nothing. A contradiction is now a state
    change on the durable entry itself (`contradictions` += 1), returned as
    the updated entry so the caller sees the state they caused. 404 keeps
    its one answer for missing and foreign entries (the OwnedStore rule).
    """
    owned = memory_entries_for(request)
    entry = owned.require(entry_id)
    t = _now()
    return owned.update(
        entry_id,
        entry.model_copy(update={"contradictions": entry.contradictions + 1, "updated_at": t}),
    )


@router.get("/stats")
def memory_stats(request: Request) -> dict:
    entries = memory_entries_for(request).values()
    total = len(entries)
    ns_counts: dict[str, int] = {}
    for e in entries:
        ns_counts[e.namespace] = ns_counts.get(e.namespace, 0) + 1
    avg_accessed = sum(e.accessed_count for e in entries) / total if total else 0
    return {"total": total, "counts_by_namespace": ns_counts, "avg_accessed_count": avg_accessed}
