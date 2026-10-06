"""A chat-launched DAG run is cancellable by its projection id while in flight (#1332).

`services.chat_completion._tool_run_workflow` opens its Recent Runs projection
under a fresh execution id before the canonical Run exists, and used to leave
that row's `canonical_run_id` empty forever: `POST /v1/dag-runs/{id}/cancel`
fell back to the projection id, sent it to the canonical store, and answered
404 while the DAG kept running. The only tests that passed manufactured the
mapping by hand -- something the chat producer never writes.

The fix records the correlation at canonical admission: `execute_dag` fires an
`on_admitted` sink after `create_run` and BEFORE any physical node work, and
the producer persists it onto the already-open row via
`DagRunStore.record_canonical_run`. These tests drive that production path end
to end -- the real `canonical_dag_runner.execute_dag` against a real canonical
spine, a node genuinely parked mid-flight, and the shipped cancel route --
with no test-seeded mapping anywhere.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from maistro.graph.durable_runs import InMemoryDurableRunStore
from maistro.identity import Principal
from maistro.runs import InMemoryRunStore
from maistro.runs.scoped_reads import ScopedRunReader

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) in sys.path:
    sys.path.remove(str(_BACKEND))
sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("integration")]

_USER_ID = "chat-cancel-user"

_DAG_ID = "chat-cancel-dag"

_LEGACY_DAG: dict[str, Any] = {
    "id": _DAG_ID,
    "name": "Chat-launched DAG",
    "description": "launched from the chat workflow tool",
    "entry_node": "n1",
    "nodes": [
        {
            "id": "n1",
            "name": "n1",
            "role": "worker",
            "prompt": "long work",
            "config": {"execution_tier": "safe"},
        }
    ],
    "edges": [],
}


class _ScopedRequest:
    """Just what the dag-runs handlers read off a request: `state.principal`."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(principal=Principal(user_id=user_id, username=user_id))


class _Records:
    """A `JsonStore` narrowed to what `DagRunStore` uses, round-tripping json.

    The real store serialises, so a record carrying something unserialisable
    must fail here too rather than pass against a plain dict.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = json.dumps(value)

    def __getitem__(self, key: str) -> Any:
        return json.loads(self._data[key])

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def values(self) -> list[Any]:
        return [json.loads(raw) for raw in self._data.values()]

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)


@pytest.fixture(autouse=True)
def _fresh_projection_store_and_dag():
    """A private projection store and DAG record, restored on exit.

    `_tool_run_workflow` writes the process-global run history and reads the
    global `stores.dags` registry; both are restored so nothing this suite
    seeded can answer another suite's question.
    """
    import stores
    from services.dag_run_store import configure_dag_run_store

    configure_dag_run_store(None)
    previous_dag = stores.dags.get(_DAG_ID)
    stores.dags[_DAG_ID] = dict(_LEGACY_DAG)
    verdict_keys = set(stores.eval_verdicts.keys())
    yield
    stores.dags.pop(_DAG_ID, None)
    if previous_dag is not None:
        stores.dags[_DAG_ID] = previous_dag
    for key in list(stores.eval_verdicts.keys()):
        if key not in verdict_keys:
            stores.eval_verdicts.pop(key, None)
    # Leave a pristine non-durable store behind: exactly the state a suite
    # that never touched durability assumes.
    configure_dag_run_store(None)


def _blocking_llm_builder(release: asyncio.Event, exited: list[str]) -> Any:
    """An LLM call parked mid-flight until `release` is set.

    Nothing in the product ever sets it, so the Attempt can only settle by
    being cancelled -- which is what lets the test distinguish "the work was
    stopped" from "the record was edited".
    """

    def build(_on_response: Any = None):
        async def call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
            try:
                await release.wait()
                return "finished"  # pragma: no cover - never reached while cancelled
            finally:
                exited.append("provider-stopped")

        return call

    return build


def _fast_llm_builder() -> Any:
    def build(_on_response: Any = None):
        async def call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
            return f"ok:{messages[0]['content']}"

        return call

    return build


async def _owned_workspace() -> Any:
    from services.workspace_authority import create_workspace

    return await create_workspace(
        creator_user_id=_USER_ID,
        name="Chat Cancel",
        persona_template_id="pm_fleet",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )


def _canonical_run_store() -> InMemoryRunStore:
    from services.workspace_authority import canonical_store_for_tests

    return InMemoryRunStore(project_store=canonical_store_for_tests().project_store)


def _install_canonical_spine(monkeypatch: pytest.MonkeyPatch, canonical: Any) -> None:
    """Point every face of the seam at one real canonical spine.

    `canonical_dag_runner` resolves its canonical Run store through the
    Container (`_container().run_store`) and its durable-record store through
    `get_run_store()`; the cancel route resolves both through
    `services.engine.get_engine()`. A wired deployment composes them from the
    same Container, and so does this suite.
    """
    import services.canonical_dag_runner as runner
    import services.engine as engine_mod
    from services.workspace_authority import canonical_store_for_tests

    workspaces = canonical_store_for_tests()
    projects = workspaces.project_store
    monkeypatch.setattr(runner, "_container", lambda: SimpleNamespace(run_store=canonical))
    monkeypatch.setattr(runner, "get_run_store", lambda: InMemoryDurableRunStore())
    reader = ScopedRunReader(canonical, workspaces, projects)
    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_store=canonical, run_reader=reader),
    )


def _install_empty_spine(monkeypatch: pytest.MonkeyPatch) -> None:
    """An engine spine that never saw any Run (for the 404-on-cancel refusals)."""
    import services.engine as engine_mod

    from maistro.projects.scope_store import InMemoryProjectScopeStore

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(
            run_store=InMemoryRunStore(project_store=InMemoryProjectScopeStore()),
            run_reader=None,
        ),
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, builder: Any) -> None:
    """Swap the facade's compatibility LLM builder (the tool injects none)."""
    import services.graph_runner as graph_runner_module

    monkeypatch.setattr(graph_runner_module, "_build_llm_call", builder)


