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
