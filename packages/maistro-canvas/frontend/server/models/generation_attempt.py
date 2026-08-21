import uuid
from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel


class GenerationAttempt(BaseModel, table=True):
    __tablename__ = "generation_attempts"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    order_id: uuid.UUID | None = Field(default=None, foreign_key="orders.id", index=True)
    template_id: uuid.UUID | None = Field(default=None, foreign_key="story_templates.id")
    creator_id: uuid.UUID | None = Field(default=None, foreign_key="creators.id")

    stage: str
    scene_number: int | None = Field(default=None)
    page_number: int | None = Field(default=None)
    iteration: int = Field(default=1)

    input_context: dict = Field(default_factory=dict, sa_column=Column(JSONB, server_default="{}"))

    ai_output: str = ""
    ai_output_url: str = ""
    ai_output_metadata: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, server_default="{}")
    )

    verdict: str = Field(default="pending")

    edited_output: str = ""
    edited_output_url: str = ""
    edit_reason: str = ""
