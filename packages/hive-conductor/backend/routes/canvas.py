"""Canvas/Davinci DAG route — run visual pipeline and hill-climb."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from services.canvas_dag import CANVAS_DAG, CanvasHillClimber, visual_quality_eval

router = APIRouter(prefix="/v1/canvas", tags=["canvas"])

_climber = CanvasHillClimber()


class CanvasRequest(BaseModel):
    prompt: str
    style: str = ""


class CanvasEvalRequest(BaseModel):
    description: str


@router.get("/dag")
async def get_canvas_dag():
    """Return the Canvas/Davinci DAG definition."""
    return CANVAS_DAG


@router.post("/eval")
async def eval_visual(req: CanvasEvalRequest):
    """Run visual quality eval on an image description."""
    return await visual_quality_eval(req.description)


@router.get("/hill-climb/status")
async def hill_climb_status():
    """Get current hill-climb status."""
    return {
        "best_score": _climber.best_score,
        "passes": len(_climber.history),
        "history": _climber.history[-10:],
    }
