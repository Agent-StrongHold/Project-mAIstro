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


@pytest.mark.asyncio
async def test_a_subprocess_run_reports_its_output_and_env() -> None:
    executor = SandboxExecutor()

    report = await executor._subprocess(
        "import os, sys; print(os.environ.get('SANDBOX_MARKER', 'unset')); print('ok', file=sys.stderr)",
        {"SANDBOX_MARKER": "present"},
        30,
    )

    assert report["success"] is True
    assert "present" in report["output"]
    assert "ok" in report["error"]


@pytest.mark.asyncio
async def test_a_command_run_reports_its_output_and_env() -> None:
    import os
    import sys as _sys

    marker = f"inherited-{os.getpid()}"
    executor = SandboxExecutor()

    report = await executor._subprocess_via_cmd(
        [
            _sys.executable,
            "-c",
            f"import os; print(os.environ.get('CMD_MARKER', 'unset')); print({marker!r})",
        ],
        {"CMD_MARKER": "present"},
        30,
    )

    assert report["success"] is True
    assert "present" in report["output"]
    assert marker in report["output"]


@pytest.mark.asyncio
async def test_a_command_that_outlives_its_deadline_is_a_timeout_not_a_hang() -> None:
    executor = SandboxExecutor()

    report = await executor._run_cancellable(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        {},
        1,
    )

    assert report == {"output": "", "error": "timeout", "success": False}


@pytest.mark.asyncio
async def test_a_transport_failure_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.hyperlight_executor as hyperlight

    async def _explode(coro: object, timeout: object) -> object:
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(hyperlight.asyncio, "wait_for", _explode)
    executor = SandboxExecutor()

    report = await executor._run_cancellable(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        {},
        30,
    )

    assert report["success"] is False
    assert "transport exploded" in report["error"]
