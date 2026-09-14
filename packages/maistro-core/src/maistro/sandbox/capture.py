"""Bounded subprocess output capture for sandbox backends.

The pipes belong to the host, so sandbox resource limits cannot bound their
contents. This module drains both pipes concurrently, retains only the policy
limit, and terminates the process as soon as either stream overflows.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from dataclasses import dataclass

from maistro.sandbox.protocol import DEFAULT_OUTPUT_CAPTURE_BYTES, output_capture_limits

#: Keep individual reads small so the asyncio transport cannot hand us a large
#: transient allocation even when a child writes in large chunks.
_READ_CHUNK_BYTES = 64 * 1024
#: A killed child should not wedge the executor while a descendant holds a pipe
#: open. The process group is killed first; this is only a final cleanup bound.
_TERMINATION_WAIT_S = 1.0


@dataclass(frozen=True)
class CapturedOutput:
    """Bounded bytes and termination state returned by :func:`capture_process`."""

    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    output_limit_exceeded: bool

    @property
    def truncated(self) -> bool:
        """Whether either stream was truncated."""
        return self.stdout_truncated or self.stderr_truncated


@dataclass(frozen=True)
class _StreamCapture:
    data: bytes
    truncated: bool


async def _read_stream(
    reader: asyncio.StreamReader,
    limit: int,
    overflow: asyncio.Event,
) -> _StreamCapture:
    retained = bytearray()
    truncated = False
    while True:
        remaining = limit - len(retained)
        # Reading one byte beyond the remaining allowance detects overflow
        # without ever retaining more than the configured bound.
        chunk = await reader.read(min(_READ_CHUNK_BYTES, remaining + 1))
        if not chunk:
            break
        if len(chunk) > remaining:
            if remaining > 0:
                retained.extend(chunk[:remaining])
            truncated = True
            overflow.set()
            break
        retained.extend(chunk)
    return _StreamCapture(bytes(retained), truncated)


def _close_transport(process: asyncio.subprocess.Process) -> None:
    """Close asyncio's pipe transport after a bounded capture completes."""
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Kill the process and its descendants without waiting indefinitely."""
    pid = process.pid
    if pid is not None:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    with suppress(ProcessLookupError):
        process.kill()
    with suppress(TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=_TERMINATION_WAIT_S)
    # The capture tasks are also bounded below; a broken child must not wedge
    # cancellation or timeout handling in the executor.


async def _wait_for_streams(
    stdout_task: asyncio.Task[_StreamCapture],
    stderr_task: asyncio.Task[_StreamCapture],
) -> tuple[_StreamCapture, _StreamCapture]:
    return await asyncio.gather(stdout_task, stderr_task)


async def _collect_streams(
    stdout_task: asyncio.Task[_StreamCapture],
    stderr_task: asyncio.Task[_StreamCapture],
) -> tuple[_StreamCapture, _StreamCapture]:
    tasks = (stdout_task, stderr_task)
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=_TERMINATION_WAIT_S)
    except TimeoutError:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    captures: list[_StreamCapture] = []
    for task in tasks:
        if task.done() and not task.cancelled() and task.exception() is None:
            captures.append(task.result())
        else:
            # A child that keeps a pipe open after group termination cannot
            # make us retain more data; preserve the completed stream and mark
            # the unfinished one as unavailable.
            captures.append(_StreamCapture(b"", False))
    return captures[0], captures[1]


async def capture_process(
    process: asyncio.subprocess.Process,
    *,
    timeout_s: float,
    max_stdout_bytes: int = DEFAULT_OUTPUT_CAPTURE_BYTES,
    max_stderr_bytes: int = DEFAULT_OUTPUT_CAPTURE_BYTES,
) -> CapturedOutput:
    """Capture a process's two output streams with fixed host memory bounds.

    Output beyond either effective limit terminates the whole process group and
    is not retained. A wall-clock timeout has the same termination guarantee.
    Both streams are drained concurrently so a child cannot deadlock by filling
    the other pipe while the first one is being read.
    """
    if process.stdout is None or process.stderr is None:
        raise ValueError("bounded capture requires stdout and stderr pipes")

    stdout_limit, stderr_limit = output_capture_limits(max_stdout_bytes, max_stderr_bytes)
    overflow = asyncio.Event()
    stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_limit, overflow))
    stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_limit, overflow))
    streams_done = asyncio.create_task(_wait_for_streams(stdout_task, stderr_task))
    overflow_task = asyncio.create_task(overflow.wait())
    started = asyncio.get_running_loop().time()
    timed_out = False
    output_limit_exceeded = False

    try:
        done, _pending = await asyncio.wait(
            (streams_done, overflow_task),
            timeout=max(timeout_s, 0),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if overflow_task in done:
            output_limit_exceeded = True
            await _terminate(process)
        elif streams_done not in done:
            timed_out = True
            await _terminate(process)

        stdout_capture, stderr_capture = await _collect_streams(stdout_task, stderr_task)

        if not timed_out and not output_limit_exceeded:
            remaining = max(timeout_s - (asyncio.get_running_loop().time() - started), 0)
            try:
                await asyncio.wait_for(process.wait(), timeout=remaining)
            except TimeoutError:
                timed_out = True
                await _terminate(process)
        else:
            # `_terminate` already waited once; do not turn an unusual
            # unkillable descendant into an unbounded executor wait.
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=_TERMINATION_WAIT_S)
    except asyncio.CancelledError:
        await _terminate(process)
        for task in (stdout_task, stderr_task, streams_done, overflow_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            stdout_task, stderr_task, streams_done, overflow_task, return_exceptions=True
        )
        raise
    finally:
        if not overflow_task.done():
            overflow_task.cancel()
        await asyncio.gather(overflow_task, return_exceptions=True)
        _close_transport(process)

    # A stream may finish in the same event-loop turn as the overflow event;
    # derive this status from the retained results rather than scheduling order.
    output_limit_exceeded = (
        output_limit_exceeded or stdout_capture.truncated or stderr_capture.truncated
    )
    return CapturedOutput(
        stdout=stdout_capture.data,
        stderr=stderr_capture.data,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        timed_out=timed_out,
        output_limit_exceeded=output_limit_exceeded,
    )


__all__ = ["CapturedOutput", "capture_process"]
