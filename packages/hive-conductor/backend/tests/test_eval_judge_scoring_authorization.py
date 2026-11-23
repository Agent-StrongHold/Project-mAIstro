"""POST /v1/eval-judge/{run_id} must not ride the Run read permission (#2470).

The shipped route authorized scoring with ``visible_run_detail`` — the READ
permission every Workspace member holds (#1174) — then launched a real
LiteLLM model call and unconditionally overwrote the globally keyed verdict
the optimizer consumes. A member who could merely *look at* a teammate's Run
could thereby spend provider budget and replace shared improvement evidence.
This suite pins the split:

* The HTTP capability table distinguishes GET (the #1174 in-route scoped
  read, no elevation) from POST (``eval.score``, assigned-and-elevated) —
  pinned both at ``required_permission`` and through the real ASGI stack, so
  reverting POST to mere ``visible_run_detail`` fails these tests.
* Through the real FastAPI app with a wired canonical spine, a peer member
  of the same Workspace can GET the initiator's Run yet is refused scoring
  (the mutation gate's non-disclosing 404) with zero model call and no
  verdict/proposal/audit-success mutation; only the initiator (or a
  Workspace administrator) scores, a terminal Run only, and the verdict is
  canonical-keyed evidence with actor/scope provenance and an audit record.
* Evidence protection: a valid verdict is terminal — retries, restarts and
  failing attempts cannot downgrade it, concurrent authorized requests share
  one model invocation, and error receipts remain retryable while a valid
  verdict never is.

The two-principal cases drive the shipped app over real ASGI (TestClient)
against the real canonical Run/Workspace/Project stores and the embedded
Workspace authority, mirroring the #2466 cancel-control suite: denials are
checked against the physical path (the scorer spy records every scoring
invocation), not merely response codes.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

SCORE_PERMISSION = "eval.score"


# --- account + client helpers ---------------------------------------------


def _seed_user(tag: str, *, permissions: list[str] | None = None) -> str:
    """A fresh role=user account; returns its id (never a shared fixture)."""
    import stores

    from maistro.security.passwords import hash_password

    uid = f"{tag}-{uuid.uuid4().hex[:8]}"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=list(permissions or []),
        created_at=datetime.now(UTC),
    )
    return uid


def _client_for(user_id: str, *, elevate: bool = False) -> TestClient:
    from main import app

    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": user_id, "password": "pw"})
    assert r.status_code == 200, r.text
    if elevate:
        e = c.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": [SCORE_PERMISSION], "task_id": "score-task"},
        )
        assert e.status_code == 200, e.text
    return c


def _elevated_scorer(tag: str) -> tuple[str, TestClient]:
    """A member holding the assigned-and-elevated eval.score capability."""
    uid = _seed_user(tag, permissions=[SCORE_PERMISSION])
    return uid, _client_for(uid, elevate=True)


# --- canonical spine rig ----------------------------------------------------


async def _workspace(name: str, creator: str) -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=creator,
        name=name,
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


async def _grant_member(workspace_id: str, user_id: str, role: Any) -> None:
    from services.workspace_authority import canonical_store_for_tests

    await canonical_store_for_tests().set_membership(workspace_id, user_id=user_id, role=role)


def _wire_spine(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Wire the engine bridge at the exact objects the route's mutation gate
    resolves through: an InMemoryRunStore + ScopedRunReader over the test
    canonical Workspace authority (the #2466 cancel-suite wiring)."""
    from services import engine as engine_mod
    from services.workspace_authority import canonical_store_for_tests

    from maistro.runs import InMemoryRunStore
    from maistro.runs.scoped_reads import ScopedRunReader

    workspaces = canonical_store_for_tests()
    store = InMemoryRunStore(project_store=workspaces.project_store)
    reader = ScopedRunReader(store, workspaces, workspaces.project_store)
    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=reader)
    )
    return store, reader


async def _canonical_run(
    store: Any, workspace_id: str, actor: str, *, status: str = "completed"
) -> str:
    """A canonical Run filed in `workspace_id`, initiated by `actor`, driven
    to `status` through the store's own legal transitions."""
    from services.workspace_authority import canonical_store_for_tests

    from maistro.graph import Graph, Node
    from maistro.runs import RunStatus

    project_store = canonical_store_for_tests().project_store
    root = await project_store.root_for_workspace(workspace_id)
    project = await project_store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Scored",
    )
    graph = Graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        name="Scored DAG",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=actor)
    target = RunStatus(status)
    if target is not RunStatus.CREATED:
        await store.transition_run(run.run_id, RunStatus.QUEUED)
        if target is not RunStatus.QUEUED:
            await store.transition_run(run.run_id, RunStatus.RUNNING)
            if target is not RunStatus.RUNNING:
                await store.transition_run(run.run_id, target)
    return run.run_id


async def _projection_row(
    row_id: str, *, canonical_run_id: str, workspace_id: str, user_id: str
) -> None:
    from services.dag_run_store import get_dag_run_store

    await get_dag_run_store().start_run(
        run_id=row_id,
        user_id=user_id,
        workspace_id=workspace_id,
        canonical_run_id=canonical_run_id,
    )


