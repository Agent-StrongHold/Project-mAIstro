"""Dashboard layout persistence — per-user widget configuration.

Layouts live in `stores.dashboard_layouts`, the same persistence boundary as
every other durable Conductor collection, through
`services/dashboard_layouts.py` (#340, ADR-082926-3b80). They used to live in a
module dict mirrored to a JSON file inside the image, with a second
fire-and-forget copy in PostgREST that the read path consulted first.

The read-only routes below this one — demos, widget examples, deck templates —
serve files shipped in the image. They are catalogue, not user state, and are
deliberately still read straight off disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services import dashboard_layouts
from services.dashboard_safety import sanitize_dashboard_layout

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])
logger = logging.getLogger("hive.dashboard")


def _user_id(request: Request) -> str:
    """The authenticated principal, or 401.

    There used to be a `"dev"` fallback here. Every unauthenticated caller
    would then share one layout key -- a pooled bucket rather than a default,
    and a cross-principal leak the moment the middleware stopped covering this
    path. The middleware does cover it today; the refusal is what keeps that
    true if it ever stops.
    """
    user = getattr(request.state, "user", None) or {}
    principal = user.get("id") or user.get("username")
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(principal)


class WidgetConfig(BaseModel):
    id: str
    type: str
    title: str
    size: str = "1"
    config: dict | None = None


class DashboardLayout(BaseModel):
    model_config: ClassVar[dict] = {"extra": "allow"}
    widgets: list[WidgetConfig] = []
    tabs: list[dict] = []
    activeTab: int = 0
    updatedAt: str = ""
    #: The revision the client believes it edited. Optional: a save without one
    #: is last-write-wins, which is what the SPA does today. Never persisted --
    #: it is a claim about the record, not part of it.
    expectedRevision: int | None = None


# Users with pre-configured dashboard templates, offered on first read.
_PRESETS: dict[str, str] = {
    "demo": "pm-command-center",
}


def _preset_for(principal: str) -> dict | None:
    """The template this principal starts from, if any.

    Returned, not saved. Seeding used to write from inside the GET handler,
    inside a bare `except`, which made a read depend on a write succeeding and
    then hid it when it did not. The preset becomes durable when the user saves,
    which is the first moment they have said anything about it.
    """
    preset = _PRESETS.get(principal)
    if not preset:
        return None
    path = Path(__file__).parent.parent / "data" / "demo_dashboards" / f"{preset}.json"
    if not path.is_file():
        return None
    try:
        return sanitize_dashboard_layout(json.loads(path.read_text()))
    except (OSError, ValueError) as exc:
        logger.warning("preset %s could not be read: %s", preset, exc)
        return None


@router.get("/layout")
async def get_layout(request: Request) -> dict:
    """This principal's stored layout, or its preset, or an empty one."""
    principal = _user_id(request)
    record = dashboard_layouts.load(principal)
    if record.revision == 0:
        preset = _preset_for(principal)
        if preset is not None:
            return {**preset, "revision": 0}
    return {**record.layout, "revision": record.revision}


@router.put("/layout")
async def save_layout(request: Request, body: DashboardLayout) -> dict:
    """Store this principal's layout, or say it was not stored.

    The `save` call is deliberately outside any `try`. The defect this route
    had was not a missing write; it was a handler that turned a failed one into
    `{"ok": true}`. Only the two failures with an answer of their own are
    caught, and each names what it is.
    """
    principal = _user_id(request)
    payload = body.model_dump(exclude={"expectedRevision"})
    try:
        record = dashboard_layouts.save(principal, payload, expected_revision=body.expectedRevision)
    except dashboard_layouts.LayoutConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "the layout changed since you loaded it",
                "revision": exc.stored.revision,
                "layout": exc.stored.layout,
            },
        ) from exc
    except dashboard_layouts.LayoutPersistenceError as exc:
        logger.error("dashboard layout was not persisted for %s: %s", principal, exc)
        raise HTTPException(
            status_code=503,
            detail=f"the layout was not saved: {exc}",
        ) from exc
    return {"ok": True, "revision": record.revision, "updatedAt": record.updated_at.isoformat()}


@router.get("/metrics")
async def get_metrics() -> dict:
    """Get live dashboard metrics for the header KPI cards."""
    from pathlib import Path

    agents_path = Path(__file__).parent.parent / "data" / "agents.json"
    agent_count = 0
    try:
        agent_count = len(json.loads(agents_path.read_text()))
    except Exception:
        agent_count = 9  # fallback to configured agent count
    return {
        "active_agents": agent_count,
        "runs_today": 0,
        "avg_latency_ms": 0,
        "total_cost": 0.0,
        "approval_rate": None,
        "ttft_ms": 0,
    }


@router.get("/widget-examples")
async def get_widget_examples(category: str | None = None) -> list[dict]:
    """Return curated widget example templates."""
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "widget_examples.json"
    try:
        examples = json.loads(path.read_text())
    except Exception:
        return []
    if category:
        examples = [e for e in examples if category.lower() in e.get("category", "").lower()]
    return examples


@router.get("/demos")
async def list_demo_dashboards() -> list[dict]:
    """List available demo dashboard templates."""
    from pathlib import Path

    demos_dir = Path(__file__).parent.parent / "data" / "demo_dashboards"
    if not demos_dir.exists():
        return []
    results = []
    for f in sorted(demos_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            results.append(
                {
                    "id": f.stem,
                    "name": data.get("name", f.stem),
                    "description": data.get("description", ""),
                    "widget_count": len(data.get("widgets", [])),
                }
            )
        except Exception:
            continue
    return results


@router.get("/demos/{demo_id}")
async def get_demo_dashboard(demo_id: str) -> dict:
    """Load a demo dashboard template."""
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "demo_dashboards" / f"{demo_id}.json"
    if not path.exists():
        return {"error": "not found"}
    return sanitize_dashboard_layout(json.loads(path.read_text()))


@router.get("/deck-templates")
async def get_deck_templates(category: str | None = None) -> list[dict]:
    """Return slide template library for the DeckBuilder."""
    path = Path(__file__).parent.parent / "data" / "deck_templates.json"
    try:
        templates = json.loads(path.read_text())
    except Exception:
        return []
    if category:
        templates = [t for t in templates if t.get("category", "").lower() == category.lower()]
    return templates
