"""#76/#77: what the builders sandbox adapter is allowed to do on the host.

These are argv-shape tests — they run everywhere, no backend needed — and pin
the cutover invariant from the *host* side:

* the adapter never constructs a Docker (or any direct sandbox) command line:
  the substrate is the canonical selector's backend, and the only host-side
  subprocesses are the two `tar` pipes that implement the credential boundary;
* the seed archive is built host-side through the `_SEED_EXCLUDES` denylist,
  never a blind copy of the whole tree;
* the sync-back extract excludes `.git` host-side — the filter the candidate
  cannot reach.

The backend's own create-time hardening (network=none, cap-drop, read-only
rootfs, ulimits) is asserted where it lives, in the canonical backend suites
(`packages/maistro-core/tests/sandbox/`), not here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import maistro_bootstrap.builders.container_sandbox as csbx_mod
from maistro.sandbox import SandboxConfig, SandboxInstance, SandboxSelector
from maistro.sandbox.protocol import ExecResult
from maistro_bootstrap.builders.container_sandbox import (
    _SEED_EXCLUDES,
    ContainerBuilderSandbox,
)


class _StubVMSandbox:
    tier = "vm"

    def __init__(self) -> None:
        self.spawned: list[SandboxConfig] = []

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.spawned.append(config)
        return SandboxInstance(id="stub-1", backend="stub", isolation_tier="vm")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        return ExecResult(0, "", "", 0)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        return b""

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        return None

    async def destroy(self, instance: SandboxInstance) -> None:
        return None


class _Recording:
    """A `subprocess.run` stand-in that records argv and touches nothing."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append(list(argv))
        stdout: Any = b""  # the tar pipes are binary (no text=True anywhere)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recording:
    rec = _Recording()
    monkeypatch.setattr(csbx_mod.subprocess, "run", rec)
    return rec


@pytest.fixture()
def sandbox(tmp_path: Path, recorder: _Recording) -> ContainerBuilderSandbox:
    selector = SandboxSelector()
    selector.register("vm", _StubVMSandbox())
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return ContainerBuilderSandbox(tmp_path, selector=selector)


def test_the_adapter_never_constructs_a_docker_command(recorder: _Recording, sandbox) -> None:
    """The #76 regression this file exists for: the builders path used to run
    its own hardened `docker run`/`docker exec` argv — a second sandbox
    implementation beside the canonical selector. Today the only host-side
    subprocesses are the credential-boundary tar pipes."""
    with sandbox:
        sandbox.run_command("echo hi")
        sandbox.read_file("hello.py")
        sandbox.write_file("new.py", "x = 1\n")
        sandbox.diff()
        sandbox.search("hi")
        sandbox.sync_to_host()

    assert recorder.calls, "expected the seed/sync tar pipes to run"
    offenders = [argv for argv in recorder.calls if argv[0] in ("docker", "podman", "nerdctl")]
    assert offenders == [], f"adapter constructed a direct container CLI: {offenders}"


def test_the_seed_archive_is_built_host_side_with_the_denylist(
    recorder: _Recording, sandbox, tmp_path: Path
) -> None:
    with sandbox:
        pass

    creates = [argv for argv in recorder.calls if argv[:3] == ["tar", "-cf", "-"]]
    assert len(creates) == 1, "entering the sandbox must build exactly one seed archive"
    argv = creates[0]
    for pattern in _SEED_EXCLUDES:
        assert f"--exclude={pattern}" in argv, f"seed dropped the {pattern!r} denylist entry"
    # The archive reads the repo from the host (the trust boundary), rooted
    # at the repo — not at / or $HOME.
    assert argv[argv.index("-C") + 1] == str(tmp_path)


def test_the_sync_extract_filters_git_host_side(
    recorder: _Recording, sandbox, tmp_path: Path
) -> None:
    with sandbox:
        sandbox.sync_to_host()

    extracts = [argv for argv in recorder.calls if argv[:3] == ["tar", "xf", "-"]]
    assert len(extracts) == 1
    argv = extracts[0]
    assert "--exclude=./.git" in argv, "the host-side .git filter is the boundary that matters"
    assert "--no-same-owner" in argv, "synced files must not land with foreign uids"
    assert argv[argv.index("-C") + 1] == str(tmp_path)


def test_failure_paths_do_not_fall_back_to_direct_execution(
    recorder: _Recording, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the seed archive cannot be built, the adapter must fail — not reach
    for a host shell or a direct container as a fallback."""
    (tmp_path / "hello.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def _failing_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        recorder.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"no space left on device")

    monkeypatch.setattr(csbx_mod.subprocess, "run", _failing_run)
    selector = SandboxSelector()
    selector.register("vm", _StubVMSandbox())
    with (
        pytest.raises(RuntimeError, match="seed tar failed"),
        ContainerBuilderSandbox(tmp_path, selector=selector),
    ):
        pass

    # `git init` (this test's own setup) and the adapter's tar pipe are the
    # only subprocesses; nothing else — no docker, no host shell — was reached
    # for as a fallback.
    reached = [argv[0] for argv in recorder.calls]
    assert set(reached) <= {"git", "tar"}, recorder.calls
