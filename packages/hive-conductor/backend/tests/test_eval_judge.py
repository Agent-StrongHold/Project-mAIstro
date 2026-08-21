"""Boy Scout — Phase 5 Signal #3 eval-judge service + endpoints.

eval-judge is an INTERNAL maistro agent (NOT a Claude Code subagent).
These tests verify:

- _build_evidence_payload pulls run_id / dag_id / status, normalizes
  enum phases to bare strings, and filters feedback outcomes to
  matching run_id only
- _parse_verdict handles:
    - pure JSON
    - JSON inside ```json … ``` fences
    - JSON with leading prose ("Here's my verdict: { … }")
    - empty / malformed → status='error'
- _validate_verdict clamps score to [0,100], drops unknown proposal
  keys, coerces wrong proposal type to None
- score_run with a stubbed llm_call returns the parsed verdict + writes
  to stores.eval_verdicts when persist=True
- score_run gracefully handles LLM exceptions → status='error' verdict
- score_run with run_record=None raises ValueError (defensive contract)
- LLM-unavailable (settings missing) graceful fallback
- get_verdict reads back via stores.eval_verdicts
- GET /v1/eval-judge/{run_id} → 200 + verdict / 404
- GET /v1/eval-judge → list, newest first
- POST /v1/eval-judge/{run_id} → scores from dag_run_store
- POST /v1/eval-judge/{missing-run} → 404
- _events_to_node_records: completed + failed events both produce records
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@dataclass
class _NR:
    node_id: str
    kind: str = ""
    phase: str = "COMPLETED"
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    error_code: Any = None
    error_message: Any = None


@dataclass
class _Run:
    run_id: str = "r-001"
    dag_id: str = "daily-status"
    project_id: str = "proj-A"
    status: str = "COMPLETED"
    node_records: list[Any] = field(default_factory=list)


@dataclass
class _Feedback:
    thumb: str = "down"
    thumb_comment: str = "missed an epic"
    dag_run_id: str = "r-001"
    node_id: str = "filter"


def _wipe_store(store: Any) -> None:
    for k in list(store.keys()):
        store.pop(k)


@pytest.fixture(autouse=True)
def _wipe_verdicts():
    import stores

    _wipe_store(stores.eval_verdicts)
    yield
    _wipe_store(stores.eval_verdicts)


# --- _build_evidence_payload --------------------------------------------


def test_build_evidence_payload_strips_enum_prefix() -> None:
    from services.eval_judge import _build_evidence_payload

    run = _Run(
        node_records=[
            _NR("n1", "jira.poll", "NodePhase.COMPLETED", 150, 5, 12),
        ]
    )
    payload = _build_evidence_payload(run)
    assert payload["run_id"] == "r-001"
    assert payload["dag_id"] == "daily-status"
    assert payload["node_records"][0]["phase"] == "COMPLETED"


def test_build_evidence_payload_with_feedback_filtered_by_run_id() -> None:
    from services.eval_judge import _build_evidence_payload

    run = _Run(run_id="r-A")
    # One feedback for r-A, one for an unrelated run
    fb_match = _Feedback(thumb="up", thumb_comment="great", dag_run_id="r-A")
    fb_other = _Feedback(thumb="down", dag_run_id="r-OTHER")
    payload = _build_evidence_payload(run, [fb_match, fb_other])
    assert len(payload["user_feedback"]) == 1
    assert payload["user_feedback"][0]["thumb"] == "up"
    assert payload["user_feedback"][0]["comment"] == "great"


def test_build_evidence_payload_none_run_returns_empty_dict() -> None:
    from services.eval_judge import _build_evidence_payload

    assert _build_evidence_payload(None) == {}


# --- _parse_verdict ------------------------------------------------------


def test_parse_pure_json_verdict() -> None:
    from services.eval_judge import _parse_verdict

    raw = '{"score": 85, "rationale": "good", "topology_proposal": null}'
    out = _parse_verdict(raw)
    assert out["score"] == 85
    assert out["rationale"] == "good"
    assert out["topology_proposal"] is None


def test_parse_fenced_json_verdict() -> None:
    from services.eval_judge import _parse_verdict

    raw = '```json\n{"score": 72, "rationale": "ok"}\n```'
    out = _parse_verdict(raw)
    assert out["score"] == 72


def test_parse_verdict_with_leading_prose() -> None:
    """Some LLMs prepend a sentence; the regex fallback finds the {…}."""
    from services.eval_judge import _parse_verdict

    raw = 'Here\'s my verdict:\n{"score": 50, "rationale": "meh"}'
    out = _parse_verdict(raw)
    assert out["score"] == 50


def test_parse_empty_response_returns_error_status() -> None:
    from services.eval_judge import _parse_verdict

    out = _parse_verdict("")
    assert out["status"] == "error"
    assert "empty" in out["detail"].lower()


def test_parse_malformed_returns_error_status() -> None:
    from services.eval_judge import _parse_verdict

    out = _parse_verdict("this is not json at all")
    assert out["status"] == "error"


def test_parse_almost_json_returns_error() -> None:
    """Has a `{` but isn't parseable."""
    from services.eval_judge import _parse_verdict

    out = _parse_verdict("{this is not valid json")
    assert out["status"] == "error"


