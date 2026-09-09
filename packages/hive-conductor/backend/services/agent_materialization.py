"""The single write path for hive-conductor's `stores.agents`.

`stores.agents` is a durable product projection -- a card index the Conductor
shows and the pulse resolves against, not an execution authority (the runtime
roster is `container.agents`, built by maistro's factory). This module is the
ONLY place permitted to mutate it; `scripts/check-agent-store-writes.py`
enforces that in CI. Every producer funnels through here:

  - `materialize_workspace_agents`  -- persona spawns → workspace-scoped rows
  - `materialize_manifest_roster`   -- the canonical factory roster → global rows
  - `upsert_agent_definition` / `update_agent_definition` /
    `delete_agent_definition` -- the CRUD, Forge, and chat-tool fronts
  - `delete_workspace_agents`       -- the workspace-delete cascade
  - the `_seed*` demo roster        -- demo mode only, at the store's own
    definition site (`stores.py`)

Centralizing the writers is what lets the invariants only Forge used to
enforce become shared: a Warden scan before store (fail-closed), stable
collision-safe ids, `workspace_id` tagging, and a uniform provenance stamp.
It started as the narrower piece connecting `maistro.personas.expander.
expand_persona()` (persona -> named agent roster) to the roster
`GET/POST /v1/agents` reads. Every persona is treated identically here:
`pm_fleet` is just one premade template like any other -- whichever persona a
workspace adopts, its own declared `spawns` become real, visible agents
through the exact same path, no special-casing.

`expand_persona()`'s `ExpandedAgent.active` governance flag ("flipped by
the review gate") has no reviewer anywhere in the codebase to flip it --
that comment describes a mechanism that was never built. A workspace's own
agents are usable as soon as the workspace exists, same as everything else
a persona declares (tools, checklist, theme) -- there's nothing to wait on.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import stores
from config import get_settings
from models.schemas import Agent

from maistro.personas.expander import expand_persona
from maistro.personas.schema import PersonaTemplate
from maistro.security.warden.detector import Warden

from .model_store import register_pop_hook

logger = logging.getLogger("hive.agents")

#: `config["provenance"]["source"]` for rows projected from the canonical
#: roster. The reap in `materialize_manifest_roster` removes exactly the
#: global rows carrying this stamp whose name the current roster no longer
#: declares -- user-created rows (CRUD uuid4 ids, `forge-*`, `chat-*`,
#: workspace-scoped `{workspace}.{spawn}`) are never touched by it.
MANIFEST_ROSTER_SOURCE = "manifest-roster"


class AgentDefinitionRejected(ValueError):
    """A definition write was refused: the Warden scan flagged it.

    Fail-closed by construction: the caller raised this before anything was
    stored, so a flagged definition can never surface as a stored row."""


class AgentScannerUnavailable(RuntimeError):
    """The Warden scanner could not run; nothing was stored.

    The same rule Forge set: a scan that did not complete can never surface
    as a stored state, so a broken scanner refuses the write instead of
    waving it through."""


# ─── Warden config scan ────────────────────────────────────────────────────
#
# Lives here rather than in a route module because scan-before-store is this
# service's write invariant, and services must not import routes. The route
# module re-exports `scan_config` / `ScanBudgetExceeded` so the HITL door and
# the chat gate -- which predate this move -- keep their import paths.

MAX_SCAN_DEPTH = 32
MAX_SCAN_NODES = 4096
MAX_SCAN_TEXT = 64 * 1024


class ScanBudgetExceeded(Exception):
    """The config is larger or deeper than the scanner will walk."""


def _text_leaves(value: object, *, path: str = "", depth: int = 0) -> Iterator[tuple[str, str]]:
    """Yield every (dotted path, string) pair in a config, in a bounded walk."""
    if depth > MAX_SCAN_DEPTH:
        raise ScanBudgetExceeded(f"config nests deeper than {MAX_SCAN_DEPTH} levels")
    if isinstance(value, str):
        yield path or "<root>", value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _text_leaves(item, path=child, depth=depth + 1)
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _text_leaves(item, path=f"{path}[{index}]", depth=depth + 1)


def _warden() -> Warden:
    """One detector for the process."""
    global _warden_instance
    if _warden_instance is None:
        _warden_instance = Warden()
    return _warden_instance


_warden_instance: Warden | None = None


async def scan_config(config: object, *, boundary: str = "user_input") -> dict:
    """Scan every string in a configuration at a Warden boundary.

    The default boundary is the one inbound configurations cross; `tool_result`
    selects the detector's second boundary (#315) so tool outputs that will be
    re-fed to a model are judged by the same detector, not a second check.
    """
    warden = _warden()
    findings: list[str] = []
    for scanned, (path, text) in enumerate(_text_leaves(config), start=1):
        if scanned > MAX_SCAN_NODES:
            raise ScanBudgetExceeded(f"config holds more than {MAX_SCAN_NODES} values")
        if len(text) > MAX_SCAN_TEXT:
            raise ScanBudgetExceeded(f"{path} is longer than {MAX_SCAN_TEXT} characters")
        verdict = await warden.scan(text, boundary)
        if not verdict.clean:
            findings.extend(f"{path}: {flag}" for flag in verdict.flags)
    return {"findings": findings, "status": "clean" if not findings else "flagged"}


# ─── Definition writes: the CRUD / Forge / chat-tool fronts ───────────────


def _provenance(source: str, scan: dict | None, when: datetime) -> dict[str, Any]:
    """The uniform provenance stamp every stored definition carries.

    Records which producer wrote the row and the Warden verdict that gated the
    write -- so a row's validation history is readable off the row itself, the
    way Forge's `config["forge"]["scan"]` already reads. A caller-supplied
    verdict (Forge scans before it calls) is recorded as-is; the service ran
    the scan itself otherwise."""
    entry: dict[str, Any] = {"source": source, "timestamp": when.isoformat()}
    if scan is not None:
        entry["scan"] = {
            "boundary": "user_input",
            "status": scan.get("status", "flagged" if scan.get("findings") else "clean"),
            "findings": list(scan.get("findings", [])),
            "scanned_at": when.isoformat(),
        }
    return entry


def _reject_if_flagged(scan: dict) -> None:
    if scan.get("findings"):
        raise AgentDefinitionRejected("; ".join(str(f) for f in scan["findings"]))


async def upsert_agent_definition(
    agent: Agent,
    *,
    source: str,
    scan: dict | None = None,
) -> Agent:
    """Store one Agent definition -- the only way a row enters the store.

    Scan before store, fail-closed: a flagged definition raises
    `AgentDefinitionRejected`, a scanner that cannot run raises
    `AgentScannerUnavailable`, and a scan budget that cannot be met raises
    `ScanBudgetExceeded` -- in all three cases nothing is stored. A caller
    that already scanned (Forge) may pass its verdict through; the service
    still refuses to record anything but a clean one. The stored row carries
    the provenance stamp either way, so a caller cannot forge one through
    `config`.
    """
    t = datetime.now(UTC)
    if scan is None:
        try:
            scan = await scan_config(agent.model_dump(mode="json"))
        except ScanBudgetExceeded:
            raise
        except Exception as exc:
            logger.warning("agent store scan failed closed for %s: %s", agent.id, exc)
            raise AgentScannerUnavailable(
                "the security scan could not run; nothing was stored"
            ) from exc
    _reject_if_flagged(scan)
    config = dict(agent.config)
    config["provenance"] = _provenance(source, scan, t)
    stored = agent.model_copy(update={"config": config})
    stores.agents[stored.id] = stored
    return stored


async def update_agent_definition(
    agent_id: str,
    updates: dict[str, Any],
    *,
    source: str,
) -> Agent:
    """Apply a patch to a stored definition through the same gate as a create.

    Raises `KeyError` when no such row exists; raises the same scan refusals
    `upsert_agent_definition` raises, judging the merged record -- an update
    is a new stored state, not a delta that escapes the scan.
    """
    existing = stores.agents.get(agent_id)
    if existing is None:
        raise KeyError(agent_id)
    merged = existing.model_copy(update=updates)
    return await upsert_agent_definition(merged, source=source)


def delete_agent_definition(agent_id: str) -> bool:
    """Remove one definition. Returns whether a row was actually removed."""
    return stores.agents.pop(agent_id, None) is not None


# ─── Stable ids ────────────────────────────────────────────────────────────


def agent_id_for(workspace_id: str, spawn_agent: str) -> str:
    """Deterministic, workspace-scoped agent id. Stable across
    re-materialization: creating/updating the same workspace's agents again
    overwrites the same records rather than piling up duplicates."""
    return f"{workspace_id}.{spawn_agent}"


def slugify_agent_name(text: str, *, limit: int = 32) -> str:
    """A readable, stable, id-safe slug for an agent name or description."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "agent"


