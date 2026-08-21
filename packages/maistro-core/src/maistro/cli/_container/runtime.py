"""Container runtime protocol and types.

Defines the abstract interface for container operations (Docker, Podman, etc.)
so the CLI is runtime-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ContainerStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    ARCHIVED = "archived"
    MISSING = "missing"


@dataclass(frozen=True)
class ContainerInfo:
    container_id: str
    name: str
    image: str
    status: ContainerStatus
    created: datetime
    ports: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    volume_name: str | None = None

    @property
    def short_id(self) -> str:
        return self.container_id[:12]


@dataclass
class ContainerCreateConfig:
    image: str
    name: str
    repo_url: str
    repo_mount_path: str = "/workspace"
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    ttl_hours: int = 72

    @property
    def ttl_label(self) -> str:
        return f"maistro.ttl={self.ttl_hours}"


@runtime_checkable
class ContainerRuntime(Protocol):
    """Abstract container runtime interface.

    Implemented by DockerRuntime, PodmanRuntime, etc.
    """

    def create(self, config: ContainerCreateConfig) -> ContainerInfo: ...
    def start(self, container_id: str) -> ContainerInfo: ...
    def stop(self, container_id: str) -> ContainerInfo: ...
    def remove(self, container_id: str, *, force: bool = False) -> None: ...
    def inspect(self, container_id: str) -> ContainerInfo: ...
    def list_containers(
        self, *, label_filter: dict[str, str] | None = None
    ) -> list[ContainerInfo]: ...
    def create_volume(self, name: str, labels: dict[str, str] | None = None) -> str: ...
    def remove_volume(self, name: str) -> None: ...
    def archive_to_volume(self, container_id: str, volume_name: str) -> str: ...
    def restore_from_volume(
        self, volume_name: str, config: ContainerCreateConfig
    ) -> ContainerInfo: ...
    def pull_image(self, image: str) -> None: ...
    def build_image(self, context_path: str, tag: str, dockerfile: str = "Dockerfile") -> str: ...
    def is_available(self) -> bool: ...


def detect_runtime() -> ContainerRuntime:
    """Auto-detect the best available container runtime."""
    from maistro.cli._container.docker_runtime import DockerRuntime

    docker = DockerRuntime()
    if docker.is_available():
        return docker

    from maistro.cli._container.podman_runtime import PodmanRuntime

    podman = PodmanRuntime()
    if podman.is_available():
        return podman

    raise RuntimeError(
        "No container runtime found. Install Docker or Podman and ensure the daemon is running."
    )
