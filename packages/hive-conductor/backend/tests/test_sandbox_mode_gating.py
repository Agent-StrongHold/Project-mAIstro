"""ADR-093 Decisions 5-6: fallback ladder order and execution-mode isolation floors.

1. gVisor outranks bubblewrap/hardened-container in backend selection.
2. Autonomous ("overnight"/full-auto) execution refuses on a shared-kernel-only
   host; interactive execution proceeds on the same host.
3. Unknown modes get the autonomous (stricter) floor — default deny.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _make_executor(monkeypatch: pytest.MonkeyPatch, available: set[str]):
    """Build a SandboxExecutor seeing exactly `available` backends on the host."""
    import services.hyperlight_executor as hx

    monkeypatch.setattr(hx, "_has_hyperlight", lambda: "hyperlight" in available)
    monkeypatch.setattr(hx, "_has_firecracker", lambda: "firecracker" in available)
    monkeypatch.setattr(hx, "_has_gvisor", lambda: "gvisor" in available)
    monkeypatch.setattr(hx, "_has_bubblewrap", lambda: "bubblewrap" in available)
    monkeypatch.setattr(hx, "_has_hardened_container", lambda: "hardened-container" in available)
    return hx.SandboxExecutor()


async def _fake_runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"output": "ok", "error": "", "success": True}


# ─── Fallback ladder order ────────────────────────────────────────────────────


def test_gvisor_outranks_bubblewrap(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make_executor(monkeypatch, {"gvisor", "bubblewrap", "hardened-container"})
    assert ex.backend == "gvisor"


def test_vm_outranks_gvisor(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make_executor(monkeypatch, {"firecracker", "gvisor", "bubblewrap"})
    assert ex.backend == "firecracker"


def test_bubblewrap_outranks_hardened_container(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make_executor(monkeypatch, {"bubblewrap", "hardened-container"})
    assert ex.backend == "bubblewrap"


# ─── Mode floors ──────────────────────────────────────────────────────────────


def test_autonomous_refuses_on_shared_kernel_only_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full-auto is blocked when the best available backend is tier 3."""
    ex = _make_executor(monkeypatch, {"bubblewrap"})
    assert ex.allows_mode("autonomous") is False

    result = asyncio.run(ex.execute_node("print('hi')", mode="autonomous"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"
    assert "REFUSED" in result["error"]


def test_interactive_allowed_on_shared_kernel_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same host still serves a human-supervised session."""
    ex = _make_executor(monkeypatch, {"bubblewrap"})
    assert ex.allows_mode("interactive") is True

    monkeypatch.setattr(ex, "_run_bubblewrap", _fake_runner)
    result = asyncio.run(ex.execute_node("print('hi')", mode="interactive"))
    assert result["success"] is True
    assert result["isolation"] == "bubblewrap"


def test_autonomous_allowed_on_gvisor(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make_executor(monkeypatch, {"gvisor"})
    assert ex.allows_mode("autonomous") is True

    monkeypatch.setattr(ex, "_run_gvisor", _fake_runner)
    result = asyncio.run(ex.execute_node("print('hi')", mode="autonomous"))
    assert result["success"] is True
    assert result["isolation"] == "gvisor"


def test_hardened_container_also_blocks_autonomous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ex = _make_executor(monkeypatch, {"hardened-container"})
    result = asyncio.run(ex.execute_node("print('hi')", mode="autonomous"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"


def test_unknown_mode_gets_autonomous_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default deny: a typo'd or novel mode must not weaken the floor."""
    ex = _make_executor(monkeypatch, {"bubblewrap"})
    result = asyncio.run(ex.execute_node("print('hi')", mode="overnight-yolo"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"


def test_no_backend_refuses_every_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = _make_executor(monkeypatch, set())
    assert ex.available is False
    assert ex.allows_mode("interactive") is False
    assert ex.allows_mode("autonomous") is False

    result = asyncio.run(ex.execute_node("print('hi')", mode="interactive"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"