def chat_agent_id(workspace_id: str | None, name: str) -> str:
    """The deterministic id a chat-created action gets.

    Workspace-scoped rows key exactly like materialized persona spawns --
    `agent_id_for` over the name the roster resolves (the spawn name, i.e.
    everything after the last dot), so the row is reachable by its own name
    through `resolve_agent`'s scoped-first lookup, and re-saving the same
    action in a workspace upserts that workspace's agent instead of piling up
    random-suffixed duplicates. Unscoped rows carry a `chat-` prefix so they
    can neither collide with a canonical roster name, a `forge-*` artifact,
    nor a demo `agent-N` row; they resolve by the id the tool returns."""
    name = str(name).strip()
    if workspace_id:
        return agent_id_for(workspace_id, name.rsplit(".", 1)[-1])
    return f"chat-{slugify_agent_name(name)}"


# ─── Persona materialization ───────────────────────────────────────────────


def materialize_workspace_agents(workspace_id: str, template: PersonaTemplate) -> list[Agent]:
    """Expand `template` and write one real Agent record per declared spawn
    into `stores.agents`, tagged with `workspace_id`. Returns the created
    records. A `kind: department` template (no spawns) materializes to an
    empty list -- nothing to do, not an error."""
    expanded = expand_persona(template)
    default_model = get_settings().chat_default_model
    now = datetime.now(UTC)
    agents: list[Agent] = []
    for expanded_agent in expanded.agents:
        recipe = expanded_agent.recipe
        spawn_agent = recipe.name.split(".", 1)[-1]
        aid = agent_id_for(workspace_id, spawn_agent)
        agent = Agent(
            id=aid,
            workspace_id=workspace_id,
            name=recipe.name,
            description=recipe.description,
            model=default_model,
            status="idle",
            capabilities=list(recipe.tools),
            skills=list(expanded_agent.skills),
            created_at=now,
            last_active=now,
        )
        stores.agents[aid] = agent
        agents.append(agent)
    return agents


