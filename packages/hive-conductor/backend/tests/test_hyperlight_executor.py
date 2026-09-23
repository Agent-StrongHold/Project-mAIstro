"""The legacy `execute_node` contract, mapped onto the canonical authority.

`SandboxExecutor` used to be a second sandbox authority with private launchers.
It is now an adapter: policy and selection live in `maistro.sandbox`, and this
suite pins only what the adapter itself owns —

1. the mapping from `allow_network` to an explicit, reasoned `EgressGrant`
   (or default deny) — the old code passed a bare boolean into a private
   launcher and the audit trail said nothing;
2. the sandbox receives exactly the caller's explicit environment, and the
   code reaches the backend as argv data, never templated into a script;
3. `memory_mb`/`timeout_s` arrive as policy ceilings and land on the config
   un-raised;
4. the legacy result dict tells the truth about bounded output (#1197):
   truncation is named, not passed off as complete output;
5. a spawned sandbox is destroyed even when execution raises.
"""

from __future__ import annotations

import asyncio

import pytest
from services.hyperlight_executor import SandboxExecutor

from maistro.sandbox import (
    DENY_ALL,
    EgressMode,
    ExecResult,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
)


class _StubBackend:
    """A bubblewrap-tier backend that records what the adapter handed it."""

    def __init__(self, tier: str = "bubblewrap") -> None:
        self.tier = tier
        self.spawned: list[SandboxConfig] = []
        self.commands: list[list[str]] = []
        self.destroyed: list[str] = []
        self._result = ExecResult(exit_code=0, stdout="ok", stderr="", duration_ms=1)

    def returns(self, result: ExecResult) -> _StubBackend:
        self._result = result
        return self

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        self.spawned.append(config)
        return SandboxInstance(
            id=f"stub-{len(self.spawned)}", backend=self.tier, isolation_tier=self.tier
        )

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        raise AssertionError("the adapter has no reason to transfer files")

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        raise AssertionError("the adapter has no reason to transfer files")

    async def destroy(self, instance: SandboxInstance) -> None:
        self.destroyed.append(instance.id)


def _executor_with(backend: _StubBackend) -> SandboxExecutor:
    selector = SandboxSelector()
    selector.register(backend.tier, backend)  # type: ignore[arg-type]
    return SandboxExecutor(selector=selector, guest_python="/usr/bin/python3")


# ─── Egress conversion (#77) ──────────────────────────────────────────────


def test_allow_network_becomes_an_explicit_reasoned_host_grant() -> None:
    backend = _StubBackend()
    result = asyncio.run(
        _executor_with(backend).execute_node("print('hi')", allow_network=True, mode="interactive")
    )
    assert result["success"] is True
    (config,) = backend.spawned
    assert config.egress.mode is EgressMode.HOST
    assert config.egress.reason  # a grant without a reason cannot be constructed


def test_the_default_is_deny_all_not_a_missing_field() -> None:
    backend = _StubBackend()
    asyncio.run(_executor_with(backend).execute_node("print('hi')", mode="interactive"))
    (config,) = backend.spawned
    assert config.egress == DENY_ALL
    assert config.egress.mode is EgressMode.DENY


# ─── Environment and code cross as data ───────────────────────────────────


def test_the_sandbox_receives_exactly_the_callers_env() -> None:
    backend = _StubBackend()
    asyncio.run(
        _executor_with(backend).execute_node(
            "print('hi')",
            env={"DAG_NODE_TASK": "say hi", "LITELLM_API_KEY": "sk-test"},
            mode="interactive",
        )
    )
    (config,) = backend.spawned
    assert config.env == {"DAG_NODE_TASK": "say hi", "LITELLM_API_KEY": "sk-test"}


def test_memory_and_timeout_ceilings_land_on_the_config() -> None:
    backend = _StubBackend()
    asyncio.run(
        _executor_with(backend).execute_node(
            "print('hi')", memory_mb=333, timeout_s=42, mode="interactive"
        )
    )
    (config,) = backend.spawned
    assert config.memory_mb == 333
    assert config.timeout_s == 42


def test_code_reaches_the_backend_as_argv_not_a_templated_script() -> None:
    backend = _StubBackend()
    asyncio.run(_executor_with(backend).execute_node("print('marker-123')", mode="interactive"))
    (command,) = backend.commands
    assert command == ["/usr/bin/python3", "-c", "print('marker-123')"]


# ─── Result mapping tells the truth about bounded output (#1197) ──────────


def test_a_failed_exit_maps_to_success_false_with_real_streams() -> None:
    backend = _StubBackend().returns(
        ExecResult(exit_code=1, stdout="partial", stderr="boom", duration_ms=2)
    )
    result = asyncio.run(_executor_with(backend).execute_node("print('hi')", mode="interactive"))
    assert result["success"] is False
    assert result["output"] == "partial"
    assert result["error"] == "boom"
    assert result["isolation"] == "bubblewrap"


def test_a_truncated_stream_is_named_not_passed_off_as_complete() -> None:
    backend = _StubBackend().returns(
        ExecResult(
            exit_code=125,
            stdout="prefix",
            stderr="",
            duration_ms=5,
            output_limit_exceeded=True,
            stdout_truncated=True,
            stdout_bytes_retained=6,
        )
    )
    result = asyncio.run(_executor_with(backend).execute_node("print('hi')", mode="interactive"))
    assert result["success"] is False
    assert "output limit exceeded" in result["error"]


def test_a_timeout_maps_to_the_legacy_timeout_result() -> None:
    backend = _StubBackend().returns(
        ExecResult(exit_code=124, stdout="", stderr="", duration_ms=1000, timed_out=True)
    )
    result = asyncio.run(_executor_with(backend).execute_node("print('hi')", mode="interactive"))
    assert result == {
        "output": "",
        "error": "timeout",
        "success": False,
        "isolation": "bubblewrap",
        "duration_ms": 1000,
    }


# ─── Lifecycle ────────────────────────────────────────────────────────────


def test_a_sandbox_is_destroyed_even_when_execution_raises() -> None:
    backend = _StubBackend().returns(RuntimeError("backend exploded"))
    with pytest.raises(RuntimeError, match="backend exploded"):
        asyncio.run(_executor_with(backend).execute_node("print('hi')", mode="interactive"))
    assert len(backend.destroyed) == 1


# ─── Fail-closed shape ────────────────────────────────────────────────────


def test_fail_closed_shape_through_a_selector_that_refuses() -> None:
    """The contract `legacy_dag_node` branches on when nothing qualifies."""
    ex = SandboxExecutor(selector=SandboxSelector())
    result = asyncio.run(ex.execute_node("print('hi')"))
    assert result["success"] is False
    assert result["isolation"] == "fail-closed"
    assert result["error"].startswith("REFUSED")
    assert "duration_ms" in result
