from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel


class Creator(BaseModel, table=True):
    __tablename__ = "creators"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    email: str = Field(unique=True, index=True)
    name: str
    display_name: str = ""
    bio: str = ""
    style_preferences: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, server_default="{}")
    )
    is_active: bool = Field(default=True)
