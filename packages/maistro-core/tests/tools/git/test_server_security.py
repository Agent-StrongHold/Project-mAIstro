"""Security tests for git MCP workspace boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.tools.git.server import git_clone, git_status


@pytest.mark.parametrize("workspace", ["/etc", "/root/.ssh", "/tmp/maistro-workspace-evil/repo"])
async def test_git_status_rejects_disallowed_workspace_before_git(
    monkeypatch: pytest.MonkeyPatch, workspace: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git subprocess should not be created for blocked workspaces")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_status(workspace)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


async def test_git_status_allows_workspace_under_allowed_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = Path("/tmp/maistro-workspace/git-server-test")
    workspace.mkdir(parents=True, exist_ok=True)

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"", None

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        assert args[:3] == ("git", "-C", str(workspace.resolve()))
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_status(str(workspace))

    assert result["success"] is True


@pytest.mark.parametrize("dest", ["/etc/repo", "/tmp/maistro-workspace-evil/repo"])
async def test_git_clone_rejects_disallowed_dest_before_git(
    monkeypatch: pytest.MonkeyPatch, dest: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should not be created for blocked destinations")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("https://example.com/repo.git", dest)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


# --- Unauthenticated git:// transport is rejected (#404) ---------------------
#
# `git://` provides neither transport encryption nor server authentication, so
# an on-path attacker can substitute repository content that the RSI cycle
# then branches, patches, builds, and tests. The gate is an allowlist
# (`https://`, `ssh://`); these tests pin that the unauthenticated protocol is
# rejected *by name* — its own error code, not a generic scheme verdict — and
# that no git subprocess is ever spawned for it.


@pytest.mark.parametrize(
    "url",
    [
        "git://example.com/repo.git",
        "git://127.0.0.1:9418/repo",
        "git://github.com/python/cpython",
    ],
)
async def test_git_clone_rejects_git_protocol_before_git(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should never spawn for the git:// protocol")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-protocol-test")

    assert result["success"] is False
    assert result["error_code"] == "blocked_unauthenticated_transport"
    assert "git://" in result["stdout"]


@pytest.mark.parametrize("url", ["GIT://example.com/repo.git", "Git://example.com/repo"])
async def test_git_clone_rejects_git_protocol_case_insensitively(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """git parses remote schemes case-insensitively (RFC 3986), so a cased
    variant names the same unauthenticated transport and must not sneak past a
    case-sensitive comparison into the generic allowlist verdict."""

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("cased git:// must never reach a git subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-protocol-test")

    assert result["success"] is False
    assert result["error_code"] == "blocked_unauthenticated_transport"


@pytest.mark.parametrize("url", ["https://example.com/repo.git", "ssh://git@example.com/repo"])
async def test_git_clone_allows_authenticated_transports(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """The policy targets the unauthenticated protocol only: authenticated
    transports still pass the scheme gate and reach git."""

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"Cloned", None

    seen: dict[str, object] = {}

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        seen["argv"] = args
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-transport-test")

    assert result["success"] is True
    assert seen["argv"][0] == "git"
    # The URL is passed after `--`, so no scheme can be reinterpreted as a
    # git flag on the way into the subprocess.
    argv = seen["argv"]
    assert argv[-3] == "--"
    assert argv[-2] == url
    assert argv[-1] == "/tmp/maistro-workspace/git-transport-test"
