"""Stateful generated API workflows over the tasks/runs/workspace surface (M8-A13, #893).

Research prototype for [#893](https://github.com/Agent-StrongHold/Project-mAIstro/issues/893):
one representative *stateful* API workflow suite, evaluating generated
multi-step workflows against a real service surface, compared with the
existing stateless endpoint tests it deliberately does not duplicate.

Shape of the experiment
-----------------------

A Hypothesis ``RuleBasedStateMachine`` drives the real ``maistro-server``
routers (tasks, runs, workspaces, projects) through an in-process ASGI
client on the same in-memory canonical Run spine the production lifespan
wires for a no-database deployment. Request bodies for task submission are
drawn from the served OpenAPI document via schemathesis positive-mode
generation — the schema stays the source of client-meaningful payload shape —
while the state machine supplies what stateless generation cannot:

- transition rules over created resources (create → query → cancel →
  stale-identifier probes),
- cross-request data dependencies (task_id/run_id/parent_project_id from
  responses feed later requests),
- authorization variants (a second principal interleaves its own workflow
  and probes the first one's resources),
- idempotency/retry relations (explicit keys, derived keys, replay after
  cancellation, key-payload mismatch, distinct keys for identical payloads).

Every rule pins a *relation*, not an endpoint: the assertions compare each
response against a model of everything this scenario did before, which is
the failure class single-request endpoint tests cannot reach (an ordering,
an interleaving, or a second principal).

The oracle encodes production semantics as they stand at this head: a Run
cancelled through ``POST /runs/{id}/cancel`` terminalizes the canonical Run
*and* projects that truth onto its task receipt inside the same request, so
the two cancel routes must agree afterwards — the receipt route refuses the
repeat cancellation and a terminal admission still replays its original
identity. (The leaf's base commit left the receipt ``queued`` pending a
worker reconcile; ``cancel_run``'s receipt projection closed that asymmetry
on develop and this suite caught the semantic change at the sync — which is
the argument for running it on every PR.)

Native Schemathesis stateful testing (``schema.as_state_machine()``) cannot
run against this surface: it requires OpenAPI response ``links``, and the
served spec declares none (asserted below as contract documentation). This
file is the "equivalent generated workflow testing" arm of the experiment;
the evaluation and disposition live in
``docs/research/893-stateful-api-workflows.md``.

Runtime knobs
-------------

PR-suitable by default (derandomized, ~25 examples, up to 12 steps each). Nightly
depth without touching the file::

    MAISTRO_STATEFUL_API_EXAMPLES=200 MAISTRO_STATEFUL_API_STEPS=40 \
        uv run pytest packages/maistro-server/tests/api/test_stateful_workflow_api.py

The suite is hermetic: no PostgreSQL, no LiteLLM, no network, no worker.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest
import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, Phase, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)
from schemathesis import GenerationMode

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.concurrency import RunConcurrencyLimits
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks import queue as queue_module
from maistro.tasks.idempotency import MAX_IDEMPOTENCY_KEY_LENGTH, InMemoryTaskIdempotencyStore
from maistro.tasks.queue import configure_task_queue
from maistro.workspaces import InMemoryWorkspaceStore
from maistro_server.api import runs as runs_api
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.projects import router as projects_router
from maistro_server.api.runs import router as runs_router
from maistro_server.api.tasks import IDEMPOTENCY_KEY_HEADER, WORKSPACE_ID_HEADER
from maistro_server.api.tasks import router as tasks_router

#: The API contract for the workspace mount root, gated by
#: ``validate_workspace_path`` — the only workspace literal admission accepts
#: without the Hive HMAC scope proof.
WORKSPACE_MOUNT = "/tmp/maistro-workspace/test"  # nosec B108 — API contract, validated by the route

PRINCIPALS = ("alice", "bob")

#: CI examples — kept small because every step issues real HTTP through the
#: ASGI stack; nightly depth comes from the env knobs above.
CI_EXAMPLES = int(os.environ.get("MAISTRO_STATEFUL_API_EXAMPLES", "25"))
CI_STEPS = int(os.environ.get("MAISTRO_STATEFUL_API_STEPS", "12"))

TERMINAL_RECEIPT = frozenset({"completed", "failed", "cancelled"})


class _Surface:
    """The hermetic app plus everything the state machine needs to drive it."""

    def __init__(
        self,
        client: TestClient,
        submit_strategy: st.SearchStrategy,
        holder: dict[str, str],
    ) -> None:
        self.client = client
        self.submit_strategy = submit_strategy
        self.holder = holder
        self.principal = holder["user"]

    def as_(self, user: str) -> None:
        # The auth dependency closure reads `holder` per request, so this is
        # exactly what a second authenticated client session would produce.
        self.holder["user"] = user
        self.principal = user


@pytest.fixture
async def surface() -> AsyncIterator[_Surface]:
    """The tasks/runs/workspaces/projects routers on the in-memory spine.

    Same wiring shape the production lifespan uses for a no-database
    deployment (see ``test_tasks_idempotency.py``): the queue resolves through
    the process singleton, so installing it here *is* the wiring, and the
    requests run on the exact code path production uses.
    """
    previous_queue = queue_module._queue
    queue_module._queue = None
    (
        _scope,
        run_store,
        admitter,
        _templates,
        _schedules,
        _continuations,
    ) = await wire_execution_spine(
        None,
        workspace_id="test-workspace",
        # The suite admits dozens of runs per scenario; the default
        # per-principal backpressure ceiling (429) must not be the first
        # thing the generator discovers. High-but-finite keeps the
        # ceiling semantics real while pointing the budget at workflow
        # relations.
        concurrency_limits=RunConcurrencyLimits(per_principal=10_000, per_workspace=10_000),
    )
    projects = InMemoryProjectScopeStore()
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    app = FastAPI()
    app.state.container = SimpleNamespace(project_scope_store=projects)
    app.include_router(workspace_api.router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(runs_router)
    workspace_api.configure_workspace_store(workspaces)
    runs_api.configure_run_store(run_store)
    configure_task_queue(admitter=admitter, idempotency_store=InMemoryTaskIdempotencyStore())

    schema = schemathesis.openapi.from_asgi("/openapi.json", app)
    operation = schema["/tasks"]["POST"]
    submit_strategy = schema.get_case_strategy(operation, generation_mode=GenerationMode.POSITIVE)

    client = TestClient(app)
    holder = {"user": "alice"}

    def _auth() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id=holder["user"],
            token=f"token-{holder['user']}",
            roles=frozenset({"user"}),
        )

    app.dependency_overrides[verify_api_key] = _auth
    yield _Surface(client, submit_strategy, holder)

    client.close()
    app.dependency_overrides.clear()
    workspace_api.configure_workspace_store(None)
    runs_api.configure_run_store(None)
    queue_module._queue = previous_queue


def _schemathesis_body(surface: _Surface, data: st.DataObject, description: str) -> dict[str, Any]:
    """One schema-generated positive body, pinned for workflow use.

    The OpenAPI document stays the source of the client-meaningful payload
    (constraints, tier, lane, priority, …). Fields with a second authority are
    pinned: ``workspace`` must satisfy the mount validator, the key slots
    belong to the header/model layer, and ``user_id`` is server-owned.
    """
    case = data.draw(surface.submit_strategy)
    body = dict(case.body or {})
    for owned in ("idempotency_key", "user_id", "workspace"):
        body.pop(owned, None)
    body["workspace"] = WORKSPACE_MOUNT
    # Distinct descriptions per scenario: a derived-key replay must only ever
    # reconcile inside the scenario that minted it (the 24h replay window
    # would otherwise reconcile across scenarios and read as a leak).
    body["description"] = description[:512]
    return body


class _Receipt:
    """The model's row for one admitted task."""

    __slots__ = (
        "body",
        "key",
        "owner",
        "receipt_status",
        "run_id",
        "run_status",
        "task_id",
    )

    def __init__(
        self,
        task_id: str,
        run_id: str,
        owner: str,
        key: str | None,
        body: dict[str, Any],
    ) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.owner = owner
        self.key = key
        self.body = body
        self.receipt_status = "queued"
        self.run_status = "queued"

    @property
    def terminal(self) -> bool:
        return self.receipt_status in TERMINAL_RECEIPT


