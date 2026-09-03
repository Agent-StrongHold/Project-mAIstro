"""Architecture-smoke tests for Hive adapter/port ownership."""

from __future__ import annotations

from contextlib import AbstractContextManager


def test_adapter_package_exports_owned_public_ports() -> None:
    import adapters

    assert adapters.__all__ == [
        "LocalTaskBackend",
        "MaistroServerTaskBackend",
        "NoopTelemetry",
        "TaskBackend",
        "TaskRecord",
    ]


def test_noop_telemetry_exposes_noop_context_managers() -> None:
    from adapters.telemetry_noop import NoopTelemetry

    telemetry = NoopTelemetry()
    trace_ctx = telemetry.trace(name="unit")
    generation_ctx = telemetry.generation(model="stub")

    assert isinstance(trace_ctx, AbstractContextManager)
    assert isinstance(generation_ctx, AbstractContextManager)
    with trace_ctx as trace_value, generation_ctx as generation_value:
        assert trace_value is None
        assert generation_value is None


def test_task_backend_protocol_defines_expected_boundary_methods() -> None:
    from adapters.task_backend import TaskBackend

    expected = {"submit", "get", "list_tasks", "cancel", "iter_events", "stop"}
    assert expected.issubset(set(TaskBackend.__dict__))


def test_privilege_middleware_currently_passes_through() -> None:
    from middleware.privilege import PrivilegeMiddleware

    assert PrivilegeMiddleware.__doc__ is not None
    assert "privilege checks" in PrivilegeMiddleware.__doc__


def test_both_telemetry_backends_satisfy_the_port() -> None:
    """The port is the seam; both backends present it (#63).

    Explicit Protocol subclassing checks conformance at class creation, and
    runtime-checkable isinstance is the same fact restated for a reader of the
    wiring — an offline deployment and a traced one hold the same boundary.
    """
    from adapters.telemetry_langfuse import LangfuseTelemetry
    from adapters.telemetry_noop import NoopTelemetry
    from protocols.telemetry import TelemetryPort

    assert isinstance(NoopTelemetry(), TelemetryPort)
    assert isinstance(LangfuseTelemetry(), TelemetryPort)


def test_the_chat_path_holds_the_telemetry_port_not_the_backend() -> None:
    """`chat_completion` composes through the port singleton, so the backend
    is chosen in the adapter, not at every span call site."""
    from adapters import telemetry_langfuse
    from services import chat_completion

    assert chat_completion.telemetry is telemetry_langfuse.telemetry
    assert callable(chat_completion.telemetry.trace)
    assert callable(chat_completion.telemetry.generation)


def test_the_engine_holds_the_agent_port_and_checks_it() -> None:
    """`_bind_agent_port` is the one assignment point and it verifies the
    port contract, so neither the bridge nor the stub can drift from it
    silently (#63)."""
    from adapters.maistro_core import StubAgentPort
    from protocols.agent import AgentPort
    from services.engine import EngineService

    engine = EngineService()
    engine._bind_agent_port(StubAgentPort())
    assert isinstance(engine._agent_port, AgentPort)

    class _NotAPort:
        pass

    import pytest

    with pytest.raises(TypeError, match="does not satisfy AgentPort"):
        engine._bind_agent_port(_NotAPort())  # type: ignore[arg-type]
