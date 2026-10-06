"""Governed UI/A2UI extension components projecting canonical state (M9-F2).

Each test names the acceptance criterion from issue #967 that it pins. The
module under test is ``maistro.extensions.ui``; a UI extension is data —
manifest bytes inspected without importing anything — and every rendered
surface projects only what the host's canonical snapshot supplies.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
import json
from datetime import UTC, datetime
from typing import Any

import pytest

import maistro.extensions.ui as ui_module
from maistro.extensions.types import ExtensionScope
from maistro.extensions.ui import (
    GOVERNED_ROUTES,
    MUTATING_INTENTS,
    ActionUnavailable,
    CatalogRejected,
    ClientStateRejected,
    ComponentAsset,
    RenderedComponent,
    UiProjectionService,
    UnknownAction,
    UnknownCatalog,
    UnknownComponent,
    assert_ui_snapshot_intact,
    inspect_ui_manifest,
    verify_component_asset,
)
from maistro.graph.definitions import Graph
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)

SCOPE = ExtensionScope(org_id="org-1", workspace_id="w-1")
EXTENSION_ID = "acme.runs_dashboard"

FROZEN_RUN_ID = "run-0123456789"
FROZEN_NODE_ID = "node-review"


def _manifest(**overrides: Any) -> dict[str, Any]:
    """A well-formed UI catalog manifest; keyword overrides per test."""
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "catalog_id": EXTENSION_ID,
        "name": "Acme Runs Dashboard",
        "version": "1.2.3",
        "publisher": "acme",
        "api_version": "1.0.0",
        "components": [_component()],
    }
    manifest.update(overrides)
    return manifest


def _component(**overrides: Any) -> dict[str, Any]:
    component: dict[str, Any] = {
        "component_id": "run_status_card",
        "title": "Run status",
        "sandbox": {
            "script_src": ["'self'"],
            "connect_src": ["https://api.acme.example"],
        },
        "bindings": [
            {"binding": "run", "kind": "run", "fields": ["run_id", "status"]},
        ],
        "actions": [
            {
                "action": "cancel",
                "intent": "cancel_run",
                "permissions": ["runs.cancel"],
                "route": "POST /v1/dag-runs/{run_id}/cancel",
                "precondition": "run_cancellable",
            },
        ],
    }
    component.update(overrides)
    return component


def _inspect(**overrides: Any):
    return inspect_ui_manifest(json.dumps(_manifest(**overrides)).encode())


async def _active(scope: ExtensionScope, extension_id: str) -> bool:
    return extension_id == EXTENSION_ID


async def _inactive(scope: ExtensionScope, extension_id: str) -> bool:
    return False


def _service(
    manifest_bytes: bytes | None = None,
    *,
    active: Any = _active,
    extension_permissions: frozenset[str] | None = frozenset({"runs.cancel"}),
) -> UiProjectionService:
    manifest = inspect_ui_manifest(manifest_bytes) if manifest_bytes is not None else _inspect()
    return UiProjectionService(
        {(SCOPE, EXTENSION_ID): manifest},
        extension_active=active,
        extension_permissions={(SCOPE, EXTENSION_ID): extension_permissions}
        if extension_permissions is not None
        else {},
    )


def _graph_snapshot() -> GraphSnapshot:
    return GraphSnapshot.from_graph(
        Graph(workspace_id=SCOPE.workspace_id, project_id="p-1", name="demo")
    )


def _run(status: RunStatus = RunStatus.RUNNING) -> Run:
    terminal = status in {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
    return Run(
        run_id=FROZEN_RUN_ID,
        workspace_id=SCOPE.workspace_id,
        project_id="p-1",
        status=status,
        actor_principal_id="dev",
        graph=_graph_snapshot(),
        finished_at=datetime.now(UTC) if terminal else None,
    )


def _node_run(status: RunStatus = RunStatus.WAITING) -> NodeRun:
    return NodeRun(run_id=FROZEN_RUN_ID, node_id=FROZEN_NODE_ID, ordinal=1, status=status)


def _attempt(status: AttemptStatus = AttemptStatus.YIELDED) -> Attempt:
    return Attempt(
        node_run_id="nr-1",
        ordinal=1,
        status=status,
        finished_at=datetime.now(UTC),
    )


STATE: dict[str, Any] = {
    "workspace": {"workspace_id": SCOPE.workspace_id, "name": "Demo", "description": "d"},
    "goal": {"goal_id": "g-1", "goal_revision": 3},
    "run": _run(),
    "node_run": _node_run(),
    "attempt": _attempt(),
}
PRINCIPAL = frozenset({"runs.read", "runs.cancel", "hitl.answer"})


async def _render_one(
    service: UiProjectionService,
    *,
    state: dict[str, Any] | None = STATE,
    permissions: frozenset[str] = PRINCIPAL,
) -> RenderedComponent:
    return await service.render_component(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        principal_permissions=permissions,
        canonical_state=state,
    )


# --------------------------------------------------------------------------
# AC: an out-of-tree UI extension renders canonical state without direct
# DB/store access.
# --------------------------------------------------------------------------


async def test_out_of_tree_manifest_projects_only_declared_canonical_fields() -> None:
    """AC-1: manifest bytes alone render a canonical projection.

    The manifest is pure data — no module to import, no store handle exists
    anywhere in the flow — and the projection carries exactly the declared
    binding fields from the host-supplied snapshot, never the rest of the
    canonical record (graph snapshot, result, principal id stay host-side).
    """
    raw = json.dumps(_manifest()).encode()
    service = _service(raw)
    rendered = await _render_one(service)
    assert rendered.visible is True
    assert rendered.data == {"run": {"run_id": FROZEN_RUN_ID, "status": "running"}}
    serialized = repr(rendered.data)
    assert "actor_principal_id" not in serialized
    assert "definition_json" not in serialized


def test_binding_field_outside_the_allowlist_is_refused() -> None:
    """AC-1: only the closed projection allowlist is bindable."""
    with pytest.raises(CatalogRejected, match="not a projectable run field"):
        _inspect(
            components=[
                _component(
                    bindings=[
                        {
                            "binding": "run",
                            "kind": "run",
                            "fields": ["actor_principal_id"],
                        }
                    ]
                )
            ]
        )


def test_binding_to_non_canonical_state_is_refused() -> None:
    """AC-1: bindings may reference canonical state only."""
    with pytest.raises(CatalogRejected, match="not canonical state"):
        _inspect(
            components=[
                _component(bindings=[{"binding": "ledger", "kind": "ledger", "fields": ["x"]}])
            ]
        )


async def test_unprojected_kind_renders_none_and_actions_stay_evaluated() -> None:
    """AC-1: a kind the host did not project renders as None, not an error."""
    service = _service()
    rendered = await _render_one(service, state={"workspace": STATE["workspace"]})
    assert rendered.data == {"run": {"run_id": None, "status": None}}


def test_contract_module_touches_no_store_or_session_surface() -> None:
    """AC-1 (structural): the projection surface has no store access at all."""
    source = inspect.getsource(ui_module)
    for forbidden in (
        "persistence",
        "sqlalchemy",
        "create_engine",
        "Session",
        "RunStore",
        "WorkspaceStore",
        ".execute(",
    ):
        assert forbidden not in source, f"contract module references {forbidden!r}"


async def test_model_objects_and_plain_mappings_project_alike() -> None:
    """AC-1: the host may pass canonical models or plain snapshot dicts."""
    service = _service()
    from_model = await _render_one(service, state={"run": _run()})
    plain = {
        "run": {"run_id": FROZEN_RUN_ID, "status": "running"},
    }
    from_dict = await _render_one(service, state=plain)
    assert from_model.data["run"]["status"] == from_dict.data["run"]["status"] == "running"


# --------------------------------------------------------------------------
# AC: mutating UI actions call governed server seams and cannot mark
# Runs/Goals complete locally.
# --------------------------------------------------------------------------


def test_mutating_action_must_name_its_governed_route_exactly() -> None:
    """AC-2: a mutating action's route is pinned to the governed seam."""
    with pytest.raises(CatalogRejected, match="governed seam"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["runs.cancel"],
                            "route": "POST /v1/runs/{run_id}/complete",
                        }
                    ]
                )
            ]
        )


