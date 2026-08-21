import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel, _utcnow


class Character(BaseModel, table=True):
    __tablename__ = "characters"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)
    creator_id: uuid.UUID | None = Field(default=None, foreign_key="creators.id")
    name: str
    age: int
    pronouns: str = ""
    nickname: str = ""
    photo_url: str

    ai_features: dict = Field(default_factory=dict, sa_column=Column(JSONB, server_default="{}"))
    parent_overrides: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, server_default="{}")
    )
    effective_features: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, server_default="{}")
    )

    character_sheet_url: str = ""
    sheet_generated: bool = Field(default=False)
    book_count: int = Field(default=0)

    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"server_default": "NOW()"}
    )


def merge_features(ai_features: dict, parent_overrides: dict) -> dict:
    effective = dict(ai_features)
    for key, value in parent_overrides.items():
        effective[key] = value
    return effective