def _score_spy(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | None = None
) -> list[str]:
    """Replace the route's scoring entry with a recording spy.

    A denial must precede the effect: after a refused POST the calls list has
    to stay empty. When `response` is given the spy returns it (a valid
    verdict), otherwise the spy fails the test by its empty-calls assertion
    alone — it still returns an error verdict so an accidental call cannot
    look like a success.
    """
    import routes.eval_judge as routes_ej

    calls: list[str] = []

    async def _spy(run_record: Any, **kw: Any) -> dict[str, Any]:
        calls.append(str(getattr(run_record, "run_id", "")))
        if response is not None:
            return dict(response)
        return {"status": "error", "detail": "scoring spy must not be reached"}

    monkeypatch.setattr(routes_ej, "score_run", _spy)
    return calls


def _stubbed_scorer(monkeypatch: pytest.MonkeyPatch, payload: str) -> list[str]:
    """Let the real service run its scoring path against a stub LLM; records
    each invocation's run id."""
    import routes.eval_judge as routes_ej
    import services.eval_judge as ej

    calls: list[str] = []

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        return payload

    async def _patched(run_record: Any, **kw: Any) -> dict[str, Any]:
        calls.append(str(getattr(run_record, "run_id", "")))
        return await ej.score_run(run_record, llm_call=_stub_llm, **kw)

    monkeypatch.setattr(routes_ej, "score_run", _patched)
    return calls


def _eval_score_audits() -> list[dict[str, Any]]:
    import stores

    return [e for e in stores.audit_log.values() if e.get("action") == "eval_judge_score"]


@pytest.fixture(autouse=True)
def _clean_eval_state():
    """Isolate the verdict store, the in-flight registry and audit rows."""
    import stores
    from services.eval_judge import reset_score_dedupe_for_tests

    def _wipe(store: Any) -> None:
        for k in list(store.keys()):
            store.pop(k)

    _wipe(stores.eval_verdicts)
    reset_score_dedupe_for_tests()
    yield
    _wipe(stores.eval_verdicts)
    reset_score_dedupe_for_tests()
    for k in list(stores.audit_log.keys()):
        if stores.audit_log[k].get("action") == "eval_judge_score":
            stores.audit_log.pop(k)


# --- 1. The permission registry distinguishes GET from POST -----------------


def test_registry_distinguishes_read_from_scoring() -> None:
    """The route-permission table must answer differently by method: POST
    carries the evaluated-effect capability; GET stays the #1174 scoped read.
    Reverting POST to mere visible_run_detail fails this pin first."""
    from services.authorization import required_permission

    assert required_permission("POST", "/v1/eval-judge") == SCORE_PERMISSION
    assert required_permission("POST", "/v1/eval-judge/run-1") == SCORE_PERMISSION
    assert required_permission("GET", "/v1/eval-judge") is None
    assert required_permission("GET", "/v1/eval-judge/run-1") is None


def test_scoring_post_requires_capability_while_reads_stay_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real ASGI: without the assigned-and-elevated capability the POST is
    403 at the middleware gate (the scorer is never reached); the GET rides
    the authenticated-only read as before."""
    _wire_spine(monkeypatch)
    uid = _seed_user("gate-plain")

    plain = _client_for(uid)
    r = plain.post("/v1/eval-judge/some-run")
    assert r.status_code == 403
    assert SCORE_PERMISSION in r.json()["detail"]

    # The read on the same path is not elevation-gated: the route answers
    # (404 — no such run), never the middleware's permission refusal.
    r2 = plain.get("/v1/eval-judge/some-run")
    assert r2.status_code == 404
    assert r2.json() == {"detail": "run not found"}


def test_assigned_and_elevated_capability_reaches_the_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capability clears the middleware gate: the same POST lands in the
    route and gets the canonical gate's answer (404 for an unknown run), not
    a 403 — proving the gate binds to the registered capability, and that
    possession alone does not authorize scoring."""
    _wire_spine(monkeypatch)
    _uid, client = _elevated_scorer("gate-holder")
    calls = _score_spy(monkeypatch)
    r = client.post("/v1/eval-judge/never-existed")
    assert r.status_code == 404
    assert r.json() == {"detail": "run not found"}
    assert calls == []


# --- 2. Two principals, one Workspace: reads shared, scoring gated ----------


