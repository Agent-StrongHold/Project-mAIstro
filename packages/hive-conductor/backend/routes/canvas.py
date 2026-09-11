"""Canvas/Davinci DAG route — run visual pipeline and hill-climb."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.canvas_dag import CANVAS_DAG, CanvasHillClimber, visual_quality_eval

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.invocation import CapabilityUnavailable

router = APIRouter(prefix="/v1/canvas", tags=["canvas"])

_climber = CanvasHillClimber()


class CanvasRequest(BaseModel):
    prompt: str
    style: str = ""


class CanvasEvalRequest(BaseModel):
    description: str = Field(min_length=1)
    # This is supplied by the canonical Canvas execution owner. The route does
    # not invent Run/NodeRun/Attempt ids for a standalone evaluation.
    context: dict[str, Any] | None = None


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
    )
    if any(value is None for value in kwargs.values()):
        raise RuntimeError("Canvas governed model egress is incompletely composed")
    configured = build_canvas_model_egress(settings=get_settings(), **kwargs)
    request.app.state.canvas_model_egress = configured
    return configured


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
            context=req.context,
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
