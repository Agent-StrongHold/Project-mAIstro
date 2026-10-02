from __future__ import annotations

import asyncio
import gc
import sys
import warnings

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


@pytest.mark.asyncio
async def test_a_transport_failure_leaves_no_unawaited_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport failure must consume the drain, not drop it.

    `_run_cancellable` hands `process.communicate()` to `wait_for`. When
    `wait_for` raises before it ever awaits that argument, an unowned
    coroutine is abandoned: `coroutine 'Process.communicate' was never
    awaited`, and a child whose pipes have no reader.

    Note on how this is caught. `-W error::RuntimeWarning` does *not* fail a
    test on this defect, and a `filterwarnings` marker would not either: the
    warning is raised by `warnings._warn_unawaited_coroutine` during garbage
    collection, so an `error` filter turns it into an *unraisable* exception
    that pytest can only re-report as a `PytestUnraisableExceptionWarning` in
    the summary. It is still green. Collecting deliberately and asserting on
    what was recorded is what actually fails, so that is what this does.
    """
    import services.hyperlight_executor as hyperlight

    async def _explode(awaitable: object, timeout: object) -> object:
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(hyperlight.asyncio, "wait_for", _explode)
    executor = SandboxExecutor()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        report = await executor._run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            {},
            30,
        )
        # The abandoned coroutine warns from its deallocation, so nothing is
        # recorded until it is actually collected.
        gc.collect()

    # Scoped to the drain by name: an unrelated coroutine leaked by a
    # neighbouring test under random ordering is not this test's finding.
    dropped = [
        str(w.message)
        for w in recorded
        if "never awaited" in str(w.message) and "communicate" in str(w.message)
    ]

    assert dropped == [], dropped
    assert report["success"] is False


@pytest.mark.asyncio
async def test_a_transport_failure_settles_the_drain_and_reaps_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same guarantee, stated structurally rather than by warning.

    What `wait_for` receives must already be owned, and must be finished by
    the time the failure is reported -- together with the child itself.
    """
    import services.hyperlight_executor as hyperlight

    handed_to_wait_for: list[object] = []
    spawned: list[asyncio.subprocess.Process] = []
    real_exec = hyperlight.asyncio.create_subprocess_exec

    async def _spy_exec(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await real_exec(*args, **kwargs)
        spawned.append(process)
        return process

    async def _explode(awaitable: object, timeout: object) -> object:
        handed_to_wait_for.append(awaitable)
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(hyperlight.asyncio, "create_subprocess_exec", _spy_exec)
    monkeypatch.setattr(hyperlight.asyncio, "wait_for", _explode)
    executor = SandboxExecutor()

    report = await executor._run_cancellable(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        {},
        30,
    )

    assert report["success"] is False
    assert "transport exploded" in report["error"]

    (drain,) = handed_to_wait_for
    assert isinstance(drain, asyncio.Future), f"drain is unowned: {drain!r}"
    assert drain.done(), "drain was left pending after the failure was reported"

    (child,) = spawned
    assert child.returncode is not None, "child was not reaped"