async def _two_principal_scene(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Initiator A and ordinary member B share one Workspace with a terminal
    canonical Run (and its projection row); B holds eval.score too, so every
    refusal below is the route's canonical gate, not the middleware's."""
    initiator, _ = _elevated_scorer("score-initiator")
    peer, _ = _elevated_scorer("score-peer")
    view = await _workspace("Score Scope", initiator)
    from maistro.workspaces.model import WorkspaceRole

    await _grant_member(view.id, peer, WorkspaceRole.MEMBER)
    store, _reader = _wire_spine(monkeypatch)
    run_id = await _canonical_run(store, view.id, initiator)
    await _projection_row(
        "score-row", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
    )
    return {
        "initiator": initiator,
        "peer": peer,
        "workspace_id": view.id,
        "canonical_run_id": run_id,
        "row_id": "score-row",
        "store": store,
    }


def test_peer_member_reads_the_run_but_cannot_score_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The #2470 headline case over real ASGI: B can GET A's Run, but B's
    POST is the mutation gate's non-disclosing 404 — with zero model calls
    and no verdict, proposal, usage or audit-success mutation."""
    from maistro.runs import RunStatus

    scene = asyncio.run(_two_principal_scene(monkeypatch))
    peer_client = _client_for(scene["peer"], elevate=True)

    # B may READ the initiator's run: membership admits reads (#1152).
    detail = peer_client.get(f"/v1/dag-runs/{scene['row_id']}")
    assert detail.status_code == 200
    assert detail.json()["canonical_run_id"] == scene["canonical_run_id"]

    calls = _score_spy(monkeypatch)
    import stores

    verdicts_before = dict(stores.eval_verdicts.items())
    audits_before = _eval_score_audits()

    refused = peer_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert refused.status_code == 404
    assert refused.json() == {"detail": "run not found"}

    # The denial preceded the effect: no scoring invocation, no evidence
    # written, no audit-success mutation.
    assert calls == []
    assert dict(stores.eval_verdicts.items()) == verdicts_before
    assert _eval_score_audits() == audits_before
    run_after = asyncio.run(scene["store"].get_run(scene["canonical_run_id"]))
    assert run_after is not None and run_after.status is RunStatus.COMPLETED


def test_initiator_scores_a_terminal_run_with_provenance_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A (initiator) scores the terminal Run under the elevated capability:
    one permitted invocation, verdict keyed by the canonical Run with actor/
    scope/evaluator provenance, readable by both ids, audited once."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _stubbed_scorer(monkeypatch, '{"score": 91, "rationale": "ace"}')

    r = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 91
    assert calls == [scene["canonical_run_id"]]

    import stores

    verdict = stores.eval_verdicts[scene["canonical_run_id"]]
    assert verdict["status"] == "ok"
    assert verdict["scored_by"] == scene["initiator"]
    assert verdict["canonical_run_id"] == scene["canonical_run_id"]
    assert verdict["workspace_id"] == scene["workspace_id"]
    assert verdict["evaluator_version"]

    # The evidence reads through both ids the caller might hold: the
    # canonical id directly, the projection id via the same authorized read.
    got = initiator_client.get(f"/v1/eval-judge/{scene['canonical_run_id']}")
    assert got.status_code == 200
    assert got.json()["score"] == 91
    got_row = initiator_client.get(f"/v1/eval-judge/{scene['row_id']}")
    assert got_row.status_code == 200
    assert got_row.json()["score"] == 91

    audits = _eval_score_audits()
    assert len(audits) == 1
    assert audits[0]["actor"] == scene["initiator"]
    assert audits[0]["target"] == scene["canonical_run_id"]


def test_workspace_administrator_scores_while_the_peer_cannot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The role rule admits the Workspace administrator (never the initiator)
    and still refuses the ordinary member — same 404, same zero-effect."""
    initiator, _ = _elevated_scorer("admin-scene-initiator")
    peer, _ = _elevated_scorer("admin-scene-peer")
    admin, _ = _elevated_scorer("admin-scene-admin")
    view = asyncio.run(_workspace("Score Admin", initiator))

    from maistro.workspaces.model import WorkspaceRole

    asyncio.run(_grant_member(view.id, peer, WorkspaceRole.MEMBER))
    asyncio.run(_grant_member(view.id, admin, WorkspaceRole.OWNER))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, view.id, initiator))
    asyncio.run(
        _projection_row(
            "admin-row", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
        )
    )

    peer_calls = _score_spy(monkeypatch)
    peer_client = _client_for(peer, elevate=True)
    refused = peer_client.post("/v1/eval-judge/admin-row")
    assert refused.status_code == 404
    assert peer_calls == []

    import routes.eval_judge as routes_ej
    import services.eval_judge as ej

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        return '{"score": 77, "rationale": "admin ok"}'

    admin_calls: list[str] = []

    async def _recording(run_record: Any, **kw: Any) -> dict[str, Any]:
        admin_calls.append(str(getattr(run_record, "run_id", "")))
        return await ej.score_run(run_record, llm_call=_stub_llm, **kw)

    # The earlier spy replaced routes_ej.score_run; rebind to the recording
    # wrapper for the admin leg.
    monkeypatch.setattr(routes_ej, "score_run", _recording)
    admin_client = _client_for(admin, elevate=True)
    ok = admin_client.post("/v1/eval-judge/admin-row")
    assert ok.status_code == 200, ok.text
    assert ok.json()["score"] == 77
    assert admin_calls == [run_id]
    assert peer_calls == []
    import stores

    assert stores.eval_verdicts[run_id]["scored_by"] == admin


# --- 3. Terminality ----------------------------------------------------------


@pytest.mark.parametrize("status", ["created", "queued", "running", "waiting", "paused"])
def test_non_terminal_runs_cannot_be_scored(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    """Running/WAITING/PAUSED (and pre-flight CREATED/QUEUED) Runs refuse to
    score — 409 to the admitted mutator, zero model effects."""
    initiator, _ = _elevated_scorer(f"live-{status}")
    view = asyncio.run(_workspace(f"Score Live {status}", initiator))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, view.id, initiator, status=status))
    asyncio.run(
        _projection_row(
            f"live-row-{status}", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
        )
    )
    client = _client_for(initiator, elevate=True)
    calls = _score_spy(monkeypatch)
    r = client.post(f"/v1/eval-judge/live-row-{status}")
    assert r.status_code == 409
    assert "terminal" in r.json()["detail"]
    assert calls == []
    import stores

    assert not stores.eval_verdicts


def test_projection_only_row_without_a_canonical_run_is_not_scoreable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row naming no canonical Run resolves no scoring target at all: the
    mutation gate refuses it like a missing run (#2470 — the old route scored
    whatever the projection returned)."""
    initiator, _ = _elevated_scorer("orphan")
    view = asyncio.run(_workspace("Score Orphan", initiator))
    _wire_spine(monkeypatch)
    asyncio.run(
        _projection_row("orphan-row", canonical_run_id="", workspace_id=view.id, user_id=initiator)
    )
    client = _client_for(initiator, elevate=True)
    calls = _score_spy(monkeypatch)
    r = client.post("/v1/eval-judge/orphan-row")
    assert r.status_code == 404
    assert calls == []
    import stores

    assert not stores.eval_verdicts


# --- 4. Cross-Workspace links cannot proxy a billed model call ---------------


def test_cross_workspace_link_cannot_proxy_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row filed in W1 pointing at a Run filed in W2 must not score: not
    for a member of W1 alone (the gate refuses what it cannot even read),
    not for the initiator via the row (the workspace attribution rule), and
    the direct canonical id stays open only to who the mutation gate admits
    — the exact #2466 cancel semantics, now on the scoring effect."""
    initiator, _ = _elevated_scorer("xlink-initiator")
    peer, _ = _elevated_scorer("xlink-peer")
    w1 = asyncio.run(_workspace("Score Link Row", initiator))
    w2 = asyncio.run(_workspace("Score Link Run", initiator))

    from maistro.workspaces.model import WorkspaceRole

    asyncio.run(_grant_member(w1.id, peer, WorkspaceRole.MEMBER))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, w2.id, initiator))
    asyncio.run(
        _projection_row("xlink-row", canonical_run_id=run_id, workspace_id=w1.id, user_id=initiator)
    )

    calls = _score_spy(monkeypatch)

    # The initiator may READ the row (it sits in W1), but the row's
    # cross-Workspace link delegates nothing: scoring through it is 404.
    initiator_client = _client_for(initiator, elevate=True)
    via_row = initiator_client.post("/v1/eval-judge/xlink-row")
    assert via_row.status_code == 404
    assert calls == []

    # A W1-member peer cannot proxy either: the gate cannot even read the
    # foreign Run.
    peer_client = _client_for(peer, elevate=True)
    assert peer_client.get("/v1/eval-judge/xlink-row").status_code == 404
    assert peer_client.post("/v1/eval-judge/xlink-row").status_code == 404
    assert calls == []

    # The direct canonical route remains open to the admitted mutator —
    # scoring by the Run's own id works with the same evidence semantics.
    stub_calls = _stubbed_scorer(monkeypatch, '{"score": 64, "rationale": "direct"}')
    direct = initiator_client.post(f"/v1/eval-judge/{run_id}")
    assert direct.status_code == 200, direct.text
    assert direct.json()["score"] == 64
    assert stub_calls == [run_id]