class WorkflowMachine(RuleBasedStateMachine):
    """Generated workflows over one real service surface.

    Each rule pins a cross-request relation; the model tracks what the
    scenario did so far, and every assertion is against that history — the
    ordering/interleaving failure class the stateless endpoint tests cannot
    reach.
    """

    task_entries: Bundle = Bundle("task_entries")
    workspace_ids: Bundle = Bundle("workspace_ids")

    def __init__(self, surface: _Surface) -> None:
        super().__init__()
        self.surface = surface
        # Per-scenario salt: explicit keys and derived-key fingerprints must
        # never collide across scenarios (the replay window is 24h, so an
        # unsalted "k-1" from an earlier example would reconcile here).
        self._scenario = next(_SCENARIO_SEQ)
        self._names = count()
        self.receipts: dict[str, _Receipt] = {}
        # textual explicit key -> {owner -> task_id}: the admission scope is
        # per-(principal, workspace, action, key), so two principals may hold
        # the same textual key side by side, and each owner's replay/409
        # verdict is computed against their own record only.
        self.keys: dict[str, dict[str, str]] = {}
        # workspace_id -> owning principal: authority travels with the id
        self.workspace_owners: dict[str, str] = {}

    # -- helpers -----------------------------------------------------------

    def _other(self, user: str) -> str:
        return "bob" if user == "alice" else "alice"

    def _switch(self, user: str) -> None:
        self.surface.as_(user)

    def _post_task(self, body: dict[str, Any], key: str | None) -> Any:
        headers = {IDEMPOTENCY_KEY_HEADER: key} if key is not None else {}
        return self.surface.client.post("/tasks", json=body, headers=headers)

    def _register(
        self, payload: dict[str, Any], owner: str, key: str | None, response: Any
    ) -> _Receipt:
        data = response.json()
        assert data["task_id"] not in self.receipts, "admission minted a duplicate task_id"
        assert response.headers.get("Location") == f"/tasks/{data['task_id']}"
        receipt = _Receipt(data["task_id"], data["run_id"], owner, key, payload)
        self.receipts[data["task_id"]] = receipt
        if key is not None:
            self.keys.setdefault(key, {})[owner] = data["task_id"]
        return receipt

    # -- workflow rules ------------------------------------------------------

    @initialize()
    def start_as_alice(self) -> None:
        self._switch("alice")

    @rule(target=task_entries, data=st.data())
    def submit_with_key(self, data: st.DataObject) -> _Receipt:
        """Admit a task under an explicit key; the key pool is small so
        retries and collisions happen inside one scenario."""
        key_n = data.draw(st.integers(min_value=0, max_value=3))
        key = f"s{self._scenario}-k{key_n}"
        owner = data.draw(st.sampled_from(PRINCIPALS))
        self._switch(owner)
        body = _schemathesis_body(self.surface, data, f"{key}:{next(self._names)}")
        response = self._post_task(body, key)
        known_task = self.keys.get(key, {}).get(owner)
        if known_task is None:
            # This principal holds no claim under the key yet — even if the
            # other principal holds the same textual key, the scope is
            # per-principal and the admission mints its own run.
            assert response.status_code == 202, response.text
            return self._register(body, owner, key, response)
        # Same principal, same key: the payload fingerprint decides — the
        # original payload reconciles to the original receipt, any other
        # payload is a 409 that mints nothing.
        original = self.receipts[known_task]
        if original.body == body:
            assert response.status_code == 202, response.text
            replayed = response.json()
            assert replayed["task_id"] == original.task_id
            assert replayed["run_id"] == original.run_id
            assert replayed["status"] == original.receipt_status
            return original
        assert response.status_code == 409, response.text
        assert "different request payload" in response.json()["detail"]
        return original

    @rule(target=task_entries, data=st.data())
    def submit_without_key(self, data: st.DataObject) -> _Receipt:
        """Admit without a header key: admission derives one from the payload,
        so a byte-identical retry inside the replay window reconciles to the
        original receipt and Run instead of minting a second one."""
        owner = data.draw(st.sampled_from(PRINCIPALS))
        self._switch(owner)
        description = f"s{self._scenario}-d{next(self._names)}"
        body = _schemathesis_body(self.surface, data, description)
        response = self._post_task(body, None)
        assert response.status_code == 202, response.text
        return self._register(body, owner, None, response)

    @precondition(lambda self: any(r.terminal for r in self.receipts.values()))
    @rule(data=st.data())
    def replay_after_cancellation(self, data: st.DataObject) -> None:
        """Retrying a terminal admission answers with the original identity
        and the terminal status — never a fresh run over finished work."""
        terminal = [r for r in self.receipts.values() if r.terminal]
        receipt = data.draw(st.sampled_from(terminal))
        self._switch(receipt.owner)
        response = self._post_task(receipt.body, receipt.key)
        assert response.status_code == 202, response.text
        replayed = response.json()
        assert replayed["task_id"] == receipt.task_id
        assert replayed["run_id"] == receipt.run_id
        assert replayed["status"] == receipt.receipt_status
        # And the canonical run behind it did not move.
        run = self.surface.client.get(f"/runs/{receipt.run_id}")
        assert run.status_code == 200
        assert run.json()["status"] == receipt.run_status

    @precondition(lambda self: any(r.key is not None for r in self.receipts.values()))
    @rule(data=st.data())
    def resubmit_varied_payload_under_key(self, data: st.DataObject) -> None:
        """Same textual key, same description, a different constraint list:
        the fingerprint must see the whole client-meaningful payload, so this
        is a 409 that mints nothing — never a silent replay of related work."""
        keyed = [r for r in self.receipts.values() if r.key is not None]
        receipt = data.draw(st.sampled_from(keyed))
        self._switch(receipt.owner)
        varied = dict(receipt.body)
        varied["constraints"] = [*varied.get("constraints", []), "m8a13-variant"]
        response = self._post_task(varied, receipt.key)
        assert response.status_code == 409, response.text
        # Nothing was minted: the keyed receipt still answers as modeled.
        current = self.surface.client.get(f"/tasks/{receipt.task_id}")
        assert current.json()["status"] == receipt.receipt_status

    @rule(entry=task_entries)
    def owner_sees_the_receipt(self, entry: _Receipt) -> None:
        """The admitted identity resolves for its owner, exactly as modeled."""
        self._switch(entry.owner)
        response = self.surface.client.get(f"/tasks/{entry.task_id}")
        assert response.status_code == 200
        assert response.json()["task_id"] == entry.task_id
        assert response.json()["run_id"] == entry.run_id
        assert response.json()["status"] == entry.receipt_status

    @rule(entry=task_entries)
    def a_foreign_principal_gets_nothing(self, entry: _Receipt) -> None:
        """Cross-principal access is a 404 — no leak, no half-answer — and
        the resource is untouched afterwards for its owner."""
        self._switch(self._other(entry.owner))
        assert self.surface.client.get(f"/tasks/{entry.task_id}").status_code == 404
        assert self.surface.client.get(f"/runs/{entry.run_id}").status_code == 404
        assert self.surface.client.post(f"/runs/{entry.run_id}/cancel").status_code == 404
        assert self.surface.client.delete(f"/tasks/{entry.task_id}").status_code == 404
        self._switch(entry.owner)
        assert self.surface.client.get(f"/tasks/{entry.task_id}").json()["status"] == (
            entry.receipt_status
        )

    @precondition(lambda self: any(not r.terminal for r in self.receipts.values()))
    @rule(data=st.data())
    def owner_cancels_a_live_task(self, data: st.DataObject) -> None:
        """Task-route cancellation terminalizes both the receipt and the
        canonical run; a repeat cancellation is the pinned 400."""
        live = [r for r in self.receipts.values() if not r.terminal]
        receipt = data.draw(st.sampled_from(live))
        self._switch(receipt.owner)
        cancelled = self.surface.client.delete(f"/tasks/{receipt.task_id}")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["cancelled"] is True
        receipt.receipt_status = "cancelled"
        receipt.run_status = "cancelled"
        assert self.surface.client.get(f"/tasks/{receipt.task_id}").json()["status"] == "cancelled"
        assert self.surface.client.get(f"/runs/{receipt.run_id}").json()["status"] == "cancelled"
        assert self.surface.client.delete(f"/tasks/{receipt.task_id}").status_code == 400

    @precondition(lambda self: any(r.run_status != "cancelled" for r in self.receipts.values()))
    @rule(data=st.data())
    def owner_cancels_through_the_run(self, data: st.DataObject) -> None:
        """Run-route cancellation terminalizes the canonical Run and, in the
        same request, projects that truth onto the task receipt — no worker
        reconcile in between. The relation this rule owns is *cross-route
        terminal agreement*: afterwards the receipt route refuses the repeat
        cancellation (the pinned 400) instead of re-cancelling or re-minting,
        the run route stays idempotent, and both surfaces keep reading the
        same terminal state to every later rule (replay, listing, foreign
        probe).

        This oracle changed shape at the develop sync: the leaf's base commit
        left the receipt ``queued`` until a worker reconciled it, and the
        run-cancel receipt projection (``cancel_run`` ->
        ``TaskQueue.settle_terminal_receipt``) closed that asymmetry. The
        suite failed on the merge and named the route pair that changed —
        the stateful form's whole argument in one red build.
        """
        live = [r for r in self.receipts.values() if r.run_status != "cancelled"]
        receipt = data.draw(st.sampled_from(live))
        self._switch(receipt.owner)
        response = self.surface.client.post(f"/runs/{receipt.run_id}/cancel")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "cancelled"
        receipt.run_status = "cancelled"
        receipt.receipt_status = "cancelled"
        assert self.surface.client.get(f"/runs/{receipt.run_id}").json()["status"] == "cancelled"
        # The projection lands inside the cancelling request, for the same Run.
        projected = self.surface.client.get(f"/tasks/{receipt.task_id}")
        assert projected.status_code == 200, projected.text
        assert projected.json()["status"] == "cancelled"
        assert projected.json()["run_id"] == receipt.run_id
        # Cross-route agreement: the receipt route refuses the repeat.
        refused = self.surface.client.delete(f"/tasks/{receipt.task_id}")
        assert refused.status_code == 400, refused.text
        # The run route stays idempotent on an already-terminal Run.
        again = self.surface.client.post(f"/runs/{receipt.run_id}/cancel")
        assert again.status_code == 200, again.text
        assert again.json()["status"] == "cancelled"

    @rule(entry=task_entries)
    def node_runs_are_a_safe_read(self, entry: _Receipt) -> None:
        """The node-run listing answers its owner (empty before execution) and
        404s a foreign principal — reading never mutates state."""
        self._switch(entry.owner)
        owned = self.surface.client.get(f"/runs/{entry.run_id}/node-runs")
        assert owned.status_code == 200
        assert isinstance(owned.json(), list)
        self._switch(self._other(entry.owner))
        assert self.surface.client.get(f"/runs/{entry.run_id}/node-runs").status_code == 404

    @rule()
    def stale_identifiers_stay_404(self) -> None:
        """Fabricated identifiers are 404s — never 403s or 5xx — on both
        surfaces, for any principal, and mint nothing."""
        client = self.surface.client
        ghost_task = f"s{self._scenario}-ghost-task"
        ghost_run = f"s{self._scenario}-ghost-run"
        for user in PRINCIPALS:
            self._switch(user)
            assert client.get(f"/tasks/{ghost_task}").status_code == 404
            assert client.delete(f"/tasks/{ghost_task}").status_code == 404
            assert client.get(f"/runs/{ghost_run}").status_code == 404
            assert client.get(f"/runs/{ghost_run}/node-runs").status_code == 404

    @rule(target=workspace_ids, data=st.data())
    def create_workspace_and_probe_it(self, data: st.DataObject) -> str:
        """Workspace creation, foreign invisibility, and root-project
        resolution: the identity backbone a real workflow sits on."""
        owner = data.draw(st.sampled_from(PRINCIPALS))
        self._switch(owner)
        created = self.surface.client.post(
            "/workspaces",
            json={"name": f"ws-{self._scenario}-{next(self._names)}"},
        )
        assert created.status_code == 201, created.text
        workspace_id = created.json()["workspace_id"]
        self.workspace_owners[workspace_id] = owner
        root = self.surface.client.get(f"/workspaces/{workspace_id}/projects/root")
        assert root.status_code == 200
        self._switch(self._other(owner))
        assert self.surface.client.get(f"/workspaces/{workspace_id}").status_code == 404
        assert (
            self.surface.client.get(f"/workspaces/{workspace_id}/projects/root").status_code == 404
        )
        return workspace_id

    @rule(workspace_id=workspace_ids, data=st.data())
    def create_project_under_root(self, workspace_id: str, data: st.DataObject) -> None:
        """A child project needs its workspace root: the parent id from the
        previous response feeds this request (cross-request dependency), and
        the request is made by the principal that owns the workspace —
        authority travels with the identifier, not beside it."""
        self._switch(self.workspace_owners[workspace_id])
        root = self.surface.client.get(f"/workspaces/{workspace_id}/projects/root")
        assert root.status_code == 200
        created = self.surface.client.post(
            f"/workspaces/{workspace_id}/projects",
            json={"parent_project_id": root.json()["project_id"], "name": f"proj-{self._scenario}"},
        )
        assert created.status_code == 201, created.text
        fetched = self.surface.client.get(
            f"/workspaces/{workspace_id}/projects/{created.json()['project_id']}"
        )
        assert fetched.status_code == 200
        assert fetched.json()["parent_project_id"] == root.json()["project_id"]

    @rule(data=st.data())
    def an_unproved_workspace_scope_is_forbidden(self, data: st.DataObject) -> None:
        """The workspace-scope header is a Hive capability, not a tenant
        selector: without the HMAC proof admission refuses with 403 and mints
        nothing."""
        owner = data.draw(st.sampled_from(PRINCIPALS))
        self._switch(owner)
        body = _schemathesis_body(
            self.surface, data, f"s{self._scenario}-scoped:{next(self._names)}"
        )
        before = len(self.receipts)
        response = self.surface.client.post(
            "/tasks", json=body, headers={WORKSPACE_ID_HEADER: "some-workspace"}
        )
        assert response.status_code == 403, response.text
        assert len(self.receipts) == before

    @rule()
    def an_oversized_key_is_422(self) -> None:
        """A key over the documented ceiling is refused at the boundary and
        registers nothing."""
        response = self._post_task(
            {"description": f"s{self._scenario}-oversized", "workspace": WORKSPACE_MOUNT},
            "k" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1),
        )
        assert response.status_code == 422

    # -- global invariants ---------------------------------------------------

    @invariant()
    def listings_match_the_model(self) -> None:
        """Every owned receipt is listed for its owner with the modeled
        status somewhere in the owner's pagination, and no other principal's
        receipt ever appears. This is the relation a stateless
        single-principal test cannot see.

        The walk follows ``next_cursor`` to exhaustion: examples share one
        in-memory store, so a deep run accumulates more tasks per principal
        than one page holds and ``list_tasks`` truncates oldest-first —
        checking only the first page would assert against a truncation
        artifact instead of the listing relation."""
        for user in PRINCIPALS:
            self._switch(user)
            listed: dict[str, str] = {}
            cursor: str | None = None
            while True:
                params: dict[str, str] = {"limit": "200"}
                if cursor is not None:
                    params["cursor"] = cursor
                page = self.surface.client.get("/tasks", params=params)
                assert page.status_code == 200, page.text
                payload = page.json()
                for item in payload["items"]:
                    assert item["task_id"] not in listed, "listing repeated a task_id"
                    listed[item["task_id"]] = item["status"]
                cursor = payload["next_cursor"]
                if cursor is None:
                    break
            for task_id, receipt in self.receipts.items():
                if receipt.owner == user:
                    assert listed.get(task_id) == receipt.receipt_status, (
                        f"{task_id} missing or stale for {user}: "
                        f"{listed.get(task_id)!r} != {receipt.receipt_status!r}"
                    )
                else:
                    assert task_id not in listed, (
                        f"{user} can list {task_id} owned by {receipt.owner}"
                    )


