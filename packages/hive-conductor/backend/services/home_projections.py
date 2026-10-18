"""Workspace Home projections: read-time compact views over canonical services (#1048).

Same shape of contract as Workspace Attention (#1049): **a read-time projection
over canonical sources.** Nothing here is persisted except one kind of
preference (adaptive dismissals), and nothing here transitions anything. Each
section names the canonical service that owns its resources; an item's
`resource_id` is that service's own id and its `href` opens the owning full
surface, so selecting a compact projection never changes the underlying
resource identity and no second id is ever minted for showing the same
Goal/backlog item/run/chat session twice.

Sections answer honestly when their service has nothing or cannot answer:
`status` is `ok`, `empty` or `unavailable` — never fabricated content. A
design service that is not open, or a canonical read that raises, reads as
`unavailable` with a reason, which is the state the issue asks for instead of
a plausible-looking zero.

The adaptive half is deterministic on purpose in this slice: candidates come
from the same canonical evidence (blocked backlog work, failed runs, dormant
goals), each carrying an `explain` line built from that evidence — not an
engagement feed, and no external content fetch. Dismissals are recorded
backend-side (`stores.home_adaptive_dismissals`), so "show me less of this" is
a durable preference the API and the Workspace Agent share, not client-only
state.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any

import stores

from services import workspace_authority

logger = logging.getLogger("hive.home")

#: Per-section item cap. A miniature surface shows the head of a list; the
#: full surface owns the scroll.
PROJECTION_LIMIT = 6

#: Run summaries are fetched across the caller's authorized universe and then
#: narrowed to the requested Workspace, so fetch a window wider than the cap:
#: capping first would let a burst of foreign runs blank out this section.
_RUN_WINDOW = 50

#: A Goal untouched this long is a dormancy candidate.
_DORMANT_AFTER = timedelta(days=14)

DISMISSALS_STORE = "home_adaptive_dismissals"


class WorkspaceNotVisible(LookupError):
    """The caller is not a member of this Workspace, or it does not exist."""


# ---------------------------------------------------------------------------
# Adaptive dismissals — the one thing this module persists, and it is a
# preference, not a domain object.
# ---------------------------------------------------------------------------


def _dismissal_key(workspace_id: str, item_type: str, item_id: str) -> str:
    return f"{workspace_id}:{item_type}:{item_id}"


def record_dismissal(
    workspace_id: str, item_type: str, item_id: str, *, actor: str
) -> dict[str, Any]:
    """Record "not this" for one adaptive candidate. Durable, counted, attributed.

    The key is the candidate's canonical identity, so dismissing a Goal's
    suggestion dismisses that suggestion everywhere it would surface in this
    Workspace — and, because the key is namespaced by Workspace, never touches
    what another Workspace's Home would show.
    """
    if not item_type or not item_id:
        raise ValueError("an adaptive dismissal names the item type and id it dismisses")
    store = stores.home_adaptive_dismissals
    key = _dismissal_key(workspace_id, item_type, item_id)
    now = datetime.now(UTC)
    prior = store.get(key)
    prior_count = int(prior.get("count", 0)) if isinstance(prior, dict) else 0
    prior_first = prior.get("first_at") if isinstance(prior, dict) else None
    record = {
        "workspace_id": workspace_id,
        "item_type": item_type,
        "item_id": item_id,
        "count": prior_count + 1,
        "first_at": prior_first or now.isoformat(),
        "last_at": now.isoformat(),
        "dismissed_by": actor,
    }
    store[key] = record
    return record


def dismissal_counts(workspace_id: str) -> dict[str, int]:
    """Dismissal counts for this Workspace, keyed `item_type:item_id`."""
    prefix = f"{workspace_id}:"
    counts: dict[str, int] = {}
    for key, record in stores.home_adaptive_dismissals.items():
        if not key.startswith(prefix) or not isinstance(record, dict):
            continue
        counts[key.removeprefix(prefix)] = int(record.get("count", 1))
    return counts


# ---------------------------------------------------------------------------
# Section reads — each one the canonical service's own answer
# ---------------------------------------------------------------------------


def _item(resource_type: str, resource_id: str, title: str, href: str, updated_at: Any) -> dict:
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "title": title,
        "href": href,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


def _section(kind: str, items: list[dict] | None, *, reason: str | None = None) -> dict:
    """`ok`, `empty` or `unavailable` — never a fabricated row."""
    if reason is not None:
        return {"kind": kind, "status": "unavailable", "items": [], "reason": reason}
    return {"kind": kind, "status": "ok" if items else "empty", "items": items or []}


def _goals(user_id: str) -> list[dict]:
    missions = [
        mission
        for mission in stores.missions.values()
        if getattr(mission, "user_id", "") == user_id and mission.status != "completed"
    ]
    missions.sort(key=lambda m: m.updated_at, reverse=True)
    return [
        _item("goal", m.id, m.name, f"/missions?open={m.id}", m.updated_at)
        for m in missions[:PROJECTION_LIMIT]
    ]


async def _backlog_items(user_id: str, workspace_id: str) -> list[dict]:
    from services import backlog as backlog_service

    items = await backlog_service.list_items(user_id, workspace_id=workspace_id)
    return [
        _item("backlog_item", item.id, item.title, f"/backlog?item={item.id}", item.updated_at)
        for item in items[:PROJECTION_LIMIT]
    ]


async def _run_items(user_id: str, workspace_id: str) -> list[dict]:
    from services import dag_run_inspection

    summaries = await dag_run_inspection.list_visible_runs(user_id, limit=_RUN_WINDOW)
    out: list[dict] = []
    for summary in summaries:
        if str(summary.get("workspace_id") or "") != workspace_id:
            continue
        run_id = str(summary.get("id") or "")
        if not run_id:
            continue
        out.append(
            _item(
                "run",
                run_id,
                str(summary.get("dag_id") or run_id),
                f"/dag-runs?run={run_id}",
                summary.get("started_at"),
            )
        )
    return out[:PROJECTION_LIMIT]


def _chat_sessions(user_id: str) -> list[dict]:
    sessions = [s for s in stores.chat_sessions.values() if getattr(s, "user_id", "") == user_id]
    sessions.sort(key=lambda s: s.updated_at, reverse=True)

    def _title(session: Any) -> str:
        for message in getattr(session, "messages", None) or []:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()[:80]
        return str(getattr(session, "title", "") or "chat session")

    return [
        _item("chat_session", s.id, _title(s), f"/chat?session={s.id}", s.updated_at)
        for s in sessions[:PROJECTION_LIMIT]
    ]


def _design() -> tuple[list[dict], str | None]:
    """The design surface's one honest answer, or why it cannot answer."""
    from services import design_service

    try:
        status = design_service.get_design_status()
    except Exception as exc:
        return [], f"design service status unavailable: {type(exc).__name__}"
    info = status.to_dict() if hasattr(status, "to_dict") else dict(status)
    if not info.get("configured", False):
        return [], "design service is not configured in this deployment"
    if not info.get("available", False):
        return [], "design service is not available"
    return [_item("design_surface", "design-studio", "Design Studio", "/design-studio", None)], None


