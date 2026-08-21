"""Tests for maistro.cli._container.lifecycle.SessionLifecycle.

Uses a real in-memory FakeRuntime (matching the ContainerRuntime protocol)
rather than mocks, per project convention.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.cli._container.lifecycle import SessionLifecycle
from maistro.cli._container.runtime import (
    ContainerCreateConfig,
    ContainerInfo,
    ContainerStatus,
)


class FakeRuntime:
    """Minimal in-memory ContainerRuntime implementation for tests."""

    def __init__(self) -> None:
        self.containers: dict[str, ContainerInfo] = {}
        self.volumes: dict[str, str] = {}
        self._next_id = 0

    def _new_id(self) -> str:
        self._next_id += 1
        return f"container-{self._next_id:03d}"

    def create(self, config: ContainerCreateConfig) -> ContainerInfo:
        cid = self._new_id()
        info = ContainerInfo(
            container_id=cid,
            name=config.name,
            image=config.image,
            status=ContainerStatus.STOPPED,
            created=datetime.now(UTC),
            labels=dict(config.labels),
        )
        self.containers[cid] = info
        return info

    def start(self, container_id: str) -> ContainerInfo:
        info = self.containers[container_id]
        updated = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=ContainerStatus.RUNNING,
            created=info.created,
            ports=info.ports,
            labels=info.labels,
            volume_name=info.volume_name,
        )
        self.containers[container_id] = updated
        return updated

    def stop(self, container_id: str) -> ContainerInfo:
        info = self.containers[container_id]
        updated = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=ContainerStatus.STOPPED,
            created=info.created,
            ports=info.ports,
            labels=info.labels,
            volume_name=info.volume_name,
        )
        self.containers[container_id] = updated
        return updated

    def remove(self, container_id: str, *, force: bool = False) -> None:
        self.containers.pop(container_id, None)

    def inspect(self, container_id: str) -> ContainerInfo:
        return self.containers[container_id]

    def list_containers(self, *, label_filter: dict[str, str] | None = None) -> list[ContainerInfo]:
        results = list(self.containers.values())
        if label_filter:
            results = [
                info
                for info in results
                if all(info.labels.get(k) == v for k, v in label_filter.items())
            ]
        return results

    def create_volume(self, name: str, labels: dict[str, str] | None = None) -> str:
        self.volumes[name] = name
        return name

    def remove_volume(self, name: str) -> None:
        self.volumes.pop(name, None)

    def archive_to_volume(self, container_id: str, volume_name: str) -> str:
        info = self.containers[container_id]
        archived = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=ContainerStatus.ARCHIVED,
            created=info.created,
            ports=info.ports,
            labels=info.labels,
            volume_name=volume_name,
        )
        self.containers[container_id] = archived
        self.volumes[volume_name] = container_id
        return volume_name

    def restore_from_volume(self, volume_name: str, config: ContainerCreateConfig) -> ContainerInfo:
        cid = self._new_id()
        info = ContainerInfo(
            container_id=cid,
            name=config.name,
            image=config.image,
            status=ContainerStatus.STOPPED,
            created=datetime.now(UTC),
            labels={"maistro.session": config.name},
        )
        self.containers[cid] = info
        return info

    def pull_image(self, image: str) -> None:
        pass

    def build_image(self, context_path: str, tag: str, dockerfile: str = "Dockerfile") -> str:
        return tag

    def is_available(self) -> bool:
        return True


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def lifecycle(runtime: FakeRuntime) -> SessionLifecycle:
    return SessionLifecycle(runtime)


class TestRuntimeProperty:
    def test_explicit_runtime_is_used(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        assert lifecycle.runtime is runtime

    def test_no_runtime_lazily_detects(self, monkeypatch) -> None:
        fake = FakeRuntime()

        def fake_detect():
            return fake

        monkeypatch.setattr("maistro.cli._container.runtime.detect_runtime", fake_detect)
        lifecycle = SessionLifecycle()
        assert lifecycle.runtime is fake
        # Cached after first access.
        assert lifecycle.runtime is fake


class TestCreateSession:
    def test_creates_and_starts_container(self, lifecycle: SessionLifecycle) -> None:
        info = lifecycle.create_session(session_id="s1", repo_url="https://example.com/repo.git")
        assert info.status == ContainerStatus.RUNNING
        assert info.labels["maistro.session"] == "s1"

    def test_task_label_is_truncated_to_200_chars(self, lifecycle: SessionLifecycle) -> None:
        long_task = "x" * 500
        info = lifecycle.create_session(
            session_id="s2", repo_url="https://example.com/repo.git", task=long_task
        )
        assert len(info.labels["maistro.task"]) == 200


class TestResumeSession:
    def test_already_running_returns_as_is(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s3", repo_url="https://example.com/repo.git")
        info = lifecycle.resume_session("s3")
        assert info.status == ContainerStatus.RUNNING

    def test_stopped_session_is_started(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s4", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("s4")
        info = lifecycle.resume_session("s4")
        assert info.status == ContainerStatus.RUNNING

    def test_archived_session_is_restored(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s5", repo_url="https://example.com/repo.git")
        lifecycle.archive_session("s5")
        info = lifecycle.resume_session("s5")
        assert info.status == ContainerStatus.RUNNING

    def test_missing_session_raises(self, lifecycle: SessionLifecycle) -> None:
        with pytest.raises(ValueError, match="not found"):
            lifecycle.resume_session("nope")

    def test_missing_status_session_raises(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="s11", repo_url="https://example.com/repo.git")
        info = lifecycle._get_by_name("s11")
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=ContainerStatus.MISSING,
            created=info.created,
            labels=info.labels,
        )
        with pytest.raises(ValueError, match="not found"):
            lifecycle.resume_session("s11")


class TestStopSession:
    def test_running_session_is_stopped(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s6", repo_url="https://example.com/repo.git")
        info = lifecycle.stop_session("s6")
        assert info.status == ContainerStatus.STOPPED

    def test_already_stopped_returns_as_is(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s7", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("s7")
        info = lifecycle.stop_session("s7")
        assert info.status == ContainerStatus.STOPPED


class TestArchiveSession:
    def test_running_session_stops_then_archives(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s8", repo_url="https://example.com/repo.git")
        volume = lifecycle.archive_session("s8")
        assert volume == "maistro-s8"

    def test_already_archived_is_idempotent(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="s9", repo_url="https://example.com/repo.git")
        lifecycle.archive_session("s9")
        volume = lifecycle.archive_session("s9")
        assert volume == "maistro-s9"

    def test_uses_existing_volume_name_if_set(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="s10", repo_url="https://example.com/repo.git")
        info = lifecycle._get_by_name("s10")
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=ContainerStatus.STOPPED,
            created=info.created,
            labels=info.labels,
            volume_name="custom-volume",
        )
        volume = lifecycle.archive_session("s10")
        assert volume == "custom-volume"


class TestPruneSessions:
    def test_skips_non_stopped_sessions(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="p1", repo_url="https://example.com/repo.git")
        pruned = lifecycle.prune_sessions(max_age_hours=0)
        assert pruned == []

    def test_skips_sessions_without_created_label(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="p2", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("p2")
        info = lifecycle._get_by_name("p2")
        labels = dict(info.labels)
        labels.pop("maistro.created_ts", None)
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=info.status,
            created=info.created,
            labels=labels,
        )
        pruned = lifecycle.prune_sessions(max_age_hours=0)
        assert pruned == []

    def test_skips_unparseable_created_label(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="p3", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("p3")
        info = lifecycle._get_by_name("p3")
        labels = dict(info.labels)
        labels["maistro.created_ts"] = "not-a-float"
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=info.status,
            created=info.created,
            labels=labels,
        )
        pruned = lifecycle.prune_sessions(max_age_hours=0)
        assert pruned == []

    def test_prunes_sessions_older_than_max_age(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="p4", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("p4")
        info = lifecycle._get_by_name("p4")
        labels = dict(info.labels)
        labels["maistro.created_ts"] = "0"  # epoch — guaranteed older than max_age_hours
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=info.status,
            created=info.created,
            labels=labels,
        )
        pruned = lifecycle.prune_sessions(max_age_hours=1)
        assert pruned == ["p4"]
        assert lifecycle.get_session("p4").status == ContainerStatus.ARCHIVED

    def test_does_not_prune_recent_sessions(
        self, lifecycle: SessionLifecycle, runtime: FakeRuntime
    ) -> None:
        lifecycle.create_session(session_id="p5", repo_url="https://example.com/repo.git")
        lifecycle.stop_session("p5")
        info = lifecycle._get_by_name("p5")
        labels = dict(info.labels)
        labels["maistro.created_ts"] = str(datetime.now(UTC).timestamp())
        runtime.containers[info.container_id] = ContainerInfo(
            container_id=info.container_id,
            name=info.name,
            image=info.image,
            status=info.status,
            created=info.created,
            labels=labels,
        )
        pruned = lifecycle.prune_sessions(max_age_hours=168)
        assert pruned == []


class TestGetSession:
    def test_existing_session_returns_info(self, lifecycle: SessionLifecycle) -> None:
        lifecycle.create_session(session_id="g1", repo_url="https://example.com/repo.git")
        info = lifecycle.get_session("g1")
        assert info is not None
        assert info.name == "g1"

    def test_missing_session_returns_none(self, lifecycle: SessionLifecycle) -> None:
        assert lifecycle.get_session("nope") is None


class TestMakeSessionId:
    def test_slugifies_repo_name_and_appends_timestamp(self) -> None:
        session_id = SessionLifecycle.make_session_id("https://example.com/My_Repo.git")
        assert session_id.startswith("My-Repo-")

    def test_special_characters_are_replaced(self) -> None:
        session_id = SessionLifecycle.make_session_id("https://example.com/weird@name!.git")
        slug = session_id.rsplit("-", 2)[0]
        assert all(c.isalnum() or c == "-" for c in slug)