def test_mutating_action_permissions_are_canonical_not_catalog_chosen() -> None:
    """AC-2: the catalog cannot pick the authority protecting a mutation.

    A governed route's required permissions are fixed by the platform: a
    declaration must match them exactly, so an extension holding only a
    low-authority token cannot bind cancel_run to that token and have the
    extension-grant and principal checks bless the swap.
    """
    with pytest.raises(CatalogRejected, match="canonical permissions"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["notes.read"],
                            "route": "POST /v1/dag-runs/{run_id}/cancel",
                        }
                    ]
                )
            ]
        )
    with pytest.raises(CatalogRejected, match="canonical permissions"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["runs.cancel", "notes.read"],
                            "route": "POST /v1/dag-runs/{run_id}/cancel",
                        }
                    ]
                )
            ]
        )


def test_completion_is_not_expressible_as_a_ui_action() -> None:
    """AC-2: no intent or route exists that marks a Run/Goal complete."""
    with pytest.raises(CatalogRejected, match="unknown intent"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "finish",
                            "intent": "complete_run",
                            "permissions": ["runs.complete"],
                            "route": "POST /v1/runs/{run_id}/complete",
                        }
                    ]
                )
            ]
        )
    with pytest.raises(CatalogRejected, match="unknown intent"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "close",
                            "intent": "complete_goal",
                            "permissions": ["goals.complete"],
                            "route": "POST /v1/goals/{goal_id}/complete",
                        }
                    ]
                )
            ]
        )
    assert not any("complete" in intent for intent in MUTATING_INTENTS)
    assert not any("complete" in route.path for route in GOVERNED_ROUTES.values())


