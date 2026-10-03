"""Task test defaults for mandatory Run actor scope."""

from __future__ import annotations

import pytest

from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


@pytest.fixture(autouse=True)
def _default_task_submit_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compatibility callers admit tasks with a principal unless they set one."""
    import maistro.tasks.queue as queue_mod

    original = queue_mod.TaskQueue.submit

    async def submit(self, task, **kwargs):  # type: ignore[no-untyped-def]
        if getattr(task, "user_id", None) is None and getattr(
            task, "service_principal_id", None
        ) is None:
            task = task.model_copy(update={"user_id": DEFAULT_TEST_ACTOR_PRINCIPAL_ID})
        return await original(self, task, **kwargs)

    monkeypatch.setattr(queue_mod.TaskQueue, "submit", submit)
