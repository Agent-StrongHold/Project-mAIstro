"""Tests for maistro.cli._container.docker_runtime — Docker SDK runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from maistro.cli._container import docker_runtime as docker_runtime_module
from maistro.cli._container.docker_runtime import DockerRuntime
from maistro.cli._container.runtime import ContainerCreateConfig, ContainerStatus


class _StubDatetime:
    """Stand-in for the `datetime` class that tolerates any `Created` shape.

    Used to isolate `_to_info` assertions (status/labels/volume/image) from the
    real `datetime.fromtimestamp` bug exercised by `test_created_iso_string_raises_typeerror`.
    """

    @staticmethod
    def fromtimestamp(_ts: Any, tz: Any = None) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def stub_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_runtime_module, "datetime", _StubDatetime)


class FakeImage:
    def __init__(
        self, *, tags: list[str] | None = None, image_id: str = "sha256:abcdef1234567890"
    ) -> None:
        self.tags = tags or []
        self.id = image_id


class FakeContainer:
    def __init__(
        self,
        *,
        container_id: str = "c1",
        name: str = "maistro-test",
        status: str = "running",
        labels: dict[str, str] | None = None,
        created: Any = "2021-01-01T00:00:00.123456789Z",
        mounts: list[dict[str, str]] | None = None,
        image: FakeImage | None = None,
    ) -> None:
        self.id = container_id
        self.name = name
        self.status = status
        self.labels = labels if labels is not None else {}
        self.image = image or FakeImage()
        self.attrs: dict[str, Any] = {"Created": created, "Mounts": mounts or []}
        self.start = MagicMock()
        self.stop = MagicMock()
        self.remove = MagicMock()
        self.reload = MagicMock()
        self.wait = MagicMock()


@pytest.fixture
def runtime() -> DockerRuntime:
    return DockerRuntime()


@pytest.fixture
def fake_client() -> MagicMock:
    return MagicMock()


def _with_client(runtime: DockerRuntime, client: MagicMock) -> DockerRuntime:
    runtime._client = client
    return runtime


class TestClientProperty:
    def test_lazy_creates_client(
        self, runtime: DockerRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_docker_module = MagicMock()
        fake_docker_module.from_env.return_value = "the-client"
        monkeypatch.setitem(__import__("sys").modules, "docker", fake_docker_module)
        result = runtime.client
        assert result == "the-client"
        fake_docker_module.from_env.assert_called_once()

    def test_reuses_existing_client(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        assert runtime.client is fake_client


class TestIsAvailable:
    def test_true_on_successful_ping(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        assert runtime.is_available() is True

    def test_false_on_exception(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        fake_client.ping.side_effect = RuntimeError("down")
        _with_client(runtime, fake_client)
        assert runtime.is_available() is False


class TestCreate:
    def test_builds_labels_and_creates_container(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.create.return_value = fake_container

        config = ContainerCreateConfig(
            image="python:3.11",
            name="test",
            repo_url="https://example.com/r.git",
        )
        info = runtime.create(config)

        fake_client.volumes.create.assert_called_once()
        vol_kwargs = fake_client.volumes.create.call_args.kwargs
        assert vol_kwargs["name"] == "maistro-test"
        assert vol_kwargs["labels"]["maistro.managed"] == "true"
        assert vol_kwargs["labels"]["maistro.session"] == "test"
        assert vol_kwargs["labels"]["maistro.ttl"] == "72"
        assert vol_kwargs["labels"]["maistro.repo_url"] == "https://example.com/r.git"

        create_kwargs = fake_client.containers.create.call_args.kwargs
        assert create_kwargs["image"] == "python:3.11"
        assert create_kwargs["name"] == "maistro-test"
        assert create_kwargs["command"] == ["sleep", "infinity"]
        assert create_kwargs["volumes"] == {"maistro-test": {"bind": "/workspace", "mode": "rw"}}

        assert info.container_id == "c1"


class TestStartStopRemoveInspect:
    def test_start(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.get.return_value = fake_container
        info = runtime.start("c1")
        fake_container.start.assert_called_once()
        fake_container.reload.assert_called_once()
        assert info.container_id == "c1"

    def test_stop(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.get.return_value = fake_container
        runtime.stop("c1")
        fake_container.stop.assert_called_once_with(timeout=10)
        fake_container.reload.assert_called_once()

    def test_remove_force_true(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.get.return_value = fake_container
        runtime.remove("c1", force=True)
        fake_container.remove.assert_called_once_with(force=True)

    def test_remove_force_false_default(
        self, runtime: DockerRuntime, fake_client: MagicMock
    ) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.get.return_value = fake_container
        runtime.remove("c1")
        fake_container.remove.assert_called_once_with(force=False)

    def test_inspect(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        fake_container = FakeContainer()
        fake_client.containers.get.return_value = fake_container
        info = runtime.inspect("c1")
        assert info.container_id == "c1"


class TestListContainers:
    def test_default_label_filter(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        fake_client.containers.list.return_value = [FakeContainer()]
        result = runtime.list_containers()
        filters = fake_client.containers.list.call_args.kwargs["filters"]
        assert filters["label"] == ["maistro.managed=true"]
        assert len(result) == 1

    def test_custom_label_filter(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        fake_client.containers.list.return_value = []
        runtime.list_containers(label_filter={"a": "b", "c": "d"})
        filters = fake_client.containers.list.call_args.kwargs["filters"]
        assert filters["label"] == ["a=b", "c=d"]


class TestCreateVolume:
    def test_no_extra_labels(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        name = runtime.create_volume("vol1")
        fake_client.volumes.create.assert_called_once_with(
            name="vol1", labels={"maistro.managed": "true"}
        )
        assert name == "vol1"

    def test_with_extra_labels(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        runtime.create_volume("vol1", labels={"x": "y"})
        fake_client.volumes.create.assert_called_once_with(
            name="vol1", labels={"maistro.managed": "true", "x": "y"}
        )


class TestRemoveVolume:
    def test_success(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        fake_volume = MagicMock()
        fake_client.volumes.get.return_value = fake_volume
        runtime.remove_volume("vol1")
        fake_volume.remove.assert_called_once()

    def test_swallows_exception(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        fake_client.volumes.get.side_effect = RuntimeError("not found")
        runtime.remove_volume("vol1")

        fake_client.volumes.get.assert_called_once_with("vol1")


class TestArchiveToVolume:
    def test_creates_starts_waits_removes(
        self, runtime: DockerRuntime, fake_client: MagicMock
    ) -> None:
        _with_client(runtime, fake_client)
        orig_container = FakeContainer(container_id="c1", name="maistro-test")
        archive_container = FakeContainer(container_id="c2", name="maistro-archive-maistro-test")

        def fake_get(cid_or_name: str) -> FakeContainer:
            if cid_or_name == "c1":
                return orig_container
            return archive_container

        fake_client.containers.get.side_effect = fake_get
        fake_client.containers.create.return_value = archive_container

        result = runtime.archive_to_volume("c1", "myvol")

        create_kwargs = fake_client.containers.create.call_args.kwargs
        assert create_kwargs["image"] == "busybox"
        assert create_kwargs["name"] == "maistro-archive-maistro-test"
        archive_container.start.assert_called_once()
        archive_container.wait.assert_called_once()
        archive_container.remove.assert_called_once()
        orig_container.remove.assert_called_once()
        assert result == "myvol"


class TestRestoreFromVolume:
    def test_creates_and_restores(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        created_container = FakeContainer(
            container_id="c1",
            mounts=[{"Destination": "/workspace", "Name": "maistro-test"}],
        )
        fake_client.containers.create.return_value = created_container
        restore_container = FakeContainer(container_id="c2", name="maistro-restore-test")

        def fake_get(name: str) -> FakeContainer:
            return restore_container

        fake_client.containers.get.side_effect = fake_get
        # First create() call returns created_container; restore container create call
        # also goes through containers.create — distinguish via call count.
        calls = {"n": 0}

        def create_side_effect(*args: Any, **kwargs: Any) -> FakeContainer:
            calls["n"] += 1
            if calls["n"] == 1:
                return created_container
            return restore_container

        fake_client.containers.create.side_effect = create_side_effect

        config = ContainerCreateConfig(image="img", name="test", repo_url="https://x/r.git")
        info = runtime.restore_from_volume("myvol", config)

        assert config.env["RESTORE_FROM_VOLUME"] == "myvol"
        restore_container.start.assert_called_once()
        restore_container.wait.assert_called_once()
        restore_container.remove.assert_called_once()
        assert info.container_id == "c1"

    def test_uses_empty_string_when_no_volume_name(
        self, runtime: DockerRuntime, fake_client: MagicMock, stub_datetime: None
    ) -> None:
        _with_client(runtime, fake_client)
        created_container = FakeContainer(container_id="c1", mounts=[])
        restore_container = FakeContainer(container_id="c2")

        calls = {"n": 0}

        def create_side_effect(*args: Any, **kwargs: Any) -> FakeContainer:
            calls["n"] += 1
            if calls["n"] == 1:
                return created_container
            return restore_container

        fake_client.containers.create.side_effect = create_side_effect
        fake_client.containers.get.return_value = restore_container

        config = ContainerCreateConfig(image="img", name="test", repo_url="https://x/r.git")
        runtime.restore_from_volume("myvol", config)

        restore_create_kwargs = fake_client.containers.create.call_args.kwargs
        assert restore_create_kwargs["volumes"][""] == {"bind": "/dest", "mode": "rw"}


class TestPullImage:
    def test_delegates(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        runtime.pull_image("python:3.11")
        fake_client.images.pull.assert_called_once_with("python:3.11")


class TestBuildImage:
    def test_returns_image_id(self, runtime: DockerRuntime, fake_client: MagicMock) -> None:
        _with_client(runtime, fake_client)
        fake_image = FakeImage(image_id="sha256:deadbeef")
        fake_client.images.build.return_value = (fake_image, iter([]))
        result = runtime.build_image("/ctx", "tag:latest")
        assert result == "sha256:deadbeef"
        build_kwargs = fake_client.images.build.call_args.kwargs
        assert build_kwargs["path"] == "/ctx"
        assert build_kwargs["tag"] == "tag:latest"
        assert build_kwargs["dockerfile"] == "Dockerfile"
        assert build_kwargs["rm"] is True


class TestToInfo:
    def test_running_status(self, runtime: DockerRuntime, stub_datetime: None) -> None:
        container = FakeContainer(status="running")
        info = runtime._to_info(container)
        assert info.status == ContainerStatus.RUNNING

    @pytest.mark.parametrize("status_str", ["exited", "stopped", "created", "paused"])
    def test_stopped_statuses(
        self, runtime: DockerRuntime, status_str: str, stub_datetime: None
    ) -> None:
        container = FakeContainer(status=status_str)
        info = runtime._to_info(container)
        assert info.status == ContainerStatus.STOPPED

    def test_unknown_status_maps_to_missing(
        self, runtime: DockerRuntime, stub_datetime: None
    ) -> None:
        container = FakeContainer(status="dead")
        info = runtime._to_info(container)
        assert info.status == ContainerStatus.MISSING

    def test_labels_none_defaults_to_empty_dict(
        self, runtime: DockerRuntime, stub_datetime: None
    ) -> None:
        container = FakeContainer(labels=None)
        info = runtime._to_info(container)
        assert info.labels == {}

    def test_volume_name_found_in_mounts(self, runtime: DockerRuntime, stub_datetime: None) -> None:
        container = FakeContainer(
            mounts=[
                {"Destination": "/other", "Name": "other-vol"},
                {"Destination": "/workspace", "Name": "found-vol"},
            ]
        )
        info = runtime._to_info(container)
        assert info.volume_name == "found-vol"

    def test_volume_name_none_when_not_found(
        self, runtime: DockerRuntime, stub_datetime: None
    ) -> None:
        container = FakeContainer(mounts=[{"Destination": "/other", "Name": "other-vol"}])
        info = runtime._to_info(container)
        assert info.volume_name is None

    def test_image_uses_first_tag_when_present(
        self, runtime: DockerRuntime, stub_datetime: None
    ) -> None:
        container = FakeContainer(image=FakeImage(tags=["python:3.11", "python:latest"]))
        info = runtime._to_info(container)
        assert info.image == "python:3.11"

    def test_image_uses_truncated_id_when_no_tags(
        self, runtime: DockerRuntime, stub_datetime: None
    ) -> None:
        container = FakeContainer(image=FakeImage(tags=[], image_id="sha256:abcdef1234567890"))
        info = runtime._to_info(container)
        assert info.image == "sha256:abcdef123456"

    def test_created_iso_string_raises_typeerror(self, runtime: DockerRuntime) -> None:
        # Confirms a real pre-existing bug: docker SDK's `attrs["Created"]` is an
        # ISO-8601 *string* in production (e.g. "2021-01-01T00:00:00.123456789Z"),
        # so `container.attrs["Created"][:19]` yields a 19-char string, and
        # `datetime.fromtimestamp(str, tz=UTC)` requires a number, raising TypeError.
        # `_to_info` is unconditionally broken against real Docker SDK containers.
        container = FakeContainer(created="2021-01-01T00:00:00.123456789Z")
        with pytest.raises(TypeError):
            runtime._to_info(container)