def workspace_agents(workspace_id: str) -> list[Agent]:
    """Every agent materialized for this workspace."""
    return [a for a in stores.agents.values() if a.workspace_id == workspace_id]


def delete_workspace_agents(workspace_id: str) -> None:
    """Delete every materialized agent owned by ``workspace_id``.

    Called as a pre-delete lifecycle hook for the workspaces store so both the
    in-memory and persisted agent records disappear before their ownership
    record does. Iterating over a snapshot avoids mutating the store while its
    values view is live.
    """
    for agent in list(workspace_agents(workspace_id)):
        stores.agents.pop(agent.id, None)


# ─── Canonical roster materialization (#840) ──────────────────────────────


def _is_manifest_row(agent: Agent) -> bool:
    """Whether this row was projected from the canonical roster by us."""
    provenance = agent.config.get("provenance") if isinstance(agent.config, dict) else None
    return agent.workspace_id is None and (
        isinstance(provenance, dict) and provenance.get("source") == MANIFEST_ROSTER_SOURCE
    )


def materialize_manifest_roster(
    roster: Mapping[str, Any] | None,
    *,
    dispatchable: bool = True,
) -> list[Agent]:
    """Project the canonical roster -- the agents maistro's factory builds
    from the shipped manifests -- into `stores.agents` as GLOBAL rows.

    Rows are keyed by the roster's own names (`workspace_id=None`, so they
    land in `pulse_roster`'s global tail and can never shadow a workspace's
    own agent, and can never collide with `{workspace}.{spawn}` keys or
    `forge-*` fingerprints). `capabilities` come from the identity's tools,
    exactly as persona materialization maps a spawn's tools, so the capability
    union `resolve_agent_task`/`pulse_roster` read keeps one contract.

    Idempotent, per boot: upserting again refreshes the projection-owned
    fields of an existing projection in place (keeping `created_at` and the
    row's counters) rather than duplicating it, and reaps projected rows the
    current roster no longer declares -- the store is SQLite-durable, so a
    stale name would otherwise outlive its manifest forever. Rows the roster
    does not declare but did not project (user-created rows) are never reaped.

    `dispatchable=False` marks the rows honestly as carrying no runtime that
    could execute them (no embedded maistro-core bridge) -- the same
    no-fabricated-success rule StubAgentPort encodes.
    """
    now = datetime.now(UTC)
    projected: list[Agent] = []
    for key, runtime_agent in (roster or {}).items():
        identity = getattr(runtime_agent, "identity", None)
        if identity is None:
            continue
        aid = str(getattr(identity, "name", "") or key)
        if not aid:
            continue
        existing = stores.agents.get(aid)
        base = existing if existing is not None and _is_manifest_row(existing) else None
        config = dict(base.config) if base is not None else {}
        config["dispatchable"] = bool(dispatchable)
        config["provenance"] = _provenance(MANIFEST_ROSTER_SOURCE, None, now)
        row = Agent(
            id=aid,
            workspace_id=None,
            name=aid,
            description=str(getattr(identity, "description", "") or ""),
            model=str(getattr(identity, "model", "") or "auto"),
            status=base.status if base is not None else "idle",
            capabilities=list(getattr(identity, "tools", ()) or ()),
            skills=list(getattr(identity, "skills", ()) or ()),
            current_mission=base.current_mission if base is not None else None,
            tasks_completed=base.tasks_completed if base is not None else 0,
            avg_response_time_ms=base.avg_response_time_ms if base is not None else 0.0,
            last_active=base.last_active if base is not None else now,
            created_at=base.created_at if base is not None else now,
            config=config,
        )
        stores.agents[aid] = row
        projected.append(row)

    kept = {row.id for row in projected}
    reaped = 0
    for agent in list(stores.agents.values()):
        if agent.workspace_id is None and _is_manifest_row(agent) and agent.id not in kept:
            stores.agents.pop(agent.id, None)
            reaped += 1
    if projected or reaped:
        logger.info(
            "manifest roster materialized rows=%d reaped=%d dispatchable=%s",
            len(projected),
            reaped,
            dispatchable,
        )
    return projected