async def test_dispatch_resolves_the_governed_seam_from_canonical_state() -> None:
    """AC-2: a dispatched cancel resolves the canonical cancel seam."""
    service = _service()
    call = await service.dispatch(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        action="cancel",
        principal="dev",
        principal_permissions=PRINCIPAL,
        canonical_state=STATE,
    )
    assert (call.method, call.path) == (
        "POST",
        f"/v1/dag-runs/{FROZEN_RUN_ID}/cancel",
    )
    assert call.permissions_required == ("runs.cancel",)


async def test_hitl_dispatch_resolves_both_canonical_targets() -> None:
    """AC-2: HITL actions resolve run *and* node from canonical state."""
    manifest = _inspect(
        components=[
            _component(
                bindings=[
                    {"binding": "run", "kind": "run", "fields": ["run_id", "status"]},
                    {"binding": "node", "kind": "node_run", "fields": ["node_id"]},
                ],
                actions=[
                    {
                        "action": "answer",
                        "intent": "answer_hitl",
                        "permissions": ["hitl.answer"],
                        "route": "POST /v1/hitl/{run_id}/{node_id}/answer",
                    }
                ],
            )
        ]
    )
    service = _service(extension_permissions=frozenset({"runs.cancel", "hitl.answer"}))
    service.register(manifest, scope=SCOPE)
    call = await service.dispatch(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        action="answer",
        principal="dev",
        principal_permissions=PRINCIPAL,
        arguments={"answer": "approve", "reason": "looks right"},
        canonical_state=STATE,
    )
    assert call.path == f"/v1/hitl/{FROZEN_RUN_ID}/{FROZEN_NODE_ID}/answer"
    # Free-form action arguments pass through; canonical identity does not.
    assert call.arguments == {"answer": "approve", "reason": "looks right"}


async def test_start_task_seam_carries_no_canonical_params() -> None:
    """AC-2: the task-admission seam is routable without canonical targets."""
    manifest = _inspect(
        components=[
            _component(
                bindings=[],
                actions=[
                    {
                        "action": "start",
                        "intent": "start_task",
                        "permissions": ["tasks.start"],
                        "route": "POST /v1/tasks",
                    }
                ],
            )
        ]
    )
    service = _service(extension_permissions=frozenset({"tasks.start"}))
    service.register(manifest, scope=SCOPE)
    call = await service.dispatch(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        action="start",
        principal="dev",
        principal_permissions=frozenset({"tasks.start"}),
        canonical_state=None,
    )
    assert (call.method, call.path) == ("POST", "/v1/tasks")


