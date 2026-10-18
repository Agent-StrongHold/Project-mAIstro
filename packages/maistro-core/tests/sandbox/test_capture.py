"""The #1197 contract: sandbox output capture is bounded at the host.

A workload that emits unbounded output must not be able to grow host memory
while staying inside its sandbox CPU budget — the sandbox's own address-space
or file-size limits say nothing about bytes the *host* reads out of a pipe.
Every helper here generates output far beyond the configured limit and proves
retention, truncation truthfulness, and that the executor neither wedges nor
loses the child's real exit status.

The asyncio and threads flavors (`communicate_bounded`, `run_bounded`) are
tested against real child processes on both streams simultaneously: a
sequential drain would deadlock exactly in that case, so the simultaneity is
the property under test, not an incidental shape.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from maistro.config.settings import SandboxSettings
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.protocol import (
    DEFAULT_MAX_OUTPUT_BYTES,
    MAX_OUTPUT_BYTES_CEILING,
    SandboxConfig,
    clamped_output_limit,
)
from maistro.tools.sandbox._capture import (
    BoundedCapture,
    capture_fd_sync,
    communicate_bounded,
    read_stream_bounded,
    run_bounded,
    truncation_notice,
)

#: Python one-liners are used as the emitter so the test does not depend on
#: coreutils (`yes`) being installed.
_EMIT_BOTH = (
    "import sys\n"
    f"sys.stdout.write('a' * {MAX_OUTPUT_BYTES_CEILING * 2})\n"
    "sys.stdout.flush()\n"
    f"sys.stderr.write('b' * {MAX_OUTPUT_BYTES_CEILING * 2})\n"
    "sys.stderr.flush()\n"
)


def test_ceiling_clamps_host_raised_limits() -> None:
    assert clamped_output_limit(10**9) == MAX_OUTPUT_BYTES_CEILING
    assert clamped_output_limit(MAX_OUTPUT_BYTES_CEILING) == MAX_OUTPUT_BYTES_CEILING
    assert clamped_output_limit(1) == 1


def test_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        clamped_output_limit(0)
    with pytest.raises(ValueError):
        clamped_output_limit(-5)


def test_settings_default_matches_the_protocol_constant() -> None:
    """Drift pin: `maistro.config` sits below `maistro.sandbox`, so it carries
    a numeric literal instead of importing `DEFAULT_MAX_OUTPUT_BYTES`. If the
    protocol default ever moves, this fails and the literal must follow."""
    assert SandboxSettings().max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES


def test_truncation_notice_states_the_limit() -> None:
    assert "1024" in truncation_notice(1024)


def test_truncation_summary_is_none_while_evidence_is_complete() -> None:
    from maistro.sandbox.protocol import ExecResult

    result = ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=1)
    assert result.truncation_summary() is None


def test_truncation_summary_names_what_was_cut_and_what_was_kept() -> None:
    """The audit contract (protocol: a truncated result is incomplete
    evidence) is only true if something reads the flags; the summary is that
    reader, and it must carry both the fact and the retained byte counts."""
    from maistro.sandbox.protocol import ExecResult

    stdout_only = ExecResult(
        exit_code=0,
        stdout="x",
        stderr="",
        duration_ms=1,
        stdout_bytes=1000,
        stdout_truncated=True,
    )
    assert stdout_only.truncation_summary() == ("stdout truncated (1000 bytes retained)")
    both = ExecResult(
        exit_code=0,
        stdout="x",
        stderr="y",
        duration_ms=1,
        stdout_bytes=1000,
        stderr_bytes=256,
        stdout_truncated=True,
        stderr_truncated=True,
    )
    summary = both.truncation_summary()
    assert summary is not None
    assert "stdout truncated (1000 bytes retained)" in summary
    assert "stderr truncated (256 bytes retained)" in summary


async def test_read_stream_bounded_retains_limit_and_reports_truncation() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * 5000)
    reader.feed_eof()
    captured = await read_stream_bounded(reader, 1000)
    assert captured == BoundedCapture(b"x" * 1000, True)


async def test_read_stream_bounded_under_limit_is_untruncated() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"short")
    reader.feed_eof()
    assert await read_stream_bounded(reader, 1000) == BoundedCapture(b"short", False)


async def test_communicate_bounded_drains_both_pipes_simultaneously() -> None:
    """A child filling both pipes must be drainable concurrently: sequential
    drains deadlock on the first full pipe. This child writes ~16 MiB to each
    stream before exiting; the bounded drain must reap it with both streams
    truncated at the limit and the real exit code intact."""
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        _EMIT_BOTH,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    start = time.monotonic()
    stdout, stderr = await communicate_bounded(proc, limit=4096)
    elapsed = time.monotonic() - start
    await proc.wait()

    assert proc.returncode == 0
    assert stdout.data == b"a" * 4096 and stdout.truncated
    assert stderr.data == b"b" * 4096 and stderr.truncated
    # The child wrote 16 MiB per stream; even at a slow drain this is seconds,
    # not the hang a sequential deadlocked drain would produce.
    assert elapsed < 30


async def test_communicate_bounded_handles_merged_stderr() -> None:
    """`stderr=STDOUT` (docker exec merge) leaves `proc.stderr` None."""
    proc = await asyncio.create_subprocess_exec(
        "python3",
        "-c",
        "import sys; sys.stdout.write('c' * 9000)",
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
    )
    stdout, stderr = await communicate_bounded(proc, limit=100)
    await proc.wait()
    assert stdout.data == b"c" * 100 and stdout.truncated
    assert stderr == BoundedCapture(b"", False)


def test_capture_fd_sync_bounds_a_raw_fd() -> None:
    r, w = os.pipe()
    try:
        os.write(w, b"d" * 5000)
        os.close(w)
        captured = capture_fd_sync(r, 500)
        assert captured == BoundedCapture(b"d" * 500, True)
    finally:
        os.close(r)


def test_run_bounded_bounds_both_streams_and_keeps_exit_code() -> None:
    run = run_bounded(["python3", "-c", _EMIT_BOTH], limit=2048)
    assert run.exit_code == 0 and not run.timed_out
    assert run.stdout.data == b"a" * 2048 and run.stdout.truncated
    assert run.stderr.data == b"b" * 2048 and run.stderr.truncated


def test_run_bounded_timeout_kills_without_wedging() -> None:
    # A child that deterministically outlives the timeout (not a sleeper that
    # races it): the kill path must fire and the caller must not wait it out.
    start = time.monotonic()
    run = run_bounded(["python3", "-c", "import time; time.sleep(30)"], limit=1024, timeout=1)
    elapsed = time.monotonic() - start
    assert run.timed_out
    assert elapsed < 15


# --- backends enforce the same contract -------------------------------------


async def test_fake_backend_truncates_beyond_config_limit() -> None:
    backend = FakeSandboxBackend()
    instance = await backend.spawn(config=SandboxConfig(max_output_bytes=1000))
    result = await backend.exec(instance, ["python3", "-c", "print('x' * 50000)"])
    assert result.exit_code == 0
    assert result.stdout == "x" * 1000
    assert result.stdout_bytes == 1000
    assert result.stdout_truncated is True


async def test_fake_backend_under_limit_reports_full_and_untruncated() -> None:
    backend = FakeSandboxBackend()
    instance = await backend.spawn(config=SandboxConfig(max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES))
    result = await backend.exec(instance, ["python3", "-c", "print('tiny')"])
    assert result.stdout.strip() == "tiny"
    assert result.stdout_truncated is False
    assert result.stdout_bytes == len("tiny\n")


async def test_fake_backend_stderr_bound_is_independent() -> None:
    backend = FakeSandboxBackend()
    instance = await backend.spawn(config=SandboxConfig(max_output_bytes=256))
    result = await backend.exec(
        instance, ["python3", "-c", "import sys; sys.stderr.write('e' * 900)"]
    )
    assert result.stderr == "e" * 256
    assert result.stderr_truncated and result.stderr_bytes == 256


async def test_fake_backend_declares_truncation_in_the_audit_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The backend is the one place that always sees a truncation, so the
    audit warning must fire there — partial evidence may not pass silently
    (#1197's 'audit must treat truncated as incomplete evidence')."""
    import logging

    backend = FakeSandboxBackend()
    instance = await backend.spawn(config=SandboxConfig(max_output_bytes=128))
    with caplog.at_level(logging.WARNING, logger="maistro.sandbox.backends.fake"):
        result = await backend.exec(instance, ["python3", "-c", "print('x' * 900)"])
    assert result.stdout_truncated
    warnings = [r for r in caplog.records if r.message.startswith("sandbox_exec_output_truncated")]
    assert len(warnings) == 1
    assert "stdout truncated (128 bytes retained)" in warnings[0].getMessage()
    assert str(instance.id) in warnings[0].getMessage()


def _bwrap_capable() -> bool:
    """Capability, not binary presence (the test_real_backend rule): a host can
    ship bwrap yet refuse to build a user namespace."""
    from maistro.sandbox.detect import detect_host_capabilities

    return detect_host_capabilities().supports("bubblewrap")


@pytest.mark.skipif(not _bwrap_capable(), reason="this host cannot build a bubblewrap sandbox")
async def test_bubblewrap_backend_truncates_beyond_config_limit(tmp_path) -> None:
    """The real backend's retained output obeys the config bound on this host;
    where bwrap is unavailable the argv-level assertions elsewhere carry the
    contract, per this suite's established capability-not-binary rule."""
    from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend

    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig(max_output_bytes=1000))
    try:
        result = await backend.exec(instance, ["python3", "-c", "print('x' * 50000)"])
    finally:
        await backend.destroy(instance)
    assert result.exit_code == 0
    assert result.stdout == "x" * 1000
    assert result.stdout_truncated and result.stdout_bytes == 1000
