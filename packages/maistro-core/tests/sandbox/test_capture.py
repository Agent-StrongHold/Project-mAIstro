"""Bounded-capture edge contracts for `maistro.sandbox.capture` (#1197).

The sandbox backends drive `capture_process` through real workloads, which
exercises the overflow, timeout and cancellation arms. The arcs pinned here
are the ones a passing workload cannot reach on its own: the defensive
guards that keep a broken child (or a broken caller) from wedging the
executor, the exact-boundary retention semantics at the limit, and the
host-policy refusal of negative capture bounds.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from maistro.sandbox.capture import (
    _close_transport,
    _collect_streams,
    _read_stream,
    _StreamCapture,
    _terminate,
    capture_process,
)
from maistro.sandbox.protocol import SandboxConfig, output_capture_limits

_LIMIT = 16


class _StubProcess:
    """Just the asyncio-process surface the capture helpers touch."""

    def __init__(
        self,
        *,
        pid: int | None = None,
        transport: object | None = None,
        wait_hangs: bool = False,
    ) -> None:
        self.pid = pid
        self.stdout = None
        self.stderr = None
        self.kill_calls = 0
        if transport is not None:
            self._transport = transport
        self._hang = asyncio.Event() if wait_hangs else None

    def kill(self) -> None:
        self.kill_calls += 1

    async def wait(self) -> int:
        if self._hang is not None:
            await self._hang.wait()
        return 0


class _ClosingTransport:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _unused_group_pid() -> int:
    """A pid whose process group provably does not exist."""
    for candidate in range(2**22, 2**23):
        try:
            os.killpg(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            continue
    raise AssertionError("no free process group found")  # pragma: no cover


async def _feed(reader: asyncio.StreamReader, data: bytes) -> None:
    reader.feed_data(data)
    await asyncio.sleep(0)


async def _finished_capture() -> _StreamCapture:
    return _StreamCapture(b"out", False)


@pytest.mark.asyncio
async def test_read_stream_retains_the_exact_prefix_when_one_read_overshoots() -> None:
    reader = asyncio.StreamReader()
    overflow = asyncio.Event()
    task = asyncio.create_task(_read_stream(reader, _LIMIT, overflow))
    await _feed(reader, b"x" * (_LIMIT + 5))

    capture = await asyncio.wait_for(task, timeout=5)

    assert capture.data == b"x" * _LIMIT
    assert capture.truncated is True
    assert overflow.is_set()


@pytest.mark.asyncio
async def test_read_stream_detects_overflow_after_an_exact_fill() -> None:
    """A child that fills the bound exactly, then keeps writing, is truncated
    by the *next* read of one byte -- still never retaining more than the
    policy allows."""
    reader = asyncio.StreamReader()
    overflow = asyncio.Event()
    task = asyncio.create_task(_read_stream(reader, _LIMIT, overflow))
    await _feed(reader, b"x" * _LIMIT)
    assert not overflow.is_set()  # an exact fill is retention, not overflow
    await _feed(reader, b"!")

    capture = await asyncio.wait_for(task, timeout=5)

    assert capture.data == b"x" * _LIMIT
    assert capture.truncated is True
    assert overflow.is_set()


@pytest.mark.asyncio
async def test_read_stream_returns_everything_when_the_child_stays_under_the_bound() -> None:
    reader = asyncio.StreamReader()
    overflow = asyncio.Event()
    task = asyncio.create_task(_read_stream(reader, _LIMIT, overflow))
    await _feed(reader, b"short")
    reader.feed_eof()

    capture = await asyncio.wait_for(task, timeout=5)

    assert capture.data == b"short"
    assert capture.truncated is False
    assert not overflow.is_set()


@pytest.mark.asyncio
async def test_capture_process_requires_both_output_pipes() -> None:
    process = _StubProcess()  # stdout/stderr are None
    with pytest.raises(ValueError, match="requires stdout and stderr pipes"):
        await capture_process(process, timeout_s=1)


@pytest.mark.asyncio
async def test_close_transport_closes_when_present_and_tolerates_absence() -> None:
    with_transport = _StubProcess(transport=_ClosingTransport())
    _close_transport(with_transport)
    assert with_transport._transport.closed is True

    without_transport = _StubProcess()
    _close_transport(without_transport)


@pytest.mark.asyncio
async def test_terminate_skips_the_group_kill_for_a_pidless_process() -> None:
    process = _StubProcess(pid=None)
    await asyncio.wait_for(_terminate(process), timeout=5)
    assert process.kill_calls == 1


@pytest.mark.asyncio
async def test_terminate_bounds_the_reap_of_an_unkillable_process() -> None:
    """A child whose wait() never settles cannot hold termination open: the
    reap gets one bounded slice, then gives up."""
    process = _StubProcess(pid=_unused_group_pid(), wait_hangs=True)
    started = time.monotonic()
    await asyncio.wait_for(_terminate(process), timeout=10)
    elapsed = time.monotonic() - started
    assert process.kill_calls == 1
    assert elapsed >= 1.0  # the bounded reap ran its full slice
    assert elapsed < 10.0  # ...and returned instead of wedging


@pytest.mark.asyncio
async def test_collect_streams_bounds_a_pipe_held_by_a_detached_descendant() -> None:
    """After the group kill a descendant that escaped the group can keep a
    pipe write-end open. Collection is bounded: the finished stream is kept,
    the unfinished one degrades to an empty capture, and the executor
    regains control."""
    finished = asyncio.create_task(_finished_capture())
    held = asyncio.create_task(asyncio.Event().wait())

    started = time.monotonic()
    stdout, stderr = await asyncio.wait_for(_collect_streams(finished, held), timeout=10)
    elapsed = time.monotonic() - started

    assert stdout.data == b"out"
    assert stdout.truncated is False
    assert stderr.data == b""
    assert stderr.truncated is False
    assert held.cancelled()
    assert 1.0 <= elapsed < 10.0


def test_capture_limits_refuse_negative_requests() -> None:
    """Negative bounds are a caller bug, not a smaller policy: refuse them
    instead of silently producing a zero-or-negative retained allowance."""
    with pytest.raises(ValueError, match="cannot be negative"):
        output_capture_limits(-1, 0)
    with pytest.raises(ValueError, match="cannot be negative"):
        output_capture_limits(0, -1)
    with pytest.raises(ValueError, match="cannot be negative"):
        SandboxConfig(max_stdout_bytes=-1, max_stderr_bytes=-1)
