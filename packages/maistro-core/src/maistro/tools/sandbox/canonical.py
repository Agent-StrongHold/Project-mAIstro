"""Compatibility-shaped adapter backed only by ``maistro.sandbox``.

The MCP tools historically exposed a Docker-shaped object. Keeping that small
surface avoids changing callers while ensuring creation, execution and cleanup
all pass through the canonical selector and policy authority.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from maistro.config.settings import SandboxSettings
from maistro.sandbox import UNTRUSTED_CODE, SandboxInstance, SandboxProtocol, build_selector
from maistro.sandbox.network import DENY_ALL, EgressMode
from maistro.sandbox.policy import WorkloadPolicy
from maistro.sandbox.selector import NoSuitableBackendError
from maistro.security.dangerous_tools import is_dangerous_command
from maistro.tools.sandbox.microvm import _parse_mib
from maistro.tools.sandbox.workspace import CONTAINER_WORKSPACE, ensure_workspace


class CanonicalSandboxContainer:
    """Legacy command/file facade over one selected canonical backend."""

    def __init__(
        self,
        backend: SandboxProtocol,
        instance: SandboxInstance,
        workspace_host: str,
        ttl: int,
    ) -> None:
        self._backend = backend
        self._instance = instance
        self.workspace_host = workspace_host
        self.created_at = time.monotonic()
        self.ttl = ttl

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created_at > self.ttl

    async def __aenter__(self) -> CanonicalSandboxContainer:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        dangers = is_dangerous_command(command)
        if dangers:
            return 1, f"Command blocked by safety filter: {', '.join(dangers[:3])}"
        result = await self._backend.exec(
            self._instance,
            ["/bin/bash", "-lc", command],
            timeout_s=timeout,
        )
        output = result.stdout + result.stderr
        return result.exit_code, output

    @staticmethod
    def _safe_path(workspace: str, path: str) -> str:
        if workspace != CONTAINER_WORKSPACE:
            raise ValueError("canonical sandbox paths must use /workspace")
        if Path(path).is_absolute():
            raise ValueError(f"Absolute paths are not allowed: {path}")
        normalized = Path(path)
        if normalized == Path("..") or ".." in normalized.parts:
            raise ValueError(f"Path traversal detected: {path}")
        return f"{workspace}/{normalized.as_posix()}"

    async def read_file(self, path: str) -> str:
        safe = self._safe_path(CONTAINER_WORKSPACE, path)
        content = await self._backend.read_file(self._instance, safe)
        return content.decode(errors="replace")

    async def write_file(self, path: str, content: str) -> None:
        safe = self._safe_path(CONTAINER_WORKSPACE, path)
        await self._backend.write_file(self._instance, safe, content.encode())

    async def destroy(self) -> None:
        await self._backend.destroy(self._instance)


async def create_sandbox(
    workspace: str,
    settings: SandboxSettings | None = None,
    *,
    ttl: int | None = None,
    env: dict[str, str] | None = None,
    policy: WorkloadPolicy = UNTRUSTED_CODE,
) -> CanonicalSandboxContainer:
    """Create through canonical policy; settings may tighten, never grant egress."""
    overrides: dict[str, int] = {}
    if settings is not None:
        if settings.network_disabled:
            policy = replace(policy, egress=DENY_ALL)
        elif policy.egress.mode is EgressMode.DENY:
            raise ValueError("network access requires an explicit policy egress grant")
        overrides = {"memory_mb": _parse_mib(settings.memory_limit), "timeout_s": settings.timeout}
    host_path = ensure_workspace(workspace)
    selector = build_selector()
    _tier, backend = selector.select(policy)
    config = selector.build_config(policy, **overrides)
    config = replace(
        config,
        workspace_host=str(host_path),
        image=settings.image if settings is not None else config.image,
        cpu_cores=settings.cpu_count if settings is not None else config.cpu_cores,
        env=dict(env or {}),
    )
    instance = await backend.spawn(config=config)
    effective_ttl = settings.timeout if settings is not None else (ttl or 3600)
    return CanonicalSandboxContainer(backend, instance, str(host_path), effective_ttl)


__all__ = ["CanonicalSandboxContainer", "NoSuitableBackendError", "create_sandbox"]