def test_local_actions_cannot_carry_routes_or_permissions() -> None:
    """AC-2: renderer-local intents stay renderer-local."""
    with pytest.raises(CatalogRejected, match="cannot declare"):
        _inspect(
            components=[
                _component(
                    actions=[{"action": "hop", "intent": "navigate", "route": "POST /v1/tasks"}]
                )
            ]
        )
    with pytest.raises(CatalogRejected, match="cannot require"):
        _inspect(
            components=[
                _component(
                    actions=[{"action": "hop", "intent": "refresh", "permissions": ["runs.read"]}]
                )
            ]
        )


# --------------------------------------------------------------------------
# AC: disabled/unauthorized actions are enforced server-side, not merely
# hidden.
# --------------------------------------------------------------------------


async def test_disabled_extension_is_unavailable_at_dispatch() -> None:
    """AC-3: a disabled extension's actions are refused, not just hidden."""
    service = _service(active=_inactive)
    rendered = await _render_one(service)
    assert rendered.visible is False
    assert rendered.data == {}
    assert rendered.actions[0].available is False
    with pytest.raises(ActionUnavailable, match="not active"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_missing_principal_permission_is_enforced_at_dispatch() -> None:
    """AC-3: an unauthorized principal cannot invoke what it cannot see."""
    service = _service()
    rendered = await _render_one(service, permissions=frozenset({"runs.read"}))
    assert rendered.actions[0].available is False
    with pytest.raises(ActionUnavailable, match="principal lacks permission"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=frozenset({"runs.read"}),
            canonical_state=STATE,
        )


async def test_component_required_permissions_are_enforced_at_dispatch() -> None:
    """AC-3: component-level required_permissions gate dispatch, not just render.

    A principal holding every action permission but missing a component-level
    requirement cannot name the component and action to obtain a governed call.
    """
    service = _service(
        json.dumps(_manifest(components=[_component(required_permissions=["admin.everything"])]))
        .encode()
    )
    rendered = await _render_one(service)
    assert rendered.visible is False
    with pytest.raises(ActionUnavailable, match="not visible to this principal"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_extension_grant_bounds_declared_action_authority() -> None:
    """AC-3: the governed install grant bounds what actions may even ask.

    An action whose permission the extension's active install was never
    granted is unavailable for every principal — a manifest cannot promise
    authority the operator never approved at install time.
    """
    service = _service(extension_permissions=frozenset({"runs.read"}))
    rendered = await _render_one(service)
    assert rendered.actions[0].available is False
    with pytest.raises(ActionUnavailable, match="extension grant"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_terminal_run_status_fails_the_cancellable_precondition() -> None:
    """AC-3: canonical preconditions are evaluated from canonical state."""
    service = _service()
    state = dict(STATE)
    state["run"] = _run(RunStatus.COMPLETED)
    rendered = await _render_one(service, state=state)
    assert rendered.actions[0].available is False
    with pytest.raises(ActionUnavailable, match="not cancellable"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=state,
        )


async def test_unresolvable_canonical_target_is_unavailable() -> None:
    """AC-3: without the canonical target projected, there is nothing to call."""
    manifest = _manifest(
        components=[
            _component(
                bindings=[
                    {"binding": "run", "kind": "run", "fields": ["run_id"]},
                    {"binding": "node", "kind": "node_run", "fields": ["node_id"]},
                ],
                actions=[
                    {
                        "action": "answer",
                        "intent": "answer_hitl",
                        "permissions": ["hitl.answer"],
                        "route": "POST /v1/hitl/{run_id}/{node_id}/answer",
                        "precondition": "always",
                    }
                ],
            )
        ]
    )
    service = _service(
        json.dumps(manifest).encode(),
        extension_permissions=frozenset({"runs.cancel", "hitl.answer"}),
    )
    # The run is projected, but the node_run half of the target is not.
    rendered = await service.render_component(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        principal_permissions=PRINCIPAL,
        canonical_state={"run": _run()},
    )
    assert rendered.actions[0].available is False
    with pytest.raises(ActionUnavailable, match="not projected"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="answer",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state={"run": _run()},
        )


# --------------------------------------------------------------------------
# AC: component state loss/reload does not alter canonical execution state.
# --------------------------------------------------------------------------


async def test_client_arguments_cannot_carry_canonical_state() -> None:
    """AC-4: canonical fields and binding names are refused in arguments."""
    service = _service()
    for smuggled in (
        {"run_id": "run-attacker-controlled"},
        {"status": "completed"},
        {"run": {"status": "completed"}},
    ):
        with pytest.raises(ClientStateRejected, match="cannot be supplied"):
            await service.dispatch(
                scope=SCOPE,
                extension_id=EXTENSION_ID,
                component_id="run_status_card",
                action="cancel",
                principal="dev",
                principal_permissions=PRINCIPAL,
                arguments=smuggled,
                canonical_state=STATE,
            )


async def test_reload_rerenders_identically_and_moves_nothing() -> None:
    """AC-4: a reload re-projects from the snapshot; the snapshot is untouched.

    The client's last-known canonical state (here: a stale, forged
    "completed" run) contributes nothing: dispatch refuses it, and the
    canonical snapshot the host supplied is byte-identical afterwards.
    """
    service = _service()
    snapshot = copy.deepcopy(STATE)
    first = await _render_one(service, state=snapshot)
    second = await _render_one(service, state=snapshot)
    assert first == second
    with pytest.raises(ClientStateRejected):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            arguments={"run_id": first.data["run"]["run_id"], "status": "completed"},
            canonical_state=snapshot,
        )
    assert snapshot == STATE


# --------------------------------------------------------------------------
# AC: extension UI cannot inject unrestricted scripts/network access outside
# declared policy.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vector",
    [
        "<script>alert(1)</script>",
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
        "eval(atob('x'))",
        "<iframe src=//evil.example></iframe>",
        "data:text/html,<script>alert(1)</script>",
        "<object data='x'></object>",
        "<embed src='x'>",
        "srcdoc='<script>'",
    ],
)
def test_injection_vectors_are_rejected_at_inspection(vector: str) -> None:
    """AC-5: component text cannot carry script-injection constructs."""
    with pytest.raises(CatalogRejected, match="script-injection"):
        _inspect(components=[_component(template=f"view: {vector}")])


@pytest.mark.parametrize(
    "token",
    [
        "'unsafe-inline'",
        "'unsafe-eval'",
        "'wasm-unsafe-eval'",
        "'strict-dynamic'",
        "*",
        "https://*.acme.example",
        "data:",
        "blob:",
        "http://api.acme.example",
        "//api.acme.example",
        "https://cdn.acme.example 'unsafe-inline'",
        "https://a.acme.example,https://b.acme.example",
    ],
)
def test_unsafe_csp_tokens_are_rejected(token: str) -> None:
    """AC-5: declared policies cannot contain unrestricted-source tokens."""
    with pytest.raises(CatalogRejected):
        _inspect(
            components=[
                _component(
                    sandbox={"script_src": ["'self'"], "img_src": [token]},
                )
            ]
        )


def test_script_policy_is_required_not_inherited() -> None:
    """AC-5: a component declares its script policy; there is no default."""
    with pytest.raises(CatalogRejected, match="script_src is required"):
        _inspect(components=[_component(sandbox={"img_src": ["'self'"]})])
    with pytest.raises(CatalogRejected, match="non-empty object"):
        _inspect(components=[_component(sandbox={})])


def test_open_url_outside_declared_origins_is_rejected() -> None:
    """AC-5: outbound navigation stays inside the declared origin allowlist."""
    for target in (
        "http://api.acme.example/docs",  # plaintext
        "https://evil.example/docs",  # undeclared host
        "ftp://api.acme.example/docs",  # wrong scheme
    ):
        with pytest.raises(CatalogRejected, match="outside the declared sandbox"):
            _inspect(
                components=[
                    _component(actions=[{"action": "docs", "intent": "open_url", "target": target}])
                ]
            )
    # A javascript: target is an injection vector before it is a routing one.
    with pytest.raises(CatalogRejected, match="script-injection"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {"action": "docs", "intent": "open_url", "target": "javascript:alert(1)"}
                    ]
                )
            ]
        )


