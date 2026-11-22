"""The #2465 public projection: sentinel failure evidence never crosses.

Endpoint tests inject distinctive secret sentinel strings, provider exception
text, filesystem paths and diagnostics into canonical failed-node evidence and
assert that no public surface — the DAG run receipt body, the champion
receipt, the websocket/SSE frame projection — returns them in ANY nested
field, while truthful canonical status, Run ids, the retryable 429/Retry-After
admission contract and bounded safe failure kinds are preserved, and a failed
Run is never projected as a successful one.

The sentinel-bearing evidence stays on the canonical NodeRun/Run records,
where the authorized inspection plane (`GET /v1/dag-runs/{id}` via the #1877
canonical overlay, and maistro-server run inspection) still serves it for
forensics. These tests pin the boundary, not the store.

The one structured remediation (`ALLOW_STUB_LLM`) and the host-authored
budget/deadline failure kinds are pinned to survive, because they are the
"bounded safe failure kinds" the policy keeps.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest
from fastapi import HTTPException

from maistro.identity import Principal

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

#: Distinctive evidence a real failure carries and a public body must not:
#: a provider reply with a bearer token, a filesystem path, a diagnostics
#: dump with an internal hostname and a fake credential.
SECRET_SENTINEL = "sk-live-SENTINEL-9f2c1"
PROVIDER_SENTINEL = (
    'provider api.internal.example: 401 {"error": {"message": '
    '"bearer sk-live-SENTINEL-9f2c1 rejected"}}'
)
PATH_SENTINEL = "/srv/hive/secrets/openai.key"
DIAGNOSTIC_SENTINEL = (
    "Traceback (most recent call last): connect to db-primary.internal:5432 "
    "failed for user svc_hive password=hunter2"
)
ALL_SENTINELS = (SECRET_SENTINEL, PROVIDER_SENTINEL, PATH_SENTINEL, DIAGNOSTIC_SENTINEL)

NODE_FAILURE_TEXT = "node failed; see server logs"
RUN_FAILURE_TEXT = "run failed; see server logs"


class _DesignState:
    """A design route request's `state`, attributes set per call."""


class _DesignRequest:
    def __init__(self, **attrs: Any) -> None:
        self.state = _DesignState()
        for name, value in attrs.items():
            setattr(self.state, name, value)


def _seed(client: Any) -> str:
    response = client.post("/v1/dags", json={"name": "sentinel", "description": ""})
    assert response.status_code == 201
    return response.json()["id"]


def _workspace(client: Any) -> str:
    response = client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "Sentinel runs"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _failed_canonical_result(run_id: str = "run-sentinel-1") -> dict[str, Any]:
    """The canonical projection shape of a DAG whose nodes failed mid-flight.

    Mirrors `canonical_dag_runner._project`: a failed node's response held the
    raw node error (`node_run.error`) and the run-level error carried the same
    text. Every sentinel class appears in a nested field.
    """
    return {
        "status": "failed",
        "run_id": run_id,
        "cycles": 1,
        "workspace_id": "ws-1",
        "project_id": "proj-1",
        "error": f"NodeFailure: {PROVIDER_SENTINEL} {PATH_SENTINEL}",
        "node_results": {
            "n-ok": {
                "role": "worker",
                "success": True,
                "response": "did the thing",
                "model": "model-a",
            },
            "n-bad": {
                "role": "worker",
                "success": False,
                "response": f"{PROVIDER_SENTINEL} {PATH_SENTINEL} {DIAGNOSTIC_SENTINEL}",
                "model": "model-a",
            },
        },
        "annotations": {},
    }


def _assert_no_sentinels(payload: Any) -> None:
    import json

    rendered = json.dumps(payload)
    for sentinel in ALL_SENTINELS:
        assert sentinel not in rendered, f"leaked sentinel {sentinel!r} in {rendered[:400]}"


