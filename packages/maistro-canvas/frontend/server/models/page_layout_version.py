import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel, _utcnow


class PageLayoutVersion(BaseModel, table=True):
    __tablename__ = "page_layout_versions"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    template_id: uuid.UUID | None = Field(default=None, foreign_key="story_templates.id")
    order_id: uuid.UUID | None = Field(default=None, foreign_key="orders.id")
    creator_id: uuid.UUID | None = Field(default=None)

    page_number: int
    version: int

    layout_state: dict = Field(default_factory=dict, sa_column=Column(JSONB, server_default="{}"))
    diff_from_previous: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, server_default="{}")
    )

    affected_element_id: str = ""
    edit_action: str = ""

    created_at: datetime = Field(default_factory=_utcnow)