def test_open_url_inside_declared_origins_is_accepted() -> None:
    """AC-5: declared-origin navigation is expressible (paths allowed)."""
    manifest = _inspect(
        components=[
            _component(
                actions=[
                    {
                        "action": "docs",
                        "intent": "open_url",
                        "target": "https://api.acme.example/docs/index.html",
                    }
                ]
            )
        ]
    )
    assert manifest.components[0].actions[0].target is not None


async def test_rendered_metadata_carries_the_header_ready_csp() -> None:
    """AC-5: the hosting client can sandbox the surface mechanically."""
    rendered = await _render_one(_service())
    assert rendered.sandbox_csp == (
        "script-src 'self'; style-src 'none'; img-src 'none'; "
        "connect-src https://api.acme.example"
    )


# --------------------------------------------------------------------------
# AC: component/version provenance is inspectable in rendered extension
# metadata.
# --------------------------------------------------------------------------


async def test_provenance_is_inspectable_in_rendered_metadata() -> None:
    """AC-6: every render states which installed bytes produced it."""
    raw = json.dumps(_manifest()).encode()
    manifest = inspect_ui_manifest(raw)
    service = _service(raw)
    rendered = await _render_one(service)
    assert rendered.provenance.catalog_id == EXTENSION_ID
    assert rendered.provenance.component_id == "run_status_card"
    assert rendered.provenance.version == "1.2.3"
    assert rendered.provenance.publisher == "acme"
    assert rendered.provenance.manifest_sha256 == manifest.source_sha256