def test_cross_workspace_link_cannot_serve_canonical_keyed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read side of the association rule: a verdict keyed under W2's
    canonical Run is not retrievable through a W1 projection row. A W1-only
    member cannot even read the foreign Run the overlay left unproven, and a
    member of both Workspaces is still refused by the Workspace association —
    only a same-Workspace row (or the Run's own admitted id) serves the
    canonical-keyed evidence."""
    initiator, _ = _elevated_scorer("xlink-read-initiator")
    peer, _ = _elevated_scorer("xlink-read-peer")
    w1 = asyncio.run(_workspace("Evidence Row", initiator))
    w2 = asyncio.run(_workspace("Evidence Run", initiator))

    from maistro.workspaces.model import WorkspaceRole

    asyncio.run(_grant_member(w1.id, peer, WorkspaceRole.MEMBER))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, w2.id, initiator))
    asyncio.run(
        _projection_row(
            "xlink-read-row", canonical_run_id=run_id, workspace_id=w1.id, user_id=initiator
        )
    )

    initiator_client = _client_for(initiator, elevate=True)
    stub_calls = _stubbed_scorer(monkeypatch, '{"score": 64, "rationale": "direct"}')
    scored = initiator_client.post(f"/v1/eval-judge/{run_id}")
    assert scored.status_code == 200, scored.text
    assert scored.json()["score"] == 64
    assert stub_calls == [run_id]
    import stores

    assert run_id in stores.eval_verdicts

    # The initiator can read both Workspaces, yet the row must not serve the
    # foreign verdict — the association boundary, not mere readability.
    via_row = initiator_client.get("/v1/eval-judge/xlink-read-row")
    assert via_row.status_code == 404
    assert via_row.json() == {"detail": "no verdict for run_id"}

    # The W1-only member reads the row (it sits in W1) but cannot read the
    # foreign Run: the same non-disclosing "no verdict" answer.
    peer_client = _client_for(peer)
    via_peer = peer_client.get("/v1/eval-judge/xlink-read-row")
    assert via_peer.status_code == 404
    assert via_peer.json() == {"detail": "no verdict for run_id"}

    # A same-Workspace row keeps the alias working: the initiator reads the
    # same evidence through the W2 twin projection.
    asyncio.run(
        _projection_row(
            "twin-read-row", canonical_run_id=run_id, workspace_id=w2.id, user_id=initiator
        )
    )
    twin = initiator_client.get("/v1/eval-judge/twin-read-row")
    assert twin.status_code == 200, twin.text
    assert twin.json() == stores.eval_verdicts[run_id]
    assert twin.json()["score"] == scored.json()["score"]
    # The peer still cannot reach the W2 twin or the Run directly.
    assert peer_client.get("/v1/eval-judge/twin-read-row").status_code == 404
    assert peer_client.get(f"/v1/eval-judge/{run_id}").status_code == 404


# --- 5. Evidence protection --------------------------------------------------


def test_retry_after_success_returns_the_prior_verdict_without_a_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid verdict IS the score: an authorized retry (double-click, or a
    restart that dropped the in-flight registry) returns it verbatim and
    pays for no second model effect."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    initiator_client = _client_for(scene["initiator"], elevate=True)
    first = _stubbed_scorer(monkeypatch, '{"score": 91, "rationale": "ace"}')
    ok = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert ok.status_code == 200 and ok.json()["score"] == 91
    assert first == [scene["canonical_run_id"]]

    from services.eval_judge import reset_score_dedupe_for_tests

    reset_score_dedupe_for_tests()  # a restart clears process memory

    second = _score_spy(monkeypatch)  # a fresh attempt must not be needed
    retry = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert retry.status_code == 200
    assert retry.json() == ok.json()
    assert second == []
    import stores

    assert stores.eval_verdicts[scene["canonical_run_id"]]["score"] == 91


def test_erroring_scoring_cannot_downgrade_a_valid_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a successful score, a failing/unavailable/garbage model attempt
    cannot replace the valid verdict with an error or unknown row — pinned
    against the persist guard itself, with the route's own serving layer on
    top of it (a retry over a valid verdict never even reaches the model)."""
    import asyncio

    import stores
    from services.eval_judge import score_run

    canonical = "evidence-guard-run"

    class _Rec:
        run_id = canonical
        dag_id = "d"
        project_id = "p"

    async def _good(messages: list[dict], **kw: Any) -> str:
        return '{"score": 82, "rationale": "good"}'

    async def _boom(messages: list[dict], **kw: Any) -> str:
        raise RuntimeError("upstream 500")

    async def _garbage(messages: list[dict], **kw: Any) -> str:
        return "not json at all"

    first = asyncio.run(score_run(_Rec(), llm_call=_good, actor_id="a-1", workspace_id="w"))
    assert first["status"] == "ok"
    before = dict(stores.eval_verdicts[canonical])

    for attempt in (_boom, _garbage):
        receipt = asyncio.run(score_run(_Rec(), llm_call=attempt))
        # The caller may see the failed attempt's receipt…
        assert receipt["status"] == "error"
        # …but the shared evidence never downgraded.
        assert stores.eval_verdicts[canonical] == before


def test_error_verdict_stays_retryable_but_valid_verdict_never_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chosen revision semantics: an error receipt may be replaced by a later
    authorized score (retry-after-failure), while a valid verdict never
    downgrades — pinned directly against the persist guard."""
    import services.eval_judge as ej
    import stores

    class _Rec:
        run_id = "rev-run"
        dag_id = "d"
        project_id = "p"

    async def _boom(messages: list[dict], **kw: Any) -> str:
        raise RuntimeError("gateway down")

    async def _good(messages: list[dict], **kw: Any) -> str:
        return '{"score": 55, "rationale": "recovered"}'

    first = asyncio.run(ej.score_run(_Rec(), llm_call=_boom))
    assert first["status"] == "error"
    assert stores.eval_verdicts["rev-run"]["status"] == "error"

    second = asyncio.run(ej.score_run(_Rec(), llm_call=_good))
    assert second["status"] == "ok"
    assert stores.eval_verdicts["rev-run"]["score"] == 55

    async def _again_boom(messages: list[dict], **kw: Any) -> str:
        raise RuntimeError("gateway down again")

    asyncio.run(ej.score_run(_Rec(), llm_call=_again_boom))
    assert stores.eval_verdicts["rev-run"]["score"] == 55
    assert stores.eval_verdicts["rev-run"]["status"] == "ok"


def test_concurrent_authorized_scores_share_one_model_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two simultaneous authorized score requests for one logical run join a
    single in-flight invocation: one model effect, identical verdicts, one
    evidence row."""
    import services.eval_judge as ej
    import stores

    invocations: list[int] = []

    async def _slow_stub(messages: list[dict], **kw: Any) -> str:
        invocations.append(1)
        await asyncio.sleep(0.01)
        return '{"score": 70, "rationale": "once"}'

    class _Rec:
        run_id = "race-run"
        dag_id = "d"
        project_id = "p"

    async def _scene() -> list[dict[str, Any]]:
        first = ej.score_run(_Rec(), llm_call=_slow_stub, actor_id="a-1")
        second = ej.score_run(_Rec(), llm_call=_slow_stub, actor_id="a-2")
        return await asyncio.gather(first, second)

    v1, v2 = asyncio.run(_scene())
    assert v1 == v2
    assert v1["score"] == 70
    assert len(invocations) == 1
    assert stores.eval_verdicts["race-run"]["score"] == 70
    assert stores.eval_verdicts["race-run"]["scored_by"] in ("a-1", "a-2")


# --- 6. One logical score across producers ---------------------------------


def _chat_result(canonical_run_id: str) -> dict[str, Any]:
    """The facade result the chat producer scores from: it names the canonical
    Run (`run_id`), which is the same value `record_outcome` correlates the
    projection row with (#35/#1332)."""
    return {
        "status": "completed",
        "run_id": canonical_run_id,
        "node_results": {"node-1": {"role": "llm", "response": "done", "latency_ms": 5}},
    }


def _patch_producer_llm(monkeypatch: pytest.MonkeyPatch, payload: str) -> list[str]:
    """Let the chat producer run the REAL service through a stub model.

    `_eval_judge_score` passes no `llm_call`, so the service takes its lazy
    `graph_runner._build_llm_call` branch — the production path — and each
    built call records that one model effect happened.
    """
    import services.graph_runner as gr

    invocations: list[str] = []

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        invocations.append("producer")
        return payload

    monkeypatch.setattr(gr, "_build_llm_call", lambda: _stub_llm)
    return invocations


def test_automatic_chat_score_and_manual_retry_are_one_logical_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat producer's automatic score and a later authorized POST are ONE
    logical score, so both must key their evidence by the canonical Run.

    `services.chat_completion._eval_judge_score` scores the projection alias
    the producer minted, while the #2470 route scores — and guards
    idempotency by — the canonical Run that alias correlates to. The split
    leaves one Run with two evidence rows the optimizer counts twice
    (`_collect_eval_verdicts` matches on dag_id, not identity), and makes the
    route blind to a score that already exists, so the "retry" pays for a
    second model call.
    """
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    invocations = _patch_producer_llm(monkeypatch, '{"score": 88, "rationale": "automatic"}')

    from services.chat_completion import _eval_judge_score

    scored = asyncio.run(
        _eval_judge_score(scene["row_id"], "dag-chat", _chat_result(scene["canonical_run_id"]))
    )
    assert scored["status"] == "ok" and scored["score"] == 88
    assert invocations == ["producer"]

    import stores

    # One evidence row, under the canonical identity the mutation gate admits
    # — never under the alias.
    assert scene["row_id"] not in stores.eval_verdicts
    verdict = stores.eval_verdicts[scene["canonical_run_id"]]
    assert verdict["status"] == "ok"
    assert verdict["canonical_run_id"] == scene["canonical_run_id"]

    # The authorized POST for the same logical Run is a retry: it returns the
    # producer's verdict verbatim and pays for no second model effect.
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _stubbed_scorer(monkeypatch, '{"score": 12, "rationale": "must not run"}')
    retry = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert retry.status_code == 200, retry.text
    assert calls == []
    assert retry.json()["score"] == 88
    assert len(stores.eval_verdicts) == 1


def test_durable_alias_keyed_verdict_is_honored_without_a_second_paid_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence recorded before canonical keying still counts (#2470).

    `stores.eval_verdicts` is durable — SQLite-backed whenever persistence is
    configured — so an upgraded deployment still holds valid verdicts under
    the projection alias a producer minted. A guard that reads only the
    canonical key scores (and bills) such a Run a second time for evidence
    that already exists. The alias the same authorized read resolved names
    the same logical Run, so honoring its valid verdict keeps one paid model
    effect per logical score across the upgrade — and leaves the durable row
    byte-identical.
    """
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    import stores

    legacy = {
        "run_id": scene["row_id"],
        "dag_id": "dag-chat",
        "status": "ok",
        "score": 73,
        "rationale": "recorded before canonical keying",
        "evaluator_version": "eval-judge/1",
        "scored_at": "2026-11-22T00:00:00+00:00",
    }
    stores.eval_verdicts[scene["row_id"]] = legacy

    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _stubbed_scorer(monkeypatch, '{"score": 12, "rationale": "must not run"}')
    r = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert r.status_code == 200, r.text
    assert calls == []
    assert r.json()["score"] == 73
    assert stores.eval_verdicts[scene["row_id"]] == legacy
    assert len(stores.eval_verdicts) == 1


def test_canonical_id_post_honors_durable_alias_keyed_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller holding only the canonical id still gets the legacy score.

    The alias-keyed guard above only runs when the caller posts the alias;
    a canonical-id POST resolves through the canonical-only read path, which
    never sees the projection row. Without discovery, the same Run that a
    pre-upgrade verdict already scored is scored — and billed — a second
    time, writing a duplicate evidence row the optimizer counts twice. The
    scoped discovery resolves the alias the authorized Run was recorded
    under whichever id the caller used, so the stored verdict is the score,
    no model effect runs, and the durable row stays byte-identical.
    """
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    import stores

    legacy = {
        "run_id": scene["row_id"],
        "dag_id": "dag-chat",
        "status": "ok",
        "score": 73,
        "rationale": "recorded before canonical keying",
        "evaluator_version": "eval-judge/1",
        "scored_at": "2026-11-22T00:00:00+00:00",
    }
    stores.eval_verdicts[scene["row_id"]] = legacy

    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _stubbed_scorer(monkeypatch, '{"score": 12, "rationale": "must not run"}')
    r = initiator_client.post(f"/v1/eval-judge/{scene['canonical_run_id']}")
    assert r.status_code == 200, r.text
    assert calls == []
    assert r.json()["score"] == 73
    assert stores.eval_verdicts[scene["row_id"]] == legacy
    assert len(stores.eval_verdicts) == 1

    # The same evidence reads through the canonical id: one logical score,
    # visible through either identity the caller might hold.
    got = initiator_client.get(f"/v1/eval-judge/{scene['canonical_run_id']}")
    assert got.status_code == 200
    assert got.json()["score"] == 73


def test_alias_discovery_stays_inside_the_scoped_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery is the scoped read's job, not id algebra (#2470).

    A row that merely names this canonical Run proves nothing: a row filed
    in another Workspace is outside the caller's universe (and a cross-link
    the overlay deliberately leaves untouched), and the canonical id itself
    is not an alias. Only the same-Workspace row this caller may inspect
    comes back — the association rule the POST gate and the canonical read
    fallback already apply.
    """
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    asyncio.run(
        _projection_row(
            "foreign-row",
            canonical_run_id=scene["canonical_run_id"],
            workspace_id="ws-not-yours",
            user_id="someone-else",
        )
    )

    from services.dag_run_inspection import visible_aliases_for_canonical_run

    aliases = asyncio.run(
        visible_aliases_for_canonical_run(
            scene["initiator"], scene["canonical_run_id"], scene["workspace_id"]
        )
    )
    assert aliases == [scene["row_id"]]

    # A Workspace outside the caller's universe is closed even when the
    # canonical correlation matches: scoping happens before any discovery.
    assert (
        asyncio.run(
            visible_aliases_for_canonical_run(
                scene["initiator"], scene["canonical_run_id"], "ws-not-yours"
            )
        )
        == []
    )
    # Unknown Run: nothing to discover, no existence signal either way.
    assert (
        asyncio.run(
            visible_aliases_for_canonical_run(
                scene["initiator"], "run-unknown", scene["workspace_id"]
            )
        )
        == []
    )


def test_chat_producer_records_the_canonical_actor_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The automatic score is attributable evidence, not an anonymous row.

    A chat-launched score is a real scoring effect with a real principal
    behind it (the turn's initiator) inside a real Workspace. A verdict that
    names neither is unattributable in the store the optimizer ranks
    improvement proposals on, so the producer seam has to carry the canonical
    actor and scope through to `_persist` exactly as the route does.
    """
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    _patch_producer_llm(monkeypatch, '{"score": 61, "rationale": "attributed"}')

    from services.chat_completion import _eval_judge_score

    asyncio.run(
        _eval_judge_score(
            scene["row_id"],
            "dag-chat",
            _chat_result(scene["canonical_run_id"]),
            actor_id=scene["initiator"],
            workspace_id=scene["workspace_id"],
        )
    )

    import stores

    verdict = stores.eval_verdicts[scene["canonical_run_id"]]
    assert verdict["status"] == "ok"
    assert verdict["scored_by"] == scene["initiator"]
    assert verdict["workspace_id"] == scene["workspace_id"]
    assert verdict["evaluator_version"]


# --- 7. Degraded-spine answers and alias-evidence discovery edges ------------


def test_alias_keyed_read_is_direct_lookup_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A projection alias serves only the evidence recorded under ITSELF.

    Alias discovery exists for a caller who holds the canonical id and no
    alias at all (#2470); it must not become a side channel between sibling
    rows: a row read by its own alias never pulls a twin row's verdict in,
    even when both rows correlate to the same Run in the same Workspace and
    the caller may read both. The twin's evidence stays reachable through
    the twin's own id — that direct lookup is the proven read.
    """
    initiator, _ = _elevated_scorer("alias-direct-initiator")
    view = asyncio.run(_workspace("Alias Direct", initiator))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, view.id, initiator))
    asyncio.run(
        _projection_row(
            "alias-direct-row", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
        )
    )
    asyncio.run(
        _projection_row(
            "alias-twin-row", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
        )
    )
    import stores

    stores.eval_verdicts["alias-twin-row"] = {
        "status": "ok",
        "score": 55,
        "run_id": "alias-twin-row",
        "scored_at": "2020-01-01T00:00:00+00:00",
    }

    client = _client_for(initiator)
    # The twin's alias-keyed verdict is NOT pulled in through the sibling
    # row: alias-addressed reads are direct lookups, never discovery.
    refused = client.get("/v1/eval-judge/alias-direct-row")
    assert refused.status_code == 404
    assert refused.json() == {"detail": "no verdict for run_id"}
    # ... while the twin's own id still serves exactly what it holds.
    direct = client.get("/v1/eval-judge/alias-twin-row")
    assert direct.status_code == 200
    assert direct.json()["score"] == 55
    assert stores.eval_verdicts["alias-twin-row"]["score"] == 55


