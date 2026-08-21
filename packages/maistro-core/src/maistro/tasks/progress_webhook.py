"""Optional HTTP webhook mirroring task progress (conductor-router shape).

See ``docs/specs/SPEC-175-task-progress-webhook.md``. Failures never
propagate to callers.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from maistro.tasks.models import TaskResponse

logger = structlog.get_logger()


class ConductorProgressPayload(BaseModel):
    """JSON body compatible with legacy ``/v1/conductor/progress`` consumers."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    filename: str = ""
    status: str
    current_step: str = ""
    steps_total: int = 0
    steps_completed: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


def payload_from_task(task: TaskResponse) -> ConductorProgressPayload:
    err = task.result.error if task.result else None
    return ConductorProgressPayload(
        task_id=task.task_id,
        status=task.status.value,
        current_step=task.progress.current,
        steps_total=task.progress.subtasks,
        steps_completed=task.progress.completed,
        details={},
        error=err,
    )


class ProgressWebhookSink(Protocol):
    async def notify(self, payload: ConductorProgressPayload) -> None: ...

    async def aclose(self) -> None: ...


class ProgressWebhookNotifier:
    """POST ``ConductorProgressPayload`` JSON to a fixed URL (full path)."""

    def __init__(
        self,
        *,
        post_url: str,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._post_url = post_url.strip()
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=5.0)

    async def notify(self, payload: ConductorProgressPayload) -> None:
        if not self._post_url:
            return
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            await self._client.post(self._post_url, json=payload.model_dump(), headers=headers)
        except Exception:
            await logger.adebug(
                "task_progress_webhook_failed",
                url=self._post_url,
                task_id=payload.task_id,
                exc_info=True,
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
