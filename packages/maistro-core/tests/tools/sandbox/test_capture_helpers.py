"""Direct contracts for the tools-layer bounded drain (`maistro.tools.sandbox._capture`).

The executors (docker, microVM, the bootstrap builder) exercise the happy
paths of these helpers incidentally, and the RSI mirror pins the policy
constants — but a drain helper whose *overflow* arm only runs inside another
package's suite is unmeasured exactly where it is defined (#1197 diff gate):
the core producer runs this suite under `--source=maistro`, so every arm of
the drain — verbatim retention, the exact-boundary take, drain-beyond-limit,
the merged-stream `_empty` arm, the sync fd drain, and `run_bounded`'s
timeout-kill and lingering-descendant joins — is evidenced here, per file,
by the package that owns the code.

Structure over wall clock: a flood child writes a multiple of the limit and
the assertions are about retained prefixes, truncation flags and the child's
real exit status — never about how long the drain took.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading

import pytest

from maistro.tools.sandbox._capture import (
    MAX_OUTPUT_BYTES_CEILING,
    BoundedCapture,
    capture_fd_sync,
    clamped_output_limit,
    communicate_bounded,
    read_stream_bounded,
    run_bounded,
    truncation_notice,
)

_FLOOD = "import sys\nsys.stdout.write('o' * {n})\nsys.stderr.write('e' * {n})\nsys.exit({code})\n"


def _python_flood(n: int, *, code: int = 0) -> list[str]:
    return [sys.executable, "-c", _FLOOD.format(n=n, code=code)]


# -- clamped_output_limit: the policy is assertable without a sandbox --------


def test_clamped_output_limit_passes_small_values_through() -> None:
    assert clamped_output_limit(1) == 1
    assert clamped_output_limit(4096) == 4096


def test_clamped_output_limit_clamps_to_the_host_ceiling() -> None:
    assert clamped_output_limit(MAX_OUTPUT_BYTES_CEILING) == MAX_OUTPUT_BYTES_CEILING
    assert clamped_output_limit(MAX_OUTPUT_BYTES_CEILING + 1) == MAX_OUTPUT_BYTES_CEILING
    assert clamped_output_limit(10**9) == MAX_OUTPUT_BYTES_CEILING


@pytest.mark.parametrize("value", [0, -1, -1000])
def test_clamped_output_limit_rejects_non_positive_values(value: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        clamped_output_limit(value)


def test_truncation_notice_names_the_effective_limit() -> None:
    notice = truncation_notice(MAX_OUTPUT_BYTES_CEILING + 5000)
    assert notice == (
        f"\n[maistro: output truncated at {MAX_OUTPUT_BYTES_CEILING} bytes; the rest was discarded]"
    )


# -- read_stream_bounded: retention is a prefix, the drain runs to EOF --------


async def test_read_stream_bounded_under_the_limit_is_verbatim() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('hello')",
        stdout=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    captured = await read_stream_bounded(proc.stdout, 4096)
    await proc.wait()
    assert captured == BoundedCapture(b"hello", False)


async def test_read_stream_bounded_retains_exact_limit_without_flag() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('a' * 64)",
        stdout=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    captured = await read_stream_bounded(proc.stdout, 64)
    await proc.wait()
    # The boundary case: the last take fills the allowance exactly, so the
    # capture is complete, not truncated.
    assert captured == BoundedCapture(b"a" * 64, False)


async def test_read_stream_bounded_drains_past_the_limit_without_wedging() -> None:
    limit = 4096
    proc = await asyncio.create_subprocess_exec(
        *_python_flood(limit * 8),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    captured = await read_stream_bounded(proc.stdout, limit)
    # EOF arrived (no wedge): the child wrote 8x the limit and its exit was
    # reaped cleanly.
    await proc.wait()
    assert proc.returncode == 0
    assert captured.data == b"o" * limit
    assert captured.truncated is True


# -- communicate_bounded: both streams at once, and the merged-stream arm -----


async def test_communicate_bounded_reaps_and_bounds_both_streams() -> None:
    limit = 2048
    proc = await asyncio.create_subprocess_exec(
        *_python_flood(limit * 8, code=3),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await communicate_bounded(proc, limit)
    # The child's real exit status survives the drain — a flood cannot turn
    # `returncode or 0` into a false success.
    assert proc.returncode == 3
    assert (stdout.data, stderr.data) == (b"o" * limit, b"e" * limit)
    assert stdout.truncated and stderr.truncated


async def test_communicate_bounded_merged_streams_yield_empty_capture() -> None:
    # stderr=STDOUT leaves `process.stderr` None: the merged arm must produce
    # an empty capture for it, not an attribute error, and the merged bytes
    # must arrive on the stdout side.
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; print('merged'); print('err', file=sys.stderr)",
        stdout=asyncio.subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.stdout is not None and proc.stderr is None
    stdout, stderr = await communicate_bounded(proc, 4096)
    await proc.wait()
    assert stderr == BoundedCapture(b"", False)
    assert b"merged" in stdout.data and b"err" in stdout.data
    assert stdout.truncated is False


# -- capture_fd_sync: the raw-fd flavour -------------------------------------


def test_capture_fd_sync_under_the_limit_is_verbatim() -> None:
    r, w = os.pipe()
    try:
        os.write(w, b"modest bytes")
        os.close(w)
        captured = capture_fd_sync(r, 4096)
        assert captured == BoundedCapture(b"modest bytes", False)
    finally:
        os.close(r)


def test_capture_fd_sync_retains_prefix_and_drains_past_the_limit() -> None:
    limit = 128
    # 200 KB is far beyond the pipe buffer, so the drain sees multiple chunks:
    # the allowance is exhausted on an early chunk and the later chunks land
    # in the already-at-limit arm — the drain must keep reading to EOF either
    # way, which is what lets the writer finish and close.
    payload = b"x" * 200_000
    r, w = os.pipe()

    def write_all() -> None:
        try:
            os.write(w, payload)
        finally:
            os.close(w)

    writer = threading.Thread(target=write_all)
    writer.start()
    try:
        captured = capture_fd_sync(r, limit)
    finally:
        os.close(r)
        writer.join()
    assert captured.data == b"x" * limit
    assert captured.truncated is True


# -- run_bounded: the sync flavour the bootstrap builder and fake use --------


def test_run_bounded_under_the_limit_is_verbatim_and_reaped() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import sys; print('out'); print('bad', file=sys.stderr)"],
        limit=4096,
    )
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout == BoundedCapture(b"out\n", False)
    assert result.stderr == BoundedCapture(b"bad\n", False)


def test_run_bounded_simultaneous_overflow_keeps_the_exit_status() -> None:
    limit = 1024
    result = run_bounded(_python_flood(limit * 8, code=3), limit=limit)
    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stdout.data == b"o" * limit
    assert result.stderr.data == b"e" * limit
    assert result.stdout.truncated and result.stderr.truncated


def test_run_bounded_rejects_non_positive_limit_before_spawning() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        run_bounded(["true"], limit=0)


def test_run_bounded_timeout_kills_the_child_and_reports_the_bound() -> None:
    result = run_bounded(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        limit=4096,
        timeout=2.0,
    )
    assert result.timed_out is True
    # A killed child has a signal exit, not a clean one: the caller must not
    # be able to mistake the kill for success.
    assert result.exit_code != 0
    assert result.stdout.data == b"" and result.stderr.data == b""


def test_run_bounded_returns_partial_when_a_descendant_holds_the_pipes() -> None:
    # The child backgrounds a `sleep` that inherits stdout/stderr, then exits.
    # EOF never arrives while the descendant lives, so `run_bounded` must
    # return what was drained by the join deadline rather than wedge — and
    # the still-live drains keep their fds instead of a racy close.
    script = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])\n"
        "print('flushed')\n"
    )
    result = run_bounded(
        [sys.executable, "-c", script],
        limit=4096,
        timeout=10.0,
        drain_join_timeout=1.0,
    )
    assert result.exit_code == 0
    assert b"flushed" in result.stdout.data
