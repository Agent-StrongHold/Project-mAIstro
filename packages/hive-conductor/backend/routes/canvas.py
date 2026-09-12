"""Canvas/Davinci DAG route - run visual pipeline and hill-climb."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.canvas_dag import CANVAS_DAG, CanvasHillClimber, visual_quality_eval

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.invocation import CapabilityUnavailable
from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES

router = APIRouter(prefix="/v1/canvas", tags=["canvas"])

_climber = CanvasHillClimber()


class CanvasRequest(BaseModel):
    prompt: str
    style: str = ""


class CanvasEvalRequest(BaseModel):
    description: str = Field(min_length=1)
    # A Run id selects the already-admitted execution. NodeRun, Attempt,
    # Binding, Workspace, and Project are resolved server-side below.
    run_id: str | None = None


def _canvas_model_egress(request: Request) -> Any:
    """Return the composition-provided egress, retaining one ledger per app."""
    configured = getattr(request.app.state, "canvas_model_egress", None)
    if configured is not None:
        return configured

    from config import get_settings
    from services.canvas_model_egress import build_canvas_model_egress
    from services.engine import get_engine

    engine = get_engine()
    container = getattr(getattr(engine, "agent_port", None), "container", None)
    kwargs: dict[str, Any] = {}
    if container is None:
        raise RuntimeError("Canvas governed model egress is not composed")
    kwargs.update(
        effects=getattr(container, "capability_effects", None),
        registry=getattr(container, "provider_registry", None),
        router=getattr(container, "llm_router", None),
        run_store=getattr(container, "run_store", None),
    )
    if any(value is None for value in kwargs.values()):
        raise RuntimeError("Canvas governed model egress is incompletely composed")
    configured = build_canvas_model_egress(settings=get_settings(), **kwargs)
    request.app.state.canvas_model_egress = configured
    return configured


def _trusted_canvas_context(request: Request) -> dict[str, str]:
    configured = getattr(request.state, "canvas_execution_context", None)
    if not isinstance(configured, Mapping):
        return {}
    return {str(key): str(value) for key, value in configured.items()}


async def _canonical_canvas_run(request: Request, run_id: str) -> Any:
    """Load and authenticate the existing canonical Run, never create one."""
    user = getattr(request.state, "user", None) or {}
    principal = str(user.get("id") or user.get("username") or "").strip()
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")

    run = await _canvas_model_egress(request).run_store.get_run(run_id)
    if run is None:
        raise BindingResolutionError("Canvas visual evaluation requires an existing canonical Run")
    if run.actor_principal_id != principal and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Canvas Run is not owned by this principal")
    if not run.actor_principal_id:
        raise BindingResolutionError("Canvas Run has no authenticated execution principal")
    return run


def _quality_node_id(run: Any, context: Mapping[str, str]) -> str:
    graph = run.graph.materialize()
    quality_nodes = [
        node
        for node in graph.nodes
        if node.node_type == "canvas.visual_quality"
        or node.metadata.get("canvas_stage") == "visual_quality"
    ]
    node_id = str(context.get("node_id") or "").strip()
    if node_id:
        if any(node.node_id == node_id for node in quality_nodes):
            return node_id
        raise BindingResolutionError("Canvas execution context does not name a quality Node")
    if len(quality_nodes) != 1:
        raise BindingResolutionError(
            "Canvas visual evaluation requires exactly one quality Node in the Run"
        )
    return quality_nodes[0].node_id


async def _quality_node_run(
    run_store: Any, run: Any, node_id: str, context: Mapping[str, str]
) -> Any:
    node_run_id = str(context.get("node_run_id") or "").strip()
    if node_run_id:
        node_run = await run_store.get_node_run(node_run_id)
        if node_run is None or node_run.run_id != run.run_id or node_run.node_id != node_id:
            raise BindingResolutionError("Canvas context does not name this Run's NodeRun")
        return node_run

    matches = [
        item for item in await run_store.list_node_runs(run.run_id) if item.node_id == node_id
    ]
    if len(matches) != 1:
        raise BindingResolutionError("Canvas Run must have exactly one quality NodeRun")
    return matches[0]


async def _quality_attempt(run_store: Any, node_run: Any, context: Mapping[str, str]) -> Any:
    attempt_id = str(context.get("attempt_id") or "").strip()
    if attempt_id:
        attempt = await run_store.get_attempt(attempt_id)
        if attempt is None or attempt.node_run_id != node_run.node_run_id:
            raise BindingResolutionError("Canvas context does not name this NodeRun's Attempt")
        return attempt

    open_attempts = [
        item
        for item in await run_store.list_attempts(node_run.node_run_id)
        if item.status not in TERMINAL_ATTEMPT_STATUSES
    ]
    if len(open_attempts) != 1:
        raise BindingResolutionError("Canvas Run must have exactly one open quality Attempt")
    return open_attempts[0]


def _quality_binding_id(settings: Any, run: Any, node_id: str, context: Mapping[str, str]) -> str:
    binding_id = str(context.get("binding_id") or "").strip()
    if binding_id:
        return binding_id

    configured_id = str(getattr(settings, "canvas_model_binding_id", "") or "").strip()
    if configured_id:
        return configured_id

    default_workspace = str(getattr(settings, "hive_default_workspace_id", "default"))
    candidates = [
        declaration.binding_id
        for declaration in settings.model_bindings
        if (declaration.workspace_id.strip() or default_workspace) == run.workspace_id
        and declaration.project_id == run.project_id
        and (not declaration.node_id or declaration.node_id == node_id)
    ]
    # Let the governed egress receive a stable missing reference when config is
    # absent or ambiguous. It settles the identified Attempt as failed instead
    # of losing that lifecycle fact in route-level validation.
    return candidates[0] if len(candidates) == 1 else "__canvas_binding_unconfigured__"


async def _canvas_execution_context(
    request: Request,
    requested_run_id: str | None,
) -> dict[str, str]:
    """Resolve trusted Canvas identity from canonical Run/NodeRun/Attempt state."""
    from config import get_settings

    state_context = _trusted_canvas_context(request)
    state_run_id = state_context.get("run_id", "").strip()
    run_id = str(requested_run_id or state_run_id).strip()
    if not run_id:
        raise BindingResolutionError("Canvas visual evaluation requires a canonical Run")
    if state_run_id and state_run_id != run_id:
        raise BindingResolutionError("Canvas context does not match the selected Run")

    egress = _canvas_model_egress(request)
    run = await _canonical_canvas_run(request, run_id)
    node_id = _quality_node_id(run, state_context)
    node_run = await _quality_node_run(egress.run_store, run, node_id, state_context)
    attempt = await _quality_attempt(egress.run_store, node_run, state_context)
    binding_id = _quality_binding_id(get_settings(), run, node_id, state_context)
    return {
        "binding_id": binding_id,
        "run_id": run.run_id,
        "node_id": node_id,
        "node_run_id": node_run.node_run_id,
        "attempt_id": attempt.attempt_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
    }


@router.get("/dag")
async def get_canvas_dag():
    """Return the Canvas/Davinci DAG definition."""
    return CANVAS_DAG


@router.post("/eval")
async def eval_visual(req: CanvasEvalRequest, request: Request):
    """Run visual quality eval through the canonical model Invocation seam."""
    try:
        return await visual_quality_eval(
            req.description,
            context=await _canvas_execution_context(request, req.run_id),
            egress=_canvas_model_egress(request),
        )
    except (BindingResolutionError, CapabilityUnavailable, RuntimeError) as exc:
        # Missing context, Binding, Provider, or gateway is an unavailable
        # evaluation. Never turn it into a score-shaped success response.
        raise HTTPException(
            status_code=503,
            detail="visual quality evaluation is unavailable",
        ) from exc
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise HTTPException(
            status_code=502,
            detail="visual quality provider returned an invalid evaluation",
        ) from exc


@router.get("/hill-climb/status")
async def hill_climb_status():
    """Get current hill-climb status."""
    return {
        "best_score": _climber.best_score,
        "passes": len(_climber.history),
        "history": _climber.history[-10:],
    }