def test_canonical_keyed_read_degrades_to_no_verdict_without_a_spine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no engine bridge at all, a canonical-keyed read of a projection
    row degrades to the ordinary no-verdict answer (#2470): the alias is not
    honored (its proof needs the reader), and nothing about the canonical
    Run is confirmed."""
    initiator, _ = _elevated_scorer("nospine-read-initiator")
    view = asyncio.run(_workspace("No Spine Read", initiator))
    from services import engine as engine_mod

    monkeypatch.setattr(engine_mod, "_singleton", None)
    asyncio.run(
        _projection_row(
            "nospine-read-row", canonical_run_id="gone-run", workspace_id=view.id, user_id=initiator
        )
    )
    client = _client_for(initiator)
    answer = client.get("/v1/eval-judge/nospine-read-row")
    assert answer.status_code == 404
    assert answer.json() == {"detail": "no verdict for run_id"}


def test_canonical_keyed_read_degrades_to_no_verdict_with_a_readerless_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bridge that kept its store but lost its reader cannot prove the
    alias either: the read degrades to the same non-disclosing answer
    instead of trusting the row's unproven canonical_run_id."""
    initiator, _ = _elevated_scorer("readerless-read-initiator")
    view = asyncio.run(_workspace("Readerless Read", initiator))
    from services import engine as engine_mod

    store, _reader = _wire_spine(monkeypatch)
    monkeypatch.setattr(engine_mod, "_singleton", SimpleNamespace(run_store=store, run_reader=None))
    asyncio.run(
        _projection_row(
            "readerless-read-row",
            canonical_run_id="unreadable-run",
            workspace_id=view.id,
            user_id=initiator,
        )
    )
    client = _client_for(initiator)
    answer = client.get("/v1/eval-judge/readerless-read-row")
    assert answer.status_code == 404
    assert answer.json() == {"detail": "no verdict for run_id"}


def test_scoring_a_visible_run_without_a_spine_answers_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row is visible, the caller authorized — but the canonical spine
    that owns terminality and the mutation gate is not running: the POST
    answers 503 instead of scoring through a seam that cannot prove
    anything. A read-only answer would be a silent unjudged run."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    from services import engine as engine_mod

    monkeypatch.setattr(engine_mod, "_singleton", None)
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _score_spy(monkeypatch)

    refused = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert refused.status_code == 503
    assert refused.json() == {"detail": "canonical execution spine unavailable"}
    assert calls == []
    import stores

    assert dict(stores.eval_verdicts.items()) == {}
    assert _eval_score_audits() == []


def test_scoring_refuses_with_503_when_the_bridge_has_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-wired bridge (a reader without a Run store) cannot answer the
    mutation gate's questions: 503, before any effect."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    from services import engine as engine_mod

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=None, run_reader=scene["store"]),
    )
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _score_spy(monkeypatch)

    refused = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert refused.status_code == 503
    assert refused.json() == {"detail": "canonical execution spine unavailable"}
    assert calls == []


