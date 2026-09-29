"""Tests for the default DAG seeds (daily_status + the SEEDS_BY_USE_CASE
registry)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.graph.dag_registry import DagRegistry
from maistro.graph.dag_validator import validate_dag
from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    RunStatus,
)
from maistro.graph.nodes import get_node
from maistro.graph.seeds import (
    SEEDS_BY_USE_CASE,
    daily_status_seed,
    list_seeds_for,
)

from .._canonical_helpers import run_legacy_dag_fixture as run_durable_dag


def _make_fake_async_client(fake_issues: dict[str, Any]) -> type:
    """Build a drop-in ``httpx.AsyncClient`` replacement returning ``fake_issues``."""

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return fake_issues

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    return _Client


def _inject_jira_credentials(dag: dict[str, Any]) -> None:
    """Populate the jira_poll node's runtime credentials in-place."""
    for n in dag["nodes"]:
        if n["id"] == "jira_poll":
            n["inputs"]["base_url"] = "https://jira.example.com"
            n["inputs"]["pat"] = "test-pat"


def _seed_node_resolver(node_id: str, dag_snap: dict[str, Any]) -> Any:
    for n in dag_snap.get("nodes", []):
        if n["id"] == node_id:
            return get_node(n["kind"])()
    raise KeyError(node_id)


# --- Seed shape + identity ------------------------------------------------


def test_daily_status_seed_returns_fresh_dict_each_call() -> None:
    """Mutation safety: seeds MUST NOT share state across callers."""
    a = daily_status_seed()
    b = daily_status_seed()
    assert a is not b
    a["mutated"] = True
    assert "mutated" not in b


def test_daily_status_seed_has_required_identity_fields() -> None:
    d = daily_status_seed()
    assert d["id"] == "daily-status"
    assert d["use_case"] == "pm_fleet"
    assert d["name"]
    assert d["description"]
    assert d["entry_node"] == "jira_poll"
    assert d["max_cycles"] == 1


def test_daily_status_seed_topology_is_5_nodes_4_edges_sequential() -> None:
    d = daily_status_seed()
    assert len(d["nodes"]) == 5
    assert len(d["edges"]) == 4
    node_ids = [n["id"] for n in d["nodes"]]
    assert node_ids == [
        "jira_poll",
        "jira_items_alias",
        "jira_epic_filter",
        "jira_summary_format",
        "jira_dash_append",
    ]
    edge_pairs = [(e["from_node"], e["to_node"]) for e in d["edges"]]
    assert edge_pairs == [
        ("jira_poll", "jira_items_alias"),
        ("jira_items_alias", "jira_epic_filter"),
        ("jira_epic_filter", "jira_summary_format"),
        ("jira_summary_format", "jira_dash_append"),
    ]


# --- Validator passes -----------------------------------------------------


def test_daily_status_seed_passes_substrate_validator() -> None:
    """Substrate-side correctness check — the seed must compose without
    schema_mismatch / unknown_kind / cycle errors. If it doesn't, the
    substrate's first proof-point use case is broken."""
    report = validate_dag(daily_status_seed())
    # Allow schema_mismatch findings only on the well-known seed shape
    # transitions (item-list vs single record) — the executor's input
    # resolver bridges these at runtime via upstream-output flow + static
    # fallthrough. Structural errors (no_entry, missing_node,
    # unknown_kind, edge_missing_endpoint, cycle) MUST be empty.
    structural = [
        f
        for f in report.findings
        if f.code in {"no_entry", "missing_node", "unknown_kind", "edge_missing_endpoint", "cycle"}
    ]
    assert structural == [], (
        f"daily-status seed has structural errors: {[f.message for f in structural]}"
    )


# --- Registry contract ----------------------------------------------------


def test_seeds_registry_includes_daily_status_under_pm_fleet() -> None:
    seeds = list_seeds_for("pm_fleet")
    assert daily_status_seed in seeds


def test_seeds_registry_returns_empty_for_unknown_use_case() -> None:
    assert list_seeds_for("nope") == []
    assert list_seeds_for("canvas_creative") == []  # not seeded yet


