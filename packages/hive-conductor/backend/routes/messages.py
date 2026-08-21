from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["messages"])


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    from_agent: str
    to: str
    subject: str
    body: str
    priority: Literal["info", "warning", "critical"] = "info"
    read: bool = False
    category: str = "general"
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("")
def list_messages(category: str | None = None, unread: bool | None = None) -> list[dict]:
    msgs = list(stores.messages.values())
    if category is not None:
        msgs = [m for m in msgs if m["category"] == category]
    if unread:
        msgs = [m for m in msgs if not m["read"]]
    return msgs


@router.get("/unread-count")
def unread_count() -> dict:
    msgs = list(stores.messages.values())
    return {"count": sum(1 for m in msgs if not m["read"])}


@router.get("/{msg_id}")
def get_message(msg_id: str) -> dict:
    if msg_id not in stores.messages:
        raise HTTPException(status_code=404, detail="message not found")
    return stores.messages[msg_id]


class CreateMessageBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    from_agent: str
    to: str
    subject: str
    body: str
    priority: Literal["info", "warning", "critical"] = "info"
    category: str = "general"


@router.post("", status_code=201)
def create_message(body: CreateMessageBody) -> dict:
    msg_id = str(uuid4())
    msg = Message(
        id=msg_id,
        from_agent=body.from_agent,
        to=body.to,
        subject=body.subject,
        body=body.body,
        priority=body.priority,
        read=False,
        category=body.category,
        created_at=_now(),
    )
    stores.messages[msg_id] = msg.model_dump(mode="json")
    return msg.model_dump(mode="json")


@router.patch("/{msg_id}/read")
def mark_read(msg_id: str) -> dict:
    if msg_id not in stores.messages:
        raise HTTPException(status_code=404, detail="message not found")
    msg = Message(**stores.messages[msg_id])
    msg = msg.model_copy(update={"read": True})
    stores.messages[msg_id] = msg.model_dump(mode="json")
    return msg.model_dump(mode="json")


@router.delete("/{msg_id}", status_code=204)
def delete_message(msg_id: str) -> None:
    if msg_id not in stores.messages:
        raise HTTPException(status_code=404, detail="message not found")
    stores.messages.pop(msg_id)


@router.post("/mark-all-read")
def mark_all_read() -> dict:
    for key in list(stores.messages.keys()):
        msg = Message(**stores.messages[key])
        stores.messages[key] = msg.model_copy(update={"read": True}).model_dump(mode="json")
    return {"status": "ok"}
