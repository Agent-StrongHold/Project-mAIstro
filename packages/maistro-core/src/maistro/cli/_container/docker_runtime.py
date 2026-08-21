"""Docker runtime implementation via the docker Python SDK."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from maistro.cli._container.runtime import (
    ContainerCreateConfig,
    ContainerInfo,
    ContainerStatus,
)

logger = logging.getLogger(__name__)

_MAISTRO_LABEL = "maistro.managed"
_MAISTRO_SESSION_LABEL = "maistro.session"
_MAISTRO_TTL_LABEL = "maistro.ttl"


class DockerRuntime:
    """ContainerRuntime implementation using the Docker SDK."""

    def __init__(self) -> None:
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import docker  # type: ignore[import-untyped]  # docker SDK ships no py.typed marker

            self._client = docker.from_env()
        return self._client

    def is_available(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def create(self, config: ContainerCreateConfig) -> ContainerInfo:
        labels = dict(config.labels)
        labels[_MAISTRO_LABEL] = "true"
        labels[_MAISTRO_SESSION_LABEL] = config.name
        labels[_MAISTRO_TTL_LABEL] = str(config.ttl_hours)
        labels["maistro.repo_url"] = config.repo_url

        volume_name = f"maistro-{config.name}"
        self.client.volumes.create(name=volume_name, labels=labels)

        container = self.client.containers.create(
            image=config.image,
            name=f"maistro-{config.name}",
            labels=labels,
            environment=config.env,
            volumes={
                volume_name: {"bind": config.repo_mount_path, "mode": "rw"},
            },
            working_dir=config.repo_mount_path,
            stdin_open=True,
            tty=True,
            detach=True,
            command=["sleep", "infinity"],
        )

        return self._to_info(container)

    def start(self, container_id: str) -> ContainerInfo:
        container = self.client.containers.get(container_id)
        container.start()
        container.reload()
        return self._to_info(container)

    def stop(self, container_id: str) -> ContainerInfo:
        container = self.client.containers.get(container_id)
        container.stop(timeout=10)
        container.reload()
        return self._to_info(container)

    def remove(self, container_id: str, *, force: bool = False) -> None:
        container = self.client.containers.get(container_id)
        container.remove(force=force)

    def inspect(self, container_id: str) -> ContainerInfo:
        container = self.client.containers.get(container_id)
        return self._to_info(container)

    def list_containers(self, *, label_filter: dict[str, str] | None = None) -> list[ContainerInfo]:
        filters: dict[str, Any] = {"all": True}
        if label_filter:
            filters["label"] = [f"{k}={v}" for k, v in label_filter.items()]
        else:
            filters["label"] = [f"{_MAISTRO_LABEL}=true"]

        containers = self.client.containers.list(filters=filters)
        return [self._to_info(c) for c in containers]

    def create_volume(self, name: str, labels: dict[str, str] | None = None) -> str:
        vol_labels: dict[str, str] = {_MAISTRO_LABEL: "true"}
        if labels:
            vol_labels.update(labels)
        self.client.volumes.create(name=name, labels=vol_labels)
        return name

    def remove_volume(self, name: str) -> None:
        try:
            volume = self.client.volumes.get(name)
            volume.remove()
        except Exception:
            logger.warning("Volume %s not found or already removed", name)

    def archive_to_volume(self, container_id: str, volume_name: str) -> str:
        container = self.client.containers.get(container_id)
        archive_name = f"maistro-archive-{container.name}"

        self.client.containers.create(
            image="busybox",
            name=archive_name,
            volumes={volume_name: {"bind": "/archive", "mode": "rw"}},
            command=["sh", "-c", "cp -a /workspace/. /archive/ 2>/dev/null || true"],
        )
        archive_container = self.client.containers.get(archive_name)
        archive_container.start()
        archive_container.wait()
        archive_container.remove()

        container.remove()
        return volume_name

    def restore_from_volume(self, volume_name: str, config: ContainerCreateConfig) -> ContainerInfo:
        config.env["RESTORE_FROM_VOLUME"] = volume_name
        info = self.create(config)

        restore_container = self.client.containers.create(
            image="busybox",
            name=f"maistro-restore-{config.name}",
            volumes={
                volume_name: {"bind": "/source", "mode": "ro"},
                info.volume_name or "": {"bind": "/dest", "mode": "rw"},
            },
            command=["sh", "-c", "cp -a /source/. /dest/ 2>/dev/null || true"],
        )
        restore_container.start()
        restore_container.wait()
        restore_container.remove()

        return info

    def pull_image(self, image: str) -> None:
        self.client.images.pull(image)

    def build_image(self, context_path: str, tag: str, dockerfile: str = "Dockerfile") -> str:
        image, _ = self.client.images.build(
            path=context_path, tag=tag, dockerfile=dockerfile, rm=True
        )
        return str(image.id)

    def _to_info(self, container: Any) -> ContainerInfo:
        status_str = container.status.lower()
        if status_str == "running":
            status = ContainerStatus.RUNNING
        elif status_str in ("exited", "stopped", "created", "paused"):
            status = ContainerStatus.STOPPED
        else:
            status = ContainerStatus.MISSING

        labels = container.labels or {}
        created = datetime.fromtimestamp(container.attrs["Created"][:19], tz=UTC)

        volume_name: str | None = None
        mounts = container.attrs.get("Mounts", [])
        for mount in mounts:
            if mount.get("Destination") == "/workspace":
                volume_name = mount.get("Name")
                break

        return ContainerInfo(
            container_id=container.id,
            name=container.name,
            image=str(container.image.tags[0])
            if container.image.tags
            else str(container.image.id[:19]),
            status=status,
            created=created,
            labels=labels,
            volume_name=volume_name,
        )
