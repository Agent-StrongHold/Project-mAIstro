"""Retained-output truth at the builders exec seam (#1197 → #76 cutover).

Under the #76 cutover the adapter no longer shells out to a private Docker
path — the fake-`docker`-on-`PATH` stand-in this file once used is gone, and
bounding itself moved into the canonical substrate: a backend retains at most
`SandboxConfig.max_stdout_bytes`/`max_stderr_bytes` per stream, terminates an
over-limit child, and reports the truth as `OUTPUT_LIMIT_EXIT_CODE` plus the
`ExecResult` truncation flags (pinned against the real backends in
`maistro-core/tests/sandbox`). What *this* adapter still decides, and what a
daemon-free host can therefore still get wrong, is how the backend's result
crosses to the caller:

* the config it spawns with carries bounded per-stream retention — the
  builders workload can never be handed an unbounded host-owned pipe;
* the child's real status survives the merge — an over-limit (125) or
  timed-out (124) child is a visible failure, never laundered to success, and
  the adapter appends no notice that pretends retained bytes are complete;
* under the limit, output crosses verbatim (stdout then stderr);
* `read_file` decodes the sandbox's bytes verbatim, and a missing file
  surfaces the backend's `FileNotFoundError` instead of empty content;
* `edit_file` refuses to write anything when its match is ambiguous — the
  surviving adapter-side guard of the #1197 review's destroyed-tail hazard
  (match found in the prefix, wrong tail written back).

The sandbox itself is not stubbed for convenience — it is not the subject.
`_exec`/`read_file` are the seams where the backend's result arrives, and
everything above them is the shape of that result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.sandbox import (
    DEFAULT_OUTPUT_CAPTURE_BYTES,
    MAX_OUTPUT_CAPTURE_BYTES,
    OUTPUT_LIMIT_EXIT_CODE,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
)
from maistro.sandbox.protocol import ExecResult
from maistro_bootstrap.builders.container_sandbox import ContainerBuilderSandbox


class _BackendStub:
    """A vm-tier `SandboxProtocol` stand-in with a canned exec result.

    `read_file`/`write_file` operate on the spawned `workspace_host` exactly
    like the real backends' host-side workspace binds, so reads answer from a
    filesystem (and a missing file really is missing) rather than from a
    mock's return values.
    """

    tier = "vm"

    def __init__(self, exec_result: ExecResult | None = None) -> None:
        self.exec_result = exec_result or ExecResult(0, "", "", 0)
        self.spawned: list[SandboxConfig] = []
        self.writes: list[tuple[str, bytes]] = []

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.spawned.append(config)
        return SandboxInstance(id="stub-1", backend="stub", isolation_tier="vm")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        return self.exec_result

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.writes.append((path, content))

    async def destroy(self, instance: SandboxInstance) -> None:
        pass

    def _resolve(self, path: str) -> Path:
        assert self.spawned, "spawn must run before file operations"
        workdir = Path(self.spawned[0].workspace_host or ".")
        relative = Path(path)
        if relative.is_absolute():
            relative = relative.relative_to("/workspace")
        return workdir / relative


def _sandbox(
    tmp_path: Path, exec_result: ExecResult | None = None
) -> tuple[ContainerBuilderSandbox, _BackendStub]:
    backend = _BackendStub(exec_result)
    selector = SandboxSelector()
    selector.register("vm", backend)
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    return ContainerBuilderSandbox(tmp_path, selector=selector), backend


def test_the_spawned_config_carries_bounded_per_stream_retention(tmp_path: Path) -> None:
    """The #1197 bound survived the cutover, relocated: whatever a caller does,
    the builders sandbox is spawned with explicit, host-capped per-stream
    retention — no path can configure an unbounded host-owned pipe."""
    sandbox, backend = _sandbox(tmp_path)

    with sandbox:
        config = backend.spawned[0]
        assert config.max_stdout_bytes == DEFAULT_OUTPUT_CAPTURE_BYTES
        assert config.max_stderr_bytes == DEFAULT_OUTPUT_CAPTURE_BYTES
        assert 0 < config.max_stdout_bytes <= MAX_OUTPUT_CAPTURE_BYTES
        assert 0 < config.max_stderr_bytes <= MAX_OUTPUT_CAPTURE_BYTES


def test_an_over_limit_child_reports_the_backend_status_and_retained_truth(
    tmp_path: Path,
) -> None:
    """A backend-terminated child crosses as the failure it is: status 125,
    retained bytes verbatim, no adapter-appended notice pretending the prefix
    is complete output, and no laundering to exit 0."""
    retained_out, retained_err = "o" * DEFAULT_OUTPUT_CAPTURE_BYTES, "e" * 32
    result = ExecResult(
        OUTPUT_LIMIT_EXIT_CODE,
        retained_out,
        retained_err,
        5,
        output_limit_exceeded=True,
        stdout_truncated=True,
        stderr_truncated=True,
        stdout_bytes_retained=len(retained_out),
        stderr_bytes_retained=len(retained_err),
    )
    sandbox, _backend = _sandbox(tmp_path, result)

    with sandbox as sb:
        status, out = sb.run_argv_status(["pytest", "-q"])

        assert status == OUTPUT_LIMIT_EXIT_CODE
        # Exactly the retained truth, merged in stream order — nothing appended.
        assert out == retained_out + retained_err
        # The agent-facing tool still gets output alone, not an exception.
        assert sb.run_argv(["pytest", "-q"]) == retained_out + retained_err


def test_under_the_limit_output_is_verbatim(tmp_path: Path) -> None:
    """Below the bound the adapter is a faithful pipe: stdout then stderr,
    exit status intact, nothing added or dropped."""
    sandbox, _backend = _sandbox(tmp_path, ExecResult(0, "modest\n", "", 1))

    with sandbox as sb:
        assert sb.run_argv_status(["echo", "modest"]) == (0, "modest\n")

    sandbox, _backend = _sandbox(tmp_path, ExecResult(2, "to-out\n", "to-err\n", 1))

    with sandbox as sb:
        assert sb.run_argv_status(["false"]) == (2, "to-out\nto-err\n")


def test_a_timed_out_child_is_a_visible_failure_not_success(tmp_path: Path) -> None:
    """The backend reports a timeout as its own exit status; a validation run
    that outlives its bound must reach its caller as a failure, never as
    silent success."""
    sandbox, _backend = _sandbox(tmp_path, ExecResult(124, "", "", 120_000, timed_out=True))

    with sandbox as sb:
        assert sb.run_argv_status(["pytest", "-q"]) == (124, "")


def test_read_file_returns_the_sandbox_bytes_verbatim(tmp_path: Path) -> None:
    sandbox, _backend = _sandbox(tmp_path)

    with sandbox as sb:
        sb.write_file("note.txt", "modest file body")

        assert sb.read_file("note.txt") == "modest file body"


def test_a_missing_file_raises_file_not_found_through_the_bridge(tmp_path: Path) -> None:
    """A backend error crosses as itself: a missing file is `FileNotFoundError`
    for the caller, not empty content and not a swallowed exception."""
    sandbox, _backend = _sandbox(tmp_path)

    with sandbox as sb, pytest.raises(FileNotFoundError):
        sb.read_file("absent.txt")


def test_edit_file_refuses_an_ambiguous_match_before_any_write(tmp_path: Path) -> None:
    """The surviving adapter-side guard of the #1197 destroyed-tail hazard: a
    match that is not exactly one occurrence must fail CLOSED — no write
    reaches the sandbox, so no partial guess can replace the file's body."""
    sandbox, backend = _sandbox(tmp_path)

    with sandbox as sb:
        sb.write_file("big.txt", "original original")
        writes_before_edit = list(backend.writes)

        with pytest.raises(ValueError, match="appears 2 times"):
            sb.edit_file("big.txt", "original", "EDITED")

    assert backend.writes == writes_before_edit