def test_parse_regex_fallback_finds_obj_but_fails_to_parse() -> None:
    """Regex fallback finds the `{...}` block but its contents are still
    invalid JSON. Hits the rare last-resort except branch (lines 141-142)."""
    from services.eval_judge import _parse_verdict

    raw = "preamble {bad-json-inside-the-braces} trailer"
    out = _parse_verdict(raw)
    assert out["status"] == "error"
    assert "JSON parse failed" in out["detail"]


async def test_score_run_llm_exception_with_persist_false() -> None:
    """LLM raises + persist=False — verdict returned, NOT stored.
    Hits the no-persist branch (216→218)."""
    import stores
    from services.eval_judge import score_run

    async def _boom(messages: list[dict], **kw: Any) -> str:
        raise RuntimeError("upstream 500")

    out = await score_run(_Run(run_id="r-no-persist-err"), llm_call=_boom, persist=False)
    assert out["status"] == "error"
    assert "r-no-persist-err" not in stores.eval_verdicts


async def test_score_run_lazy_llm_unavailable_with_persist_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _build_llm_call raises AND persist=False, no verdict is
    written but the error verdict is still returned. Hits branch 233→235."""
    import services.eval_judge as ej
    import services.graph_runner as gr

    def _bad() -> Any:
        raise ImportError("no graph_runner")

    monkeypatch.setattr(gr, "_build_llm_call", _bad)
    out = await ej.score_run(_Run(run_id="r-lazy-no-persist"), persist=False)
    assert out["status"] == "error"


# --- _validate_verdict ---------------------------------------------------


def test_validate_clamps_score_above_100() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"score": 999, "rationale": "x"})
    assert out["score"] == 100


def test_validate_clamps_score_below_zero() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"score": -50, "rationale": "x"})
    assert out["score"] == 0


def test_validate_strips_unknown_proposal_keys() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict(
        {
            "score": 50,
            "rationale": "x",
            "topology_proposal": {
                "kind": "tune_param",
                "target_node_id": "n1",
                "from_value": "0.3",
                "to_value": "0.7",
                "expected_improvement": "more diversity",
                "hacker_field": "bogus",
            },
        }
    )
    assert "hacker_field" not in out["topology_proposal"]
    assert out["topology_proposal"]["kind"] == "tune_param"


def test_validate_drops_non_dict_proposal() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict(
        {
            "score": 80,
            "rationale": "x",
            "topology_proposal": "not-a-dict",
        }
    )
    assert out["topology_proposal"] is None


def test_validate_passes_error_status_through() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"status": "error", "detail": "x"})
    assert out["status"] == "error"


def test_validate_score_not_int_coerces_to_zero() -> None:
    from services.eval_judge import _validate_verdict

    out = _validate_verdict({"score": "not-a-number", "rationale": "x"})
    assert out["score"] == 0


# --- score_run end-to-end -----------------------------------------------


async def test_score_run_with_stub_llm_writes_verdict() -> None:
    import stores
    from services.eval_judge import score_run

    async def _stub(messages: list[dict], **kw: Any) -> str:
        return '{"score": 88, "rationale": "solid run", "topology_proposal": null}'

    run = _Run(run_id="r-stub")
    out = await score_run(run, llm_call=_stub)
    assert out["score"] == 88
    assert out["status"] == "ok"
    # Persisted
    persisted = stores.eval_verdicts["r-stub"]
    assert persisted["score"] == 88
    assert persisted["run_id"] == "r-stub"
    assert persisted["dag_id"] == "daily-status"
    assert "scored_at" in persisted


async def test_score_run_persist_false_skips_storage() -> None:
    import stores
    from services.eval_judge import score_run

    async def _stub(messages: list[dict], **kw: Any) -> str:
        return '{"score": 50, "rationale": "x"}'

    await score_run(_Run(run_id="r-no-persist"), llm_call=_stub, persist=False)
    assert "r-no-persist" not in stores.eval_verdicts


async def test_score_run_llm_exception_writes_error_verdict() -> None:
    import stores
    from services.eval_judge import score_run

    async def _boom(messages: list[dict], **kw: Any) -> str:
        raise RuntimeError("upstream 500")

    out = await score_run(_Run(run_id="r-boom"), llm_call=_boom)
    assert out["status"] == "error"
    assert "RuntimeError" in out["detail"]
    persisted = stores.eval_verdicts["r-boom"]
    assert persisted["status"] == "error"


async def test_score_run_llm_returns_empty_response_writes_error_verdict() -> None:
    from services.eval_judge import score_run

    async def _empty(messages: list[dict], **kw: Any) -> str:
        return ""

    out = await score_run(_Run(run_id="r-empty"), llm_call=_empty)
    assert out["status"] == "error"


async def test_score_run_none_run_raises_value_error() -> None:
    from services.eval_judge import score_run

    with pytest.raises(ValueError, match="run_record is required"):
        await score_run(None)


async def test_score_run_falls_back_to_default_llm_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _build_llm_call import raises, score_run writes an error
    verdict instead of propagating."""
    import services.eval_judge as ej

    def _bad_import() -> Any:
        raise ImportError("graph_runner not available in this context")

    # Patch the lazy import path
    import services.graph_runner as gr

    monkeypatch.setattr(gr, "_build_llm_call", _bad_import)
    out = await ej.score_run(_Run(run_id="r-no-llm"))
    assert out["status"] == "error"