class TestTheDagRunReceiptCarriesNoNestedFailureText:
    def test_canonical_failure_body_is_fully_projected(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole body — result.error and every node_results response —
        obeys the same kind-only policy the top-level error always had."""
        import services.graph_runner as graph_runner

        failed = _failed_canonical_result()

        async def fail(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
            raise graph_runner.CanonicalDagExecutionError(dict(failed))

        monkeypatch.setattr(graph_runner, "execute_dag", fail)
        dag_id = _seed(admin_client)
        workspace_id = _workspace(admin_client)
        response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
        assert response.status_code == 200
        body = response.json()

        # Truthful canonical facts survive the projection.
        assert body["status"] == "failed"
        assert body["run_id"] == "run-sentinel-1"
        assert body["result"]["run_id"] == "run-sentinel-1"
        # No sentinel in any nested field.
        _assert_no_sentinels(body)
        # Bounded kinds, not the raw text.
        assert body["error"] == "CanonicalDagExecutionError: execution failed; see server logs"
        assert body["result"]["error"] == RUN_FAILURE_TEXT
        assert body["result"]["node_results"]["n-bad"]["response"] == NODE_FAILURE_TEXT
        # A failure is never laundered into success.
        assert body["result"]["node_results"]["n-bad"]["success"] is False
        # Authorized task output stays verbatim (the explicit contract).
        assert body["result"]["node_results"]["n-ok"]["response"] == "did the thing"

        # The persisted Recent Runs projection and its SSE replay events the
        # UI serves are projected too: no sentinel in any event payload, and
        # failed nodes record no response text at all.
        from services.dag_run_store import get_dag_run_store

        projection = get_dag_run_store().get_run("run-sentinel-1")
        assert projection is not None
        assert projection["status"] == "failed"
        _assert_no_sentinels(projection)
        assert projection["node_states"].get("worker.n-bad") == "failed"

    def test_success_body_still_carries_the_task_output(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The presentation contract: successful responses are the caller's
        own task output and cross verbatim — the policy bounds failure
        evidence, not work product."""
        import services.graph_runner as graph_runner

        completed = {
            "status": "completed",
            "run_id": "run-sentinel-ok",
            "cycles": 1,
            "error": "",
            "node_results": {
                "n1": {
                    "role": "worker",
                    "success": True,
                    "response": f"answer citing {PATH_SENTINEL}-like task text is still the user's own output",
                    "model": "model-a",
                }
            },
            "annotations": {},
        }

        async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
            return dict(completed)

        monkeypatch.setattr(graph_runner, "execute_dag", ok)
        dag_id = _seed(admin_client)
        workspace_id = _workspace(admin_client)
        response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert (
            body["result"]["node_results"]["n1"]["response"]
            == completed["node_results"]["n1"]["response"]
        )

    def test_champion_receipt_is_projected_too(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.graph_runner as graph_runner

        completed = {
            "status": "completed",
            "run_id": "run-champion-sentinel",
            "cycles": 1,
            "node_results": {
                "n1": {"role": "worker", "success": False, "response": PROVIDER_SENTINEL},
            },
            "annotations": {},
        }

        async def ok(**_kwargs: Any) -> dict[str, Any]:
            return dict(completed)

        monkeypatch.setattr(graph_runner, "execute_champion", ok)
        workspace_id = _workspace(admin_client)
        response = admin_client.post("/v1/dags/run-champion", json={"workspace_id": workspace_id})
        assert response.status_code == 200
        _assert_no_sentinels(response.json())
        assert response.json()["result"]["node_results"]["n1"]["response"] == NODE_FAILURE_TEXT


class TestAdmissionBackpressureKeepsItsContract:
    def test_a_full_ceiling_is_still_a_retryable_429(
        self, admin_client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The #1182 admission contract is untouched by the projection policy:
        a full canonical root-Run ceiling answers 429 + Retry-After before any
        execution, never a failure receipt."""
        import services.graph_runner as graph_runner

        from maistro.runs.chat_refusal import CHAT_TURN_RETRY_AFTER_S
        from maistro.runs.concurrency import RunConcurrencyExceeded

        async def refuse(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RunConcurrencyExceeded(scope="principal", limit=3, active=3)

        monkeypatch.setattr(graph_runner, "execute_dag", refuse)
        dag_id = _seed(admin_client)
        workspace_id = _workspace(admin_client)
        response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
        assert response.status_code == 429
        assert response.headers["Retry-After"] == str(CHAT_TURN_RETRY_AFTER_S)
        assert "too many active runs for this principal" in response.json()["detail"]
        assert "hunter2" not in response.text


class TestBudgetKindsSurviveTheProjection:
    def test_host_authored_failure_text_is_kept(self) -> None:
        """Cycle budgets and deadlines are the host's own bounded sentences —
        the "bounded safe failure kinds" that must stay actionable."""
        from services.safe_projection import public_failure_text

        budget = (
            "CycleBudgetExhausted: run exceeded max_cycles=1 after 1 completed "
            "frontier(s); the graph owes work its declared cycle budget does not cover"
        )
        deadline = "AttemptDeadlineExceeded: attempt deadline exceeded (timeout_s=15)"
        assert public_failure_text(budget) == budget
        assert "max_cycles=1" in public_failure_text(budget)
        assert public_failure_text(deadline) == deadline

    def test_unclassified_run_text_is_bounded(self) -> None:
        from services.safe_projection import RUN_FAILURE_TEXT, public_failure_text

        raw = f"NodeFailure: {PROVIDER_SENTINEL}"
        assert public_failure_text(raw) == RUN_FAILURE_TEXT
        assert PATH_SENTINEL not in public_failure_text(raw)

    def test_stub_refusal_remediation_survives(self) -> None:
        """The no-gateway refusal names ALLOW_STUB_LLM on purpose; the policy
        keeps that one env-var name actionable at the run level."""
        from services.safe_projection import public_failure, public_failure_text

        refusal = "No LLM gateway is configured: ... set ALLOW_STUB_LLM=true ..."
        assert "ALLOW_STUB_LLM" in public_failure_text(refusal)
        exc = RuntimeError(refusal)
        assert "ALLOW_STUB_LLM" in public_failure(exc)


class TestTheStreamProjectionCarriesNoNestedFailureText:
    async def test_replayed_frames_project_failed_nodes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The websocket/SSE generator projects the same result: a failed
        node's replayed frame carries the bounded kind, and the terminal frame
        stays a kind — the sentinels never reach the socket."""
        import services.graph_runner as graph_runner

        failed = _failed_canonical_result("run-sentinel-stream")

        async def fail(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
            raise graph_runner.CanonicalDagExecutionError(dict(failed))

        monkeypatch.setattr(graph_runner, "execute_dag", fail)

        frames: list[dict[str, Any]] = []
        async for frame in graph_runner.execute_dag_streaming({"nodes": [], "edges": []}):
            frames.append(frame)

        _assert_no_sentinels(frames)
        terminal = frames[-1]
        assert terminal["status"] == "failed"
        assert terminal["error"] == "CanonicalDagExecutionError: execution failed; see server logs"
        node_frames = [f for f in frames if f.get("status") == "node_complete"]
        failed_frames = [f for f in node_frames if f["node_id"] == "n-bad"]
        assert failed_frames and failed_frames[0]["response"] == NODE_FAILURE_TEXT
        assert failed_frames[0]["success"] is False
        ok_frames = [f for f in node_frames if f["node_id"] == "n-ok"]
        assert ok_frames and ok_frames[0]["response"] == "did the thing"

    async def test_live_node_frames_carry_no_error_payload(self) -> None:
        """A node_failed live frame (the only failure-bearing live frame)
        carries no response text: the adapter emits node_failed without a
        response payload, and the frame projects exactly that emptiness — the
        raw error has no path to a live consumer at all."""
        from services.graph_runner import _live_node_frame

        # The exact event shape the legacy node adapter emits on failure
        # (services.legacy_dag_node._execute's node_failed emit): identity and
        # role only — never a response.
        frame = _live_node_frame(
            {
                "kind": "node_failed",
                "run_id": "run-x",
                "node_run_id": "nr-1",
                "attempt_id": "at-1",
                "node_id": "n-bad",
                "role": "worker",
            }
        )
        assert frame["success"] is False
        assert frame["response"] == ""
        _assert_no_sentinels(frame)

    async def test_recorded_sse_events_carry_no_error_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SSE projection (`LiveRunProjection.record_event`) records a
        response payload only for completed nodes; a failed node's durable
        live event payload carries no failure text — the replayed stream
        cannot leak what the frames do not."""
        from services.dag_execution_scope import DagExecutionScope
        from services.dag_run_live import LiveRunProjection

        captured: list[dict[str, Any]] = []

        class _Event:
            seq = 1

        class _Store:
            async def start_run(self, **_: Any) -> None:
                return None

            async def append_event(self, _run_id: str, **kwargs: Any) -> Any:
                captured.append(dict(kwargs.get("payload") or {}))
                return _Event()

        import services.dag_run_store as store_module

        monkeypatch.setattr(store_module, "get_dag_run_store", lambda: _Store())

        scope = DagExecutionScope(workspace_id="ws", project_id="proj", user_id="u1")
        projection = LiveRunProjection(dag_id="dag", scope=scope)
        await projection.record_event(
            {
                "kind": "node_failed",
                "run_id": "run-sse",
                "node_id": "n-bad",
                "role": "worker",
                "response": DIAGNOSTIC_SENTINEL,
            }
        )
        assert captured, "the failed-node event must be recorded"
        assert "response" not in captured[0]
        _assert_no_sentinels(captured[0])


class TestDesignRoutesNameTheKindNeverTheText:
    """Design's generic 500 branches used to answer `detail=str(e)` /
    `f"... failed: {e!s}"` — unclassified exception text (paths, provider
    replies, diagnostics) straight to the client (#2465). Classified domain
    errors (404/400 with their own user-facing messages), the recorded
    startup causes (#293/#1826) and the retryable 429 contract keep their
    documented shapes; only the unexpected-exception branches are bounded.
    """

    @pytest.fixture()
    def ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from routes import design as design_routes

        class _Status:
            ready = True
            cause = ""
            store_cause = None

        monkeypatch.setattr(design_routes, "get_design_status", lambda: _Status())

    class _Store:
        async def get(self, project_id: str, *, org_id: str) -> Any:
            raise RuntimeError(f"dsn=postgresql://svc:hunter2@db.internal/design {PATH_SENTINEL}")

        async def list_by_org(self, org_id: str) -> list[Any]:
            raise RuntimeError(f"list failed against db-primary.internal: {PATH_SENTINEL}")

    async def test_project_fetch_500_names_the_kind_not_the_store_detail(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from routes import design as design_routes

        monkeypatch.setattr(design_routes, "get_design_store", lambda: self._Store())
        with pytest.raises(HTTPException) as raised:
            await design_routes.get_design_project("p-1", _DesignRequest())
        assert raised.value.status_code == 500
        assert "Project fetch failed" in str(raised.value.detail)
        assert "RuntimeError" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))

    async def test_project_listing_500_names_the_kind_not_the_store_detail(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from routes import design as design_routes

        monkeypatch.setattr(design_routes, "get_design_store", lambda: self._Store())
        with pytest.raises(HTTPException) as raised:
            await design_routes.list_design_projects(_DesignRequest())
        assert raised.value.status_code == 500
        assert "Project listing failed" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))

    async def test_preparation_500_keeps_its_operation_name_and_drops_the_text(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The create route's 500 keeps the "Project preparation failed"
        operation name (the #52-era honest-500 contract) while the exception
        text is bounded to its kind."""
        from routes import design as design_routes

        class _Engine:
            @staticmethod
            async def generate(*a: Any, **k: Any) -> Any:
                raise RuntimeError(f"prompt assembler exploded: {PROVIDER_SENTINEL}")

        class _Canonical:
            @staticmethod
            async def generate(*, operation: Any, **_: Any) -> Any:
                return await operation()

        monkeypatch.setattr(design_routes, "get_design_store", lambda: object())
        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())

        async def _canonical_for(_principal_id: str) -> Any:
            return _Canonical()

        monkeypatch.setattr(
            design_routes, "get_design_canonical_execution_for_principal", _canonical_for
        )
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_design_project(
                _DesignRequest(org_id="org-7", principal=Principal(user_id="user-1")),
                object(),
            )
        assert raised.value.status_code == 500
        assert "Project preparation failed" in str(raised.value.detail)
        assert "RuntimeError" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))

    async def test_skill_listing_500_names_the_kind_not_the_catalog_detail(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /design/skills' generic 500 bounds the exception text (#2465)."""
        from routes import design as design_routes

        class _Skills:
            @staticmethod
            def list_available(_filled: Any) -> list[Any]:
                raise ValueError(f"catalog enumerate walked {PATH_SENTINEL}: {DIAGNOSTIC_SENTINEL}")

        class _Engine:
            _skills = _Skills()

        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())
        monkeypatch.setattr(
            design_routes,
            "get_renderer_registry",
            lambda: type("R", (), {"filled_slots": staticmethod(lambda: frozenset())})(),
        )
        with pytest.raises(HTTPException) as raised:
            await design_routes.list_design_skills()
        assert raised.value.status_code == 500
        assert "Skill listing failed" in str(raised.value.detail)
        assert "ValueError" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))

    async def test_discovery_form_500_names_the_kind_not_the_engine_detail(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /design/skills/{slug}/discovery's generic 500 (distinct from the
        classified 404 SkillNotFoundError branch, which keeps its message)."""
        from routes import design as design_routes

        class _Engine:
            @staticmethod
            async def run_discovery(_slug: str) -> Any:
                raise RuntimeError(f"discovery probe failed: {PROVIDER_SENTINEL}")

        monkeypatch.setattr(design_routes, "get_design_engine", lambda: _Engine())
        with pytest.raises(HTTPException) as raised:
            await design_routes.get_skill_discovery_form("deck-builder")
        assert raised.value.status_code == 500
        assert "Discovery form unavailable" in str(raised.value.detail)
        assert "RuntimeError" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))

    async def test_render_creation_500_names_the_kind_not_the_store_detail(
        self, ready: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /design/projects/{id}/render's generic 500 (#2465); the 404
        unknown-project and 501 capability branches keep their own shapes."""
        from routes import design as design_routes

        monkeypatch.setattr(design_routes, "get_design_store", lambda: self._Store())
        with pytest.raises(HTTPException) as raised:
            await design_routes.create_render_job("p-1", _DesignRequest())
        assert raised.value.status_code == 500
        assert "Render job creation failed" in str(raised.value.detail)
        assert "RuntimeError" in str(raised.value.detail)
        _assert_no_sentinels(str(raised.value.detail))


class TestTheProjectionSeamIsTheSinglePolicy:
    async def test_node_results_project_failed_responses_at_the_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_project` itself bounds failed-node responses, so every transport
        (HTTP receipt, websocket, the LiveRunProjection recorder) inherits the
        policy from one seam — not from per-route fixes."""
        import services.canonical_dag_runner as runner

        from maistro.runs.model import RunStatus

        record = type(
            "Record",
            (),
            {
                "run_id": "run-proj",
                "node_runs": [
                    type(
                        "NodeRun",
                        (),
                        {
                            "node_id": "n-bad",
                            "status": RunStatus.FAILED,
                            "result": {"response": PROVIDER_SENTINEL, "role": "worker"},
                            "error": PROVIDER_SENTINEL,
                        },
                    )(),
                    type(
                        "NodeRun",
                        (),
                        {
                            "node_id": "n-ok",
                            "status": RunStatus.COMPLETED,
                            "result": {"response": "fine", "role": "worker", "model": "m"},
                            "error": None,
                        },
                    )(),
                ],
                "run": type(
                    "Run",
                    (),
                    {
                        "status": RunStatus.FAILED,
                        "error": f"NodeFailure: {PATH_SENTINEL}",
                        "workspace_id": "ws",
                        "project_id": "proj",
                        "provenance": {},
                    },
                )(),
                "graph_state": type("State", (), {"cycle": 1, "blackboard_snapshot": {}})(),
            },
        )()

        projected = runner._project(record, {"n-bad": {}, "n-ok": {}})

        assert projected["node_results"]["n-bad"]["response"] == NODE_FAILURE_TEXT
        assert projected["node_results"]["n-ok"]["response"] == "fine"
        _assert_no_sentinels(projected["node_results"])