async def _wait_for_admitted_row(*, workspace_id: str, timeout_s: float = 15.0) -> dict[str, Any]:
    """Poll Recent Runs until the chat row carries its canonical correlation.

    The test never learns the projection id ahead of time -- the producer
    mints it -- and never writes the mapping: the row surfaces here only
    because the production admission seam recorded it. The row's `dag_id` is
    the producer's empty default; the workspace scope and the correlation are
    what identify it.
    """
    from services.dag_run_store import get_dag_run_store

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        for summary in get_dag_run_store().list_runs(limit=100):
            if summary.get("canonical_run_id") and summary.get("workspace_id") == workspace_id:
                return summary
        await asyncio.sleep(0.01)
    pytest.fail("chat-launched row never recorded its canonical admission")


async def _wait_for_running_attempt(canonical_run_store: Any, run_id: str) -> None:
    """Block until the Run's first Attempt is durably RUNNING (mid-flight)."""
    from maistro.runs import AttemptStatus

    for _ in range(1000):
        node_runs = await canonical_run_store.list_node_runs(run_id)
        if node_runs:
            attempts = await canonical_run_store.list_attempts(node_runs[0].node_run_id)
            if attempts and attempts[-1].status is AttemptStatus.RUNNING:
                return
        await asyncio.sleep(0.01)
    pytest.fail("Attempt never reached RUNNING; nothing mid-flight to cancel")


def _projection_detail(run_id: str) -> dict[str, Any]:
    from services.dag_run_store import get_dag_run_store

    detail = get_dag_run_store().get_run(run_id)
    assert detail is not None
    return detail


