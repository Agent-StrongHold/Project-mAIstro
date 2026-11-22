"""Build a selector from what the host actually has (ADR-093, #76).

Registration used to be the caller's job, and no shipped caller did it — the
subsystem had a selector, a policy ladder and one fake backend, and nothing
assembled them. A ladder nobody climbs cannot fail closed, because it is never
consulted.

This is the assembly step: probe the host, register the real backends it
evidenced, and hand back a selector whose `strongest_tier` is a measurement
rather than a claim.

The fake is opt-in and never automatic. `allow_fake=True` is what a unit test
or an explicitly-dev-mode process passes, and the resulting selector satisfies
`DEV_ONLY` and nothing above it. A host with no real backend and no opt-in gets
a selector that refuses every workload, which is the intended reading of
ADR-093's "fail closed: if none of the above is present, refuse to execute.
There is no bare-subprocess tier."
"""

from __future__ import annotations

import logging

from maistro.sandbox.detect import HostCapabilities, detect_host_capabilities
from maistro.sandbox.protocol import SandboxConfig
from maistro.sandbox.selector import SandboxSelector

logger = logging.getLogger("maistro.sandbox.wiring")


def build_selector(
    *,
    capabilities: HostCapabilities | None = None,
    allow_fake: bool = False,
    sandbox_config: SandboxConfig | None = None,
) -> SandboxSelector:
    """Assemble a selector for this host.

    `capabilities` is injectable so the assembly can be tested against hosts
    this machine is not — the interesting cases are a KVM host, a gVisor host
    and a bare one, and no single runner is all three.

    `sandbox_config` is the config execution will run under, forwarded to
    detection when `capabilities` is not injected (#1328): the Tier-3 probe
    budgets itself with it, so the tier it evidences is one *that* config can
    reproduce at spawn. A host that fits the default `max_processes=128`
    budget but not a configured `max_processes=1` answers "no" — here, before
    a workload is placed — instead of failing EAGAIN at spawn after the policy
    check believed it had a boundary.
    """
    caps = capabilities if capabilities is not None else detect_host_capabilities(sandbox_config)
    selector = SandboxSelector()

    if caps.supports("bubblewrap"):
        from maistro.sandbox.backends.bubblewrap import (
            BubblewrapSandboxBackend,
            BubblewrapUnavailableError,
        )

        try:
            selector.register("bubblewrap", BubblewrapSandboxBackend())
        except BubblewrapUnavailableError:
            # Detection said yes and construction disagreed: the binary went
            # away between probe and build, or is on PATH but not executable.
            # Believe the construction, and leave the tier unregistered.
            logger.warning("sandbox_backend_unavailable tier=bubblewrap despite detection")

    if allow_fake:
        from maistro.sandbox.backends.fake import FakeSandboxBackend

        selector.register("fake", FakeSandboxBackend())

    if not selector.available_tiers:
        logger.warning(
            "sandbox_no_backends host_notes=%s — every workload will be refused",
            "; ".join(f"{tier}: {why}" for tier, why in sorted(caps.notes.items())),
        )
    return selector


__all__ = ["build_selector"]
