"""Bounded host-side capture of child output (#1197).

Every sandbox execution path that captures a child's stdout/stderr must do so
through one of the helpers here. The contract they implement (#1197,
`SandboxConfig.max_output_bytes` in the canonical protocol):

- **Retain at most `limit` bytes per stream.** Beyond the limit the bytes are
  still *read* — and immediately discarded, never buffered — so an unbounded
  emitter (`yes`, a runaway test runner) cannot grow host memory while staying
  inside its sandbox CPU budget.
- **Never wedge on a full pipe.** Because the drain continues after the limit,
  the child's writes keep completing; execution runs to its natural end (or
  the caller's timeout) instead of deadlocking against a full pipe.
- **Report the truth.** Callers get the retained bytes plus a `truncated`
  flag, so partial output can never pass as complete evidence.

Both an asyncio flavor (`communicate_bounded`, for `create_subprocess_exec`
callers) and a threads flavor (`run_bounded`, for sync `Popen` callers) live
here so the executors cannot drift apart. The timeout itself stays with the
caller: each executor owns its timeout semantics (exit codes, kill strategy),
and this module only owns the bounded drain.

Location is load-bearing: this package directory sits on the promotion path
(`scripts/check-promotion-surface.py` walks the import graph from the RSI
roots, and `maistro/tools/sandbox/` is a protected pattern there), so the
helpers and the policy the product executors need live HERE: importing a
`maistro.tools.sandbox._capture`-only module initializes nothing beyond this
package, while importing any `maistro.sandbox` leaf initializes that package's
facade — wiring, selector, backends — which the promotion-surface gate forbids
on the RSI path (it flags every newly reached module, as it did when the
executors first imported the policy through `maistro.sandbox.protocol`). This
module imports nothing but the standard library and owns the policy;
`maistro.sandbox.protocol` re-exports the constants from here as the policy's
public home inside the subsystem. The RSI runtime keeps its own mirror
(`maistro_rsi.sandbox._capture`) pinned by test, because that package must not
depend on maistro-core at all.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from dataclasses import dataclass

#: Read/drain chunk size. Small enough that a chunk never meaningfully
#: overshoots the limit, large enough that draining a discarded stream is not
#: a syscall-per-byte tax on the host.
_CHUNK = 65536

#: Default host-selected bound (#1197) on how much stdout/stderr a sandbox
#: *retains*. Output beyond the limit is still read and discarded — never
#: buffered — so the workload cannot block on a full pipe and grow host memory.
#: Re-exported as the canonical default by `maistro.sandbox.protocol`.
DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024

#: Hard ceiling for retained output. A caller may lower the limit per workload;
#: nothing — workload, config file, or environment — can raise a backend's
#: retained output above this (#1197: "untrusted workload/config cannot raise
#: them beyond the allowed ceiling").
MAX_OUTPUT_BYTES_CEILING = 8 * 1024 * 1024

#: Marker appended by the `(int, str)` callers (docker/microVM executors)
#: whose return shape has no room for structured truncation flags. Structured
#: `ExecResult` callers use the boolean fields instead.
_TRUNCATION_NOTICE = "\n[maistro: output truncated at {} bytes; the rest was discarded]"


def clamped_output_limit(value: int) -> int:
    """Host policy for retained output: positive, and never above the ceiling.

    Pure function so the effective limit is assertable without spawning a
    sandbox, the same reason ``resource_limits`` and ``build_argv`` are pure.
    """
    if value <= 0:
        raise ValueError(f"max_output_bytes must be positive, got {value}")
    return min(value, MAX_OUTPUT_BYTES_CEILING)


@dataclass(frozen=True)
class BoundedCapture:
    """What a bounded drain retained from one output stream."""

    #: The retained bytes (never more than the limit).
    data: bytes
    #: True when bytes beyond `data` were drained and discarded.
    truncated: bool


def truncation_notice(limit: int) -> str:
    """The textual notice `(int, str)`-shaped executors append when truncated."""
    return _TRUNCATION_NOTICE.format(clamped_output_limit(limit))


async def read_stream_bounded(stream: asyncio.StreamReader, limit: int) -> BoundedCapture:
    """Drain an asyncio stream to EOF, retaining at most `limit` bytes.

    Reads run to EOF even after the limit is hit — discarding chunks — so the
    writing child is never blocked on a full pipe and this coroutine always
    terminates when the child does.
    """
    chunks: list[bytes] = []
    retained = 0
    truncated = False
    while chunk := await stream.read(_CHUNK):
        if retained < limit:
            take = chunk[: limit - retained]
            chunks.append(take)
            retained += len(take)
            if len(take) < len(chunk):
                truncated = True
        else:
            truncated = True
    return BoundedCapture(b"".join(chunks), truncated)


async def communicate_bounded(
    process: asyncio.subprocess.Process, limit: int
) -> tuple[BoundedCapture, BoundedCapture]:
    """Drain a subprocess's stdout/stderr concurrently, bounded per stream.

    Concurrent because a child that fills both pipes must be able to progress
    on either while we drain the other — a sequential drain can deadlock
    exactly in the simultaneous-output case #1197's tests exercise. A `None`
    stream (merged `stderr=STDOUT`, or no pipe) yields an empty capture.
    """
    streams = (process.stdout, process.stderr)
    results = await asyncio.gather(
        *(
            read_stream_bounded(stream, limit) if stream is not None else _empty()
            for stream in streams
        )
    )
    stdout, stderr = results
    return stdout, stderr


async def _empty() -> BoundedCapture:
    return BoundedCapture(b"", False)


def capture_fd_sync(fd: int, limit: int) -> BoundedCapture:
    """Drain a pipe fd to EOF on the calling thread, retaining `limit` bytes."""
    chunks: list[bytes] = []
    retained = 0
    truncated = False
    while chunk := os.read(fd, _CHUNK):
        if retained < limit:
            take = chunk[: limit - retained]
            chunks.append(take)
            retained += len(take)
            if len(take) < len(chunk):
                truncated = True
        else:
            truncated = True
    return BoundedCapture(b"".join(chunks), truncated)


@dataclass(frozen=True)
class BoundedRun:
    """Outcome of `run_bounded` — the sync bounded analogue of `communicate`."""

    exit_code: int
    stdout: BoundedCapture
    stderr: BoundedCapture
    timed_out: bool = False


def run_bounded(
    argv: list[str],
    *,
    limit: int,
    timeout: float | None = None,
) -> BoundedRun:
    """Run `argv` capturing stdout/stderr with a per-stream retention bound.

    The sync counterpart of `communicate_bounded` for callers that run
    `subprocess.Popen` on a worker thread (the fake backend, the bootstrap
    container sandbox). Each pipe is drained by its own daemon thread — the
    same simultaneity argument as the async flavor — and the calling thread
    waits on the process. On timeout the child is killed and the (quickly
    reaching-EOF) drains are joined, so neither the child nor a full pipe can
    wedge the caller. Workloads receive input through argv or their own
    redirection; stdin is never piped here.
    """
    limit = clamped_output_limit(limit)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None and proc.stderr is not None
    results: list[BoundedCapture] = [BoundedCapture(b"", False), BoundedCapture(b"", False)]

    def drain(index: int, fd: int) -> None:
        results[index] = capture_fd_sync(fd, limit)

    threads = [
        threading.Thread(target=drain, args=(i, fd), daemon=True)
        for i, fd in enumerate((proc.stdout.fileno(), proc.stderr.fileno()))
    ]
    for t in threads:
        t.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        exit_code = proc.wait()

    for t in threads:
        # The child is dead (or killed), so both pipes reach EOF and the
        # drains finish; the join only bounds thread scheduling, not the
        # child. A daemon thread that somehow lingered must not wedge the
        # caller, hence daemon=True above.
        t.join(timeout=5)
    proc.stdout.close()
    proc.stderr.close()
    return BoundedRun(
        exit_code=exit_code,
        stdout=results[0],
        stderr=results[1],
        timed_out=timed_out,
    )


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "MAX_OUTPUT_BYTES_CEILING",
    "BoundedCapture",
    "BoundedRun",
    "capture_fd_sync",
    "clamped_output_limit",
    "communicate_bounded",
    "read_stream_bounded",
    "run_bounded",
    "truncation_notice",
]