async def test_provenance_rides_on_every_dispatched_call() -> None:
    """AC-6: the audit trail can attribute a mutation to a component version."""
    service = _service()
    call = await service.dispatch(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        action="cancel",
        principal="dev",
        principal_permissions=PRINCIPAL,
        canonical_state=STATE,
    )
    assert call.provenance.manifest_sha256 == _inspect().source_sha256
    assert call.principal == "dev"


def test_manifest_snapshot_tampering_is_detected() -> None:
    """AC-6 (and every render): the snapshot anchor re-verifies each use."""
    manifest = _inspect()
    tampered = inspect_ui_manifest(json.dumps(_manifest()).encode())
    object.__setattr__(tampered, "raw", manifest.raw + b" ")
    with pytest.raises(CatalogRejected, match="integrity failure"):
        assert_ui_snapshot_intact(tampered)


def test_replace_cannot_smuggle_fields_past_the_anchor() -> None:
    """Substituted fields fail the snapshot check even with matching bytes."""
    manifest = _inspect()
    unsafe = ui_module.SandboxPolicy(script_src=("'self'", "*"), connect_src=("https://evil.example",))
    smuggled = dataclasses.replace(
        manifest,
        components=(dataclasses.replace(manifest.components[0], sandbox=unsafe),),
    )
    assert smuggled.raw == manifest.raw
    assert smuggled.source_sha256 == manifest.source_sha256
    with pytest.raises(CatalogRejected, match="parsed fields differ"):
        assert_ui_snapshot_intact(smuggled)


# --------------------------------------------------------------------------
# Versioned component assets.
# --------------------------------------------------------------------------


def test_asset_digest_pins_the_exact_bytes() -> None:
    """Scope: versioned component assets are digest-pinned and verifiable."""
    payload = b"component tree v1\n"
    asset = ComponentAsset(
        path="cards/main.json", sha256=hashlib.sha256(payload).hexdigest(), size=len(payload)
    )
    assert verify_component_asset(asset, payload) == asset.sha256
    with pytest.raises(CatalogRejected, match="digest mismatch"):
        verify_component_asset(asset, b"component tree v2\n")
    with pytest.raises(CatalogRejected, match="size mismatch"):
        verify_component_asset(
            ComponentAsset(path="cards/main.json", sha256=asset.sha256, size=999),
            payload,
        )


