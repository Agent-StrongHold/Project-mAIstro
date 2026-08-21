"""Builder session lifecycle — create, stop, archive, resume, prune.

Manages the lifecycle of builder dev containers:
  running → stopped → archived (volume only)
                 ↑        │
                 └─resume─┘

Sessions older than their TTL (default 72h) are automatically pruned.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from maistro.cli._container.runtime import (
    ContainerCreateConfig,
    ContainerInfo,
    ContainerRuntime,
    ContainerStatus,
)

logger = logging.getLogger(__name__)

_LABEL_SESSION = "maistro.session"
_LABEL_REPO = "maistro.repo_url"
_LABEL_TASK = "maistro.task"
_LABEL_TTL = "maistro.ttl"
_LABEL_CREATED = "maistro.created_ts"

_BUILDERS_IMAGE = "maistro-builders:latest"


class SessionLifecycle:
    """Manages builder session container lifecycle."""

    def __init__(self, runtime: ContainerRuntime | None = None) -> None:
        self._runtime = runtime

    @property
    def runtime(self) -> ContainerRuntime:
        if self._runtime is None:
            from maistro.cli._container.runtime import detect_runtime

            self._runtime = detect_runtime()
        return self._runtime

    def create_session(
        self,
        *,
        session_id: str,
        repo_url: str,
        task: str = "",
        ttl_hours: int = 72,
        image: str = _BUILDERS_IMAGE,
        env: dict[str, str] | None = None,
    ) -> ContainerInfo:
        labels = {
            _LABEL_SESSION: session_id,
            _LABEL_REPO: repo_url,
            _LABEL_TASK: task[:200],
            _LABEL_TTL: str(ttl_hours),
            _LABEL_CREATED: str(datetime.now(UTC).timestamp()),
        }

        config = ContainerCreateConfig(
            image=image,
            name=session_id,
            repo_url=repo_url,
            env=env or {},
            labels=labels,
            ttl_hours=ttl_hours,
        )

        info = self.runtime.create(config)
        self.runtime.start(info.container_id)

        logger.info("created session %s (container %s)", session_id, info.short_id)
        return self.runtime.inspect(info.container_id)

    def resume_session(self, session_id: str) -> ContainerInfo:
        info = self._get_by_name(session_id)

        if info.status == ContainerStatus.RUNNING:
            return info

        if info.status == ContainerStatus.STOPPED:
            return self.runtime.start(info.container_id)

        if info.status == ContainerStatus.ARCHIVED:
            return self._restore_archived(session_id)

        raise ValueError(f"session {session_id} not found")

    def stop_session(self, session_id: str) -> ContainerInfo:
        info = self._get_by_name(session_id)
        if info.status == ContainerStatus.RUNNING:
            return self.runtime.stop(info.container_id)
        return info

    def archive_session(self, session_id: str) -> str:
        info = self._get_by_name(session_id)

        if info.status == ContainerStatus.RUNNING:
            self.runtime.stop(info.container_id)

        volume_name = info.volume_name or f"maistro-{session_id}"
        if info.status != ContainerStatus.ARCHIVED:
            self.runtime.archive_to_volume(info.container_id, volume_name)

        return volume_name

    def prune_sessions(self, *, max_age_hours: int = 168) -> list[str]:
        pruned: list[str] = []
        now = datetime.now(UTC)

        for info in self.list_sessions():
            if info.status != ContainerStatus.STOPPED:
                continue

            created_ts = info.labels.get(_LABEL_CREATED, "")
            if not created_ts:
                continue

            try:
                created = datetime.fromtimestamp(float(created_ts), tz=UTC)
            except (ValueError, OSError):
                continue

            age_hours = (now - created).total_seconds() / 3600
            if age_hours > max_age_hours:
                self.archive_session(info.name)
                pruned.append(info.name)

        return pruned

    def list_sessions(self) -> list[ContainerInfo]:
        return self.runtime.list_containers()

    def get_session(self, session_id: str) -> ContainerInfo | None:
        try:
            return self._get_by_name(session_id)
        except ValueError:
            return None

    def _get_by_name(self, session_id: str) -> ContainerInfo:
        containers = self.runtime.list_containers(label_filter={_LABEL_SESSION: session_id})
        if not containers:
            raise ValueError(f"session {session_id} not found")
        return containers[0]

    def _restore_archived(self, session_id: str) -> ContainerInfo:
        volume_name = f"maistro-{session_id}"

        config = ContainerCreateConfig(
            image=_BUILDERS_IMAGE,
            name=session_id,
            repo_url="restored",
        )

        info = self.runtime.restore_from_volume(volume_name, config)
        self.runtime.start(info.container_id)
        return self.runtime.inspect(info.container_id)

    @staticmethod
    def make_session_id(repo_url: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9-]", "-", repo_url.split("/")[-1].replace(".git", ""))
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return f"{slug}-{ts}"
