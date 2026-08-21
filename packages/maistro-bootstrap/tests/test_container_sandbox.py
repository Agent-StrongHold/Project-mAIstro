"""Isolation test for ContainerBuilderSandbox (ADR-093).

Docker-gated: skipped unless docker is on PATH and the maistro-builders image is
present, so it runs where the isolated backend actually exists and is a no-op
elsewhere (e.g. a CI box without Docker).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from maistro_bootstrap.builders.container_sandbox import DEFAULT_IMAGE, ContainerBuilderSandbox


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    r = subprocess.run(
        ["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, text=True
    )
    return r.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ready(), reason=f"docker or {DEFAULT_IMAGE} image unavailable"
)


def test_agent_edits_are_isolated_from_host(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    host_before = (tmp_path / "hello.py").read_text(encoding="utf-8")

    with ContainerBuilderSandbox(tmp_path) as sb:
        assert sb.read_file("hello.py") == host_before
        sb.edit_file("hello.py", "original", "EDITED")
        assert "EDITED" in sb.read_file("hello.py")
        sb.write_file("pkg/new.py", "x = 1\n")
        assert sb.search("EDITED", glob="**/*.py") == ["hello.py"]
        # Isolation: the agent's edits have NOT touched the host yet.
        assert (tmp_path / "hello.py").read_text(encoding="utf-8") == host_before

        sb.sync_to_host()

    # After an explicit sync, the host reflects the container's work.
    assert "EDITED" in (tmp_path / "hello.py").read_text(encoding="utf-8")
    assert (tmp_path / "pkg" / "new.py").exists()


def test_path_escape_blocked(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    from maistro_bootstrap.builders.errors import SandboxEscapeError

    with ContainerBuilderSandbox(tmp_path) as sb:
        with pytest.raises(SandboxEscapeError):
            sb.read_file("../escape.txt")
        with pytest.raises(SandboxEscapeError):
            sb.write_file("/etc/passwd", "bad")