async def _attention_items(user_id: str, workspace_id: str) -> list[dict]:
    from services import attention as attention_service

    body = await attention_service.list_attention(user_id, workspace_id, now=datetime.now(UTC))
    if body is None:
        return []
    out: list[dict] = []
    for entry in body.get("items", [])[:PROJECTION_LIMIT]:
        source_id = str(entry.get("source_id") or "")
        if not source_id:
            continue
        out.append(
            _item(
                "attention_item",
                source_id,
                str(entry.get("reason") or entry.get("attention_class") or "needs attention"),
                str(entry.get("answer_href") or "/attention"),
                entry.get("created_at"),
            )
        )
    return out


async def _resolve(section: str, coro: Awaitable[list[dict]]) -> dict:
    """One section's read. A failure is that section's `unavailable`, never a
    failed response for all of Home and never a stand-in row."""
    try:
        return _section(section, await coro)
    except Exception as exc:
        logger.warning("home projection section %r failed: %s", section, exc)
        return _section(section, [], reason=f"{type(exc).__name__} while reading {section}")


async def list_projections(user_id: str, workspace_id: str) -> dict[str, Any]:
    """Every Home section, read from its canonical service at call time.

    Raises `WorkspaceNotVisible` when the caller is not a member: the
    projections are membership-scoped like every other Workspace read, and the
    refusal happens before any section is computed.
    """
    if await workspace_authority.visible_view(user_id, workspace_id) is None:
        raise WorkspaceNotVisible(workspace_id)

    design_items, design_reason = _design()

    sections = await asyncio.gather(
        _resolve("goals", asyncio.sleep(0, result=_goals(user_id))),
        _resolve("backlog", _backlog_items(user_id, workspace_id)),
        _resolve("runs", _run_items(user_id, workspace_id)),
        _resolve("chat", asyncio.sleep(0, result=_chat_sessions(user_id))),
        _resolve("design", asyncio.sleep(0, result=design_items))
        if design_reason is None
        else _unavailable("design", design_reason),
        _resolve("attention", _attention_items(user_id, workspace_id)),
    )

    return {
        "workspace_id": workspace_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "sections": list(sections),
        "dismissed": dismissal_counts(workspace_id),
    }