def test_readerless_bridge_scores_through_the_embedded_workspace_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The degraded-bridge path stays open to the authorized initiator: with
    a store but no reader, the gate wires the embedded Workspace authority
    into the store boundary and the terminal Run scores normally — one
    invocation, provenance intact, audited."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    from services import engine as engine_mod

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=scene["store"], run_reader=None),
    )
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _stubbed_scorer(monkeypatch, '{"score": 77, "rationale": "degraded"}')

    scored = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert scored.status_code == 200, scored.text
    assert scored.json()["score"] == 77
    assert calls == [scene["canonical_run_id"]]

    import stores

    verdict = stores.eval_verdicts[scene["canonical_run_id"]]
    assert verdict["status"] == "ok"
    assert verdict["workspace_id"] == scene["workspace_id"]
    audits = _eval_score_audits()
    assert len(audits) == 1
    assert audits[0]["target"] == scene["canonical_run_id"]


def test_scoring_refuses_with_503_when_the_embedded_authority_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When even the embedded Workspace authority cannot answer, the
    degraded path fails closed: 503, no model call, no evidence."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    from services import engine as engine_mod
    from services import workspace_authority as wa

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=scene["store"], run_reader=None),
    )

    def _unavailable() -> Any:
        raise wa.EmbeddedRuntimeUnavailable("embedded authority offline")

    monkeypatch.setattr(wa, "canonical_workspace_store", _unavailable)
    initiator_client = _client_for(scene["initiator"], elevate=True)
    calls = _score_spy(monkeypatch)

    refused = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert refused.status_code == 503
    assert refused.json() == {"detail": "canonical execution spine unavailable"}
    assert calls == []
    import stores

    assert dict(stores.eval_verdicts.items()) == {}
    assert _eval_score_audits() == []


