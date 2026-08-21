import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel, _utcnow


class StoryTemplate(BaseModel, table=True):
    __tablename__ = "story_templates"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    slug: str = Field(unique=True, index=True)
    display_title: str
    title_pattern: str
    age_range: list[int] = Field(default_factory=list, sa_column=Column(JSONB, server_default="[]"))
    page_count: int = Field(default=32)
    illustration_style: str = Field(default="full_color")
    compatible_products: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, server_default="[]")
    )

    required_variables: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, server_default="[]")
    )
    optional_variables: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, server_default="[]")
    )
    wizard_steps: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, server_default="[]")
    )

    story_prompt: str = ""
    scene_structure: list[dict] = Field(
        default_factory=list, sa_column=Column(JSONB, server_default="[]")
    )

    description: str = ""
    themes: list[str] = Field(default_factory=list, sa_column=Column(JSONB, server_default="[]"))
    etsy_tags: list[str] = Field(default_factory=list, sa_column=Column(JSONB, server_default="[]"))
    preview_image_url: str = ""
    sample_book_url: str = ""
    max_characters: int = Field(default=1)

    creator_id: uuid.UUID | None = Field(default=None, foreign_key="creators.id")
    version: int = Field(default=1)
    parent_template_id: uuid.UUID | None = Field(default=None, foreign_key="story_templates.id")
    is_active: bool = Field(default=True)

    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"server_default": "NOW()"}
    )
