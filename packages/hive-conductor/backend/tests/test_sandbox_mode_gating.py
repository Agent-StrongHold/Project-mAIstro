"""ADR-093 decisions 5-6 through the one canonical authority (#18).

These tests used to pin a private ladder: `hyperlight_executor` carried its own
tier integers, its own backend probes and five private launchers, and "gVisor
on PATH" meant unattended execution was allowed. The support matrix calls that
tier "detected, not implemented" — no gVisor backend exists behind the
canonical protocol — so what is pinned now is the honest refusal:

1. The strongest *registered* backend wins, per the canonical ladder.
2. Unattended execution on a host whose best backend is below the `gvisor`
   floor refuses (fail-closed result), whatever binaries sit on PATH.
3. Supervised execution proceeds on that same host.
4. Unknown modes get the unattended (stricter) floor — default deny.
5. A tier that is detected but has no shipped backend is a refusal, not a
   downgrade.
6. A host with no backend at all refuses every mode.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.hyperlight_executor import SandboxExecutor

from maistro.sandbox import (
    ExecResult,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
    build_selector,
)
from maistro.sandbox.detect import HostCapabilities


class _StubBackend:
    """A backend that is only its tier declaration and a canned result.

    The selector's contract is the declaration (`TierMismatchError` on a
    mismatched registration); these tests are about which tier gets
    *selected*, so execution itself is a fixed success that records what it
    was handed.
    """

    def __init__(self, tier: str) -> None:
        self.tier = tier
        self.spawned: list[SandboxConfig] = []
        self.destroyed: list[str] = []

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.spawned.append(config)
        return SandboxInstance(
            id=f"stub-{len(self.spawned)}", backend=self.tier, isolation_tier=self.tier
        )

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        return ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=1)

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        raise AssertionError("the adapter has no reason to transfer files")

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        raise AssertionError("the adapter has no reason to transfer files")

    async def destroy(self, instance: SandboxInstance) -> None:
        self.destroyed.append(instance.id)


def _selector_with(*tiers: str) -> SandboxSelector:
    selector = SandboxSelector()
    for tier in tiers:
        selector.register(tier, _StubBackend(tier))  # type: ignore[arg-type]
    return selector


def _executor_with(*tiers: str) -> tuple[SandboxExecutor, list[_StubBackend]]:
    backends = [_StubBackend(tier) for tier in tiers]
    selector = SandboxSelector()
    for backend in backends:
        selector.register(backend.tier, backend)  # type: ignore[arg-type]
    return SandboxExecutor(selector=selector), backends


# ─── Fallback ladder order ────────────────────────────────────────────────


def test_the_strongest_registered_tier_wins() -> None:
    ex, _ = _executor_with("bubblewrap", "container")
    assert ex.backend == "container"
    assert ex.tier == "container"
    assert ex.available is True


def test_vm_tiers_outrank_tier_3_when_a_backend_eventually_ships() -> None:
    """The canonical ladder is vm > gvisor > container > bubblewrap."""
    ex, _ = _executor_with("bubblewrap", "vm")
    assert ex.backend == "vm"


# ─── Mode floors ──────────────────────────────────────────────────────────


def test_unattended_refuses_on_a_tier_3_only_host() -> None:
    """Full-auto is blocked when the best registered backend is below gvisor."""
    ex, _ = _executor_with("bubblewrap")
    assert ex.allows_mode("autonomous") is False

    result = asyncio.run(ex.execute_node("print('hi')", mode="autonomous"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"
    assert "REFUSED" in result["error"]


def test_supervised_execution_is_served_on_the_same_host() -> None:
    ex, backends = _executor_with("bubblewrap")
    assert ex.allows_mode("interactive") is True

    result = asyncio.run(ex.execute_node("print('hi')", mode="interactive"))
    assert result["success"] is True
    assert result["isolation"] == "bubblewrap"
    # The adapter owns the lifecycle: a sandbox it spawned is one it destroys.
    assert len(backends[0].destroyed) == 1


def test_a_container_backend_does_not_satisfy_the_unattended_floor() -> None:
    """Container sits between gvisor and bubblewrap — still below the floor."""
    ex, _ = _executor_with("container")
    assert ex.allows_mode("autonomous") is False
    assert ex.allows_mode("interactive") is True


def test_an_unknown_mode_gets_the_unattended_floor() -> None:
    """Default deny: a typo'd or novel mode must not weaken the floor."""
    ex, _ = _executor_with("bubblewrap")
    result = asyncio.run(ex.execute_node("print('hi')", mode="overnight-yolo"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"


# ─── Detected-but-unimplemented tiers refuse honestly ─────────────────────


def test_a_detected_gvisor_without_a_backend_refuses_unattended_execution() -> None:
    """The retired executor allowed unattended code on `runsc`-on-PATH hosts.

    No gVisor backend ships behind the protocol (SANDBOX-SUPPORT-MATRIX.md),
    so a host whose detection reports gvisor registers nothing and the
    selector refuses — the honest answer, not a downgrade to a launcher the
    repository does not maintain.
    """
    capabilities = HostCapabilities(tiers=("gvisor",), notes={})
    ex = SandboxExecutor(selector=build_selector(capabilities=capabilities))

    assert ex.available is False
    assert ex.backend is None
    assert ex.allows_mode("autonomous") is False

    result = asyncio.run(ex.execute_node("print('hi')", mode="autonomous"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"
    assert "REFUSED" in result["error"]


def test_a_host_with_no_backends_refuses_every_mode() -> None:
    ex = SandboxExecutor(selector=SandboxSelector())
    assert ex.available is False
    assert ex.allows_mode("interactive") is False
    assert ex.allows_mode("autonomous") is False

    result = asyncio.run(ex.execute_node("print('hi')", mode="interactive"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"


# ─── The refusal shape is the consumer contract ───────────────────────────


def test_refusal_carries_the_selectors_reason_not_a_generic_no() -> None:
    ex, _ = _executor_with("bubblewrap")
    result: dict[str, Any] = asyncio.run(ex.execute_node("print('hi')"))
    assert "gvisor" in result["error"]
    assert result["duration_ms"] == 0