async def materialize_boot_roster(settings: Any, agent_port: Any) -> list[Agent] | None:
    """Boot projection of the canonical roster, or None where it does not run.

    Runs on EVERY boot in non-demo, non-POC modes -- not only when the store
    happens to be empty: the store is durable, so the when-empty branch alone
    would silently skip both re-materialization and stale-row reap after the
    first boot. Demo and PM-POC modes keep exactly the seeding they had.

    The roster comes from the bridge's container when one exists; without a
    bridge it is built the same way the bridge builds it (fail-closed:
    `require_agents=True`), and rows are stamped `dispatchable=False` because
    there is no runtime behind them. A roster that cannot be built at all
    produces NO rows and a loud boot error -- never the fabricated demo rows
    as a side effect.
    """
    from settings_defaults import is_pm_poc_mode

    if getattr(settings, "hive_mode", "production") == "demo" or is_pm_poc_mode():
        return None

    container = getattr(agent_port, "container", None)
    if container is not None and getattr(container, "agents", None):
        return materialize_manifest_roster(container.agents, dispatchable=True)

    from adapters.maistro_core import build_canonical_roster

    try:
        roster = await build_canonical_roster(settings)
    except Exception as exc:
        logger.error(
            "AGENT ROSTER NOT MATERIALIZED: the canonical roster could not be built "
            "from %s (%s: %s). stores.agents carries no manifest roster; the fabricated "
            "demo roster is demo-mode-only and will not substitute for it.",
            settings.maistro_agents_dir,
            type(exc).__name__,
            exc,
        )
        return []
    return materialize_manifest_roster(roster, dispatchable=False)


# Register once when the workspace routes import this module. Keeping the
# cascade at the store lifecycle boundary means future non-HTTP deletion paths
# cannot accidentally recreate permanent orphan agents.
register_pop_hook("workspaces", delete_workspace_agents)
