"""Tests for the unified maistro CLI — container lifecycle and subcommand routing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from maistro.cli._container.lifecycle import SessionLifecycle
from maistro.cli._container.runtime import (
    ContainerCreateConfig,
    ContainerInfo,
    ContainerStatus,
)

runner = CliRunner()


# ── Fake container runtime ───────────────────────────────────────────────────


class FakeRuntime:
    """In-memory container runtime for testing."""

    def __init__(self) -> None:
        self._containers: dict[str, dict[str, Any]] = {}
        self._volumes: dict[str, dict[str, str]] = {}

    def create(self, config: ContainerCreateConfig) -> ContainerInfo:
        cid = f"fake-{config.name[:12]}"
        self._containers[config.name] = {
            "id": cid,
            "name": config.name,
            "image": config.image,
            "status": ContainerStatus.STOPPED,
            "labels": dict(config.labels),
            "volume": f"maistro-{config.name}",
        }
        self._volumes[f"maistro-{config.name}"] = {"labels": dict(config.labels)}
        return self.inspect(cid)

    def start(self, container_id: str) -> ContainerInfo:
        for c in self._containers.values():
            if c["id"] == container_id:
                c["status"] = ContainerStatus.RUNNING
                return self._to_info(c)
        raise ValueError(f"container {container_id} not found")

    def stop(self, container_id: str) -> ContainerInfo:
        for c in self._containers.values():
            if c["id"] == container_id:
                c["status"] = ContainerStatus.STOPPED
                return self._to_info(c)
        raise ValueError(f"container {container_id} not found")

    def remove(self, container_id: str, *, force: bool = False) -> None:
        to_remove = None
        for name, c in self._containers.items():
            if c["id"] == container_id:
                to_remove = name
                break
        if to_remove:
            del self._containers[to_remove]

    def inspect(self, container_id: str) -> ContainerInfo:
        for c in self._containers.values():
            if c["id"] == container_id:
                return self._to_info(c)
        raise ValueError(f"container {container_id} not found")

    def list_containers(self, *, label_filter: dict[str, str] | None = None) -> list[ContainerInfo]:
        results = []
        for c in self._containers.values():
            if label_filter:
                match = all(c["labels"].get(k) == v for k, v in label_filter.items())
                if not match:
                    continue
            results.append(self._to_info(c))
        return results

    def create_volume(self, name: str, labels: dict[str, str] | None = None) -> str:
        self._volumes[name] = {"labels": labels or {}}
        return name

    def remove_volume(self, name: str) -> None:
        self._volumes.pop(name, None)

    def archive_to_volume(self, container_id: str, volume_name: str) -> str:
        for c in self._containers.values():
            if c["id"] == container_id:
                c["status"] = ContainerStatus.MISSING
                self._containers.pop(c["name"])
                return volume_name
        raise ValueError(f"container {container_id} not found")

    def restore_from_volume(self, volume_name: str, config: ContainerCreateConfig) -> ContainerInfo:
        return self.create(config)

    def pull_image(self, image: str) -> None:
        pass

    def build_image(self, context_path: str, tag: str, dockerfile: str = "Dockerfile") -> str:
        return f"sha256:fake-{tag}"

    def is_available(self) -> bool:
        return True

    def _to_info(self, c: dict[str, Any]) -> ContainerInfo:
        return ContainerInfo(
            container_id=c["id"],
            name=c["name"],
            image=c["image"],
            status=c["status"],
            created=datetime.now(UTC),
            labels=c["labels"],
            volume_name=c.get("volume"),
        )


# ── Lifecycle tests ──────────────────────────────────────────────────────────


class TestSessionLifecycle:
    def setup_method(self) -> None:
        self.runtime = FakeRuntime()
        self.lifecycle = SessionLifecycle(runtime=self.runtime)

    def test_create_session(self) -> None:
        info = self.lifecycle.create_session(
            session_id="test-session",
            repo_url="https://github.com/org/repo",
            task="fix the bug",
        )
        assert info.status == ContainerStatus.RUNNING
        assert "test-session" in info.name

    def test_list_sessions(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo1")
        self.lifecycle.create_session(session_id="s2", repo_url="https://github.com/org/repo2")
        sessions = self.lifecycle.list_sessions()
        assert len(sessions) == 2

    def test_stop_session(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo")
        info = self.lifecycle.stop_session("s1")
        assert info.status == ContainerStatus.STOPPED

    def test_resume_stopped_session(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo")
        self.lifecycle.stop_session("s1")
        info = self.lifecycle.resume_session("s1")
        assert info.status == ContainerStatus.RUNNING

    def test_resume_running_session(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo")
        info = self.lifecycle.resume_session("s1")
        assert info.status == ContainerStatus.RUNNING

    def test_get_session(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo")
        info = self.lifecycle.get_session("s1")
        assert info is not None
        assert info.name == "s1"

    def test_get_missing_session(self) -> None:
        assert self.lifecycle.get_session("nonexistent") is None

    def test_make_session_id(self) -> None:
        sid = SessionLifecycle.make_session_id("https://github.com/org/my-repo")
        assert "my-repo" in sid
        assert len(sid) > 10

    def test_archive_session(self) -> None:
        self.lifecycle.create_session(session_id="s1", repo_url="https://github.com/org/repo")
        volume = self.lifecycle.archive_session("s1")
        assert "maistro-s1" in volume
        assert self.lifecycle.get_session("s1") is None

    def test_prune_sessions(self) -> None:
        old_labels = {
            "maistro.session": "old",
            "maistro.repo_url": "https://github.com/org/repo",
            "maistro.ttl": "72",
            "maistro.created_ts": str(datetime.now(UTC).timestamp() - 200 * 3600),
        }
        self.lifecycle.create_session(session_id="old", repo_url="https://github.com/org/repo")
        self.runtime._containers["old"]["labels"] = old_labels
        self.lifecycle.stop_session("old")

        self.lifecycle.create_session(session_id="fresh", repo_url="https://github.com/org/repo")

        pruned = self.lifecycle.prune_sessions(max_age_hours=168)
        assert "old" in pruned
        assert "fresh" not in pruned


# ── CLI routing tests ────────────────────────────────────────────────────────


class TestCLI:
    def test_no_args_shows_help(self) -> None:
        from maistro.cli import app

        result = runner.invoke(app, [])
        # click >= 8.2 treats "group invoked with no subcommand" as a usage
        # error (exit 2) rather than a success, while still printing the help.
        # We're on >= 8.3.3 because 8.1.x carries PYSEC-2026-2132, so exit 2 is
        # the contract now. What this test guards is that help is still shown.
        assert result.exit_code == 2
        assert "maistro" in result.output.lower()
        assert "Usage" in result.output
        assert "Commands" in result.output

    def test_approvals_list_no_server(self) -> None:
        from maistro.cli import app

        result = runner.invoke(app, ["approvals", "list"])
        # Should try to connect and fail gracefully
        assert (
            result.exit_code != 0
            or "error" in result.output.lower()
            or "no pending" in result.output.lower()
        )

    def test_builders_launches_app(self) -> None:
        from maistro.cli import app

        with patch("maistro.cli._builders._launch_app"):
            result = runner.invoke(app, ["builders"])
            assert result.exit_code == 0

    def test_launch_tui_placeholder(self) -> None:
        from maistro.cli import app

        result = runner.invoke(app, ["launch", "tui"])
        assert result.exit_code == 0
        assert "coming soon" in result.output.lower()

    def test_upgrade_no_git(self) -> None:
        from maistro.cli import app

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = runner.invoke(app, ["upgrade"])
            assert "git not found" in result.output.lower()


# ── Container types tests ────────────────────────────────────────────────────


class TestContainerTypes:
    def test_container_info_short_id(self) -> None:
        info = ContainerInfo(
            container_id="abc1234567890def",
            name="test",
            image="test:latest",
            status=ContainerStatus.RUNNING,
            created=datetime.now(UTC),
        )
        assert info.short_id == "abc123456789"

    def test_container_config_ttl_label(self) -> None:
        config = ContainerCreateConfig(
            image="test:latest",
            name="test",
            repo_url="https://github.com/org/repo",
            ttl_hours=48,
        )
        assert config.ttl_label == "maistro.ttl=48"

    def test_container_status_values(self) -> None:
        assert ContainerStatus.RUNNING.value == "running"
        assert ContainerStatus.STOPPED.value == "stopped"
        assert ContainerStatus.ARCHIVED.value == "archived"
        assert ContainerStatus.MISSING.value == "missing"


# ── Runtime detection tests ─────────────────────────────────────────────────


class TestRuntimeDetection:
    def test_detect_runtime_with_fake(self) -> None:
        from maistro.cli._container.runtime import detect_runtime

        with patch(
            "maistro.cli._container.docker_runtime.DockerRuntime.is_available",
            return_value=True,
        ):
            runtime = detect_runtime()
            assert runtime.is_available()

    def test_detect_runtime_none_available(self) -> None:
        from maistro.cli._container.runtime import detect_runtime

        with (
            patch(
                "maistro.cli._container.docker_runtime.DockerRuntime.is_available",
                return_value=False,
            ),
            patch(
                "maistro.cli._container.podman_runtime.PodmanRuntime.is_available",
                return_value=False,
            ),
            pytest.raises(RuntimeError, match="No container runtime"),
        ):
            detect_runtime()
