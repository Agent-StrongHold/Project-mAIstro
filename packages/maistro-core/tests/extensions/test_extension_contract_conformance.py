"""Conformance suite for the canonical extension contract (#950).

These tests pin the public interface contracts themselves — context surface,
least-authority refusals, configuration scope, service grants, effect seams,
cancellation, and lifecycle error attribution — using throwaway lifecycle
objects defined here, never a shipped reference extension. An implementation
that passes only because one particular extension works cannot pass this
suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.extensions import (
    ConfigurationKeyNotDeclared,
    EffectNotDeclared,
    EffectReceipt,
    ExtensionCancellation,
    ExtensionCancelled,
    ExtensionConfigView,
    ExtensionContext,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionIdentity,
    ExtensionLifecycle,
    ExtensionLifecycleError,
    ExtensionProgress,
    InvocationScope,
    ScopeMismatch,
    ServiceNotGranted,
    UngrantedProgressReporter,
    run_activation,
    run_deactivation,
    run_invocation,
)

pytestmark = pytest.mark.contract("behavioral")

IDENTITY = ExtensionIdentity(extension_id="conformance.probe", version="1.2.3")


def _descriptor(**overrides: Any) -> ExtensionDescriptor:
    fields: dict[str, Any] = {
        "identity": IDENTITY,
        "config_keys": frozenset({"temperature"}),
        "services": frozenset({"clock"}),
        "effects": frozenset({"echo"}),
    }
    fields.update(overrides)
    return ExtensionDescriptor(**fields)


async def _echo_dispatcher(effect_key: str, request: Any) -> Any:
    return EffectReceipt(
        invocation_id="invocation-1",
        binding_id="binding-1",
        capability="probe.echo",
        effect_key=effect_key,
        status="completed",
        result=request,
    )


def _context(**overrides: Any) -> ExtensionContext:
    """A host-built context over a fully granted probe descriptor."""
    fields: dict[str, Any] = {
        "descriptor": _descriptor(),
        "scope": InvocationScope(
            workspace_id="ws-1",
            agent_id="agent-1",
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
        ),
        "config": ExtensionConfigView(
            extension_id=IDENTITY.extension_id,
            declared=frozenset({"temperature"}),
            values={"temperature": 0.7},
        ),
        "cancellation": ExtensionCancellation.from_predicate(lambda: False),
        "progress": UngrantedProgressReporter(IDENTITY.extension_id),
        "services": {"clock": "granted-clock"},
        "dispatch_effect": _echo_dispatcher,
    }
    fields.update(overrides)
    return ExtensionContext(**fields)


class _ProbeLifecycle:
    """First throwaway lifecycle: records hooks, returns a canned result."""

    def __init__(self) -> None:
        self.hooks: list[tuple[str, str]] = []

    async def activate(self, context: ExtensionContext) -> None:
        self.hooks.append(("activate", context.scope.workspace_id))

    async def invoke(self, context: ExtensionContext) -> str:
        self.hooks.append(("invoke", context.scope.attempt_id))
        return "probe-result"

    async def deactivate(self, context: ExtensionContext) -> None:
        self.hooks.append(("deactivate", context.scope.workspace_id))


class _ExplodingLifecycle:
    """Second, independent lifecycle: every hook raises its own error."""

    async def activate(self, context: ExtensionContext) -> None:
        raise RuntimeError("activation boom")

    async def invoke(self, context: ExtensionContext) -> Any:
        raise RuntimeError("invocation boom")

    async def deactivate(self, context: ExtensionContext) -> None:
        raise RuntimeError("deactivation boom")


# ---------------------------------------------------------------------------
# Identity / descriptor / scope validation
# ---------------------------------------------------------------------------


def test_identity_and_descriptor_reject_empty_authority_names() -> None:
    with pytest.raises(ValueError, match="extension id"):
        ExtensionIdentity(extension_id=" ", version="1.0.0")
    with pytest.raises(ValueError, match="extension version"):
        ExtensionIdentity(extension_id="ext", version="")
    with pytest.raises(ValueError, match="config key"):
        _descriptor(config_keys=frozenset({""}))
    with pytest.raises(ValueError, match="service"):
        _descriptor(services=frozenset({"  "}))
    with pytest.raises(ValueError, match="effect"):
        _descriptor(effects=frozenset({""}))


def test_invocation_scope_requires_correlated_execution_ids() -> None:
    InvocationScope(workspace_id="ws-1", agent_id="agent-1")
    InvocationScope(
        workspace_id="ws-1",
        agent_id="agent-1",
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
    )
    with pytest.raises(ScopeMismatch, match="correlated"):
        InvocationScope(workspace_id="ws-1", agent_id="agent-1", run_id="run-1")
    with pytest.raises(ScopeMismatch, match="correlated"):
        InvocationScope(
            workspace_id="ws-1",
            agent_id="agent-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
        )


# ---------------------------------------------------------------------------
# Context surface: no ambient handles
# ---------------------------------------------------------------------------


def test_context_public_surface_is_exactly_the_documented_seams() -> None:
    """The context exposes the documented seams and nothing else.

    This is the "no unrestricted DB/store/container handles" acceptance
    criterion, pinned structurally: a new attribute or method on
    ExtensionContext must be added here explicitly or the surface drifted.
    """
    context = _context()
    public = {name for name in dir(context) if not name.startswith("_")}
    assert public == {
        "config",
        "cancellation",
        "descriptor",
        "identity",
        "invoke_effect",
        "progress",
        "report_progress",
        "scope",
        "service",
    }
    for banned in (
        "container",
        "db",
        "session",
        "store",
        "stores",
        "runtime",
        "events",
        "event_store",
        "bindings",
        "invocations",
        "services",
        "dispatch_effect",
    ):
        assert not hasattr(context, banned), f"context leaked {banned!r}"
    # A slots object cannot carry attributes it was not built with, so no
    # later host or extension code can smuggle a handle onto it either.
    assert not hasattr(context, "__dict__")


def test_context_identity_and_scope_expose_canonical_identifiers_only() -> None:
    context = _context()
    assert context.identity is IDENTITY
    assert context.scope.workspace_id == "ws-1"
    assert context.scope.agent_id == "agent-1"
    assert context.scope.run_id == "run-1"
    assert context.scope.node_run_id == "node-run-1"
    assert context.scope.attempt_id == "attempt-1"
    # Identifiers only: every scope field is a plain string.
    assert all(
        isinstance(getattr(context.scope, field), str)
        for field in (
            "workspace_id",
            "agent_id",
            "run_id",
            "node_run_id",
            "attempt_id",
        )
    )


# ---------------------------------------------------------------------------
# Declared configuration access
# ---------------------------------------------------------------------------


def test_config_view_reads_only_declared_keys() -> None:
    view = ExtensionConfigView(
        extension_id=IDENTITY.extension_id,
        declared=frozenset({"temperature"}),
        values={"temperature": 0.7, "secret_token": "hunter2"},
    )
    assert view["temperature"] == 0.7
    assert view.get("temperature") == 0.7
    assert list(view) == ["temperature"]
    assert len(view) == 1
    assert "temperature" in view
    # Undeclared keys are refused everywhere, including get(): an undeclared
    # key reveals nothing, not even whether the host happens to hold it.
    with pytest.raises(ConfigurationKeyNotDeclared, match="secret_token"):
        view["secret_token"]
    with pytest.raises(ConfigurationKeyNotDeclared, match="secret_token"):
        view.get("secret_token", "fallback")
    with pytest.raises(ConfigurationKeyNotDeclared, match="missing"):
        view["missing"]
    assert "secret_token" not in view
    assert view.as_dict() == {"temperature": 0.7}


def test_config_view_snapshots_host_values_and_detaches_copies() -> None:
    host_values = {"temperature": 0.7}
    view = ExtensionConfigView(
        extension_id=IDENTITY.extension_id,
        declared=frozenset({"temperature"}),
        values=host_values,
    )
    host_values["temperature"] = 99
    # A running extension sees the snapshot from context build time.
    assert view["temperature"] == 0.7
    # And the copy it can obtain is detached from the view.
    copied = view.as_dict()
    copied["temperature"] = -1
    assert view["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Scoped service access
# ---------------------------------------------------------------------------


def test_service_access_requires_declaration_and_grant() -> None:
    context = _context()
    assert context.service("clock") == "granted-clock"
    # Undeclared: refused even though the host mapping is where a grant
    # would live — declaration alone is not authority either.
    with pytest.raises(ServiceNotGranted, match="not declared"):
        context.service("registry")
    # Declared but not granted by the host: same refusal class, different
    # reason, still no object.
    ungranted = _context(services={})
    with pytest.raises(ServiceNotGranted, match="granted no instance"):
        ungranted.service("clock")


# ---------------------------------------------------------------------------
# Capability/effect seam
# ---------------------------------------------------------------------------


async def test_declared_routed_effect_crosses_dispatcher_and_returns_receipt() -> None:
    dispatched: list[tuple[str, Any]] = []

    async def dispatcher(effect_key: str, request: Any) -> Any:
        dispatched.append((effect_key, request))
        return await _echo_dispatcher(effect_key, request)

    context = _context(dispatch_effect=dispatcher)
    receipt = await context.invoke_effect("echo", {"value": 41})
    assert dispatched == [("echo", {"value": 41})]
    assert receipt.invocation_id == "invocation-1"
    assert receipt.binding_id == "binding-1"
    assert receipt.capability == "probe.echo"
    assert receipt.effect_key == "echo"
    assert receipt.status == "completed"
    assert receipt.result == {"value": 41}


async def test_undeclared_effect_is_refused_before_any_dispatch() -> None:
    dispatched: list[str] = []

    async def dispatcher(effect_key: str, request: Any) -> Any:
        dispatched.append(effect_key)
        return await _echo_dispatcher(effect_key, request)

    context = _context(dispatch_effect=dispatcher)
    with pytest.raises(EffectNotDeclared, match="exfiltrate"):
        await context.invoke_effect("exfiltrate", {"value": 1})
    assert dispatched == []


async def test_declared_effect_without_a_host_route_is_refused() -> None:
    """Authority needs both halves: the descriptor declares, the host routes."""
    host = ExtensionHost(
        descriptor=_descriptor(effects=frozenset({"echo"})),
        # No effect_routes granted.
    )
    context = host.invocation_context(
        InvocationScope(
            workspace_id="ws-1",
            agent_id="agent-1",
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
        )
    )
    with pytest.raises(EffectNotDeclared, match="granted no governed route"):
        await context.invoke_effect("echo", {"value": 1})


async def test_effect_dispatch_checks_cancellation_first() -> None:
    cancelled = asyncio.Event()
    dispatched: list[str] = []

    async def dispatcher(effect_key: str, request: Any) -> Any:
        dispatched.append(effect_key)
        return await _echo_dispatcher(effect_key, request)

    context = _context(
        cancellation=ExtensionCancellation.from_predicate(cancelled.is_set),
        dispatch_effect=dispatcher,
    )
    cancelled.set()
    with pytest.raises(ExtensionCancelled):
        await context.invoke_effect("echo", {"value": 1})
    assert dispatched == []


# ---------------------------------------------------------------------------
# Cancellation view
# ---------------------------------------------------------------------------


async def test_cancellation_view_observes_pending_task_cancellation() -> None:
    """``of_current_task`` reads the canonical fence, not its own state.

    The ExecutionRuntime's cancel path ultimately calls ``Task.cancel()`` on
    the work task; the view must report the pending request before the error
    is delivered at the next await point. The observation shape here is also
    the documented integration shape: an executor may catch the delivered
    ``CancelledError`` to record evidence, observe the view, and re-raise.
    """
    stop = asyncio.Event()
    observed: list[bool] = []

    async def worker() -> None:
        view = ExtensionCancellation.of_current_task()
        try:
            await stop.wait()
        except asyncio.CancelledError:
            observed.append(view.cancelled())
            try:
                view.check()
            except ExtensionCancelled:
                observed.append(True)
            raise

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)  # let the worker reach its await
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed == [True, True]


async def test_cancellation_view_wait_resolves_on_host_predicate() -> None:
    """``wait`` is for host-predicate sources (activation stop flags)."""
    cancelled = asyncio.Event()
    view = ExtensionCancellation.from_predicate(cancelled.is_set)

    async def stop_soon() -> None:
        await asyncio.sleep(0.01)
        cancelled.set()

    stopper = asyncio.create_task(stop_soon())
    with pytest.raises(ExtensionCancelled):
        await view.wait(timeout_s=5)
    await stopper


async def test_cancellation_view_wait_times_out_as_an_ordinary_event() -> None:
    view = ExtensionCancellation.from_predicate(lambda: False)
    with pytest.raises(TimeoutError):
        await view.wait(timeout_s=0.02)


async def test_cancellation_wait_never_swallows_canonical_cancellation() -> None:
    """A task-cancel landing during ``wait`` propagates unchanged.

    The canonical Attempt fence delivers ``asyncio.CancelledError``; the view
    must not convert or absorb it, or a cancelled Attempt would be recorded
    as an extension failure instead of CANCELLED.
    """
    task = asyncio.current_task()
    assert task is not None
    view = ExtensionCancellation.of_current_task()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await view.wait()


# ---------------------------------------------------------------------------
# Progress hook
# ---------------------------------------------------------------------------


async def test_ungranted_progress_reporter_fails_loudly() -> None:
    reporter = UngrantedProgressReporter(IDENTITY.extension_id)
    with pytest.raises(ExtensionContractError, match="no progress sink"):
        await reporter.report(ExtensionProgress(message="hello", percent=50.0))


def test_progress_payload_is_validated() -> None:
    assert ExtensionProgress(message="step").percent is None
    with pytest.raises(ValueError, match="non-empty"):
        ExtensionProgress(message="   ")
    with pytest.raises(ValueError, match="0, 100"):
        ExtensionProgress(message="step", percent=150.0)


# ---------------------------------------------------------------------------
# Lifecycle protocol and host driving
# ---------------------------------------------------------------------------


def test_lifecycle_protocol_is_structural() -> None:
    """Any object with the three hooks is an ExtensionLifecycle."""
    assert isinstance(_ProbeLifecycle(), ExtensionLifecycle)
    assert isinstance(_ExplodingLifecycle(), ExtensionLifecycle)
    assert not isinstance(object(), ExtensionLifecycle)


async def test_host_drives_all_three_hooks_with_narrowed_contexts() -> None:
    host = ExtensionHost(descriptor=_descriptor(), service_grants={"clock": "granted-clock"})
    lifecycle = _ProbeLifecycle()

    activation = host.activation_context(workspace_id="ws-1", agent_id="agent-1")
    assert activation.scope.in_attempt is False
    await host.activate(lifecycle, activation)

    invocation = host.invocation_context(
        InvocationScope(
            workspace_id="ws-1",
            agent_id="agent-1",
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
        )
    )
    assert await host.invoke(lifecycle, invocation) == "probe-result"
    await host.deactivate(lifecycle, activation)

    assert lifecycle.hooks == [
        ("activate", "ws-1"),
        ("invoke", "attempt-1"),
        ("deactivate", "ws-1"),
    ]


def test_invocation_context_rejects_activation_scope() -> None:
    host = ExtensionHost(descriptor=_descriptor())
    with pytest.raises(ValueError, match="activation_context"):
        host.invocation_context(InvocationScope(workspace_id="ws-1", agent_id="agent-1"))


async def test_lifecycle_failures_are_attributed_to_the_extension() -> None:
    host = ExtensionHost(descriptor=_descriptor())
    context = host.activation_context(workspace_id="ws-1", agent_id="agent-1")
    lifecycle = _ExplodingLifecycle()

    with pytest.raises(ExtensionLifecycleError, match=r"conformance\.probe.*activate"):
        await run_activation(lifecycle, context)
    with pytest.raises(ExtensionLifecycleError, match=r"conformance\.probe.*invoke"):
        await run_invocation(lifecycle, context)
    with pytest.raises(ExtensionLifecycleError, match=r"conformance\.probe.*deactivate"):
        await run_deactivation(lifecycle, context)
    # The wrapper preserves the original failure for diagnosis.
    with pytest.raises(ExtensionLifecycleError) as exc_info:
        await run_invocation(lifecycle, context)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
