from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class ProductFormat(SQLModel, table=True):
    __tablename__ = "product_formats"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    name: str
    pod_package_id: str
    price_usd: float
    page_count: int
    trim_size_in: list[float] = Field(sa_column=Column(JSONB, server_default="[]"))
    bleed_size_in: list[float] = Field(sa_column=Column(JSONB, server_default="[]"))
    binding: str
    paper: str
    color_mode: str
    description: str = ""
    weight_oz: float = Field(default=0)
    is_active: bool = Field(default=True)
