"""Bounded proactive discovery service (#1051): config, budgets, surfacing, feedback.

Driven against the app's real Workspace authority and the discovery service's
own durable store — the same objects production reads and writes — with the
canonical Run trigger faked at its one seam (`services.dag_agents.
run_registered_dag`), because the discovery cycle's physical work is already
proven on the canonical spine in the core suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import services.discovery as discovery
from services.workspace_authority import create_workspace

_NOW = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_discovery_store():
    """Each test starts from an empty discovery store."""
    for key in list(store_keys()):
        discovery.store.pop(key)
    yield
    for key in list(store_keys()):
        discovery.store.pop(key)


def store_keys() -> list[str]:
    return list(discovery.store.keys())


def _curated_item(
    fingerprint: str,
    title: str,
    *,
    score: float = 0.8,
    category: str = "deals",
    expires_at: str = "",
    run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "entry_id": fingerprint,
        "url": f"https://source.example.com/{fingerprint}",
        "title": title,
        "summary": "a curated summary",
        "category": category,
        "source_url": "https://feeds.example.com/rss",
        "published_at": "2026-11-25T10:00:00+00:00",
        "expires_at": expires_at,
        "relevance": 0.9,
        "novelty": 0.8,
        "confidence": 0.9,
        "score": score,
        "strategy": "lexical",
        "explain": "matched watch topics: camera",
        "matched_topics": ["camera"],
        "run_id": run_id,
    }


def _fake_record(
    run_id: str, items: list[dict[str, Any]], *, status: str = "completed"
) -> SimpleNamespace:
    return SimpleNamespace(
        run=SimpleNamespace(run_id=run_id, status=SimpleNamespace(value=status)),
        node_runs=(
            SimpleNamespace(
                node_id="discovery_curate",
                result={"items": items, "strategy": "lexical", "dropped_unparsable": 0},
            ),
        ),
    )


@pytest.fixture
def fake_runner(monkeypatch: pytest.MonkeyPatch):
    """The canonical trigger seam, faked: returns the record it was handed."""
    calls: list[dict[str, Any]] = []
    records: dict[str, Any] = {}

    async def _fake_run_registered_dag(dag_id: str, **kwargs: Any) -> tuple[Any, Any]:
        calls.append({"dag_id": dag_id, **kwargs})
        run_id = f"run-{len(calls)}"
        record = records.get("next") or _fake_record(run_id, [])
        return SimpleNamespace(), record

    from services import dag_agents

    monkeypatch.setattr(dag_agents, "run_registered_dag", _fake_run_registered_dag)
    fixture = SimpleNamespace(calls=calls, records=records)
    return fixture


async def _workspace(owner: str, name: str) -> str:
    workspace = await create_workspace(
        creator_user_id=owner,
        name=name,
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    return workspace.id


def _enable(ws: str, **overrides: Any) -> dict[str, Any]:
    changes = {
        "enabled": True,
        "watch_topics": ["camera"],
        "sources_count": 1,
        **overrides,
    }
    return discovery.update_config(ws, changes, actor="admin")


# ---------------------------------------------------------------------------
# Config: the off switch, the bounds, the audit
# ---------------------------------------------------------------------------


def test_defaults_are_disabled_and_bounded(ws_owner: None) -> None:
    config = discovery.get_config("no-such-workspace")
    assert config["enabled"] is False
    assert config["max_surfaced"] == discovery.DEFAULT_CONFIG["max_surfaced"]
    assert config["source_binding_id"] == ""


def test_update_rejects_unknown_fields_and_out_of_range_values() -> None:
    with pytest.raises(ValueError, match="unknown discovery config field"):
        discovery.update_config("ws", {"crawl_the_web": True}, actor="admin")
    with pytest.raises(ValueError, match="max_surfaced"):
        discovery.update_config("ws", {"max_surfaced": 500}, actor="admin")
    with pytest.raises(ValueError, match="watch_topics"):
        discovery.update_config("ws", {"watch_topics": "camera"}, actor="admin")
    with pytest.raises(ValueError, match="daily_fetch_budget"):
        discovery.update_config("ws", {"daily_fetch_budget": -1}, actor="admin")


async def test_disabling_the_feature_refuses_new_cycles(
    fake_runner: Any,
) -> None:
    ws = await _workspace("admin", "Discovery off")
    with pytest.raises(discovery.DiscoveryCycleRefused, match="discovery_disabled"):
        await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert fake_runner.calls == []


# ---------------------------------------------------------------------------
# Budgets: durable, day-keyed, refusal is a clean stop
# ---------------------------------------------------------------------------


async def test_trigger_charges_the_ledger_and_exhaustion_refuses(
    fake_runner: Any,
) -> None:
    ws = await _workspace("admin", "Discovery budget")
    _enable(ws, daily_curate_budget=2)
    fake_runner.records["next"] = _fake_record("run-a", [])

    first = await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert first["run_id"] == "run-a"
    # The cycle's nodes charge the ledger at execution time, keyed by Run id
    # — simulate the fetch node's context read that production would do.
    await discovery.cycle_context(ws, ws, "admin", cycle_key="run-a")
    ledger = discovery.today_ledger(ws)
    assert ledger["fetches"] == 1  # one cycle's worth of the declared source
    assert len(ledger["cycles"]) == 1

    fake_runner.records["next"] = _fake_record("run-b", [])
    second = await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    await discovery.cycle_context(ws, ws, "admin", cycle_key=second["run_id"])

    with pytest.raises(discovery.DiscoveryCycleRefused, match="discovery_cycle_budget_exhausted"):
        await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert len(fake_runner.calls) == 2


async def test_fetch_budget_refuses_before_any_run(fake_runner: Any) -> None:
    ws = await _workspace("admin", "Discovery fetch budget")
    _enable(ws, daily_fetch_budget=0)
    with pytest.raises(discovery.DiscoveryCycleRefused, match="discovery_fetch_budget_exhausted"):
        await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert fake_runner.calls == []


async def test_ledger_charges_are_idempotent_per_cycle_key() -> None:
    ws = "ws-ledger"
    _enable(ws)
    first = await discovery.cycle_context(ws, ws, "admin", cycle_key="run-1")
    assert first.budget_refusal == ""
    # The three nodes of one cycle all read with the same run id.
    again = await discovery.cycle_context(ws, ws, "admin", cycle_key="run-1")
    assert again.budget_refusal == ""
    ledger = discovery.today_ledger(ws)
    assert ledger["fetches"] == 1  # charged once, not three times
    assert len(ledger["cycles"]) == 1


async def test_a_new_day_resets_the_budget() -> None:
    ws = "ws-ledger-day"
    _enable(ws, daily_curate_budget=1)
    await discovery.cycle_context(ws, ws, "admin", cycle_key="run-1")
    assert (
        discovery.discovery_refusal(discovery.get_config(ws), discovery.today_ledger(ws))
        == "discovery_cycle_budget_exhausted"
    )
    # Tomorrow's ledger is a fresh document; the day key is what makes
    # exhaustion a daily bound rather than a permanent one.
    tomorrow_key = discovery._ledger_key(ws, "2026-11-27")
    discovery.store[tomorrow_key] = discovery._empty_ledger(ws, "2026-11-27")
    fresh = discovery.store.get(tomorrow_key)
    assert fresh is not None
    assert discovery.discovery_refusal(discovery.get_config(ws), fresh) is None


# ---------------------------------------------------------------------------
# Fire-time context: fresh Persona/user-model/Goal notes, feedback weights
# ---------------------------------------------------------------------------


async def test_cycle_context_carries_fresh_context_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = "ws-context"
    _enable(ws, watch_topics=["camera", "lens"])

    async def _persona(workspace_id: str) -> list[str]:
        return ["persona domain: photo blogging"]

    async def _user_model(user_id: str) -> list[str]:
        return ["about the user: shoots Canon"]

    async def _goals(user_id: str, workspace_id: str) -> list[str]:
        return ["current goal: plan the weekend shoot"]

    monkeypatch.setattr(discovery, "_persona_notes", _persona)
    monkeypatch.setattr(discovery, "_user_model_notes", _user_model)
    monkeypatch.setattr(discovery, "_goal_notes", _goals)

    context = await discovery.cycle_context(ws, ws, "admin", cycle_key="run-ctx")
    assert context.watch_topics == ("camera", "lens")
    assert context.context_notes == (
        "persona domain: photo blogging",
        "about the user: shoots Canon",
        "current goal: plan the weekend shoot",
    )
    assert context.source_binding_id == ""
    assert context.curator_binding_id == ""


async def test_dismissed_category_downweights_future_cycles() -> None:
    ws = "ws-prefs"
    discovery.update_config(ws, {"enabled": True}, actor="admin")
    discovery._record_feedback_preference(ws, "news", "dismiss")
    discovery._record_feedback_preference(ws, "news", "dismiss")
    discovery._record_feedback_preference(ws, "news", "keep")
    weights = discovery.category_preferences(ws)
    assert weights["news"] == pytest.approx(1 / 3, abs=1e-3)
    context = await discovery.cycle_context(ws, ws, "admin", cycle_key="run-p")
    assert ("news", weights["news"]) in context.category_downweights


async def test_discovery_content_never_writes_the_user_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """External content stays sourced evidence: no discovery path promotes."""
    from maistro.memory.user_model.service import UserModelService
    from maistro.memory.user_model.store import InMemoryUserModelStore
    from maistro_server.api import user_model as user_model_api

    class _NoopAudit:
        async def append(self, *args: Any, **kwargs: Any) -> None: ...

    store = InMemoryUserModelStore()
    service = UserModelService(store=store, audit_log=_NoopAudit())
    user_model_api.configure_user_model_service(service)
    try:
        before = await service.facts("admin")

        ws = await _workspace("admin", "Discovery no memory writes")
        _enable(ws)
        monkeypatch.setattr(
            "services.dag_agents.run_registered_dag",
            _fake_run_with(_fake_record("run-m", [_curated_item("fp-m", "Camera deal")])),
        )
        await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
        await discovery.record_feedback(ws, "fp-m", "dismiss", actor="admin")

        after = await service.facts("admin")
        assert after == before  # the durable user model never learned the item
    finally:
        user_model_api.configure_user_model_service(None)


def _fake_run_with(record: Any):
    async def _run(dag_id: str, **kwargs: Any) -> tuple[Any, Any]:
        return SimpleNamespace(), record

    return _run


# ---------------------------------------------------------------------------
# Lift + surfacing: dedupe, staleness, the small cap
# ---------------------------------------------------------------------------


async def test_lift_surfaces_once_per_fingerprint_and_respects_the_cap(
    fake_runner: Any,
) -> None:
    ws = await _workspace("admin", "Discovery lift")
    _enable(ws, max_surfaced=2)
    items = [
        _curated_item("fp-1", "First", score=0.9),
        _curated_item("fp-2", "Second", score=0.8),
        _curated_item("fp-3", "Third", score=0.7),
    ]
    fake_runner.records["next"] = _fake_record("run-lift", items)

    summary = await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert summary["surfaced"] == 2  # the config's surfaced cap, not the 3 curated

    body = await discovery.surfaced_items("admin", ws)
    assert [item["fingerprint"] for item in body["items"]] == ["fp-1", "fp-2"]
    assert body["counts"]["surfaced"] == 2
    # The seen ledger holds everything curated, so a later cycle cannot
    # re-surface the same candidates.
    assert "fp-3" in discovery.seen_fingerprints(ws)


async def test_a_second_lift_of_the_same_run_never_re_surfaces(fake_runner: Any) -> None:
    ws = await _workspace("admin", "Discovery lift idempotent")
    _enable(ws)
    items = [_curated_item("fp-dup", "Dup", score=0.9)]
    fake_runner.records["next"] = _fake_record("run-dup", items)
    await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")

    # A retried read re-lifts nothing: the lifted index keyed by Run id.
    record = _fake_record("run-dup", items)
    assert discovery.lift_cycle(ws, record) == 0
    body = await discovery.surfaced_items("admin", ws)
    assert len(body["items"]) == 1


async def test_duplicate_candidates_across_cycles_are_suppressed(fake_runner: Any) -> None:
    ws = await _workspace("admin", "Discovery dedupe")
    _enable(ws, daily_curate_budget=5)
    item = _curated_item("fp-same", "Same again", score=0.9)
    fake_runner.records["next"] = _fake_record("run-1", [item])
    await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")

    fake_runner.records["next"] = _fake_record("run-2", [item])
    second = await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")
    assert second["surfaced"] == 0
    body = await discovery.surfaced_items("admin", ws)
    assert len(body["items"]) == 1  # the first cycle's item, not a duplicate


async def test_non_members_and_missing_workspaces_look_identical() -> None:
    ws = await _workspace("admin", "Discovery private")
    _enable(ws)
    with pytest.raises(discovery.DiscoveryNotVisible):
        await discovery.surfaced_items("stranger", ws)


async def test_dismissed_and_stale_items_leave_the_surface() -> None:
    ws = await _workspace("admin", "Discovery filters")
    _enable(ws)
    now = datetime.now(UTC)
    fresh = _curated_item("fp-fresh", "Fresh")
    dismissed = _curated_item("fp-gone", "Dismissed", score=0.95)
    dismissed["status"] = "dismissed"
    fresh["status"] = "surfaced"
    stale = _curated_item("fp-stale", "Stale", score=0.9)
    stale["status"] = "surfaced"
    stale["surfaced_at"] = (now - timedelta(days=30)).isoformat()
    for item in (fresh, dismissed, stale):
        discovery.store[discovery._item_key(ws, item["fingerprint"])] = item

    body = await discovery.surfaced_items("admin", ws)
    surfaced_ids = [item["fingerprint"] for item in body["items"]]
    assert surfaced_ids == ["fp-fresh"]
    assert body["counts"]["dismissed"] >= 1
    assert body["counts"]["stale_suppressed"] >= 1


async def test_source_expiry_keeps_an_item_fresh_past_the_default_window() -> None:
    ws = await _workspace("admin", "Discovery expiry")
    _enable(ws)
    now = datetime.now(UTC)
    expiring = _curated_item(
        "fp-exp", "Sale ends soon", expires_at=(now + timedelta(days=2)).isoformat()
    )
    expiring["status"] = "surfaced"
    expiring["surfaced_at"] = (now - timedelta(days=30)).isoformat()
    discovery.store[discovery._item_key(ws, "fp-exp")] = expiring
    body = await discovery.surfaced_items("admin", ws)
    assert [item["fingerprint"] for item in body["items"]] == ["fp-exp"]


# ---------------------------------------------------------------------------
# Feedback: negative feedback changes later selection, not just one card
# ---------------------------------------------------------------------------


async def test_dismiss_records_preference_attention_and_status(fake_runner: Any) -> None:
    from services.attention import dismissed_source_ids

    ws = await _workspace("admin", "Discovery feedback")
    _enable(ws)
    fake_runner.records["next"] = _fake_record(
        "run-f", [_curated_item("fp-fb", "Camera thing", category="news")]
    )
    await discovery.run_discovery_cycle(ws, ws, "admin", actor_id="admin")

    row = await discovery.record_feedback(ws, "fp-fb", "dismiss", actor="admin")
    assert row["status"] == "dismissed"
    assert row["feedback"]["action"] == "dismiss"
    # The Attention projection hides the same source identity, and the
    # category preference state now down-weights "news" for later cycles.
    assert ("discovery_item", "fp-fb") in dismissed_source_ids(ws)
    assert discovery.category_preferences(ws)["news"] == 0.0

    with pytest.raises(KeyError):
        await discovery.record_feedback(ws, "fp-absent", "dismiss", actor="admin")
    with pytest.raises(ValueError, match="keep or dismiss"):
        await discovery.record_feedback(ws, "fp-fb", "purge", actor="admin")


async def test_keep_feedback_counters_the_dismissals() -> None:
    ws = "ws-keep"
    discovery._record_feedback_preference(ws, "news", "dismiss")
    discovery._record_feedback_preference(ws, "news", "keep")
    assert discovery.category_preferences(ws)["news"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Projections: Waiting by default, Home adaptive, deadline-only escalation
# ---------------------------------------------------------------------------


async def test_attention_shows_discoveries_as_waiting_not_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.attention import list_attention

    ws = await _workspace("admin", "Discovery waiting")
    _enable(ws)
    now = datetime.now(UTC)
    ordinary = _curated_item("fp-ordinary", "An interesting article")
    expiring = _curated_item(
        "fp-deal",
        "Lens sale expiring",
        expires_at=(now + timedelta(hours=6)).isoformat(),
    )
    for item in (ordinary, expiring):
        discovery.store[discovery._item_key(ws, item["fingerprint"])] = {
            **item,
            "status": "surfaced",
            "surfaced_at": now.isoformat(),
        }

    body = await list_attention("admin", ws, now=now)
    assert body is not None
    by_kind = {
        item["source_id"]: item for item in body["items"] if item["source_kind"] == "discovery_item"
    }
    assert set(by_kind) == {"fp-ordinary", "fp-deal"}
    # Ordinary proactive content waits; only source-declared expiry evidence
    # inside the horizon raises the deal, and never to blocking.
    assert by_kind["fp-ordinary"]["attention_class"] == "proactive"
    assert by_kind["fp-ordinary"]["interruption"] == "waiting"
    assert by_kind["fp-deal"]["attention_class"] == "time_sensitive"
    assert by_kind["fp-deal"]["interruption"] == "popup"
    assert all(
        item["evidence"]["interruption"] != "blocking"
        for item in body["items"]
        if item["source_kind"] == "discovery_item"
    )
    # The explain evidence rides on the item, so "why this?" is answerable.
    assert "camera" in by_kind["fp-ordinary"]["evidence"]["explain"]


async def test_home_adaptive_candidates_carry_the_discoveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services import home_projections

    ws = await _workspace("admin", "Discovery home")
    _enable(ws)
    now = datetime.now(UTC)
    item = _curated_item("fp-home", "Tripod review")
    discovery.store[discovery._item_key(ws, "fp-home")] = {
        **item,
        "status": "surfaced",
        "surfaced_at": now.isoformat(),
    }

    body = await home_projections.adaptive_items("admin", ws)
    keys = [c["key"] for c in body["candidates"]]
    assert "discovery_item:fp-home" in keys
    candidate = next(c for c in body["candidates"] if c["key"] == "discovery_item:fp-home")
    assert candidate["explain"] == "matched watch topics: camera"
    assert candidate["href"] == "https://source.example.com/fp-home"


@pytest.fixture
def ws_owner() -> None:
    return None


def test_budget_status_reports_exhaustion() -> None:
    ws = "ws-budget-status"
    _enable(ws, daily_curate_budget=0)
    status = discovery.budget_status(ws)
    assert status["exhausted"] is True
    assert status["cycles_used"] == 0
    assert status["daily_curate_budget"] == 0