def test_route_level_error_receipt_is_returned_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A route-level scoring attempt whose model call fails returns the
    error receipt it produced (the caller sees what the evidence path
    holds), writes no audit success, and leaves the canonical Run free for
    a real retry — which then lands a valid verdict and audits once."""
    scene = asyncio.run(_two_principal_scene(monkeypatch))
    initiator_client = _client_for(scene["initiator"], elevate=True)

    failed = _stubbed_scorer(monkeypatch, "this is not json")
    first = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "error"
    assert failed == [scene["canonical_run_id"]]

    import stores

    receipt = stores.eval_verdicts[scene["canonical_run_id"]]
    assert receipt["status"] == "error"
    assert _eval_score_audits() == []

    retried = _stubbed_scorer(monkeypatch, '{"score": 80, "rationale": "recovered"}')
    second = initiator_client.post(f"/v1/eval-judge/{scene['row_id']}")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "ok"
    assert second.json()["score"] == 80
    assert retried == [scene["canonical_run_id"]]
    assert stores.eval_verdicts[scene["canonical_run_id"]]["score"] == 80
    assert len(_eval_score_audits()) == 1


def test_alias_discovery_refuses_workspaces_outside_the_callers_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery answers [] for a caller whose Workspace universe does not
    contain the row's Workspace — the #1174 boundary guard in
    ``visible_aliases_for_canonical_run`` — and the same caller after
    joining sees the alias. The guard, not merely emptiness, is the pin:
    both calls run against the same seeded row."""
    from services.dag_run_inspection import visible_aliases_for_canonical_run

    initiator, _ = _elevated_scorer("alias-universe-initiator")
    outsider = _seed_user("alias-universe-outsider")
    view = asyncio.run(_workspace("Alias Universe", initiator))
    store, _reader = _wire_spine(monkeypatch)
    run_id = asyncio.run(_canonical_run(store, view.id, initiator))
    asyncio.run(
        _projection_row(
            "alias-universe-row", canonical_run_id=run_id, workspace_id=view.id, user_id=initiator
        )
    )
    import stores

    stores.eval_verdicts["alias-universe-row"] = {
        "status": "ok",
        "score": 61,
        "run_id": "alias-universe-row",
        "scored_at": "2020-01-01T00:00:00+00:00",
    }

    assert asyncio.run(visible_aliases_for_canonical_run(outsider, run_id, view.id)) == []

    from maistro.workspaces.model import WorkspaceRole

    asyncio.run(_grant_member(view.id, outsider, WorkspaceRole.MEMBER))
    assert asyncio.run(visible_aliases_for_canonical_run(outsider, run_id, view.id)) == [
        "alias-universe-row"
    ]
    # Blank keys refuse before any store or authority work: discovery is
    # defined for a real canonical Run in a real Workspace only.
    assert asyncio.run(visible_aliases_for_canonical_run(outsider, "", view.id)) == []
    assert asyncio.run(visible_aliases_for_canonical_run(outsider, run_id, "")) == []
