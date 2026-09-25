"""Legacy sandbox seam — now a facade over the one canonical authority (#18).

This module used to be a second sandbox launcher: it hand-assembled its own
``docker run`` argv, re-added capability bits after dropping every capability
from the container, ran the image's default user (often root), gated
networking on a settings boolean instead of a policy grant, and never touched
the selector/policy/egress machinery of :mod:`maistro.sandbox`.
``scripts/check-sandbox-authority.py`` now pins that it stays a facade: every
policy-shaped decision below belongs to ``maistro.sandbox``; this module only
translates the legacy call signature.

What callers get, in canonical terms:

- **Selection** goes through ``build_selector().select(policy)`` — the same
  fail-closed ladder every other consumer climbs. There is no fallback
  launcher here; if no registered backend meets the policy, ``create_sandbox``
  raises :class:`NoSuitableBackendError` and the caller fails closed.
- **Trust class** is stated honestly: the workloads that reach this seam
  (evolve benchmark candidates, RSI development cycles) are model-generated
  and unattended, so the policy is ``min_tier="vm"`` with the AUTONOMOUS mode
  floor (ADR-093 decision 6). On a container-only host that is a refusal —
  the same honest downgrade the conductor adapter documents. The retired
  launcher "succeeded" there by running a container it called a sandbox;
  a container is not a VM boundary and the ladder no longer pretends it is.
- **Egress** is the policy's grant, not a launcher flag: default-deny (#77).
  ``SandboxSettings.network_disabled`` keeps its meaning (the default,
  ``True``, is denied); ``False`` is an explicit operator opt-in that becomes
  an audited ``EgressGrant(mode=HOST, reason=...)``, mirroring the conductor
  adapter's ``allow_network`` mapping.
- **Environment** is exactly the caller's explicit dict; canonical backends
  start from a cleared environment, so ambient host credentials cannot leak
  into the sandbox (#78).
- **No launcher knobs**: ``SandboxSettings.image`` is no longer
  caller-selectable through this seam (the registered backend owns its
  image, per-call launcher flags were the retired vulnerability surface),
  and ``cpu_count`` crosses as the config's ``cpu_cores`` default ceiling.

Resource limits and timeouts cross as policy ceilings and are clamped by
``SandboxSelector.build_config``; output capture is bounded by the canonical
capture machinery (#1197); the workspace must be an authorized host root and
is mounted read/write only at ``/work`` as a fixed non-root uid (#1198).
"""

from __future__ import annotations

import time
from typing import Any

from maistro.config.settings import SandboxSettings
from maistro.sandbox import (
    DENY_ALL,
    EgressGrant,
    EgressMode,
    ExecutionMode,
    NoSuitableBackendError,
    SandboxInstance,
    WorkloadPolicy,
    build_selector,
)
from maistro.sandbox.paths import validate_host_root
from maistro.security.dangerous_tools import is_dangerous_command


def _memory_limit_mb(memory_limit: str) -> int:
    """Parse a docker-style memory string ('512m', '1g') into whole MiB."""
    text = memory_limit.strip().lower()
    if text.endswith("g"):
        return int(float(text[:-1]) * 1024)
    if text.endswith("m"):
        return int(float(text[:-1]))
    if text.endswith("k"):
        return max(1, int(float(text[:-1]) / 1024))
    return max(1, int(float(text)) // (1024 * 1024))  # bare bytes


class SandboxContainer:
    """Legacy handle shape (``exec``/``read_file``/``write_file``/``destroy``).

    Wraps one canonical ``SandboxInstance`` behind its protocol backend. The
    string-command ``exec`` is translated to an argv command; path containment
    and env/egress policy are enforced by the backend, not here.
    """

    def __init__(self, backend: Any, instance: SandboxInstance, *, ttl: int = 3600) -> None:
        self._backend = backend
        self._instance = instance
        self._created = time.monotonic()
        self.ttl = ttl

    @property
    def expired(self) -> bool:
        """Check if sandbox has exceeded its TTL."""
        return (time.monotonic() - self._created) > self.ttl

    async def __aenter__(self) -> SandboxContainer:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        """Execute a command in the sandbox. Returns (exit_code, output)."""
        dangers = is_dangerous_command(command)
        if dangers:
            return 1, f"Command blocked by safety filter: {', '.join(dangers[:3])}"
        result = await self._backend.exec(
            self._instance,
            ["/bin/sh", "-c", command],
            timeout_s=timeout,
        )
        return result.exit_code, result.stdout + result.stderr

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox workspace (backend-enforced containment)."""
        content: bytes = await self._backend.read_file(self._instance, path)
        return content.decode("utf-8", errors="replace")

    async def write_file(self, path: str, content: str) -> None:
        """Write a file into the sandbox workspace (backend-enforced containment)."""
        await self._backend.write_file(self._instance, path, content.encode())

    async def destroy(self) -> None:
        """Tear the sandbox down (idempotent, per the canonical protocol)."""
        await self._backend.destroy(self._instance)


async def create_sandbox(
    workspace: str,
    settings: SandboxSettings | None = None,
    env: dict[str, str] | None = None,
) -> SandboxContainer:
    """Create a sandbox through the one selector/policy authority.

    Raises :class:`NoSuitableBackendError` when no registered backend meets
    the unattended/untrusted floor — that refusal is the product behaving
    correctly on a host without a Tier-2 backend, not a failure of this seam.
    """
    settings = settings or SandboxSettings()

    # The workspace must be an authorized host root (#1198); the backend mounts
    # it (and only it) read/write. Denied roots raise here, before selection.
    authorized = validate_host_root(workspace, create=True)

    if settings.network_disabled:
        egress = DENY_ALL
    else:
        egress = EgressGrant(
            mode=EgressMode.HOST,
            reason="operator set SandboxSettings.network_disabled=False on the "
            "legacy sandbox seam; explicit egress opt-in (ADR-093 decision 3)",
        )
    policy = WorkloadPolicy(
        min_tier="vm",
        network_allowed=not settings.network_disabled,
        max_memory_mb=_memory_limit_mb(settings.memory_limit),
        max_timeout_s=settings.timeout,
        reason="legacy sandbox seam runs model-generated, unattended code "
        "(evolve candidates, RSI dev cycles); ADR-093 decision 6",
        mode=ExecutionMode.AUTONOMOUS,
        untrusted=True,
        egress=egress,
    )

    selector = build_selector()
    _tier, backend = selector.select(policy)
    config = selector.build_config(
        policy,
        writable_paths=[str(authorized)],
        env=dict(env or {}),
    )
    instance = await backend.spawn(config=config)
    return SandboxContainer(backend, instance, ttl=settings.timeout)


__all__ = [
    "NoSuitableBackendError",
    "SandboxContainer",
    "create_sandbox",
]
