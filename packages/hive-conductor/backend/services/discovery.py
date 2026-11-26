"""Bounded proactive discovery for the Workspace (#1051).

The product half of M3-E5. The *physical* work of discovery is a canonical
Run of the registered ``proactive-discovery`` seed DAG (fetch → scout →
curate through the governed egress); this module owns the Workspace-scoped
product state around it:

- **config** — the feature is off until a Workspace turns it on; the config
  carries the Binding ids, watch topics, cycle caps and budgets. This is
  what "the user can disable the feature or constrain discovery" edits.
- **budgets** — a durable, day-keyed ledger of discovery cycles, source
  fetches and surfaced candidates. Exhaustion refuses new cycles cleanly
  (no partially-charged work), and because the ledger is a registered
  durable store it survives restart.
- **surfaced items** — the intentionally small curated set Home/Attention
  project. Duplicate fingerprints never surface twice; stale items age out.
- **feedback** — keep/dismiss updates per-category preference evidence the
  next cycle's scout applies as score down-weights. Dismissal is durable
  preference state, not client-side hiding.

Authority boundaries this module keeps:

- No second scheduler: cycles are triggered by callers that already hold a
  canonical trigger — the discovery trigger route (a member's request, run
  through ``run_registered_dag`` like a schedule fire) or a canonical
  Schedule targeting the seed template. The ledger charge is keyed by Run id
  so a retry can never double-spend a cycle.
- No second memory authority: surfaced items and context notes are sourced
  *evidence*. Nothing here writes the user model — promotion stays behind
  the canonical ``promote_evidence`` door.
- Fire-time context (Persona, user model, current Goals) is read fresh at
  node execution through the ``discovery_context`` authority, so a
  scheduled overnight fire ranks against the Workspace's *current* state.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import stores

from maistro.graph.nodes.discovery_context import DiscoveryCycleContext
from services.model_store import JsonStore

logger = logging.getLogger("hive.discovery")

DISCOVERY_STORE = "proactive_discovery"

#: The durable discovery store, owned by this service and registered with the
#: central persistence wiring so a restart reloads config, budgets, the seen
#: ledger and surfaced items.
store: JsonStore = stores.register_json_store(JsonStore(DISCOVERY_STORE))

DISCOVERY_DAG_ID = "proactive-discovery"

#: How long a surfaced item stays eligible for Home/Waiting after it was
#: curated, when the source declared no expiry of its own.
SURFACE_FRESH_HOURS = 24 * 7

#: The seen-fingerprint ledger cap. Old fingerprints fall off the end; a
#: re-surfaced item after eviction is a rare, bounded repeat, not a leak.
SEEN_LEDGER_CAP = 1000

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "source_binding_id": "",
    "curator_binding_id": "",
    "curator_model": "gemini-3.1-flash",
    "watch_topics": [],
    "min_scout_score": 0.1,
    "max_candidates_per_cycle": 24,
    "max_surfaced": 3,
    "daily_fetch_budget": 60,
    "daily_curate_budget": 6,
    "sources_count": 0,
}

#: Field ranges the update path enforces; a hostile value cannot turn the
#: budget into an uncrawl or the surfaced set into a feed.
LIMITS: dict[str, tuple[float, float]] = {
    "min_scout_score": (0.0, 1.0),
    "max_candidates_per_cycle": (1, 100),
    "max_surfaced": (1, 10),
    "daily_fetch_budget": (0, 500),
    "daily_curate_budget": (0, 50),
}


class DiscoveryNotVisible(LookupError):
    """The caller is not a member of this Workspace, or it does not exist."""


class DiscoveryCycleRefused(RuntimeError):
    """The trigger was refused before any Run was admitted (disabled/budget)."""


def _config_key(workspace_id: str) -> str:
    return f"config:{workspace_id}"


def _ledger_key(workspace_id: str, day: str) -> str:
    return f"ledger:{workspace_id}:{day}"


def _seen_key(workspace_id: str) -> str:
    return f"seen:{workspace_id}"


def _prefs_key(workspace_id: str) -> str:
    return f"prefs:{workspace_id}"


def _item_key(workspace_id: str, fingerprint: str) -> str:
    return f"item:{workspace_id}:{fingerprint}"


def _lifted_key(workspace_id: str) -> str:
    return f"lifted:{workspace_id}"


def get_config(workspace_id: str) -> dict[str, Any]:
    """The Workspace's discovery config with defaults filled in."""
    raw = store.get(_config_key(workspace_id))
    config = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        config.update({k: v for k, v in raw.items() if k in DEFAULT_CONFIG})
    return config


