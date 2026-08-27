"""Dashboard layout persistence — per-user widget configuration.

Uses the same SQLite persistence layer as the rest of Hive's stores.
Falls back to in-memory if persistence isn't configured.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from fastapi import APIRouter, Request
from pydantic import BaseModel
from services.dashboard_safety import sanitize_dashboard_layout

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])
logger = logging.getLogger("hive.dashboard")

# SQLite-backed file (same dir as other Hive state)
_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_layouts.json"
_LAYOUTS: dict[str, dict] = {}


def _load_from_disk() -> None:
    """Load persisted layouts on startup."""
    if _DB_PATH.is_file():
        try:
            raw = json.loads(_DB_PATH.read_text())
            if isinstance(raw, dict):
                _LAYOUTS.update(
                    {str(uid): sanitize_dashboard_layout(layout) for uid, layout in raw.items()}
                )
        except Exception as e:
            logger.warning("Failed to load dashboard layouts: %s", e)


def _save_to_disk() -> None:
    """Persist layouts to disk."""
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DB_PATH.write_text(json.dumps(_LAYOUTS, indent=2))
    except Exception as e:
        logger.warning("Failed to save dashboard layouts: %s", e)


# Load on import
_load_from_disk()


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("id") or user.get("username") or "dev")


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


@router.get("/layout")
async def get_layout(request: Request) -> dict:  # noqa: C901  layered preset/PG/disk fallbacks
    """Get the current user's dashboard layout. Seeds preset for known users."""
    uid = _user_id(request)
    # Try PostgREST first (survives restarts)
    if uid not in _LAYOUTS:
        try:
            from services.pg_store import POSTGREST_URL

            if POSTGREST_URL:
                import httpx

                r = httpx.get(
                    f"{POSTGREST_URL}/user_service_state",
                    params={
                        "user_id": f"eq.{uid}",
                        "service": "eq.fantasia",
                        "key": "eq.dashboard_layout",
                    },
                    timeout=3,
                )
                if r.status_code == 200:
                    rows = r.json()
                    if rows:
                        val = rows[0].get("value")
                        layout = json.loads(val) if isinstance(val, str) else val
                        if layout:
                            _LAYOUTS[uid] = sanitize_dashboard_layout(layout)
        except Exception:
            pass
    if uid not in _LAYOUTS:
        preset = _PRESETS.get(uid)
        if preset:
            demo_path = Path(__file__).parent.parent / "data" / "demo_dashboards" / f"{preset}.json"
            if demo_path.is_file():
                try:
                    _LAYOUTS[uid] = sanitize_dashboard_layout(json.loads(demo_path.read_text()))
                    _save_to_disk()
                except Exception:
                    pass
    safe = sanitize_dashboard_layout(_LAYOUTS.get(uid, {"widgets": []}))
    _LAYOUTS[uid] = safe
    return safe


# Users with pre-configured dashboard templates (loaded on first access)
_PRESETS: dict[str, str] = {
    "demo": "portfolio-overview",
}


@router.put("/layout")
async def save_layout(request: Request, body: DashboardLayout) -> dict:
    """Save the current user's dashboard layout after M0 request-field sanitization."""
    uid = _user_id(request)
    safe_layout = sanitize_dashboard_layout(body.model_dump())
    _LAYOUTS[uid] = safe_layout
    _save_to_disk()
    # Persist to PostgREST
    try:
        from services.pg_store import is_pg_available, pg_upsert

        if is_pg_available():
            import asyncio

            _task = asyncio.ensure_future(  # noqa: RUF006  fire-and-forget mirror write
                pg_upsert(
                    "user_service_state",
                    {
                        "user_id": uid,
                        "service": "fantasia",
                        "key": "dashboard_layout",
                        "value": json.dumps(safe_layout),
                    },
                )
            )
    except Exception:
        pass
    return {"ok": True}


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
