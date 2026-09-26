"""Coverage for tools/sandbox/server.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from maistro.sandbox import (
    UNTRUSTED_CODE,
    HostCapabilities,
    NoSuitableBackendError,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
    WorkloadPolicy,
    build_selector,
    paths,
)
from maistro.sandbox.network import EgressMode
from maistro.tools.sandbox import server
from maistro.tools.sandbox.server import (
    _check_path,
    _get_or_create,
    _parse_grep_matches,
    cleanup_all_containers,
    sandbox_destroy,
    sandbox_exec,
    sandbox_glob,
    sandbox_grep,
    sandbox_read,
    sandbox_write,
)


@pytest.fixture(autouse=True)
def _reset_containers() -> Any:
    server._containers.clear()
    yield
    server._containers.clear()


class _FakeContainer:
    def __init__(self, expired: bool = False) -> None:
        self.expired = expired
        self.destroyed = False
        self.exec_calls: list[tuple[str, int]] = []
        self.exec_result: tuple[int, str] = (0, "")
        self.read_result: str | Exception = "content"
        self.write_exc: Exception | None = None

    async def destroy(self) -> None:
        self.destroyed = True

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        self.exec_calls.append((command, timeout))
        return self.exec_result

    async def read_file(self, path: str) -> str:
        if isinstance(self.read_result, Exception):
            raise self.read_result
        return self.read_result

    async def write_file(self, path: str, content: str) -> None:
        if self.write_exc:
            raise self.write_exc


def test_check_path_blocks_blocked_path() -> None:
    result = _check_path("/etc/passwd")
    assert result is not None
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"
    assert "Blocked" in result["stdout"]


def test_check_path_allows_safe_path() -> None:
    assert _check_path("src/main.py") is None


def test_parse_grep_matches_parses_valid_lines() -> None:
    output = "src/a.py:10:def foo():\nsrc/b.py:20:x = 1"
    matches = _parse_grep_matches(output)
    assert matches == [
        {"path": "src/a.py", "line": 10, "text": "def foo():"},
        {"path": "src/b.py", "line": 20, "text": "x = 1"},
    ]


def test_parse_grep_matches_skips_line_without_colon() -> None:
    assert _parse_grep_matches("no colon here") == []


def test_parse_grep_matches_skips_non_digit_line_number() -> None:
    assert _parse_grep_matches("src/a.py:notanumber:text") == []


def test_parse_grep_matches_empty_output() -> None:
    assert _parse_grep_matches("") == []


async def test_get_or_create_returns_cached_container() -> None:
    fake = _FakeContainer(expired=False)
    server._containers["/ws"] = fake  # type: ignore[assignment]
    with patch("maistro.tools.sandbox.server.create_sandbox", new=AsyncMock()) as mock_create:
        result = await _get_or_create("/ws")
    assert result is fake
    mock_create.assert_not_called()


async def test_get_or_create_destroys_expired_and_creates_new() -> None:
    expired = _FakeContainer(expired=True)
    fresh = _FakeContainer(expired=False)
    server._containers["/ws"] = expired  # type: ignore[assignment]
    with patch("maistro.tools.sandbox.server.create_sandbox", new=AsyncMock(return_value=fresh)):
        result = await _get_or_create("/ws")
    assert expired.destroyed is True
    assert result is fresh
    assert server._containers["/ws"] is fresh


async def test_get_or_create_creates_when_absent() -> None:
    fresh = _FakeContainer()
    with patch("maistro.tools.sandbox.server.create_sandbox", new=AsyncMock(return_value=fresh)):
        result = await _get_or_create("/new-ws")
    assert result is fresh
    assert server._containers["/new-ws"] is fresh


async def test_cleanup_all_containers_destroys_all() -> None:
    a = _FakeContainer()
    b = _FakeContainer()
    server._containers["/a"] = a  # type: ignore[assignment]
    server._containers["/b"] = b  # type: ignore[assignment]
    await cleanup_all_containers()
    assert a.destroyed is True
    assert b.destroyed is True
    assert server._containers == {}


async def test_cleanup_all_containers_swallows_destroy_exceptions() -> None:
    class _Broken(_FakeContainer):
        async def destroy(self) -> None:
            raise RuntimeError("boom")

    broken = _Broken()
    server._containers["/broken"] = broken  # type: ignore[assignment]
    await cleanup_all_containers()
    assert server._containers == {}


async def test_sandbox_exec_blocks_dangerous_command() -> None:
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock()) as mock_get:
        result = await sandbox_exec("/ws", "rm -rf /")
    assert result["success"] is False
    assert result["error_code"] == "dangerous_command"
    mock_get.assert_not_called()


async def test_sandbox_exec_success() -> None:
    fake = _FakeContainer()
    fake.exec_result = (0, "hello")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_exec("/ws", "echo hello")
    assert result == {"success": True, "exit_code": 0, "stdout": "hello"}


async def test_sandbox_exec_failure() -> None:
    fake = _FakeContainer()
    fake.exec_result = (1, "boom")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_exec("/ws", "false")
    assert result["success"] is False
    assert result["exit_code"] == 1
    assert result["error_code"] == "command_failed"
    assert result["recoverable"] is True


async def test_sandbox_read_blocks_path() -> None:
    result = await sandbox_read("/ws", "/etc/passwd")
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"


async def test_sandbox_read_success() -> None:
    fake = _FakeContainer()
    fake.read_result = "file contents"
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_read("/ws", "a.txt")
    assert result == {"success": True, "exit_code": 0, "stdout": "file contents", "path": "a.txt"}


async def test_sandbox_read_not_found() -> None:
    fake = _FakeContainer()
    fake.read_result = FileNotFoundError("Cannot read a.txt: not found")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_read("/ws", "a.txt")
    assert result["success"] is False
    assert result["error_code"] == "file_not_found"
    assert result["path"] == "a.txt"


async def test_sandbox_write_blocks_path() -> None:
    result = await sandbox_write("/ws", "/etc/passwd", "x")
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"


async def test_sandbox_write_success() -> None:
    fake = _FakeContainer()
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_write("/ws", "a.txt", "hello")
    assert result == {"success": True, "exit_code": 0, "stdout": "Written: a.txt", "path": "a.txt"}


async def test_sandbox_write_failure() -> None:
    fake = _FakeContainer()
    fake.write_exc = OSError("disk full")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_write("/ws", "a.txt", "hello")
    assert result["success"] is False
    assert result["error_code"] == "write_failed"
    assert result["recoverable"] is True
    assert result["path"] == "a.txt"


async def test_sandbox_glob_blocks_path() -> None:
    result = await sandbox_glob("/ws", "/etc/*")
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"


async def test_sandbox_glob_returns_files() -> None:
    fake = _FakeContainer()
    fake.exec_result = (0, "/workspace/a.py\n/workspace/b.py\n")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_glob("/ws", "**/*.py")
    assert result["success"] is True
    assert result["files"] == ["/workspace/a.py", "/workspace/b.py"]
    assert result["file_count"] == 2
    command = fake.exec_calls[0][0]
    assert "find /workspace -path" in command
    assert "**/*.py" in command


async def test_sandbox_glob_no_files_found() -> None:
    fake = _FakeContainer()
    fake.exec_result = (0, "")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_glob("/ws", "*.missing")
    assert result["stdout"] == "No files found"
    assert result["files"] == []
    assert result["file_count"] == 0


async def test_sandbox_grep_blocks_path() -> None:
    result = await sandbox_grep("/ws", "pattern", "/etc")
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"


async def test_sandbox_grep_returns_matches() -> None:
    fake = _FakeContainer()
    fake.exec_result = (0, "src/a.py:10:def foo():\n")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_grep("/ws", "def foo")
    assert result["success"] is True
    assert result["matches"] == [{"path": "src/a.py", "line": 10, "text": "def foo():"}]
    assert result["match_count"] == 1
    command = fake.exec_calls[0][0]
    assert "grep -rn --" in command


async def test_sandbox_grep_no_matches_found() -> None:
    fake = _FakeContainer()
    fake.exec_result = (0, "")
    with patch("maistro.tools.sandbox.server._get_or_create", new=AsyncMock(return_value=fake)):
        result = await sandbox_grep("/ws", "nomatch")
    assert result["stdout"] == "No matches found"
    assert result["matches"] == []
    assert result["match_count"] == 0


async def test_sandbox_destroy_existing_container() -> None:
    fake = _FakeContainer()
    server._containers["/ws"] = fake  # type: ignore[assignment]
    result = await sandbox_destroy("/ws")
    assert result == {"success": True, "exit_code": 0, "stdout": "Sandbox destroyed for /ws"}
    assert fake.destroyed is True
    assert "/ws" not in server._containers


async def test_sandbox_destroy_missing_container() -> None:
    result = await sandbox_destroy("/missing")
    assert result["success"] is False
    assert result["error_code"] == "sandbox_not_found"


# --- the policy the tool sandbox actually selects (#18, round 3) ---------------
#
# sandbox_exec runs model-chosen shell. ADR-093's context names the tool
# sandbox as a place untrusted, model-generated code runs, so this seam must
# select UNTRUSTED_CODE — not TRUSTED_TOOL, which is for first-party API
# calls and granted this path the host network namespace (a #77 violation the
# 2026-09 review measured live: tier=container, network_mode=host).


class _SpawnRecordingBackend:
    """Enough backend for create_sandbox: record the config it spawns."""

    tier = "vm"

    def __init__(self, configs: list[SandboxConfig]) -> None:
        self._configs = configs

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self._configs.append(config)
        return SandboxInstance(
            id="rec-1", backend="recording", isolation_tier=self.tier, metadata={}
        )


class _RecordingSelector:
    """Real clamping via the real build_config; selection is recorded."""

    def __init__(self) -> None:
        self.selected: list[WorkloadPolicy] = []
        self.configs: list[SandboxConfig] = []

    def select(self, policy: WorkloadPolicy) -> tuple[str, Any]:
        self.selected.append(policy)
        return "vm", _SpawnRecordingBackend(self.configs)

    def build_config(self, policy: WorkloadPolicy, **overrides: Any) -> SandboxConfig:
        return SandboxSelector().build_config(policy, **overrides)


def _authorized_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "authorized-root" / "ws"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(paths, "AUTHORIZED_HOST_ROOTS", (tmp_path / "authorized-root",))
    return workspace


async def test_create_sandbox_selects_the_untrusted_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _authorized_workspace(monkeypatch, tmp_path)
    selector = _RecordingSelector()

    with patch.object(server, "build_selector", return_value=selector):
        sandbox = await server.create_sandbox(str(workspace))

    assert selector.selected == [UNTRUSTED_CODE]
    config = selector.configs[0]
    # Default-deny egress (#77): the tool never receives a network namespace.
    assert config.egress.mode is EgressMode.DENY
    assert not UNTRUSTED_CODE.network_allowed
    # Exactly one authorized writable host root, and no ambient env (#78).
    assert config.writable_paths == [str(workspace)]
    assert config.env == {}
    assert sandbox._instance.backend == "recording"


async def test_create_sandbox_refuses_without_a_vm_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Untrusted code refuses on Tier-3-only hosts — the honest disposition.

    The selector fails closed rather than serving model-chosen shell from a
    hardened container relabelled into a trust class ADR-093 never granted it.
    """
    workspace = _authorized_workspace(monkeypatch, tmp_path)
    empty = build_selector(capabilities=HostCapabilities(tiers=(), notes={}))

    with (
        patch.object(server, "build_selector", return_value=empty),
        pytest.raises(NoSuitableBackendError, match="min_tier='vm'"),
    ):
        await server.create_sandbox(str(workspace))
