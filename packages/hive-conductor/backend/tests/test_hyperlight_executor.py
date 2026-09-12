from __future__ import annotations

import asyncio
import sys

import pytest
from services.hyperlight_executor import SandboxExecutor


@pytest.mark.asyncio
async def test_cancelling_a_subprocess_adapter_kills_the_child() -> None:
    executor = SandboxExecutor()
    running = asyncio.create_task(
        executor._run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            {},
            30,
        )
    )
    await asyncio.sleep(0.05)
    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running
