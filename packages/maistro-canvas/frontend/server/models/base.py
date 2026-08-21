import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow():
    return datetime.now(UTC)


def _new_id():
    return uuid.uuid4()


class BaseModel(SQLModel):
    id: uuid.UUID = Field(default_factory=_new_id, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow)
