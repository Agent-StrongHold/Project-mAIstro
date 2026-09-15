from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class GraphEvent(BaseModel):
    type: str
    run_id: str
    node_id: str | None = None
    role: str | None = None
    phase: str | None = None
    timestamp: float = Field(default_factory=time.monotonic)
    detail: dict[str, Any] = Field(default_factory=dict)