def test_persist_with_empty_run_id_is_noop() -> None:
    import stores
    from services.eval_judge import _persist

    _persist(_Run(run_id=""), {"score": 50, "status": "ok"})
    assert "" not in stores.eval_verdicts


def test_get_verdict_returns_persisted_or_none() -> None:
    from services.eval_judge import _persist, get_verdict

    _persist(
        _Run(run_id="r-G"), {"score": 99, "status": "ok"}, now=datetime(2026, 5, 22, tzinfo=UTC)
    )
    out = get_verdict("r-G")
    assert out is not None
    assert out["score"] == 99
    assert get_verdict("nope") is None


# --- HTTP route tests ----------------------------------------------------


def test_get_verdict_endpoint_returns_persisted(authed_client: Any) -> None:
    from services.eval_judge import _persist

    _persist(
        _Run(run_id="r-V"),
        {"score": 70, "rationale": "ok", "topology_proposal": None, "status": "ok"},
    )
    r = authed_client.get("/v1/eval-judge/r-V")
    assert r.status_code == 200
    assert r.json()["score"] == 70


def test_get_verdict_endpoint_404(authed_client: Any) -> None:
    r = authed_client.get("/v1/eval-judge/missing-run")
    assert r.status_code == 404


def test_list_verdicts_endpoint_returns_newest_first(authed_client: Any) -> None:
    from services.eval_judge import _persist

    _persist(
        _Run(run_id="r-old"), {"score": 50, "status": "ok"}, now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _persist(
        _Run(run_id="r-new"), {"score": 80, "status": "ok"}, now=datetime(2026, 5, 22, tzinfo=UTC)
    )
    r = authed_client.get("/v1/eval-judge?limit=10")
    assert r.status_code == 200
    items = r.json()
    assert items[0]["run_id"] == "r-new"
    assert items[1]["run_id"] == "r-old"


def test_list_verdicts_limit_clamped_to_100(authed_client: Any) -> None:
    from services.eval_judge import _persist

    for i in range(110):
        _persist(_Run(run_id=f"r-{i}"), {"score": i % 100, "status": "ok"})
    r = authed_client.get("/v1/eval-judge?limit=999")
    assert r.status_code == 200
    assert len(r.json()) == 100


def test_trigger_score_endpoint_runs_against_dag_run_store(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed a fake run into dag_run_store, stub the LLM, hit POST."""
    import services.eval_judge as ej
    from services.dag_run_store import get_dag_run_store

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        return '{"score": 91, "rationale": "ace"}'

    async def _patched_score(run_record: Any, **kw: Any) -> dict[str, Any]:
        return await ej.score_run(run_record, llm_call=_stub_llm, **kw)

    # Patch route's score_run import to use our stubbed LLM
    import routes.eval_judge as routes_ej

    monkeypatch.setattr(routes_ej, "score_run", _patched_score)

    # Seed a fake run via dag_run_store's public start_run + append_event
    import asyncio

    store = get_dag_run_store()

    async def _seed() -> str:
        run = await store.start_run(user_id="testuser", run_id="r-trigger")
        await store.append_event(
            "r-trigger",
            event_type="pm_node_completed",
            role="filter",
            capability="transform.filter_by_type",
            payload={"node_id": "filter", "latency_ms": 200, "tokens_in": 5, "tokens_out": 10},
        )
        await store.finish_run("r-trigger")
        return run.id

    # asyncio.run() uses a fresh loop — robust regardless of prior async tests
    # (get_event_loop() can return a closed loop under pytest-asyncio auto mode).
    rid = asyncio.run(_seed())
    assert rid == "r-trigger"

    r = authed_client.post(f"/v1/eval-judge/{rid}")
    assert r.status_code == 200
    assert r.json()["score"] == 91


def test_trigger_score_missing_run_returns_404(authed_client: Any) -> None:
    r = authed_client.post("/v1/eval-judge/never-existed")
    assert r.status_code == 404


def test_events_to_node_records_handles_completed_and_failed() -> None:
    from routes.eval_judge import _events_to_node_records

    events = [
        {
            "event_type": "pm_node_completed",
            "role": "n1",
            "capability": "k",
            "payload": {"node_id": "n1", "latency_ms": 100, "tokens_in": 1, "tokens_out": 2},
        },
        {
            "event_type": "pm_node_failed",
            "role": "n2",
            "capability": "k",
            "payload": {"node_id": "n2", "error_code": "RuntimeError", "error_message": "boom"},
        },
    ]
    recs = _events_to_node_records(events)
    by = {r.node_id: r for r in recs}
    assert by["n1"].phase == "COMPLETED"
    assert by["n1"].latency_ms == 100
    assert by["n2"].phase == "FAILED"
    assert by["n2"].error_code == "RuntimeError"


def test_events_to_node_records_skips_anonymous_events() -> None:
    from routes.eval_judge import _events_to_node_records

    events = [
        {
            "event_type": "log",
            "role": "",
            "capability": "",
            "payload": {"node_id": ""},
        },  # no id → skipped
    ]
    assert _events_to_node_records(events) == []


def test_events_to_node_records_unknown_event_type_keeps_empty_phase() -> None:
    """A node-identifying event whose type is neither completed nor
    failed/error produces a record with phase='' (the elif falls
    through both branches — covers 101→85 branch)."""
    from routes.eval_judge import _events_to_node_records

    events = [
        {
            "event_type": "pm_node_started",
            "role": "n1",
            "capability": "k",
            "payload": {"node_id": "n1", "latency_ms": 0},
        },
    ]
    recs = _events_to_node_records(events)
    assert len(recs) == 1
    assert recs[0].node_id == "n1"
    assert recs[0].phase == ""