_SCENARIO_SEQ = count()

WORKFLOW_SETTINGS = settings(
    max_examples=CI_EXAMPLES,
    stateful_step_count=CI_STEPS,
    deadline=None,
    # Deterministic on PRs (same scenarios every run); nightly exploration
    # opts out with MAISTRO_STATEFUL_API_DERANDOMIZE=0 so each night samples
    # fresh orderings.
    derandomize=os.environ.get("MAISTRO_STATEFUL_API_DERANDOMIZE", "1") != "0",
    phases=(Phase.explicit, Phase.generate, Phase.shrink),
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.data_too_large,
    ],
)


async def test_api_workflow_statefulness(surface: _Surface) -> None:
    """The representative stateful API workflow suite (M8-A13, #893)."""
    run_state_machine_as_test(lambda: WorkflowMachine(surface), settings=WORKFLOW_SETTINGS)


async def test_the_served_contract_has_the_workflow_surface(surface: _Surface) -> None:
    """The OpenAPI document the suite generates from still exposes the four
    operation families, and still declares no response links — the documented
    reason native Schemathesis stateful testing cannot run against this
    surface without a links/inference layer."""
    schema = schemathesis.openapi.from_asgi("/openapi.json", surface.client.app)
    for path, method in (
        ("/tasks", "POST"),
        ("/tasks/{task_id}", "GET"),
        ("/tasks/{task_id}", "DELETE"),
        ("/runs/{run_id}", "GET"),
        ("/runs/{run_id}/cancel", "POST"),
        ("/runs/{run_id}/node-runs", "GET"),
        ("/workspaces", "POST"),
        ("/workspaces/{workspace_id}/projects", "POST"),
    ):
        operation = schema[path][method]
        assert operation is not None
    assert schema.operations_with_incoming_links() == set()