async def _unavailable(section: str, reason: str) -> dict:
    return _section(section, [], reason=reason)


# ---------------------------------------------------------------------------
# Adaptive candidates — deterministic, explainable, dismissible
# ---------------------------------------------------------------------------


def _backlog_candidate(item: Any) -> dict[str, Any]:
    """One backlog item's adaptive case, from its own state."""
    if item.status == "blocked":
        return {
            "key": f"backlog_item:{item.id}",
            "item_type": "backlog_item",
            "resource_id": item.id,
            "title": item.title,
            "explain": f"blocked in this Workspace's backlog (priority {item.priority})",
            "href": f"/backlog?item={item.id}",
        }
    if item.priority == "critical":
        return {
            "key": f"backlog_item:{item.id}",
            "item_type": "backlog_item",
            "resource_id": item.id,
            "title": item.title,
            "explain": "critical-priority item in this Workspace's backlog",
            "href": f"/backlog?item={item.id}",
        }
    return {}


async def _collect_backlog_candidates(user_id: str, workspace_id: str) -> list[dict[str, Any]]:
    from services import backlog as backlog_service

    try:
        items = await backlog_service.list_items(user_id, workspace_id=workspace_id)
    except Exception as exc:
        logger.warning("adaptive backlog candidates unavailable: %s", exc)
        return []
    return [c for c in (_backlog_candidate(item) for item in items) if c]


async def _collect_run_candidates(user_id: str, workspace_id: str) -> list[dict[str, Any]]:
    """A failed run is a usefulness candidate: the user will want to know."""
    from services import dag_run_inspection

    try:
        summaries = await dag_run_inspection.list_visible_runs(user_id, limit=_RUN_WINDOW)
    except Exception as exc:
        logger.warning("adaptive run candidates unavailable: %s", exc)
        return []
    candidates: list[dict[str, Any]] = []
    for summary in summaries:
        if str(summary.get("workspace_id") or "") != workspace_id:
            continue
        run_id = str(summary.get("id") or "")
        if run_id and str(summary.get("status") or "") == "failed":
            candidates.append(
                {
                    "key": f"run:{run_id}",
                    "item_type": "run",
                    "resource_id": run_id,
                    "title": str(summary.get("dag_id") or run_id),
                    "explain": "this run failed; open it to see what failed",
                    "href": f"/dag-runs?run={run_id}",
                }
            )
    return candidates


def _goal_candidate(mission: Any, owner_id: str, now: datetime) -> dict[str, Any]:
    """A dormant Goal's adaptive case, or {} when it is not dormant."""
    if getattr(mission, "user_id", "") != owner_id or mission.status != "pending":
        return {}
    updated = mission.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    if updated >= now - _DORMANT_AFTER:
        return {}
    idle_days = max(0, (now - updated).days)
    return {
        "key": f"goal:{mission.id}",
        "item_type": "goal",
        "resource_id": mission.id,
        "title": mission.name,
        "explain": f"dormant Goal — untouched for {idle_days} days",
        "href": f"/missions?open={mission.id}",
    }


async def adaptive_items(user_id: str, workspace_id: str) -> dict[str, Any]:
    """What the unpinned space could show now, with the evidence for each choice.

    Deterministic internal evidence only in this slice: each candidate names
    the canonical item it would project and a one-line `explain` derived from
    that item's actual state (blocked, failed, dormant). Selecting is
    usefulness-first by construction — there is no time-on-screen term to
    optimize. Dismissed candidates are excluded and their dismissal counts
    reported, so negative reinforcement is visible to whichever caller applies
    it (route or Workspace Agent tool alike).
    """
    if await workspace_authority.visible_view(user_id, workspace_id) is None:
        raise WorkspaceNotVisible(workspace_id)

    backlog_candidates, run_candidates = await asyncio.gather(
        _collect_backlog_candidates(user_id, workspace_id),
        _collect_run_candidates(user_id, workspace_id),
    )
    now = datetime.now(UTC)
    goal_candidates = [
        c for c in (_goal_candidate(m, user_id, now) for m in stores.missions.values()) if c
    ]

    counts = dismissal_counts(workspace_id)
    candidates = sorted(
        (
            c
            for c in [*backlog_candidates, *run_candidates, *goal_candidates]
            if c["key"] not in counts
        ),
        key=lambda c: c["key"],
    )
    return {
        "workspace_id": workspace_id,
        "candidates": candidates,
        "dismissed": counts,
    }