@pytest.mark.parametrize(
    "path",
    ["../escape.json", "/etc/passwd", "https://evil.example/x", "a\\b.json", "scheme:x"],
)
def test_asset_paths_cannot_escape_the_bundle(path: str) -> None:
    """Scope: asset paths are relative bundle paths, nothing else."""
    with pytest.raises(CatalogRejected, match="relative bundle path"):
        _inspect(assets=[{"path": path, "sha256": hashlib.sha256(b"x").hexdigest(), "size": 1}])


# --------------------------------------------------------------------------
# Inspection hardening (fail closed on every malformed shape).
# --------------------------------------------------------------------------


def test_unknown_manifest_keys_are_refused() -> None:
    """An ignored key is authority the operator never saw."""
    manifest = _manifest()
    manifest["telemetry"] = True
    with pytest.raises(CatalogRejected, match="unknown manifest keys"):
        inspect_ui_manifest(json.dumps(manifest).encode())


def test_unsupported_manifest_version_is_refused() -> None:
    with pytest.raises(CatalogRejected, match="unsupported manifest_version"):
        _inspect(manifest_version=2)


def test_missing_required_keys_are_refused() -> None:
    manifest = _manifest()
    del manifest["publisher"]
    with pytest.raises(CatalogRejected, match="missing manifest keys"):
        inspect_ui_manifest(json.dumps(manifest).encode())


def test_semver_fields_are_strict() -> None:
    with pytest.raises(CatalogRejected, match="semver"):
        _inspect(version="1.0")
    with pytest.raises(CatalogRejected, match="semver"):
        _inspect(api_version="one")


def test_duplicate_component_ids_are_refused() -> None:
    with pytest.raises(CatalogRejected, match="duplicate component id"):
        _inspect(components=[_component(), _component()])


def test_duplicate_bindings_and_actions_are_refused() -> None:
    with pytest.raises(CatalogRejected, match="duplicate binding"):
        _inspect(
            components=[
                _component(
                    bindings=[
                        {"binding": "run", "kind": "run", "fields": ["run_id"]},
                        {"binding": "run", "kind": "run", "fields": ["status"]},
                    ]
                )
            ]
        )
    with pytest.raises(CatalogRejected, match="duplicate action"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["runs.cancel"],
                            "route": "POST /v1/dag-runs/{run_id}/cancel",
                        },
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["runs.cancel"],
                            "route": "POST /v1/dag-runs/{run_id}/cancel",
                        },
                    ]
                )
            ]
        )


def test_unknown_sandbox_directive_is_refused() -> None:
    with pytest.raises(CatalogRejected, match="unknown sandbox directives"):
        _inspect(components=[_component(sandbox={"script_src": ["'self'"], "worker_src": ["*"]})])


def test_unknown_action_keys_are_refused() -> None:
    with pytest.raises(CatalogRejected, match="unknown action keys"):
        _inspect(
            components=[
                _component(
                    actions=[
                        {
                            "action": "cancel",
                            "intent": "cancel_run",
                            "permissions": ["runs.cancel"],
                            "route": "POST /v1/dag-runs/{run_id}/cancel",
                            "on_success": "close",
                        }
                    ]
                )
            ]
        )


def test_malformed_json_is_refused() -> None:
    with pytest.raises(CatalogRejected, match="not valid UTF-8 JSON"):
        inspect_ui_manifest(b"{not json")
    with pytest.raises(CatalogRejected, match="top-level document"):
        inspect_ui_manifest(b"[1,2]")


# --------------------------------------------------------------------------
# Lookup and registration errors.
# --------------------------------------------------------------------------


