"""Podman runtime implementation.

Uses the Docker-compatible API exposed by Podman's socket.
Most operations are identical to DockerRuntime; the differences
are in socket discovery and availability checks.
"""

from __future__ import annotations

import os
from typing import Any

from maistro.cli._container.docker_runtime import DockerRuntime


class PodmanRuntime(DockerRuntime):
    """ContainerRuntime via Podman's Docker-compatible socket.

    Podman exposes a Docker-compatible API at:
      - $XDG_RUNTIME_DIR/podman/podman.sock (rootless)
      - /run/podman/podman.sock (rootful)
    """

    def __init__(self) -> None:
        super().__init__()
        self._socket: str | None = None

    @property
    def client(self) -> Any:
        """Bind the SDK client to Podman's socket without touching `os.environ`.

        `DockerRuntime.client` uses `docker.from_env()`, which reads the
        process-wide `DOCKER_HOST`. Setting that variable here — as this class
        used to, inside a mere availability *probe* — silently repoints every
        other Docker consumer in the process for the rest of its lifetime.
        That includes `maistro.tools.sandbox.docker`, which spawns the `docker`
        CLI with an inherited environment, so a probe could send the security
        sandbox at Podman's socket. Binding the endpoint to this instance keeps
        the choice local to the runtime that made it.
        """
        if self._client is None:
            import docker  # type: ignore[import-untyped]  # docker SDK ships no py.typed marker

            sock = self._socket or self._find_socket()
            if sock is None:
                raise RuntimeError("no Podman socket found")
            self._client = docker.DockerClient(base_url=f"unix://{sock}")
        return self._client

    def is_available(self) -> bool:
        sock = self._find_socket()
        if sock is None:
            return False

        self._socket = sock
        try:
            return super().is_available()
        except (
            Exception
        ):  # pragma: no cover — DockerRuntime.is_available() already swallows all exceptions
            return False

    @staticmethod
    def _find_socket() -> str | None:
        candidates = [
            os.path.join(
                os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
                "podman",
                "podman.sock",
            ),
            "/run/podman/podman.sock",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None
