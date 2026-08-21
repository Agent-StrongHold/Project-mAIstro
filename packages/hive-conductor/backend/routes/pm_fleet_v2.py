"""PM Fleet v2 routes — knowledge distillation, GitHub/GitLab tools, topK testing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from services.pm_fleet_v2 import (
    GITHUB_TOOLS,
    JIRA_PROJECT_KEY,
    execute_github_tool,
    execute_gitlab_tool,
    get_distiller,
    get_topk_tester,
)

router = APIRouter(prefix="/v1/pm-fleet", tags=["pm-fleet"])


class DistillRequest(BaseModel):
    question: str
    answer: str
    score: float = 0.0


class ToolCallRequest(BaseModel):
    tool: str
    args: dict[str, Any] = {}


@router.get("/config")
async def get_config():
    """Get PM Fleet configuration."""
    return {
        "jira_project_key": JIRA_PROJECT_KEY,
        "topk": get_topk_tester().stats,
        "tools_available": [t["function"]["name"] for t in GITHUB_TOOLS],
        "distiller_faq_count": len(get_distiller().faq),
    }


@router.post("/distill/record")
async def record_answer(req: DistillRequest):
    """Record a high-quality answer for distillation."""
    get_distiller().record_opus_answer(req.question, req.answer, req.score)
    return {"recorded": True, "total": len(get_distiller().opus_answers)}


@router.post("/distill/run")
async def run_distillation():
    """Run knowledge distillation on collected answers."""
    faq = await get_distiller().distill()
    return {"faq_count": len(faq), "faq": faq[:5]}


@router.get("/distill/lookup")
async def lookup_faq(q: str):
    """Try to answer from distilled FAQ."""
    answer = get_distiller().lookup(q)
    return {"found": answer is not None, "answer": answer}


@router.post("/tools/execute")
async def execute_tool(req: ToolCallRequest):
    """Execute a GitHub/GitLab tool."""
    if req.tool.startswith("github_"):
        return await execute_github_tool(req.tool, req.args)
    elif req.tool.startswith("gitlab_"):
        return await execute_gitlab_tool(req.tool, req.args)
    return {"error": f"Unknown tool: {req.tool}"}


@router.get("/tools")
async def list_tools():
    """List available tools."""
    return {"tools": GITHUB_TOOLS}


@router.post("/topk/record")
async def record_topk(topk: int, score: float):
    """Record a topK test result."""
    get_topk_tester().record_result(topk, score)
    return get_topk_tester().stats


@router.get("/topk")
async def get_topk_stats():
    """Get topK testing stats."""
    return get_topk_tester().stats
