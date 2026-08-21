import enum
import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from .base import BaseModel, _utcnow


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    CHARACTERIZING = "CHARACTERIZING"
    STORYWRITING = "STORYWRITING"
    STORYBOARDING = "STORYBOARDING"
    ILLUSTRATING = "ILLUSTRATING"
    COMPOSING = "COMPOSING"
    PREFLIGHTING = "PREFLIGHTING"
    SUBMITTING = "SUBMITTING"
    PRINTING = "PRINTING"
    SHIPPED = "SHIPPED"
    FULFILLED = "FULFILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Order(BaseModel, table=True):
    __tablename__ = "orders"
    __table_args__: ClassVar[dict[str, Any]] = {"extend_existing": True}

    customer_id: uuid.UUID = Field(foreign_key="customers.id", index=True)
    character_id: uuid.UUID = Field(foreign_key="characters.id")
    template_id: uuid.UUID = Field(foreign_key="story_templates.id", index=True)
    product_id: str = Field(foreign_key="product_formats.id")
    status: str = Field(default=OrderStatus.PENDING.value, index=True)

    variables: dict = Field(default_factory=dict, sa_column=Column(JSONB, server_default="{}"))

    source: str = ""
    source_id: str = ""

    interior_pdf_url: str = ""
    cover_pdf_url: str = ""
    lulu_job_id: str = ""
    tracking_number: str = ""
    tracking_url: str = ""
    tracking_carrier: str = ""

    price_paid: float = Field(default=0)
    print_cost: float = Field(default=0)

    error_message: str = ""

    updated_at: datetime = Field(
        default_factory=_utcnow, sa_column_kwargs={"server_default": "NOW()"}
    )
