"""Scoped inspection over the DAG-Run projection — the one authorization door (#1174).

`DagRunStore` is projection storage (#697): it answers what a run recorded to
whoever holds the id. That is an implementation detail, not an authorization
decision. Every reader of run data — the list/detail/SSE API routes and the
in-repo consumers that inspect runs (eval-judge scoring and its verdict
read side today; #804/#1046 extend the same door to Workspace/Home/Attention
surfaces) — goes through this module, which enforces the same canonical
boundary every other scoped Hive surface uses: the caller's Workspace
universe from `services.workspace_authority` (#37). Hive's legacy Workspace records are
never consulted here; the authority is the canonical store and nothing else.

A run is visible only inside the Workspace the canonical Run was admitted
into (mirrored onto the projection by the write path). A projection row that
carries no Workspace scope is a row written before #1174 threaded scope
through `start_run`: it is visible to no one, fail-closed, until #1036's
canonical inspection migration retires or re-scopes it.

`run.user_id` is deliberately NOT an authorization shortcut here. The
canonical boundary is Workspace membership; a route-local
`user_id == ...` comparison would be a second, divergent authority (#1174's
stop condition).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from services.dag_run_store import MAX_RUNS, get_dag_run_store
from services.workspace_authority import list_views_for_user


def _canonical_run_id(record: dict[str, Any]) -> str:
    return str(record.get("canonical_run_id") or record.get("id") or "")


async def _readable_canonical_runs(run_ids: list[str], user_id: str) -> dict[str, Any]:
    """The canonical Runs among `run_ids` that `user_id` may read, keyed by id."""
    wanted = [run_id for run_id in run_ids if run_id]
    if not wanted:
        return {}
    try:
        from services.engine import get_engine

        reader = get_engine().run_reader
        if reader is None:
            return {}
        return dict(await reader.get_runs(wanted, principal_id=user_id))
    except Exception:
        # Projection reads remain available in standalone mode, but never
        # invent canonical status when the spine is unavailable.
        return {}


def _overlay(record: dict[str, Any], run: Any) -> dict[str, Any]:
    # No readable canonical Run -- none recorded, or one outside the caller's
    # Workspaces (#1152) -- leaves the projection row as it is.
    if run is None:
        return record
    # A canonical Run filed in a different Workspace than the projection row
    # is a cross-link (legacy or corrupt), not this row's lifecycle truth,
    # even when the caller can read both Workspaces.
    if run.workspace_id != str(record.get("workspace_id") or ""):
        return record
    creative = _creative_run_provenance(run)
    return {
        **record,
        # Canonical lifecycle truth replaces the projection row's wholesale
        # (#1877): status, result, error AND finished_at all come from the
        # canonical Run now. A null canonical result/error overwrites a stale
        # projection value instead of letting it stand, a nonterminal Run
        # clears any stale finished_at (the Run model forbids finished_at on
        # nonterminal Runs), and a terminal Run's finished_at converts to the
        # epoch-seconds shape the projection already serves -- derived from
        # the canonical timestamp only, never a wall-clock value minted at
        # read time.
        "status": run.status.value,
        "result": run.result,
        "error": run.error,
        "finished_at": (run.finished_at.timestamp() if run.finished_at is not None else None),
        **({"creative_provenance": creative} if creative else {}),
    }


_CREATIVE_PROVENANCE_KEYS: tuple[str, ...] = (
    "goal_id",
    "goal_revision",
    "brief_id",
    "brief_lineage_id",
    "brief_version",
    "goal_owner_agent_id",
    "goal_delegation_ref",
    "persona_id",
    "design_system_slug",
    "graph_template",
)


def _creative_run_provenance(run: Any) -> dict[str, Any]:
    """The creative-fulfillment lineage a readable canonical Run carries (#775).

    `maistro_design.creative_graph.run_creative_graph` records a
    `goal_run_evidence` provenance block on the canonical Run (the #458
    Goal-Run evidence relationship): the exact Goal identity/revision it
    fulfills, the CreativeBrief lineage/version that plans it, and the
    accountable/delegated Agent. Inspection relays that block verbatim so
    Conductor's Graph inspection can say which Goal revision, brief version
    and Agent delegation stand behind a run — no Design-Studio-private read,
    and no lineage for runs that never carried one.
    """
    provenance = dict(getattr(run, "provenance", None) or {})
    if provenance.get("relationship") != "goal_run_evidence":
        return {}
    return {key: provenance[key] for key in _CREATIVE_PROVENANCE_KEYS if key in provenance}


async def _creative_artifacts(canonical_run_id: str) -> list[dict[str, Any]]:
    """Per-artifact lineage from the persisted canonical durable record (#775).

    Reads the DurableRunRecord the canonical executor already checkpointed —
    Run provenance, NodeRuns, Attempts, graph snapshot, blackboard snapshot —
    through `maistro_design.creative_graph.artifact_provenance`, so each
    artifact names the Goal revision, CreativeBrief version, consumed
    shared-decision identities and Agent delegation that produced it, plus
    its status and attempt count. Reconstruction from persisted state only:
    no workflow replay, no client memory. The store read is keyed by a run id
    the scoped reader has already authorized for this caller, so this opens
    no second authorization door.
    """
    try:
        from maistro_design.creative_graph import artifact_provenance
        from services.engine import get_engine

        durable_store = get_engine().graph_run_store
        if durable_store is None:
            return []
        durable_record = await durable_store.get(canonical_run_id)
    except Exception:
        # Inspection stays available without the durable graph spine, exactly
        # like the canonical-status overlay above; it then answers without
        # per-artifact graph state rather than inventing any.
        return []
    if durable_record is None:
        return []
    return [asdict(item) for item in artifact_provenance(durable_record)]


async def _canonical_projection(record: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Overlay lifecycle truth from the canonical Run `user_id` may read, if any."""
    run_id = _canonical_run_id(record)
    runs = await _readable_canonical_runs([run_id], user_id)
    return _overlay(record, runs.get(run_id))


async def authorized_workspace_ids(user_id: str) -> set[str]:
    """The canonical Workspaces whose runs `user_id` may inspect.

    One universe, computed once per request and shared by the list and the
    by-id lookups, so the two can never disagree about what is visible
    (#1174).
    """
    views = await list_views_for_user(user_id)
    return {view.id for view in views}


def _in_scope(record: dict[str, Any], allowed: set[str]) -> bool:
    # An empty scope is never in scope: a record that names no Workspace
    # proves nothing about where it executed, and guessing a visibility rule
    # for it would rebuild the leak this closes.
    return str(record.get("workspace_id") or "") in allowed


async def list_visible_runs(user_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Recent-run summaries, restricted to the caller's Workspace universe."""
    allowed = await authorized_workspace_ids(user_id)
    # Fetch the complete retained window before applying the caller's limit.
    # Limiting the global projection first lets a burst of foreign runs hide a
    # caller's own older run (or return an empty page), even though it is in
    # scope. Filtering first preserves normal pagination semantics without
    # exposing any additional rows. Each surviving summary is overlaid with
    # canonical execution truth before the caller's limit is applied.
    in_scope = [
        summary
        for summary in get_dag_run_store().list_runs(limit=MAX_RUNS)
        if _in_scope(summary, allowed)
    ]
    # One batched canonical read for the page, not one membership resolution
    # per row.
    runs = await _readable_canonical_runs(
        [_canonical_run_id(summary) for summary in in_scope], user_id
    )
    visible = [_overlay(summary, runs.get(_canonical_run_id(summary))) for summary in in_scope]
    return visible[:limit]


async def can_inspect_run(user_id: str, run_id: str) -> bool:
    """May `user_id` open this run's detail/event stream?

    Called before the SSE route opens anything: the stream, its replay, and
    every existence signal behind it stay closed until this says yes (#1174).
    """
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return False
    allowed = await authorized_workspace_ids(user_id)
    return _in_scope(record, allowed)


async def visible_run_detail(user_id: str, run_id: str) -> dict[str, Any] | None:
    """Full detail for one run, or None when it may not be inspected.

    None is the answer for "does not exist" AND for "exists beyond your
    boundary" — deliberately indistinguishable, so a cross-Workspace id gets
    the same 404-shaped refusal a missing id gets and the response confirms
    nothing about runs the caller cannot see (#1174).
    """
    record = get_dag_run_store().get_run(run_id)
    if record is None:
        return None
    allowed = await authorized_workspace_ids(user_id)
    if not _in_scope(record, allowed):
        return None
    detail = await _canonical_projection(record, user_id)
    # AC-10 (#775): Graph inspection in Conductor explains each artifact's
    # lineage. Only reachable when the creative block survived the scoped
    # overlay — i.e. the caller just read the canonical Run — so per-artifact
    # state is never exposed beyond the run-level authorization above.
    if detail.get("creative_provenance"):
        detail["artifacts"] = await _creative_artifacts(_canonical_run_id(record))
    return detail


async def visible_run_ids(user_id: str, run_ids: Iterable[str]) -> set[str]:
    """Which of these candidate run ids may `user_id` inspect?

    The list-shaped companion to `visible_run_detail` (the eval-judge verdict
    list reads through it, #1174): the caller's Workspace universe is resolved
    once for the whole batch, and every candidate is answered by the same
    projection-scope rule `visible_run_detail` applies, so a page-level answer
    and a by-id answer can never disagree about what is visible. A candidate
    whose run is missing — or whose projection row carries no Workspace scope
    — is simply absent from the result, exactly as it is invisible to the
    by-id readers.
    """
    allowed = await authorized_workspace_ids(user_id)
    store = get_dag_run_store()
    visible: set[str] = set()
    for run_id in run_ids:
        record = store.get_run(str(run_id))
        if record is not None and _in_scope(record, allowed):
            visible.add(str(run_id))
    return visible