async def test_chat_launched_run_is_cancelled_by_projection_id_while_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production path: admit, park mid-flight, cancel by projection id.

    Every earlier test of this route seeded `canonical_run_id` by hand; this
    one holds a real chat-launched DAG in flight after canonical admission and
    cancels it through the exact canonical Run/Attempt -- with the mapping
    written by nobody but the producer's admission seam.
    """
    from routes.dag_runs import cancel_run as cancel_route
    from routes.dag_runs import get_run as get_run_route
    from services.chat_completion import _tool_run_workflow

    from maistro.runs import AttemptStatus, RunStatus

    view = await _owned_workspace()
    canonical = _canonical_run_store()
    _install_canonical_spine(monkeypatch, canonical)

    exited: list[str] = []
    release = asyncio.Event()
    _patch_llm(monkeypatch, _blocking_llm_builder(release, exited))

    # The producer itself: the same tool the chat surface calls. It mints the
    # projection id, opens the row, and runs the real canonical executor.
    tool_task = asyncio.create_task(
        _tool_run_workflow({"dag_id": _DAG_ID, "workspace_id": view.id}, _USER_ID, None)
    )

    row = await _wait_for_admitted_row(workspace_id=view.id)
    projection_id = str(row["id"])
    canonical_id = str(row["canonical_run_id"])
    # The correlation names a real, admitted canonical Run in the caller's own
    # Workspace -- before physical work is even cancellable.
    admitted = await canonical.get_run(canonical_id)
    assert admitted is not None
    assert admitted.workspace_id == view.id
    await _wait_for_running_attempt(canonical, canonical_id)

    # Scope authorization stands between a foreign principal and the canonical
    # target: the refusal is 404-shaped and the mid-flight Run is untouched.
    with pytest.raises(HTTPException) as refused:
        await cancel_route(projection_id, _ScopedRequest("not-a-member"))
    assert refused.value.status_code == 404
    still_running = await canonical.get_run(canonical_id)
    assert still_running is not None and still_running.status is RunStatus.RUNNING

    response = await cancel_route(projection_id, _ScopedRequest(_USER_ID))
    assert response == {"run_id": canonical_id, "status": "cancelled", "cancelled": True}

    # The physical work is over: the parked provider unwound, and the durable
    # record agrees at every altitude -- Run, NodeRun, Attempt.
    assert exited == ["provider-stopped"]
    assert release.is_set() is False
    run_after = await canonical.get_run(canonical_id)
    assert run_after is not None and run_after.status is RunStatus.CANCELLED
    node_runs = await canonical.list_node_runs(canonical_id)
    assert node_runs and all(nr.status is RunStatus.CANCELLED for nr in node_runs)
    attempts = await canonical.list_attempts(node_runs[0].node_run_id)
    assert attempts and attempts[-1].status is AttemptStatus.CANCELLED

    # The producer sees the cancelled Run settle: the walk's cancel fence is
    # answered with the spine's own truth, the row follows canonical
    # cancellation (not a failed stamp), and the turn gets a result instead of
    # an escaping CancelledError.
    answer = await asyncio.wait_for(tool_task, timeout=15)
    assert answer == {
        "run_id": projection_id,
        "dag_id": _DAG_ID,
        "status": "cancelled",
        "cancelled": True,
    }
    assert _projection_detail(projection_id)["status"] == "cancelled"
    detail = await get_run_route(projection_id, _ScopedRequest(_USER_ID))
    assert detail["status"] == "cancelled"
    assert detail["canonical_run_id"] == canonical_id


async def test_chat_launched_row_preserves_its_mapping_across_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh/reopen: the correlation is durable projection state, not memory.

    `record_canonical_run` persists like every other row mutation, so a
    process that reopens the records store still resolves the row to the same
    canonical Run.
    """
    from routes.dag_runs import get_run as get_run_route
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import DagRunStore, configure_dag_run_store, get_dag_run_store

    view = await _owned_workspace()
    _install_canonical_spine(monkeypatch, _canonical_run_store())
    _patch_llm(monkeypatch, _fast_llm_builder())

    records = _Records()
    configure_dag_run_store(records)
    answer = await _tool_run_workflow({"dag_id": _DAG_ID, "workspace_id": view.id}, _USER_ID, None)
    assert answer["status"] == "completed"
    projection_id = str(answer["run_id"])

    canonical_id = str(get_dag_run_store().get_run(projection_id)["canonical_run_id"])
    assert canonical_id, "the completed chat row records its canonical Run"

    # Reopen: a fresh store over the same durable records resolves the
    # projection id to the same canonical Run.
    reopened = DagRunStore(records=records)
    assert reopened.get_run(projection_id)["canonical_run_id"] == canonical_id

    # And so does the shipped read route.
    detail = await get_run_route(projection_id, _ScopedRequest(_USER_ID))
    assert detail["canonical_run_id"] == canonical_id