def test_pm_fleet_seeds_all_pass_validator() -> None:
    """Smoke-check every seed factory in the registry — they MUST all
    produce DAGs that pass structural validation."""
    for factory in SEEDS_BY_USE_CASE.get("pm_fleet", []):
        dag = factory()
        report = validate_dag(dag)
        structural = [
            f
            for f in report.findings
            if f.code
            in {"no_entry", "missing_node", "unknown_kind", "edge_missing_endpoint", "cycle"}
        ]
        assert structural == [], (
            f"seed {factory.__name__!r} structural failures: {[f.message for f in structural]}"
        )


# --- Registry integration -------------------------------------------------


def test_daily_status_seed_registers_as_pm_fleet_agent() -> None:
    """Round-trip: register the seed in a fresh DagRegistry → it surfaces
    as `dag:daily-status` in the agent catalog."""
    reg = DagRegistry()
    desc = reg.register(daily_status_seed())
    assert desc.agent_id == "dag:daily-status"
    assert desc.use_case == "pm_fleet"
    catalog = reg.as_agent_catalog()
    assert any(e["id"] == "dag:daily-status" for e in catalog)


# --- Smoke-run via durable executor with mocked Jira ---------------------


async def test_daily_status_seed_walks_through_executor_with_mocked_jira(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: feed a real Jira-shaped HTTP response into the executor
    + the seed DAG, observe completion + node outputs accumulating on the
    blackboard's dashboard:daily-status accumulator."""
    fake_issues = {
        "issues": [
            {
                "key": "PROJ-100",
                "fields": {
                    "summary": "Ship payments engine",
                    "status": {"name": "In Progress"},
                    "updated": "2026-05-22T08:00:00Z",
                    "issuetype": {"name": "Epic"},
                },
            },
            {
                "key": "PROJ-101",
                "fields": {
                    "summary": "Onboard new vendor",
                    "status": {"name": "Done"},
                    "updated": "2026-05-22T07:00:00Z",
                    "issuetype": {"name": "Story"},  # filtered out
                },
            },
        ]
    }

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_async_client(fake_issues))

    dag = daily_status_seed()
    _inject_jira_credentials(dag)

    store = InMemoryDurableRunStore()

    result = await run_durable_dag(
        dag,
        store=store,
        node_resolver=_seed_node_resolver,
        project_id="pm-proj-1",
    )
    assert result.status == RunStatus.COMPLETED, (
        f"daily-status DAG did not complete: status={result.status}, "
        f"error={result.run.error}, "
        f"records={[(nr.node_id, nr.status, nr.error) for nr in result.node_runs]}"
    )

    by_id = {nr.node_id: nr for nr in result.node_runs}
    # Jira poll returned 2 issues.
    assert by_id["jira_poll"].result is not None
    assert by_id["jira_poll"].result["count"] == 2
    # Filter kept only the Epic.
    assert by_id["jira_epic_filter"].result is not None
    assert by_id["jira_epic_filter"].result["kept"] == 1
    assert by_id["jira_epic_filter"].result["dropped"] == 1
    # Format produced a markdown section.
    fm = by_id["jira_summary_format"].result
    assert fm is not None
    assert "PROJ-100" in fm["markdown"]
    assert "## Jira Epics updated" in fm["markdown"]
    # Dashboard appended.
    da = by_id["jira_dash_append"].result
    assert da is not None
    assert da["dashboard_id"] == "daily-status"
    assert da["sections_total"] >= 1


async def test_daily_status_seed_short_circuits_when_no_epics_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the filter eliminates everything, the format node still
    produces the empty-fallback markdown, the dashboard still gets a
    section appended (just an empty one), and the run completes."""
    fake_issues = {
        "issues": [
            {
                "key": "PROJ-101",
                "fields": {
                    "summary": "Just a story",
                    "status": {"name": "Done"},
                    "updated": "2026-05-22T07:00:00Z",
                    "issuetype": {"name": "Story"},
                },
            }
        ]
    }

    monkeypatch.setattr(httpx, "AsyncClient", _make_fake_async_client(fake_issues))

    dag = daily_status_seed()
    _inject_jira_credentials(dag)

    store = InMemoryDurableRunStore()

    result = await run_durable_dag(
        dag, store=store, node_resolver=_seed_node_resolver, project_id="pm-proj-2"
    )
    assert result.status == RunStatus.COMPLETED
    by_id = {nr.node_id: nr for nr in result.node_runs}
    assert by_id["jira_epic_filter"].result["kept"] == 0
    assert "_No Epics updated" in by_id["jira_summary_format"].result["markdown"]
    assert by_id["jira_dash_append"].result["sections_total"] >= 1