async def test_unknown_catalog_component_and_action_fail_distinctly() -> None:
    service = _service()
    with pytest.raises(UnknownCatalog):
        await service.render_component(
            scope=SCOPE,
            extension_id="other.dashboard",
            component_id="run_status_card",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )
    with pytest.raises(UnknownComponent):
        await service.render_component(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="missing_card",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )
    with pytest.raises(UnknownAction):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="explode",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_renderer_local_actions_dispatch_nothing() -> None:
    """Local intents have no server seam; dispatching one is refused."""
    manifest = _inspect(
        components=[_component(actions=[{"action": "reload", "intent": "refresh"}])]
    )
    service = _service()
    service.register(manifest, scope=SCOPE)
    with pytest.raises(ActionUnavailable, match="renderer-local"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="reload",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


def test_catalog_registers_only_under_its_own_extension_id() -> None:
    """A catalog is addressable only by the extension that shipped it."""
    manifest = _inspect(catalog_id="other.dashboard")
    with pytest.raises(ValueError, match="only by the extension id"):
        UiProjectionService(
            {(SCOPE, EXTENSION_ID): manifest},
            extension_active=_active,
        )


async def test_scoped_state_keeps_installs_isolated_per_scope() -> None:
    """The same extension active in two scopes carries its own catalog and
    grant per scope: a grant in the broad org scope must not make a mutating
    action available in the narrower workspace scope, and provenance must
    reflect the manifest actually installed in each scope."""
    org_manifest = _inspect(
        version="2.0.0",
        components=[
            _component(
                actions=[
                    {
                        "action": "cancel",
                        "intent": "cancel_run",
                        "permissions": ["runs.cancel"],
                        "route": "POST /v1/dag-runs/{run_id}/cancel",
                    }
                ],
            )
        ],
    )
    ws_manifest = _inspect(
        version="1.0.0",
        components=[
            _component(
                actions=[
                    {
                        "action": "cancel",
                        "intent": "cancel_run",
                        "permissions": ["runs.cancel"],
                        "route": "POST /v1/dag-runs/{run_id}/cancel",
                    }
                ],
            )
        ],
    )
    org_scope = ExtensionScope(org_id="org-1")
    service = UiProjectionService(
        {(org_scope, EXTENSION_ID): org_manifest, (SCOPE, EXTENSION_ID): ws_manifest},
        extension_active=_active,
        extension_permissions={(org_scope, EXTENSION_ID): frozenset({"runs.cancel"})},
    )

    org_render = await service.render_component(
        scope=org_scope,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        principal_permissions=PRINCIPAL,
        canonical_state=STATE,
    )
    ws_render = await service.render_component(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        component_id="run_status_card",
        principal_permissions=PRINCIPAL,
    )
    assert org_render.provenance.version == "2.0.0"
    assert ws_render.provenance.version == "1.0.0"
    cancel = lambda rendered: next(  # noqa: E731
        a for a in rendered.actions if a.action == "cancel"
    )
    # Granted in the org scope…
    assert cancel(org_render).available is True
    # …but the workspace-scoped install carries no such grant.
    assert cancel(ws_render).available is False
    with pytest.raises(ActionUnavailable, match="grant does not cover"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="dev",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_dispatch_requires_an_attribution_principal() -> None:
    service = _service()
    with pytest.raises(ValueError, match="principal is required"):
        await service.dispatch(
            scope=SCOPE,
            extension_id=EXTENSION_ID,
            component_id="run_status_card",
            action="cancel",
            principal="  ",
            principal_permissions=PRINCIPAL,
            canonical_state=STATE,
        )


async def test_render_all_projects_every_component_in_the_catalog() -> None:
    service = _service(
        json.dumps(
            _manifest(components=[_component(), _component(component_id="goal_card")])
        ).encode()
    )
    rendered = await service.render(
        scope=SCOPE,
        extension_id=EXTENSION_ID,
        principal_permissions=PRINCIPAL,
        canonical_state=STATE,
    )
    assert [item.component_id for item in rendered] == [
        "run_status_card",
        "goal_card",
    ]


async def test_component_visibility_withholds_the_whole_projection() -> None:
    """A component the principal cannot see renders no data at all."""
    service = _service(
        json.dumps(
            _manifest(
                components=[_component(required_permissions=["runs.read", "admin.everything"])]
            )
        ).encode()
    )
    rendered = await _render_one(service, permissions=frozenset({"runs.read"}))
    assert rendered.visible is False
    assert rendered.data == {}