def _validate_config_value(config: dict[str, Any], key: str, value: Any) -> None:
    """One field's range/type rule; raises ValueError on a bad value."""
    if key in LIMITS:
        low, high = LIMITS[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{key} must be a number")
        if not low <= float(value) <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    elif key == "watch_topics":
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise ValueError("watch_topics must be a list of strings")
    elif key in {"source_binding_id", "curator_binding_id", "curator_model"}:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
    elif key == "sources_count":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("sources_count must be a nonnegative integer")


def update_config(workspace_id: str, changes: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Validate + persist a config change. The enabled flag is the off switch."""
    from routes.audit import log_audit

    config = get_config(workspace_id)
    for key, value in changes.items():
        if key not in DEFAULT_CONFIG:
            raise ValueError(f"unknown discovery config field {key!r}")
        _validate_config_value(config, key, value)
        if key == "enabled":
            config[key] = bool(value)
        elif key == "watch_topics":
            config[key] = [t.strip() for t in value if t.strip()][:50]
        elif key in {"source_binding_id", "curator_binding_id", "curator_model"}:
            config[key] = str(value).strip()
        elif key == "sources_count":
            config[key] = min(value, 100)
        else:
            config[key] = value
    config["updated_at"] = datetime.now(UTC).isoformat()
    config["updated_by"] = actor
    store[_config_key(workspace_id)] = config
    log_audit(
        "discovery_config_update",
        actor,
        target=workspace_id,
        detail={"enabled": config["enabled"]},
    )
    return config


# ---------------------------------------------------------------------------
# Budget ledger — durable, day-keyed, charged once per Run
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _empty_ledger(workspace_id: str, day: str) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "day": day,
        "cycles": [],
        "fetches": 0,
        "curated": 0,
        "surfaced": 0,
        "updated_at": "",
    }


def today_ledger(workspace_id: str) -> dict[str, Any]:
    day = _today()
    raw = store.get(_ledger_key(workspace_id, day))
    if isinstance(raw, dict) and isinstance(raw.get("cycles"), list):
        return raw
    return _empty_ledger(workspace_id, day)


def budget_status(workspace_id: str) -> dict[str, Any]:
    """What the budget allows and what today already spent."""
    config = get_config(workspace_id)
    ledger = today_ledger(workspace_id)
    return {
        "day": ledger["day"],
        "cycles_used": len(ledger["cycles"]),
        "daily_curate_budget": config["daily_curate_budget"],
        "fetches_used": ledger["fetches"],
        "daily_fetch_budget": config["daily_fetch_budget"],
        "surfaced_today": ledger["surfaced"],
        "exhausted": discovery_refusal(config, ledger) is not None,
    }


def discovery_refusal(config: dict[str, Any], ledger: dict[str, Any]) -> str | None:
    """Why a new cycle must not start, or None when the budget allows one."""
    if not config.get("enabled"):
        return "discovery_disabled"
    if len(ledger.get("cycles", [])) >= int(config["daily_curate_budget"]):
        return "discovery_cycle_budget_exhausted"
    if ledger.get("fetches", 0) + int(config.get("sources_count", 0)) > int(
        config["daily_fetch_budget"]
    ):
        return "discovery_fetch_budget_exhausted"
    return None


def _charge(
    workspace_id: str, config: dict[str, Any], ledger: dict[str, Any], *, cycle_key: str
) -> None:
    """Charge one cycle to the ledger, idempotent by Run id.

    Every node of one cycle consults the context with the same Run id, so the
    charge lands once even though three nodes read it; a replayed or retried
    Run keeps its charge rather than minting a second one.
    """
    if cycle_key and cycle_key in ledger["cycles"]:
        return
    if cycle_key:
        ledger["cycles"].append(cycle_key)
    ledger["fetches"] = int(ledger.get("fetches", 0)) + int(config.get("sources_count", 0))
    ledger["curated"] = int(ledger.get("curated", 0)) + 1
    ledger["updated_at"] = datetime.now(UTC).isoformat()
    store[_ledger_key(workspace_id, ledger["day"])] = ledger


def _record_surface(workspace_id: str, ledger: dict[str, Any], count: int) -> None:
    ledger["surfaced"] = int(ledger.get("surfaced", 0)) + count
    ledger["updated_at"] = datetime.now(UTC).isoformat()
    store[_ledger_key(workspace_id, ledger["day"])] = ledger


# ---------------------------------------------------------------------------
# Seen ledger + category preferences (feedback state)
# ---------------------------------------------------------------------------


def seen_fingerprints(workspace_id: str) -> frozenset[str]:
    raw = store.get(_seen_key(workspace_id))
    if isinstance(raw, dict) and isinstance(raw.get("fingerprints"), dict):
        return frozenset(raw["fingerprints"].keys())
    return frozenset()


def _record_seen(workspace_id: str, fingerprints: list[str]) -> None:
    if not fingerprints:
        return
    raw = store.get(_seen_key(workspace_id))
    seen: dict[str, str] = {}
    if isinstance(raw, dict) and isinstance(raw.get("fingerprints"), dict):
        seen = {str(k): str(v) for k, v in raw["fingerprints"].items()}
    now = datetime.now(UTC).isoformat()
    for fingerprint in fingerprints:
        seen[fingerprint] = now
    # Evict oldest-seen past the cap so the ledger cannot grow without bound.
    if len(seen) > SEEN_LEDGER_CAP:
        ordered = sorted(seen.items(), key=lambda kv: kv[1])
        seen = dict(ordered[len(ordered) - SEEN_LEDGER_CAP :])
    store[_seen_key(workspace_id)] = {"fingerprints": seen, "updated_at": now}


def category_preferences(workspace_id: str) -> dict[str, float]:
    """Per-category score weights from keep/dismiss feedback.

    A category the user never gave feedback on weighs 1.0; dismissals pull it
    toward 0 (``kept / (kept + dismissed)``). This is the canonical
    preference state later selection reads — negative feedback changes what
    future cycles surface, it does not merely hide one card client-side.
    """
    raw = store.get(_prefs_key(workspace_id))
    out: dict[str, float] = {}
    if isinstance(raw, dict) and isinstance(raw.get("categories"), dict):
        for category, counts in raw["categories"].items():
            if not isinstance(counts, dict):
                continue
            kept = int(counts.get("keep", 0))
            dismissed = int(counts.get("dismiss", 0))
            total = kept + dismissed
            if total > 0:
                out[str(category)] = round(kept / total, 4)
    return out


def _record_feedback_preference(workspace_id: str, category: str, action: str) -> None:
    if not category:
        return
    raw = store.get(_prefs_key(workspace_id))
    doc: dict[str, Any] = raw if isinstance(raw, dict) else {}
    categories: dict[str, Any] = (
        doc.get("categories") if isinstance(doc.get("categories"), dict) else {}
    )
    counts = categories.get(category) if isinstance(categories.get(category), dict) else {}
    counts[action] = int(counts.get(action, 0)) + 1
    categories[category] = counts
    doc["categories"] = categories
    doc["updated_at"] = datetime.now(UTC).isoformat()
    store[_prefs_key(workspace_id)] = doc


# ---------------------------------------------------------------------------
# Fire-time context — the discovery_context authority's Hive implementation
# ---------------------------------------------------------------------------


async def _persona_notes(workspace_id: str) -> list[str]:
    """The Workspace Persona's declared domain, as curator context notes."""
    try:
        from services.workspace_authority import presentation_store

        presentation = presentation_store().get(workspace_id)
        persona_id = str(getattr(presentation, "persona_template_id", "") or "")
        if not persona_id:
            return []
        from services.persona_authoring import all_persona_templates

        template = all_persona_templates().get(persona_id)
        if template is None:
            return []
        notes: list[str] = []
        if template.business_model.strip():
            notes.append(f"persona domain: {template.business_model.strip()[:200]}")
        return notes
    except Exception as exc:  # pragma: no cover - persona store unavailable
        logger.debug("discovery persona context unavailable: %s", exc)
        return []


async def _user_model_notes(user_id: str) -> list[str]:
    """Durable user-model statements, read through the one canonical service."""
    try:
        from maistro_server.api.user_model import get_user_model_service

        service = get_user_model_service()
        facts = await service.facts(user_id)
        notes: list[str] = []
        for fact in facts[:8]:
            statement = str(getattr(fact, "statement", "") or "").strip()
            if statement:
                notes.append(f"about the user: {statement[:200]}")
        return notes
    except Exception as exc:
        # No durable store configured (503 path) is a context gap, not a
        # cycle failure: curation proceeds on topics + goals alone.
        logger.debug("discovery user-model context unavailable: %s", exc)
        return []


async def _goal_notes(user_id: str, workspace_id: str) -> list[str]:
    """Current Goal/Workspace activity, from the #65 inspection projection."""
    try:
        from services import goal_inspection

        views = await goal_inspection.list_goal_views(user_id, limit=5, workspace_id=workspace_id)
        notes: list[str] = []
        for view in views:
            title = str(view.get("desired_state") or view.get("goal_state") or "").strip()
            if title:
                notes.append(f"current goal: {title[:200]}")
        return notes
    except Exception as exc:  # pragma: no cover - inspection unavailable
        logger.debug("discovery goal context unavailable: %s", exc)
        return []


async def cycle_context(
    workspace_id: str, project_id: str, user_id: str, *, cycle_key: str
) -> DiscoveryCycleContext:
    """One cycle's full context, read fresh at node execution time.

    Charges the budget for this Run (idempotently) and refuses cleanly when
    the feature is off or the day's budget is spent — the refusal travels to
    the fetch node as its output, so a scheduled fire ends as an honest,
    visible no-op rather than new spend.
    """
    config = get_config(workspace_id)
    ledger = today_ledger(workspace_id)
    refusal = discovery_refusal(config, ledger)
    if refusal is not None:
        return DiscoveryCycleContext(budget_refusal=refusal)
    _charge(workspace_id, config, ledger, cycle_key=cycle_key)

    notes = [
        *await _persona_notes(workspace_id),
        *await _user_model_notes(user_id),
        *await _goal_notes(user_id, workspace_id),
    ]
    downweights = [
        (category, weight)
        for category, weight in category_preferences(workspace_id).items()
        if weight < 1.0
    ]
    return DiscoveryCycleContext(
        watch_topics=tuple(str(t) for t in config.get("watch_topics", [])),
        context_notes=tuple(notes),
        seen_fingerprints=seen_fingerprints(workspace_id),
        category_downweights=tuple(downweights),
        source_binding_id=str(config.get("source_binding_id") or ""),
        curator_binding_id=str(config.get("curator_binding_id") or ""),
        curator_model=str(config.get("curator_model") or ""),
        max_candidates=int(config.get("max_candidates_per_cycle") or 0),
        max_surfaced=int(config.get("max_surfaced") or 0),
        min_scout_score=float(config.get("min_scout_score") or 0.0),
    )


class HiveDiscoveryContext:
    """The ``discovery_context`` authority wired into the node resolver."""

    async def context_for(
        self, workspace_id: str, project_id: str, user_id: str, cycle_key: str = ""
    ) -> DiscoveryCycleContext:
        return await cycle_context(workspace_id, project_id, user_id, cycle_key=cycle_key)


_context: HiveDiscoveryContext | None = None


def discovery_context_provider() -> HiveDiscoveryContext:
    global _context
    if _context is None:
        _context = HiveDiscoveryContext()
    return _context


# ---------------------------------------------------------------------------
# Trigger + lift
# ---------------------------------------------------------------------------


async def run_discovery_cycle(
    workspace_id: str,
    project_id: str,
    user_id: str,
    *,
    actor_id: str,
    admission_source: str = "discovery_manual",
) -> dict[str, Any]:
    """Trigger one bounded discovery cycle as a canonical Run.

    The gate runs before admission: a disabled feature or an exhausted
    budget refuses with ``DiscoveryCycleRefused`` and no Run exists — budget
    exhaustion stops new discovery cleanly, not mid-flight.
    """
    from services.workspace_authority import visible_view

    if await visible_view(user_id, workspace_id) is None:
        raise DiscoveryNotVisible(workspace_id)
    config = get_config(workspace_id)
    refusal = discovery_refusal(config, today_ledger(workspace_id))
    if refusal is not None:
        raise DiscoveryCycleRefused(refusal)

    from services.dag_agents import run_registered_dag

    provenance = {
        "admission_source": admission_source,
        "feature": "proactive_discovery",
        "triggered_by": actor_id,
        "request_id": uuid.uuid4().hex[:12],
    }
    _, record = await run_registered_dag(
        DISCOVERY_DAG_ID,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        provenance=provenance,
    )
    surfaced = _lift_workspace_idempotent(workspace_id, record)
    return {
        "run_id": record.run.run_id,
        "status": str(getattr(record.run.status, "value", record.run.status)),
        "surfaced": surfaced,
    }


def _run_status(record: Any) -> str:
    status = getattr(record.run, "status", "")
    return str(getattr(status, "value", status) or "").lower()


def _curate_items_from_record(record: Any) -> list[dict[str, Any]]:
    """The curator node's output items from one durable run record."""
    items: list[dict[str, Any]] = []
    for node_run in getattr(record, "node_runs", ()) or ():
        if str(getattr(node_run, "node_id", "")) != "discovery_curate":
            continue
        result = getattr(node_run, "result", None)
        if isinstance(result, dict):
            rows = result.get("items")
        elif result is not None and hasattr(result, "items"):
            rows = getattr(result, "items", [])
        else:
            rows = []
        for row in rows or ():
            if isinstance(row, dict):
                items.append(dict(row))
            elif hasattr(row, "model_dump"):
                items.append(row.model_dump())
    return items


def lift_cycle(workspace_id: str, record: Any, *, now: datetime | None = None) -> int:
    """Persist one completed cycle's curated items (deduped, capped).

    Fingerprints already surfaced or seen are suppressed here — the durable
    suppression layer behind "duplicate items never re-surface". Returns how
    many items this lift added.
    """
    now = now or datetime.now(UTC)
    config = get_config(workspace_id)
    cap = int(config.get("max_surfaced") or 3)
    items = _curate_items_from_record(record)
    if not items:
        return 0
    items.sort(key=lambda i: (-float(i.get("score") or 0.0), str(i.get("fingerprint"))))
    seen = seen_fingerprints(workspace_id)
    added: list[str] = []
    evaluated: list[str] = []
    for item in items:
        fingerprint = str(item.get("fingerprint") or "")
        if not fingerprint or fingerprint in seen or fingerprint in evaluated:
            continue
        evaluated.append(fingerprint)
        if len(added) >= cap:
            continue
        record_row = {
            **item,
            "workspace_id": workspace_id,
            "status": "surfaced",
            "surfaced_at": now.isoformat(),
            "run_id": str(item.get("run_id") or getattr(record.run, "run_id", "")),
        }
        store[_item_key(workspace_id, fingerprint)] = record_row
        added.append(fingerprint)
    # Every curated fingerprint becomes seen — surfaced or capped — so a
    # later cycle never re-surfaces what this one already evaluated.
    _record_seen(workspace_id, evaluated)
    ledger = today_ledger(workspace_id)
    _record_surface(workspace_id, ledger, len(added))
    if added:
        from routes.audit import log_audit

        log_audit(
            "discovery_surfaced",
            "system",
            target=workspace_id,
            detail={"count": len(added), "run_id": str(getattr(record.run, "run_id", ""))},
        )
    return len(added)


def _lift_workspace_idempotent(workspace_id: str, record: Any) -> int:
    """Lift once per Run: a retried read never re-surfaces the same cycle."""
    run_id = str(getattr(record.run, "run_id", ""))
    raw = store.get(_lifted_key(workspace_id))
    lifted: dict[str, str] = raw if isinstance(raw, dict) else {}
    if run_id and run_id in lifted:
        return 0
    count = lift_cycle(workspace_id, record)
    if run_id:
        lifted[run_id] = datetime.now(UTC).isoformat()
        store[_lifted_key(workspace_id)] = lifted
    return count


def _item_fresh(item: dict[str, Any], *, now: datetime) -> bool:
    expires = str(item.get("expires_at") or "").strip()
    if expires:
        try:
            stamp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return stamp > now
        except ValueError:
            pass
    surfaced_at = str(item.get("surfaced_at") or "").strip()
    if not surfaced_at:
        return True
    try:
        stamp = datetime.fromisoformat(surfaced_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp) <= timedelta(hours=SURFACE_FRESH_HOURS)


async def _lift_pending_scheduled_runs(user_id: str, workspace_id: str) -> None:
    """Lift completed scheduled discovery Runs this Workspace has not lifted.

    A configured production schedule fires through the canonical admitter and
    the Container consumer, which has no per-template completion hook — so
    the first authorized Workspace read that sees the Run lifts its curated
    output here. The lift is idempotent per Run, so concurrent reads converge
    instead of re-surfacing the same candidates.
    """
    from services import dag_run_inspection
    from services.dag_agents import get_canonical_run_store

    try:
        summaries = await dag_run_inspection.list_visible_runs(user_id, limit=200)
    except Exception as exc:  # pragma: no cover - inspection unavailable
        logger.debug("discovery scheduled-run scan unavailable: %s", exc)
        return
    raw = store.get(_lifted_key(workspace_id))
    lifted: dict[str, str] = raw if isinstance(raw, dict) else {}
    candidates = [
        summary
        for summary in summaries
        if str(summary.get("workspace_id") or "") == workspace_id
        and str(summary.get("dag_id") or "") == DISCOVERY_DAG_ID
        and str(summary.get("status") or "") == "completed"
        and str(summary.get("id") or "") not in lifted
    ]
    if not candidates:
        return
    try:
        run_store = get_canonical_run_store()
    except Exception as exc:  # pragma: no cover - spine unavailable
        logger.debug("discovery scheduled-run lift unavailable: %s", exc)
        return
    for summary in candidates:
        run_id = str(summary.get("id") or "")
        try:
            record = await run_store.get(run_id)
        except Exception as exc:
            logger.warning("discovery lift failed for run %s: %s", run_id, exc)
            continue
        if record is None:
            continue
        _lift_workspace_idempotent(workspace_id, record)


async def surfaced_items(user_id: str, workspace_id: str) -> dict[str, Any]:
    """The small curated set Home/Waiting may project, with counts.

    Membership-scoped like every Workspace read. Also lifts any completed
    scheduled discovery Runs this read is first to see, so an overnight
    schedule's work surfaces without a separate writer path.
    """
    from services.workspace_authority import visible_view

    if await visible_view(user_id, workspace_id) is None:
        raise DiscoveryNotVisible(workspace_id)
    await _lift_pending_scheduled_runs(user_id, workspace_id)
    return _surfaced_items_impl(workspace_id)


def _surfaced_items_impl(workspace_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    config = get_config(workspace_id)
    cap = int(config.get("max_surfaced") or 3)
    items: list[dict[str, Any]] = []
    dismissed = 0
    stale = 0
    prefix = f"item:{workspace_id}:"
    for key, row in store.items():
        if not key.startswith(prefix) or not isinstance(row, dict):
            continue
        if str(row.get("status") or "") != "surfaced":
            dismissed += 1
            continue
        if not _item_fresh(row, now=now):
            stale += 1
            continue
        items.append(row)
    items.sort(
        key=lambda i: (
            -float(i.get("score") or 0.0),
            str(i.get("surfaced_at") or ""),
        )
    )
    return {
        "workspace_id": workspace_id,
        "items": items[:cap],
        "counts": {
            "surfaced": len(items),
            "shown": min(len(items), cap),
            "dismissed": dismissed,
            "stale_suppressed": stale,
        },
        "budget": budget_status(workspace_id),
    }


async def record_feedback(
    workspace_id: str, fingerprint: str, action: str, *, actor: str
) -> dict[str, Any]:
    """Keep/dismiss one surfaced item; the preference state shapes next cycles.

    ``dismiss`` also hides the item from Waiting via the Attention dismissal
    preference (same source identity), so one user action updates both the
    selection evidence and this Workspace's projection.
    """
    if action not in {"keep", "dismiss"}:
        raise ValueError("action must be keep or dismiss")
    key = _item_key(workspace_id, fingerprint)
    row = store.get(key)
    if not isinstance(row, dict):
        raise KeyError(fingerprint)
    row["status"] = "kept" if action == "keep" else "dismissed"
    row["feedback"] = {
        "action": action,
        "by": actor,
        "at": datetime.now(UTC).isoformat(),
    }
    store[key] = row
    _record_feedback_preference(workspace_id, str(row.get("category") or ""), action)
    if action == "dismiss":
        try:
            from services.attention import record_dismissal

            record_dismissal(
                workspace_id, "discovery_item", fingerprint, actor=actor, action="dismiss"
            )
        except Exception as exc:  # pragma: no cover - attention unavailable
            logger.debug("attention dismissal not recorded: %s", exc)
    from routes.audit import log_audit

    log_audit(
        "discovery_feedback",
        actor,
        target=workspace_id,
        detail={"fingerprint": fingerprint, "action": action},
    )
    return row


__all__ = [
    "DISCOVERY_DAG_ID",
    "DISCOVERY_STORE",
    "DiscoveryCycleRefused",
    "DiscoveryNotVisible",
    "budget_status",
    "category_preferences",
    "cycle_context",
    "discovery_context_provider",
    "discovery_refusal",
    "get_config",
    "lift_cycle",
    "record_feedback",
    "run_discovery_cycle",
    "seen_fingerprints",
    "surfaced_items",
    "today_ledger",
    "update_config",
]