async def test_missing_admission_cannot_create_a_falsely_cancellable_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No canonical Container, no admission, no correlation -- and no cancel.

    A deployment without the canonical Container admits nothing, so the sink
    never fires and the row keeps its honest empty `canonical_run_id`. The
    row may complete as a success record, but the cancel route must refuse it
    (404) rather than pretend a projection id is a canonical Run.
    """
    import services.canonical_dag_runner as runner
    from routes.dag_runs import cancel_run as cancel_route
    from services.chat_completion import _tool_run_workflow

    view = await _owned_workspace()
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: InMemoryDurableRunStore())
    _install_empty_spine(monkeypatch)
    _patch_llm(monkeypatch, _fast_llm_builder())

    answer = await _tool_run_workflow({"dag_id": _DAG_ID, "workspace_id": view.id}, _USER_ID, None)
    assert answer["status"] == "completed"
    projection_id = str(answer["run_id"])

    assert _projection_detail(projection_id)["canonical_run_id"] == ""

    with pytest.raises(HTTPException) as refused:
        await cancel_route(projection_id, _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 404
    assert refused.value.detail == "run not found"


async def test_failed_admission_cannot_create_a_falsely_cancellable_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission that raises leaves a failed row with no correlation.

    The canonical store refusing `create_run` fails the execution; the
    producer's failure branch stamps the row failed, the sink never fires,
    and the cancel route answers 404 -- no mapping written only on the happy
    path, and no row that looks cancellable.
    """
    import services.canonical_dag_runner as runner
    from routes.dag_runs import cancel_run as cancel_route
    from services.chat_completion import _tool_run_workflow

    view = await _owned_workspace()

    class _RefusingStore:
        async def create_run(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("admission refused")

    monkeypatch.setattr(runner, "_container", lambda: SimpleNamespace(run_store=_RefusingStore()))
    monkeypatch.setattr(runner, "get_run_store", lambda: InMemoryDurableRunStore())
    _install_empty_spine(monkeypatch)

    answer = await _tool_run_workflow({"dag_id": _DAG_ID, "workspace_id": view.id}, _USER_ID, None)
    assert "error" in answer

    listed = _dag_run_summaries()
    assert [row["status"] for row in listed] == ["failed"]
    assert all(row["canonical_run_id"] == "" for row in listed)

    # The failure branch answers with the error only -- the row is where the
    # projection id lives.
    (row,) = listed
    with pytest.raises(HTTPException) as refused:
        await cancel_route(str(row["id"]), _ScopedRequest(_USER_ID))
    assert refused.value.status_code == 404


def _dag_run_summaries() -> list[dict[str, Any]]:
    from services.dag_run_store import get_dag_run_store

    return get_dag_run_store().list_runs(limit=100)


class TestTheAdmissionSinkItself:
    """`canonical_dag_runner.execute_dag`'s admission seam, in isolation."""

    async def _authorized_scope(self) -> Any:
        from services.dag_execution_scope import DagExecutionScope

        view = await _owned_workspace()
        root = await _owned_workspace_root_project(view)
        return DagExecutionScope(workspace_id=view.id, project_id=root.project_id, user_id=_USER_ID)

    async def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        scope: Any,
        canonical_run_store: Any,
        on_admitted: Any,
    ) -> dict[str, Any]:
        import services.canonical_dag_runner as runner

        monkeypatch.setattr(
            runner, "_container", lambda: SimpleNamespace(run_store=canonical_run_store)
        )
        monkeypatch.setattr(runner, "get_run_store", lambda: InMemoryDurableRunStore())
        return await runner.execute_dag(
            dict(_LEGACY_DAG),
            llm_builder=_fast_llm_builder(),
            scope=scope,
            on_admitted=on_admitted,
        )

    async def test_the_sink_fires_once_at_admission_before_physical_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly one call, with the admitted id, while the Run is still QUEUED.

        QUEUED is the admission state: physical work moves the Run past it, so
        a sink that observes QUEUED observed the correlation window the
        cancellation timing requires (#1332).
        """
        from maistro.runs.model import RunStatus

        scope = await self._authorized_scope()
        canonical = _canonical_run_store()
        seen: list[tuple[str, Any]] = []

        async def on_admitted(run_id: str) -> None:
            run = await canonical.get_run(run_id)
            seen.append((run_id, run.status if run else None))

        result = await self._run(
            monkeypatch, scope=scope, canonical_run_store=canonical, on_admitted=on_admitted
        )

        assert result["status"] == "completed"
        assert len(seen) == 1
        assert seen[0][0] == result["run_id"]
        assert seen[0][1] is RunStatus.QUEUED

    async def test_the_sink_is_not_invoked_without_a_canonical_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scope = await self._authorized_scope()
        seen: list[str] = []

        async def on_admitted(run_id: str) -> None:  # pragma: no cover - must not run
            seen.append(run_id)

        result = await self._run(
            monkeypatch, scope=scope, canonical_run_store=None, on_admitted=on_admitted
        )

        assert result["status"] == "completed"
        assert seen == []

    async def test_a_raising_sink_does_not_fail_the_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The canonical Run is already admitted when the sink runs; a failed
        projection write must not abort execution and strand it QUEUED."""
        scope = await self._authorized_scope()

        async def on_admitted(run_id: str) -> None:
            raise RuntimeError("the projection row is gone")

        result = await self._run(
            monkeypatch,
            scope=scope,
            canonical_run_store=_canonical_run_store(),
            on_admitted=on_admitted,
        )

        assert result["status"] == "completed"


async def _owned_workspace_root_project(view: Any) -> Any:
    from services.workspace_authority import canonical_store_for_tests

    return await canonical_store_for_tests().project_store.root_for_workspace(view.id)


class TestRecordCanonicalRun:
    """`DagRunStore.record_canonical_run` -- the write the producer's sink makes."""

    async def test_the_mapping_is_written_and_persisted(self) -> None:
        from services.dag_run_store import DagRunStore

        records = _Records()
        store = DagRunStore(records=records)
        await store.start_run(run_id="exec-1", workspace_id="ws-1")

        assert await store.record_canonical_run("exec-1", canonical_run_id="run-can-1") is True
        assert store.list_runs()[0]["canonical_run_id"] == "run-can-1"
        # Durable form, not just the working set.
        assert records["exec-1"]["canonical_run_id"] == "run-can-1"

    async def test_a_reopened_store_still_resolves_the_mapping(self) -> None:
        from services.dag_run_store import DagRunStore

        records = _Records()
        store = DagRunStore(records=records)
        await store.start_run(run_id="exec-1")
        await store.record_canonical_run("exec-1", canonical_run_id="run-can-1")

        reopened = DagRunStore(records=records)
        assert reopened.get_run("exec-1")["canonical_run_id"] == "run-can-1"

    async def test_a_missing_row_records_nothing(self) -> None:
        from services.dag_run_store import DagRunStore

        store = DagRunStore()
        assert await store.record_canonical_run("ghost", canonical_run_id="run-can-1") is False

    async def test_an_empty_id_is_refused(self) -> None:
        from services.dag_run_store import DagRunStore

        store = DagRunStore()
        await store.start_run(run_id="exec-1")
        assert await store.record_canonical_run("exec-1", canonical_run_id="") is False
        assert store.list_runs()[0]["canonical_run_id"] == ""

    async def test_the_first_link_wins(self) -> None:
        from services.dag_run_store import DagRunStore

        store = DagRunStore()
        await store.start_run(run_id="exec-1")

        assert await store.record_canonical_run("exec-1", canonical_run_id="run-a") is True
        # Re-recording the same id is idempotent...
        assert await store.record_canonical_run("exec-1", canonical_run_id="run-a") is True
        # ...but re-pointing the row at another Run is refused: the read
        # overlay treats a cross-linked row as its own truth, and the write
        # side must not manufacture one.
        assert await store.record_canonical_run("exec-1", canonical_run_id="run-b") is False
        assert store.list_runs()[0]["canonical_run_id"] == "run-a"
