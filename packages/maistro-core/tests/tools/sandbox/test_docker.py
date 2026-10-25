"""Coverage for tools/sandbox/docker.py.

Mocks asyncio.create_subprocess_exec at the boundary -- no real Docker daemon
required -- and asserts exact container-creation kwargs/args rather than
skipping the isolation-guarantee assertions.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from maistro.config.settings import SandboxSettings
from maistro.tools.sandbox.docker import SandboxContainer, _shell_quote, create_sandbox


class _FakeProc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def test_shell_quote_escapes_dangerous_characters() -> None:
    assert _shell_quote("a; rm -rf /") == "'a; rm -rf /'"


def test_expired_false_when_within_ttl() -> None:
    container = SandboxContainer("abc123", "/host", ttl=3600)
    assert container.expired is False


def test_expired_true_when_ttl_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SandboxContainer("abc123", "/host", ttl=10)
    monkeypatch.setattr(
        "maistro.tools.sandbox.docker.time.monotonic", lambda: container.created_at + 20
    )
    assert container.expired is True


async def test_async_context_manager_calls_destroy() -> None:
    container = SandboxContainer("abc123", "/host")
    with patch.object(container, "destroy", new=AsyncMock()) as mock_destroy:
        async with container:
            pass
        mock_destroy.assert_awaited_once()


async def test_exec_blocks_dangerous_command_without_spawning_subprocess() -> None:
    container = SandboxContainer("abc123", "/host")
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=["rm -rf"]),
        patch("maistro.tools.sandbox.docker.asyncio.create_subprocess_exec") as mock_exec,
    ):
        code, output = await container.exec("rm -rf /")
    assert code == 1
    assert "blocked by safety filter" in output
    assert "rm -rf" in output
    mock_exec.assert_not_called()


async def test_exec_runs_command_and_returns_output() -> None:
    container = SandboxContainer("abc123", "/host")
    fake_proc = _FakeProc(stdout=b"hello\n", returncode=0)
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ) as mock_exec,
    ):
        code, output = await container.exec("echo hello")
    assert (code, output) == (0, "hello\n")
    args = mock_exec.call_args.args
    assert args == ("docker", "exec", "abc123", "bash", "-c", "echo hello")


async def test_exec_returns_nonzero_default_zero_when_returncode_none() -> None:
    container = SandboxContainer("abc123", "/host")
    fake_proc = _FakeProc(stdout=b"", returncode=None)
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ),
    ):
        code, output = await container.exec("true")
    assert code == 0
    assert output == ""


async def test_exec_times_out() -> None:
    container = SandboxContainer("abc123", "/host")

    class _HangingProc:
        returncode = None

        async def communicate(self) -> tuple[bytes, bytes]:
            import asyncio

            await asyncio.sleep(10)
            return b"", b""

    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_HangingProc()),
        ),
    ):
        code, output = await container.exec("sleep 100", timeout=0.01)
    assert code == 124
    assert "timed out after 0.01s" in output


async def test_exec_reraises_file_not_found_error() -> None:
    container = SandboxContainer("abc123", "/host")
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("no docker binary"),
        ),
        pytest.raises(FileNotFoundError),
    ):
        await container.exec("echo hi")


async def test_exec_reraises_permission_error() -> None:
    container = SandboxContainer("abc123", "/host")
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            side_effect=PermissionError("no socket access"),
        ),
        pytest.raises(PermissionError),
    ):
        await container.exec("echo hi")


async def test_exec_returns_error_string_on_os_error() -> None:
    container = SandboxContainer("abc123", "/host")
    with (
        patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=[]),
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            side_effect=OSError("boom"),
        ),
    ):
        code, output = await container.exec("echo hi")
    assert code == 1
    assert "Exec error: boom" in output


def test_safe_path_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        SandboxContainer._safe_path("/workspace", "/etc/passwd")


def test_safe_path_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="Path traversal detected"):
        SandboxContainer._safe_path("/workspace", "../../etc/passwd")


def test_safe_path_resolves_relative_path_within_workspace() -> None:
    assert SandboxContainer._safe_path("/workspace", "src/main.py") == "/workspace/src/main.py"


async def test_read_file_returns_output_on_success() -> None:
    container = SandboxContainer("abc123", "/host")
    with patch.object(container, "exec", new=AsyncMock(return_value=(0, "file contents"))):
        result = await container.read_file("a.txt")
    assert result == "file contents"


async def test_read_file_raises_when_exec_fails() -> None:
    container = SandboxContainer("abc123", "/host")
    with (
        patch.object(container, "exec", new=AsyncMock(return_value=(1, "not found"))),
        pytest.raises(FileNotFoundError, match=r"Cannot read a\.txt"),
    ):
        await container.read_file("a.txt")


async def test_write_file_creates_parent_dir_and_writes_content() -> None:
    container = SandboxContainer("abc123", "/host")
    calls: list[str] = []

    async def fake_exec(command: str, timeout: int = 60) -> tuple[int, str]:
        calls.append(command)
        return 0, ""

    with patch.object(container, "exec", new=fake_exec):
        await container.write_file("sub/dir/a.txt", "hello world")

    assert any(cmd.startswith("mkdir -p") for cmd in calls)
    assert any("base64 -d" in cmd for cmd in calls)


async def test_write_file_no_mkdir_when_path_has_no_parent() -> None:
    container = SandboxContainer("abc123", "/host", workspace_container="")
    calls: list[str] = []

    async def fake_exec(command: str, timeout: int = 60) -> tuple[int, str]:
        calls.append(command)
        return 0, ""

    with patch.object(container, "exec", new=fake_exec):
        await container.write_file("a.txt", "hello")

    assert len(calls) == 1
    assert "mkdir" not in calls[0]


async def test_write_file_raises_on_failure() -> None:
    container = SandboxContainer("abc123", "/host")

    async def fake_exec(command: str, timeout: int = 60) -> tuple[int, str]:
        return 1, "disk full"

    with (
        patch.object(container, "exec", new=fake_exec),
        pytest.raises(OSError, match=r"Cannot write a\.txt"),
    ):
        await container.write_file("a.txt", "hello")


async def test_destroy_logs_success_on_zero_exit() -> None:
    container = SandboxContainer("abc123def456", "/host")
    fake_proc = _FakeProc(stderr=b"", returncode=0)
    with patch(
        "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        await container.destroy()
    mock_exec.assert_awaited_once()
    assert mock_exec.call_args.args == ("docker", "rm", "-f", "abc123def456")


async def test_destroy_logs_warning_on_nonzero_exit() -> None:
    container = SandboxContainer("abc123", "/host")
    fake_proc = _FakeProc(stderr=b"no such container", returncode=1)
    with patch(
        "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        await container.destroy()

    mock_exec.assert_awaited_once_with(
        "docker",
        "rm",
        "-f",
        "abc123",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def test_create_sandbox_builds_expected_docker_run_args(tmp_path: Any) -> None:
    settings = SandboxSettings(
        image="python:3.12-slim",
        memory_limit="256m",
        cpu_count=1,
        timeout=120,
        network_disabled=True,
    )
    workspace = f"/tmp/maistro-workspace/{tmp_path.name}"
    fake_proc = _FakeProc(stdout=b"deadbeef1234\n", returncode=0)

    with patch(
        "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        container = await create_sandbox(workspace, settings=settings, env={"TZ": "UTC"})

    assert container.container_id == "deadbeef1234"
    args = mock_exec.call_args.args
    assert args[0:2] == ("docker", "run")
    assert "--memory=256m" in args
    assert "--cpus=1" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--cap-drop=ALL" in args
    assert "--network=none" in args
    assert "-e" in args
    tz_index = args.index("-e") + 1
    assert args[tz_index] == "TZ=UTC"
    assert "python:3.12-slim" in args
    assert "sleep" in args
    assert "120" in args


async def test_create_sandbox_omits_network_none_when_disabled_false(tmp_path: Any) -> None:
    settings = SandboxSettings(network_disabled=False)
    workspace = f"/tmp/maistro-workspace/{tmp_path.name}"
    fake_proc = _FakeProc(stdout=b"cafebabe\n", returncode=0)

    with patch(
        "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec:
        await create_sandbox(workspace, settings=settings)

    assert "--network=none" not in mock_exec.call_args.args


async def test_create_sandbox_raises_on_docker_failure(tmp_path: Any) -> None:
    settings = SandboxSettings()
    workspace = f"/tmp/maistro-workspace/{tmp_path.name}"
    fake_proc = _FakeProc(stderr=b"image not found", returncode=1)

    with (
        patch(
            "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ),
        pytest.raises(RuntimeError, match="Failed to create sandbox: image not found"),
    ):
        await create_sandbox(workspace, settings=settings)


async def test_create_sandbox_uses_default_settings_when_none_provided(tmp_path: Any) -> None:
    workspace = f"/tmp/maistro-workspace/{tmp_path.name}"
    fake_proc = _FakeProc(stdout=b"abc123\n", returncode=0)
    with patch(
        "maistro.tools.sandbox.docker.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        container = await create_sandbox(workspace)
    assert container.ttl == SandboxSettings().timeout
