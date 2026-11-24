"""Named M1 cross-product parity suite (#459).

The active product convergence PRs are dependencies, not implementation material
for this branch. Source probes remain development diagnostics; strict mode requires
each scenario to return a real producer/spine/observer observation and records a
missing seam as a failure. No missing product behavior is recreated here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.definitions import Graph, GraphTemplate, Node
from maistro.identity import Principal
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from tests.cross_product_parity.harness import (
    BUILDERS,
    CONDUCTOR_INSPECTION,
    EVOLVE,
    GOLDEN_BASELINES,
    ONTOLOGY,
    REAL_BUILDERS_CONDUCTOR_SCENARIO,
    REAL_EVOLVE_CONDUCTOR_SCENARIO,
    REAL_GOLDEN_PRODUCT_OBSERVATION,
    REAL_SCHEDULE_CONDUCTOR_SCENARIO,
    SCHEDULER,
    CloseoutFailure,
    Dependency,
    DependencyUnavailable,
    ParityContractError,
    ParityMode,
    ParityScenario,
    ScenarioAbstained,
    ScenarioExecution,
    SourceProbe,
    assert_identity_projection,
    assert_matches_golden,
    assert_ontology_identity_projection,
    dependency_assessment,
    execute_closeout,
    execute_scenario_sync,
    open_durable_profile,
    parity_mode,
    require_dependencies,
)

pytestmark = [pytest.mark.contract("cross-service"), pytest.mark.scope("integration")]


def _unavailable_real_seam(owner: str) -> ScenarioExecution:
    """Keep missing producer/observer work owned by the product issue."""
    raise ScenarioAbstained(
        f"real {owner} producer -> canonical spine -> Conductor boundary is not shipped; "
        "the parity harness must not recreate it"
    )


_SCHEDULE_PARITY_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_SCHEDULE_PARITY_WS = "parity-schedule-ws"
_SCHEDULE_PARITY_TEMPLATE = "parity-schedule-template"
_SCHEDULE_PARITY_ID = "parity-schedule"


class _FixedScheduleClock:
    """The scheduler's clock, pinned to the parity noon (the #1199 tick test idiom)."""

    @staticmethod
    def now(tz: object = None) -> datetime:
        return _SCHEDULE_PARITY_NOW


async def _stop_schedule_lifespan(sched: Any) -> None:
    """Stop the real lifespan loop and wait until its task has actually ended."""
    runner = getattr(sched, "_runner", None)
    sched.stop_scheduler()
    task = getattr(runner, "task", None) if runner is not None else None
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    except Exception:
        task.exception()  # retrieved so the loop stays warning-free


async def _wait_for_schedule_run(run_store: Any, *, timeout_s: float = 20.0) -> Any:
    """Poll the canonical store until the tick's occurrence is terminal."""
    from maistro.runs import RunStatus

    deadline = time.monotonic() + timeout_s
    observed: dict[str, int] = {}
    while time.monotonic() < deadline:
        found = []
        for status in RunStatus:
            found.extend(await run_store.list_by_status(status, limit=100))
        observed = {}
        for run in found:
            observed[run.status.value] = observed.get(run.status.value, 0) + 1
        terminal = [run for run in found if run.status in (RunStatus.COMPLETED, RunStatus.FAILED)]
        if len(terminal) == 1:
            return terminal[0]
        if len(terminal) > 1:
            raise ParityContractError(
                "the parity occurrence admitted more than one canonical Run: "
                f"{[run.run_id for run in terminal]}"
            )
        await asyncio.sleep(0.05)
    raise ParityContractError(
        f"the configured scheduler never reached one terminal occurrence within "
        f"{timeout_s}s (observed: {observed})"
    )


async def _seed_stale_hive_schedule(container: Any) -> Any:
    """Write a Hive projection row that disagrees with canonical truth.

    This is the stale projection a #2467 crash leaves behind: the canonical
    store already holds the acknowledged definition, and the in-process Hive
    row still describes an older one. The restart must repair the row from
    the store, never restore the row over the store.
    """
    import stores
    from models.schemas import Schedule as HiveSchedule

    canonical = await container.schedule_store.get(_SCHEDULE_PARITY_ID)
    assert canonical is not None
    row = HiveSchedule(
        id=canonical.schedule_id,
        user_id=str(canonical.actor_principal_id or ""),
        workspace_id=canonical.workspace_id,
        project_id=canonical.project_id,
        name="stale Hive name",
        description="",
        cron_expression="9 9 9 9 9",
        mission_template_id="wrong-template",
        max_runs=canonical.max_runs,
        catchup_window_seconds=canonical.catchup_window_seconds,
        enabled=canonical.enabled,
        timezone=canonical.timezone,
        created_at=canonical.created_at,
        updated_at=canonical.created_at,
        last_run=canonical.last_fired_at,
    )
    stores.schedules._data[row.id] = row
    return row


async def _schedule_conductor_scenario() -> ScenarioExecution:
    """Scenario 2 as a real execution: the configured scheduler lifespan fires
    one occurrence into the canonical spine and Conductor inspects it.

    REAL_SCENARIO_EVIDENCE: schedule-conductor

    The producer half is the shipped scheduler exactly as the app lifespan
    wires it (``services.scheduler.start_scheduler`` driving the real loop's
    startup backfill and due tick) against a configured core ``Container`` on
    the supported durable SQLite spine: the due tick admits the occurrence
    through the canonical ``ScheduleRunAdmitter`` (one claimed occurrence ->
    QUEUED canonical Run) and the same tick's canonical consumer executes it
    into real NodeRun/Attempt evidence, advancing the durable due cursor.

    The observer half is Conductor's landed inspection seam (#1174/#1036
    ``dag_run_inspection``) wired to the same canonical stores exactly as the
    app wires it. The scenario requires: the tick recorded no Conductor
    projection row (the Hive row is not the run's discovery mechanism), the
    Run is discoverable, inspectable, and evidence-complete by its canonical
    id alone for a Workspace member, and a caller outside the Workspace is
    refused indistinguishably from a missing id.

    The restart half reopens the canonical database (a real close and
    reopen, not a process-local dict) after reseeding a stale Hive
    projection row, then starts the lifespan again (#1199/#2467): the
    durable cursor admits no second occurrence, and the stale projection is
    repaired from canonical truth — the row can neither resurrect the
    schedule nor override the acknowledged definition.
    """
    _bind_hive_backend()

    import services.engine as engine_mod
    import services.scheduler as sched
    import stores
    from services.dag_run_inspection import (
        can_inspect_run,
        list_visible_runs,
        visible_run_detail,
        visible_run_ids,
    )
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import presentation_store

    from maistro.container import create_container
    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.scheduling import Schedule
    from maistro.types.config import AgentConfig
    from maistro.workspaces.model import WorkspaceRole

    scratch = Path(tempfile.mkdtemp(prefix="schedule-conductor-parity-"))
    db_path = scratch / "spine.sqlite3"
    monkey = pytest.MonkeyPatch()
    container: Any = None
    # The scheduler's startup reconciliation writes process-global product
    # state (#2467): the projection ledger's migration marker, tombstones,
    # and pending-create markers. Snapshot it before the lifespan runs so
    # the finally below can hand the next suite in this interpreter a
    # pristine ledger — the backend suite's ledger isolation preserves
    # pre-existing state by design, so a leaked `migrated` marker flips its
    # legacy-import tests into repair mode (ci.yml's leakage step runs
    # tests/ and packages/hive-conductor/backend/tests in one process).
    from services.schedule_projection import reset_projection_health, schedule_migration

    ledger_snapshot = dict(schedule_migration.items())
    try:
        # The parity process must not run the scheduler's side self-repair
        # cadence; this scenario pins the schedule tick contract only.
        monkey.setenv("SELF_REPAIR_INTERVAL_S", "0")
        # The scheduler's clock is pinned to the parity noon, so one hourly
        # occurrence is due exactly once no matter how long a slow host takes.
        monkey.setattr(sched, "datetime", _FixedScheduleClock)
        # The real cadence stays 30s; the parity lifespan drives the same loop
        # with a pause it can actually wait out.
        monkey.setattr(sched, "_TICK_INTERVAL_S", 0.05)
        monkey.setattr(stores.schedules, "_data", {})

        container = await create_container(
            AgentConfig(
                router_api_key="test-key",
                workspace_id=_SCHEDULE_PARITY_WS,
                database_url=f"sqlite:///{db_path}",
            )
        )
        monkey.setattr(
            sched._ScheduleRunner,
            "_canonical_container",
            staticmethod(lambda: container),
        )
        # Composition provisions the configured Workspace (#1152); the parity
        # actor's membership is this scenario's own contribution.
        if await container.workspace_store.get(_SCHEDULE_PARITY_WS) is None:
            await container.workspace_store.create(
                creator_user_id=_PARITY_USER,
                name="Schedule parity",
                workspace_id=_SCHEDULE_PARITY_WS,
            )
        else:
            await container.workspace_store.set_membership(
                _SCHEDULE_PARITY_WS,
                user_id=_PARITY_USER,
                role=WorkspaceRole.CONTRIBUTOR,
            )
        root = await container.project_scope_store.root_for_workspace(_SCHEDULE_PARITY_WS)
        await container.template_store.put(
            GraphTemplate(
                template_id=_SCHEDULE_PARITY_TEMPLATE,
                workspace_id=_SCHEDULE_PARITY_WS,
                version=1,
                name="parity schedule template",
                nodes=[
                    Node(
                        node_id="only",
                        node_type="transform.alias_keys",
                        parameters={"mapping": {}},
                    )
                ],
                metadata={"entry_node": "only"},
            )
        )
        await container.schedule_store.put(
            Schedule(
                schedule_id=_SCHEDULE_PARITY_ID,
                workspace_id=_SCHEDULE_PARITY_WS,
                project_id=root.project_id,
                name="canonical parity schedule",
                cron="0 * * * *",
                graph_template_id=_SCHEDULE_PARITY_TEMPLATE,
                actor_principal_id=_PARITY_USER,
                created_at=_SCHEDULE_PARITY_NOW - timedelta(days=1),
                last_fired_at=_SCHEDULE_PARITY_NOW - timedelta(hours=1),
            )
        )
        # A crash between the canonical write and the projection write leaves
        # a stale Hive row behind (#2467); the restart below must not serve it.
        await _seed_stale_hive_schedule(container)
        # The presentation the app's workspace routes would have created; the
        # canonical membership above is what authorizes, this is the view.
        from models.workspace import WorkspacePresentation

        presentation_store()[_SCHEDULE_PARITY_WS] = WorkspacePresentation(
            workspace_id=_SCHEDULE_PARITY_WS,
            persona_template_id="pm_fleet",
            updated_at=_SCHEDULE_PARITY_NOW,
        )

        # -- Producer: the real configured lifespan fires the occurrence. -----
        sched.start_scheduler()
        fired = await _wait_for_schedule_run(container.run_store)
        assert fired.status is RunStatus.COMPLETED, f"tick ended {fired.status}: {fired.error}"
        assert fired.workspace_id == _SCHEDULE_PARITY_WS
        assert fired.provenance["schedule_id"] == _SCHEDULE_PARITY_ID
        assert fired.actor_principal_id == _PARITY_USER
        await _stop_schedule_lifespan(sched)

        recorded = await container.schedule_store.get(_SCHEDULE_PARITY_ID)
        assert recorded is not None
        assert recorded.runs_so_far == 1
        assert recorded.last_run_id == fired.run_id
        assert recorded.next_due_at == _SCHEDULE_PARITY_NOW + timedelta(hours=1)
        [node] = await container.run_store.list_node_runs(fired.run_id)
        attempts = await container.run_store.list_attempts(node.node_run_id)
        assert attempts, "the fired occurrence must expose physical Attempt evidence"

        # The startup projection repair (#2467) must have replaced the stale
        # row's definition with the canonical definition it crashed over.
        repaired = stores.schedules.get(_SCHEDULE_PARITY_ID)
        assert repaired is not None
        assert repaired.name == "canonical parity schedule"
        assert repaired.cron_expression == "0 * * * *"
        assert repaired.mission_template_id == _SCHEDULE_PARITY_TEMPLATE

        # -- Observer: Conductor inspects the same canonical id. --------------
        # The scheduler never recorded a projection row: the dag_run_store is
        # not the discovery mechanism for another producer's Run (#1036).
        assert get_dag_run_store().get_run(fired.run_id) is None
        monkey.setattr(
            engine_mod,
            "_singleton",
            SimpleNamespace(
                _agent_port=SimpleNamespace(container=container),
                run_store=container.run_store,
                run_reader=ScopedRunReader(
                    container.run_store,
                    container.workspace_store,
                    container.project_scope_store,
                ),
            ),
        )
        detail = await visible_run_detail(_PARITY_USER, fired.run_id)
        assert detail is not None
        assert detail["id"] == detail["canonical_run_id"] == fired.run_id
        assert detail["workspace_id"] == _SCHEDULE_PARITY_WS
        assert detail["project_id"] == root.project_id
        assert detail["status"] == "completed"
        node_runs = detail.get("node_runs") or []
        assert node_runs, "the fired occurrence must expose physical NodeRun evidence"
        observed_attempts = [a for n in node_runs for a in n.get("attempts", [])]
        assert observed_attempts, "the fired occurrence must expose physical Attempt evidence"
        assert all(a["status"] == "completed" for a in observed_attempts)
        assert await can_inspect_run(_PARITY_USER, fired.run_id)
        assert await visible_run_ids(_PARITY_USER, [fired.run_id, "no-such-run"]) == {fired.run_id}
        listed = await list_visible_runs(_PARITY_USER, limit=25)
        assert fired.run_id in {row["id"] for row in listed}

        # A caller outside the producing Workspace is refused without learning
        # the id exists -- the same answer a missing id gets (#1174).
        assert await visible_run_detail(_PARITY_FOREIGN_USER, fired.run_id) is None
        assert not await can_inspect_run(_PARITY_FOREIGN_USER, fired.run_id)
        assert await visible_run_ids(_PARITY_FOREIGN_USER, [fired.run_id]) == set()

        # -- Restart: reopen the canonical database and start again. ----------
        # The stale row is reseeded to model the crash window, then the real
        # database is closed and reopened: nothing may resurrect from the
        # process-local dict or re-fire the already-claimed occurrence.
        await _seed_stale_hive_schedule(container)
        real_due = container.schedule_store.due
        due_calls = 0

        async def counted_due(**kwargs: Any) -> Any:
            nonlocal due_calls
            due_calls += 1
            return await real_due(**kwargs)

        await container.aclose()
        monkey.setattr(
            engine_mod,
            "_singleton",
            None,
        )
        container = await create_container(
            AgentConfig(
                router_api_key="test-key",
                workspace_id=_SCHEDULE_PARITY_WS,
                database_url=f"sqlite:///{db_path}",
            )
        )
        monkey.setattr(
            sched._ScheduleRunner,
            "_canonical_container",
            staticmethod(lambda: container),
        )
        monkey.setattr(container.schedule_store, "due", counted_due)
        sched.start_scheduler()
        deadline = time.monotonic() + 20.0
        while due_calls == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert due_calls >= 1, "the reopened lifespan never reached its first due selection"
        await _stop_schedule_lifespan(sched)

        reopened_runs: list[Any] = []
        for status in RunStatus:
            reopened_runs.extend(await container.run_store.list_by_status(status, limit=100))
        assert [run.run_id for run in reopened_runs] == [fired.run_id], (
            "the restart must resume from the durable cursor, not fire again"
        )
        resumed = await container.schedule_store.get(_SCHEDULE_PARITY_ID)
        assert resumed is not None
        assert resumed.runs_so_far == 1 and resumed.last_run_id == fired.run_id
        assert resumed.next_due_at == _SCHEDULE_PARITY_NOW + timedelta(hours=1)
        repaired_after = stores.schedules.get(_SCHEDULE_PARITY_ID)
        assert repaired_after is not None
        assert repaired_after.cron_expression == "0 * * * *"
        assert repaired_after.name == "canonical parity schedule"
        assert repaired_after.mission_template_id == _SCHEDULE_PARITY_TEMPLATE

        # The reopened canonical Run stays inspectable through the same seam.
        monkey.setattr(
            engine_mod,
            "_singleton",
            SimpleNamespace(
                _agent_port=SimpleNamespace(container=container),
                run_store=container.run_store,
                run_reader=ScopedRunReader(
                    container.run_store,
                    container.workspace_store,
                    container.project_scope_store,
                ),
            ),
        )
        reopened_detail = await visible_run_detail(_PARITY_USER, fired.run_id)
        assert reopened_detail is not None and reopened_detail["status"] == "completed"

        return ScenarioExecution(
            {
                "producer": "scheduler",
                "observer": "conductor",
                "run_id": fired.run_id,
                "workspace_id": _SCHEDULE_PARITY_WS,
                "project_id": root.project_id,
                "producer_status": "completed",
                "physical_node_runs": len(node_runs),
                "physical_attempts": len(attempts),
                "projection_rows_for_run": 0,
                "foreign_observer_visible": False,
                "cursor_runs_so_far": resumed.runs_so_far,
                "restart_new_runs": len(reopened_runs) - 1,
                "stale_projection_repaired": True,
            }
        )
    finally:
        runner = getattr(sched, "_runner", None)
        if runner is not None:
            await _stop_schedule_lifespan(sched)
        if container is not None:
            await container.aclose()
        from services.workspace_authority import presentation_store as _presentation_store

        _presentation_store().pop(_SCHEDULE_PARITY_WS, None)
        # Restore the projection ledger this lifespan marked migrated (#2467)
        # and reset the health surface the reconciliation wrote; see the
        # snapshot above for why the next suite needs pristine globals.
        schedule_migration.clear()
        for ledger_key, ledger_value in ledger_snapshot.items():
            schedule_migration[ledger_key] = ledger_value
        reset_projection_health()
        monkey.undo()
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            from maistro.capabilities.effect_context import default_effect_context

            default_effect_context.cache_clear()
        except Exception:
            pass


def _validate_schedule_observation(observation: Mapping[str, Any]) -> None:
    """The strict invariant over the real scheduler/observer records (#1199)."""
    assert observation["producer"] == "scheduler"
    assert observation["observer"] == "conductor"
    for field in ("run_id", "workspace_id", "project_id"):
        assert observation[field], f"observation lacks canonical {field}"
    assert observation["producer_status"] == "completed"
    assert observation["physical_node_runs"] >= 1
    assert observation["physical_attempts"] >= 1
    assert observation["projection_rows_for_run"] == 0
    assert observation["foreign_observer_visible"] is False
    assert observation["cursor_runs_so_far"] == 1
    assert observation["restart_new_runs"] == 0
    assert observation["stale_projection_repaired"] is True


def _abstaining_scenario() -> ScenarioExecution:
    """A required producer that never reached its real boundary.

    Negative-oracle fixture: the Evolve scenario is a real execution now, so
    the closeout-report test exercises its stop-on-first-failure contract with
    an explicitly abstaining callback instead of Evolve's scaffold.
    """
    raise ScenarioAbstained("producer did not execute its real boundary")


def _evolve_genome(genome_id: str, score: float) -> Any:
    """A pre-scored, pre-fitnessed proxy genome: plan-pairs → battles → finalize."""
    from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome
    from maistro_evolve.types import PipelineGenome as RealGenome

    genome = RealGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    genome.eval_scores = {"proxy": score}
    genome.fitness_score = score
    return genome


def _evolve_population() -> Any:
    from maistro_evolve.population import PopulationStore

    population = PopulationStore()
    for genome_id, score in (("g1", 0.9), ("g2", 0.2), ("g3", 0.8), ("g4", 0.3)):
        population.add(_evolve_genome(genome_id, score))
    return population


class _DeterministicEvolveCycle:
    """The deterministic finalize double the shipped replay suite also uses.

    Every genome arrives pre-scored, so the canonical graph is
    plan-pairs → battles → finalize and the LLM seams never fire; the double
    keeps finalize's own mutations (fitness fold, one bred child, cycle
    advance) deterministic without an LLM or official benchmarks. The producer
    evidence under test — canonical Run/NodeRun/Attempt admission over the
    durable spine and the exactly-once battle/finalize publication ledger
    (#1064) — is entirely real.
    """

    fidelity = "proxy"

    def __init__(self, harness: Any = None, tournament: Any = None, archive: Any = None) -> None:
        self.harness = harness
        self.tournament = tournament
        self.archive = archive
        self._island_pop = None
        self._cycle_count = 0

    @staticmethod
    def _fold_score(genome: Any, benchmark: str, score: float, stub: bool, alpha: float) -> None:
        genome.eval_scores[benchmark] = score

    def _compute_all_fitness(self, population: Any) -> list[Any]:
        for genome in population.list_all():
            genome.fitness_score = sum(genome.eval_scores.values())
        return population.list_all()

    def _breed_island(
        self, island_pop: Any, island_id: int, population: Any, config: Any, cap: int
    ) -> None:
        # Idempotent by content, not by a per-process latch: a restarted
        # process's fresh cycle object cannot breed the same child twice.
        if any(g.id == "child-1" for g in population.list_all()):
            return
        child = _evolve_genome("child-1", 0.5)
        child.parent_a_id = "g1"
        child.parent_b_id = "g2"
        population.add(child)

    async def _self_improve_top(self, population: Any, config: Any, llm_call: Any) -> None:
        return None


async def _evolve_conductor_scenario() -> ScenarioExecution:
    """Scenario 3 as a real execution, not a source probe.

    REAL_SCENARIO_EVIDENCE: evolve-conductor

    The producer half runs the shipped canonical Evolve cycle
    (``run_canonical_evolution_cycle`` -> ``run_durable_graph``) against the
    supported durable SQLite spine plus the durable Evolve domain ledger
    (#1064), so the Workspace/Project/Graph/Run identity chain, the physical
    NodeRun/Attempt evidence, and the exactly-once battle/finalize publication
    rows are real durable records, not test doubles of the spine. Only the
    breeding genetics are a deterministic double, exactly as the shipped
    backend replay suite stages them; the canonical admission/execution and
    the publication ledger under test are the real ones.

    The observer half is Conductor's landed inspection seam (#1036's
    ``dag_run_inspection``), wired to the same canonical stores through the
    engine bridge exactly as the app wires it. The scenario requires: the
    projection store never recorded the Run; list/detail answer by the
    canonical id alone; the battle/finalize NodeRun/Attempt tree is readable
    through the scoped seam; the durable publication ledger caught exactly one
    row per battle NodeRun plus a committed finalize marker; and an observer
    outside the Workspace is refused indistinguishably from a missing id.
    """
    _bind_hive_backend()

    import services.engine as engine_mod
    from services.dag_run_inspection import (
        can_inspect_run,
        list_visible_runs,
        visible_run_detail,
        visible_run_ids,
    )
    from services.dag_run_store import get_dag_run_store
    from services.evolution_graph import run_canonical_evolution_cycle
    from services.evolve_domain_store import SqliteEvolveDomainStore
    from services.workspace_authority import canonical_store_for_tests, create_workspace

    from maistro.graph.durable_runs import CanonicalDurableRunStore
    from maistro.runs.scoped_reads import ScopedRunReader

    scratch = Path(tempfile.mkdtemp(prefix="evolve-conductor-parity-"))
    profile = None
    monkey = pytest.MonkeyPatch()
    try:
        # The producer acts as a member of a real canonical Workspace (the
        # Conductor-side authority the observation half authorizes against).
        view = await create_workspace(
            creator_user_id=_PARITY_USER,
            name="Evolve parity",
            persona_template_id="pm_fleet",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
        profile = await open_durable_profile(scratch / "spine.sqlite3", workspace_id=view.id)
        durable = CanonicalDurableRunStore(profile.run_store, profile.continuation_store)
        domain = SqliteEvolveDomainStore(str(scratch / "evolve_domain.db"))
        await domain.ensure_schema()

        population = _evolve_population()
        from maistro_evolve.tournament import EloTournament

        tournament = EloTournament()
        monkey.setattr("maistro_evolve.cycle.EvolutionCycle", _DeterministicEvolveCycle)
        record = await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=SimpleNamespace(
                eval_batch_size=4,
                target_benchmarks=["proxy"],
                eval_ema_alpha=0.5,
                cull_pct=0.0,
                island_count=1,
                population_size=4,
                migration_interval=1000,
            ),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_PARITY_USER,
            cycle_number=1,
            container=SimpleNamespace(
                config=SimpleNamespace(workspace_id=profile.workspace_id),
                project_scope_store=profile.project_store,
                run_store=profile.run_store,
                graph_run_store=durable,
            ),
            domain_store=domain,
        )
        from maistro.runs import RunStatus

        assert record.run.status is RunStatus.COMPLETED, (
            f"cycle ended {record.run.status}: {record.run.error}"
        )
        run_id = record.run_id

        # The durable publication ledger caught exactly one row per battle
        # NodeRun the cycle executed, plus the committed finalize marker —
        # #1064's exactly-once evidence is part of the parity observation.
        node_runs = await profile.run_store.list_node_runs(run_id)
        battle_node_ids = {
            node.node_run_id for node in node_runs if str(node.node_id).startswith("evolve-battle")
        }
        finalize_node_ids = {
            node.node_run_id for node in node_runs if node.node_id == "evolve-finalize"
        }
        assert battle_node_ids, "the cycle must execute at least one battle NodeRun"
        battle_publications = await domain.list_battle_publications(profile.workspace_id)
        assert {p.node_run_id for p in battle_publications} == battle_node_ids
        assert all(p.run_id == run_id for p in battle_publications)
        finalize_markers = await domain.list_finalize_markers(profile.workspace_id)
        assert {m.node_run_id for m in finalize_markers} == finalize_node_ids
        assert all(m.payload["status"] == "committed" for m in finalize_markers)

        # -- Observer: Conductor inspects the same canonical id. --------------
        # The producer never recorded a projection row: the dag_run_store is
        # not the discovery mechanism for another product's Run (#1036).
        assert get_dag_run_store().get_run(run_id) is None
        monkey.setattr(
            engine_mod,
            "_singleton",
            SimpleNamespace(
                run_store=profile.run_store,
                run_reader=ScopedRunReader(
                    profile.run_store,
                    canonical_store_for_tests(),
                    profile.project_store,
                ),
            ),
        )

        detail = await visible_run_detail(_PARITY_USER, run_id)
        assert detail is not None
        assert detail["id"] == detail["canonical_run_id"] == run_id
        assert detail["workspace_id"] == view.id == profile.workspace_id
        assert detail["project_id"] == profile.project_id
        assert detail["status"] == "completed"
        observed_nodes = detail.get("node_runs") or []
        assert observed_nodes, "the completed cycle must expose physical NodeRun evidence"
        attempts = [a for node in observed_nodes for a in node.get("attempts", [])]
        assert attempts, "the completed cycle must expose physical Attempt evidence"
        assert all(attempt["status"] == "completed" for attempt in attempts)
        assert await can_inspect_run(_PARITY_USER, run_id)
        assert await visible_run_ids(_PARITY_USER, [run_id, "no-such-run"]) == {run_id}
        listed = await list_visible_runs(_PARITY_USER, limit=25)
        assert run_id in {row["id"] for row in listed}

        # A caller outside the producing Workspace is refused without learning
        # the id exists — the same answer a missing id gets (#1174).
        assert await visible_run_detail(_PARITY_FOREIGN_USER, run_id) is None
        assert not await can_inspect_run(_PARITY_FOREIGN_USER, run_id)
        assert await visible_run_ids(_PARITY_FOREIGN_USER, [run_id]) == set()

        return ScenarioExecution(
            {
                "producer": "evolve",
                "observer": "conductor",
                "run_id": run_id,
                "workspace_id": profile.workspace_id,
                "project_id": profile.project_id,
                "producer_status": detail["status"],
                "physical_node_runs": len(observed_nodes),
                "physical_attempts": len(attempts),
                "battle_node_runs": len(battle_node_ids),
                "durable_battle_publications": len(battle_publications),
                "finalize_publications": len(finalize_markers),
                "projection_rows_for_run": 0,
                "foreign_observer_visible": False,
            }
        )
    finally:
        monkey.undo()
        if profile is not None:
            await profile.close()
        shutil.rmtree(scratch, ignore_errors=True)


def _validate_evolve_observation(observation: Mapping[str, Any]) -> None:
    """The strict invariant over the real producer/observer records."""
    assert observation["producer"] == "evolve"
    assert observation["observer"] == "conductor"
    for field in ("run_id", "workspace_id", "project_id"):
        assert observation[field], f"observation lacks canonical {field}"
    assert observation["producer_status"] == "completed"
    assert observation["physical_node_runs"] >= 2
    assert observation["physical_attempts"] >= 1
    assert observation["battle_node_runs"] >= 1
    # The exactly-once ledger caught every battle the cycle executed.
    assert observation["durable_battle_publications"] == observation["battle_node_runs"]
    assert observation["finalize_publications"] >= 1
    assert observation["projection_rows_for_run"] == 0
    assert observation["foreign_observer_visible"] is False


def _golden_scenario() -> ScenarioExecution:
    return _unavailable_real_seam("golden observation (#463)")


_PARITY_USER = "builders-parity-owner"
_PARITY_FOREIGN_USER = "builders-parity-outsider"
_HIVE_BACKEND = str(Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend")


class _CompletedRunner:
    """A TurnRunner double whose ReAct turn finishes on its first model reply."""

    def __init__(self, content: str) -> None:
        self._content = content

    async def execute_turn(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content": self._content, "stop_reason": "end_turn"}


class _ParkedRunner:
    """A TurnRunner double whose physical work only ends when it is released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def execute_turn(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
        await self.release.wait()
        return {"content": "late completion", "stop_reason": "end_turn"}


class _ParityRequest:
    """Just what the dag-runs route handlers read off a request."""

    def __init__(self, user_id: str) -> None:
        self.state = SimpleNamespace(principal=Principal(user_id=user_id, username=user_id))


def _bind_hive_backend() -> None:
    """Import the Conductor app modules the scenario observes through."""
    if _HIVE_BACKEND in sys.path:
        sys.path.remove(_HIVE_BACKEND)
    sys.path.insert(0, _HIVE_BACKEND)


async def _wait_for_running_turn(
    run_store: Any,
    workspace_id: str,
    *,
    timeout_s: float = 15.0,
) -> str:
    """Poll the canonical store until an admitted Run is physically mid-flight."""
    from maistro.runs import RunStatus

    deadline = time.monotonic() + timeout_s
    last_statuses: list[str] = []
    while time.monotonic() < deadline:
        runs = await run_store.list_recent_runs(workspace_id, limit=25)
        last_statuses = sorted(run.status.value for run in runs)
        running = [run for run in runs if run.status is RunStatus.RUNNING]
        if running:
            return running[0].run_id
        await asyncio.sleep(0.01)
    raise ScenarioAbstained(
        "the in-flight Builders turn never reached canonical RUNNING within "
        f"{timeout_s}s (observed: {last_statuses})"
    )


async def _builders_conductor_scenario() -> ScenarioExecution:
    """Scenario 1 as a real execution, not a source probe.

    REAL_SCENARIO_EVIDENCE: builders-conductor

    The producer half runs the shipped Builders interactive composition
    (``CanonicalInteractiveTurnExecutor`` -> ``CanonicalGraphPipelineExecutor``,
    the same executor the ``maistro builders`` CLI process opens through
    ``BuildersExecutionSpine``) against the supported durable SQLite spine, so
    the Workspace/Project/Graph/Run identity chain and the physical
    NodeRun/Attempt evidence are real records, not test doubles of the spine.

    The observer half is Conductor's landed inspection/control seam
    (#1036's ``dag_run_inspection`` plus the #1169 cancel route), wired to the
    same canonical stores through the engine bridge exactly as the app wires
    it. The scenario requires: the projection store never recorded the Run,
    list/detail answer by the canonical id alone, the NodeRun/Attempt tree is
    readable through the scoped seam, an observer outside the Workspace is
    refused indistinguishably from a missing id, and cancel through the same
    id fences the canonical Run so the still-running Builders turn can never
    publish success over it.

    The post-fence settlement of the in-flight durable walk (how the aborted
    attempt's own records close out) is #44/#1169 territory; this scenario
    pins only the cross-product contract: Conductor's cancel decided, and no
    Builders-local completion overrode it.
    """
    _bind_hive_backend()

    import services.engine as engine_mod
    from routes.dag_runs import cancel_run as cancel_route
    from services.dag_run_inspection import (
        can_inspect_run,
        list_visible_runs,
        visible_run_detail,
        visible_run_ids,
    )
    from services.dag_run_store import get_dag_run_store
    from services.workspace_authority import canonical_store_for_tests, create_workspace

    from maistro.builders.interactive import CanonicalInteractiveTurnExecutor
    from maistro.graph.durable_runs import CanonicalDurableRunStore
    from maistro.runs import RunStatus
    from maistro.runs.scoped_reads import ScopedRunReader

    scratch = Path(tempfile.mkdtemp(prefix="builders-conductor-parity-"))
    profile = None
    monkey = pytest.MonkeyPatch()
    try:
        # The producer acts as a member of a real canonical Workspace (the
        # Conductor-side authority the observation half authorizes against).
        view = await create_workspace(
            creator_user_id=_PARITY_USER,
            name="Builders parity",
            persona_template_id="pm_fleet",
            checklist=[],
            theme_id="default",
            voice_tone_override=None,
        )
        profile = await open_durable_profile(scratch / "spine.sqlite3", workspace_id=view.id)
        producer = CanonicalInteractiveTurnExecutor(
            run_store=profile.run_store,
            durable_store=CanonicalDurableRunStore(profile.run_store, profile.continuation_store),
            workspace_id=profile.workspace_id,
            project_id=profile.project_id,
            actor_principal_id=_PARITY_USER,
        )

        # -- Producer: one real interactive turn becomes canonical work. ------
        done = await producer.execute(
            session_id="parity-session-1",
            repo="agent-stronghold/project-maistro",
            prompt="ship the parity scenario",
            messages=[{"role": "user", "content": "ship the parity scenario"}],
            runner=_CompletedRunner("spec, tests, code, review: all green"),
        )
        assert done.status is RunStatus.COMPLETED, f"turn ended {done.status}: {done.error}"
        run_id = done.run_id

        # -- Observer: Conductor inspects the same canonical id. --------------
        # The producer never recorded a projection row: the dag_run_store is
        # not the discovery mechanism for another product's Run (#1036).
        assert get_dag_run_store().get_run(run_id) is None
        monkey.setattr(
            engine_mod,
            "_singleton",
            SimpleNamespace(
                run_store=profile.run_store,
                run_reader=ScopedRunReader(
                    profile.run_store,
                    canonical_store_for_tests(),
                    profile.project_store,
                ),
            ),
        )

        detail = await visible_run_detail(_PARITY_USER, run_id)
        assert detail is not None
        assert detail["id"] == detail["canonical_run_id"] == run_id
        assert detail["workspace_id"] == view.id == profile.workspace_id
        assert detail["project_id"] == profile.project_id
        assert detail["status"] == "completed"
        node_runs = detail.get("node_runs") or []
        assert node_runs, "the completed turn must expose physical NodeRun evidence"
        attempts = [attempt for node in node_runs for attempt in node.get("attempts", [])]
        assert attempts, "the completed turn must expose physical Attempt evidence"
        assert all(attempt["status"] == "completed" for attempt in attempts)
        assert await can_inspect_run(_PARITY_USER, run_id)
        assert await visible_run_ids(_PARITY_USER, [run_id, "no-such-run"]) == {run_id}
        listed = await list_visible_runs(_PARITY_USER, limit=25)
        assert run_id in {row["id"] for row in listed}

        # A caller outside the producing Workspace is refused without learning
        # the id exists -- the same answer a missing id gets (#1174).
        assert await visible_run_detail(_PARITY_FOREIGN_USER, run_id) is None
        assert not await can_inspect_run(_PARITY_FOREIGN_USER, run_id)
        assert await visible_run_ids(_PARITY_FOREIGN_USER, [run_id]) == set()

        # -- Control: cancel a genuinely mid-flight turn by the same id. ------
        parked = _ParkedRunner()
        live = asyncio.create_task(
            producer.execute(
                session_id="parity-session-2",
                repo="agent-stronghold/project-maistro",
                prompt="long-running turn",
                messages=[{"role": "user", "content": "long-running turn"}],
                runner=parked,
            )
        )
        live_id = await _wait_for_running_turn(profile.run_store, profile.workspace_id)
        response = await cancel_route(live_id, _ParityRequest(_PARITY_USER))
        # #1242: the receipt is strict closeout evidence, not a bare success.
        # The fence is durable CANCELLED; the walk had not claimed the turn's
        # physical try yet, so there was nothing to signal and the durable
        # fence is what refuses a competing consumer claim afterwards.
        assert response == {
            "run_id": live_id,
            "status": "cancelled",
            "cancelled": True,
            "stop_confirmed": True,
            "disposition": "stop_confirmed",
            "cause": "requested",
            "diagnosis": (
                "the Run owned no physical try; the durable CANCELLED fence is what refuses "
                "a competing consumer claim, so no invocation can start afterwards"
            ),
            "attempts": [],
        }
        fenced = await profile.run_store.get_run(live_id)
        assert fenced is not None and fenced.status is RunStatus.CANCELLED
        after = await visible_run_detail(_PARITY_USER, live_id)
        assert after is not None and after["status"] == "cancelled"

        # The still-parked physical work can no longer publish success over
        # the fence: it is released, and whatever the durable walk does with
        # its own in-flight settlement (#44/#1169), the canonical record and
        # every inspection read stay cancelled.
        parked.release.set()
        try:
            await asyncio.wait_for(asyncio.shield(live), timeout=30.0)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            if not live.done():
                raise
        except Exception:
            pass
        if not live.done():
            live.cancel()
            with contextlib.suppress(BaseException):
                await live
        if live.done() and not live.cancelled():
            # Retrieve the outcome so the loop stays warning-free; the
            # turn's own aborted-settlement error is #44/#1169 evidence,
            # not a pass/fail input for this scenario.
            live.exception()
        turn_completed_cleanly = (
            live.done()
            and not live.cancelled()
            and live.exception() is None
            and live.result().status is RunStatus.COMPLETED
        )
        assert not turn_completed_cleanly, (
            "a cancelled Builders turn must never complete successfully"
        )
        final = await profile.run_store.get_run(live_id)
        assert final is not None and final.status is RunStatus.CANCELLED
        final_detail = await visible_run_detail(_PARITY_USER, live_id)
        assert final_detail is not None and final_detail["status"] == "cancelled"

        return ScenarioExecution(
            {
                "producer": "builders",
                "observer": "conductor",
                "run_id": run_id,
                "workspace_id": profile.workspace_id,
                "project_id": profile.project_id,
                "producer_status": detail["status"],
                "physical_node_runs": len(node_runs),
                "physical_attempts": len(attempts),
                "projection_rows_for_run": 0,
                "foreign_observer_visible": False,
                "cancelled_run_id": live_id,
                "cancelled_status": final_detail["status"],
            }
        )
    finally:
        monkey.undo()
        if profile is not None:
            await profile.close()
        shutil.rmtree(scratch, ignore_errors=True)


def _validate_builders_observation(observation: Mapping[str, Any]) -> None:
    """The strict invariant over the real producer/observer records (#2210)."""
    assert observation["producer"] == "builders"
    assert observation["observer"] == "conductor"
    for field in ("run_id", "workspace_id", "project_id", "cancelled_run_id"):
        assert observation[field], f"observation lacks canonical {field}"
    assert observation["producer_status"] == "completed"
    assert observation["physical_node_runs"] >= 1
    assert observation["physical_attempts"] >= 1
    assert observation["projection_rows_for_run"] == 0
    assert observation["foreign_observer_visible"] is False
    assert observation["cancelled_status"] == "cancelled"


def _required_golden_scenarios() -> tuple[tuple[str, str], ...]:
    """Every (product, scenario_id) the locked #463 manifest requires."""
    require_dependencies(GOLDEN_BASELINES)
    manifest_path = Path(__file__).resolve().parents[1] / "golden_baselines" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = {item["product"]: item for item in manifest["fixtures"]}
    required: list[tuple[str, str]] = []
    for product in manifest["required_products"]:
        fixture_entry = fixtures.get(product)
        if fixture_entry is None:
            raise ParityContractError(
                f"golden manifest requires {product!r} without a declared fixture"
            )
        fixture = json.loads(
            (manifest_path.parent / fixture_entry["path"]).read_text(encoding="utf-8")
        )
        for scenario in fixture["scenarios"]:
            required.append((product, scenario["id"]))
    assert required, "golden manifest must require at least one product scenario"
    return tuple(required)


def _validate_golden_observation(observation: Mapping[str, object]) -> None:
    """Match every manifest-required scenario, not one Builders case (#463)."""
    required = _required_golden_scenarios()
    required_keys = {f"{product}/{scenario_id}" for product, scenario_id in required}
    registered = {str(key) for key in observation}
    missing = sorted(required_keys - registered)
    if missing:
        raise ParityContractError(
            "golden observation lacks required product scenarios: " + ", ".join(missing)
        )
    unexpected = sorted(registered - required_keys)
    if unexpected:
        raise ParityContractError(
            "golden observation registered unrequired scenarios: " + ", ".join(unexpected)
        )
    for key in sorted(required_keys):
        product, scenario_id = key.split("/", 1)
        assert_matches_golden(product, scenario_id, observation[key])


BUILDERS_SCENARIO = ParityScenario(
    name="builders-producer-to-conductor",
    dependencies=(BUILDERS, CONDUCTOR_INSPECTION, REAL_BUILDERS_CONDUCTOR_SCENARIO),
    execute=_builders_conductor_scenario,
    validate_observation=_validate_builders_observation,
)
SCHEDULER_SCENARIO = ParityScenario(
    name="scheduler-occurrence-to-conductor",
    dependencies=(SCHEDULER, CONDUCTOR_INSPECTION, REAL_SCHEDULE_CONDUCTOR_SCENARIO),
    execute=_schedule_conductor_scenario,
    validate_observation=_validate_schedule_observation,
)
EVOLVE_SCENARIO = ParityScenario(
    name="evolve-cycle-to-conductor",
    dependencies=(EVOLVE, CONDUCTOR_INSPECTION, REAL_EVOLVE_CONDUCTOR_SCENARIO),
    execute=_evolve_conductor_scenario,
    validate_observation=_validate_evolve_observation,
)
GOLDEN_SCENARIO = ParityScenario(
    name="golden-real-observation",
    dependencies=(GOLDEN_BASELINES,),
    execute=_golden_scenario,
    validate_observation=_validate_golden_observation,
)


@pytest.mark.asyncio
async def test_cross_product_parity_profile_is_real_sqlite_and_survives_restart(
    tmp_path: Path,
) -> None:
    """The suite's fixture is the supported durable spine, not an in-memory double."""
    db_path = tmp_path / "m1-459-parity.sqlite3"
    first = await open_durable_profile(db_path, workspace_id="workspace-parity")
    graph = Graph(
        graph_id="graph-parity-restart",
        workspace_id=first.workspace_id,
        project_id=first.project_id,
        name="M1 parity restart probe",
        nodes=[Node(node_id="node-parity", node_type="parity.probe", name="Probe")],
    )
    run = await first.run_store.create_run(
        graph,
        provenance={"admission_source": "m1-459-harness"},
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    first_project_id = first.project_id
    await first.close()

    second = await open_durable_profile(db_path, workspace_id="workspace-parity")
    try:
        restored = await second.run_store.get_run(run.run_id)
        assert restored is not None
        assert restored.run_id == run.run_id
        assert restored.graph.graph_id == graph.graph_id
        assert restored.workspace_id == first.workspace_id
        assert restored.project_id == first_project_id == second.project_id
        assert restored.provenance["admission_source"] == "m1-459-harness"
    finally:
        await second.close()


def test_identical_cross_product_identity_projection_is_accepted() -> None:
    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "event_id": "event-1",
        "invocation_id": "invocation-1",
        "artifact_id": "artifact-1",
        "provenance_id": "provenance-1",
        "status": "completed",
    }
    projected = {**canonical, "terminal_state": "completed"}

    assert_identity_projection(canonical, projected)


def test_second_run_id_mapping_and_private_terminal_state_are_rejected() -> None:
    """Scenario 5: planted parallel identity/lifecycle authority must fail closed."""
    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "status": "completed",
    }

    with pytest.raises(ParityContractError, match="second Run identity"):
        assert_identity_projection(
            canonical,
            {**canonical, "product_run_id": "run-2", "terminal_state": "completed"},
        )

    with pytest.raises(ParityContractError, match="product-private terminal state"):
        assert_identity_projection(
            canonical,
            {**canonical, "terminal_state": "product_done"},
        )


def test_builders_created_work_has_public_conductor_inspection_seams() -> None:
    """Scenario 1 activation contract for Builders -> Conductor parity.

    The scaffold-era import/source checks below are still true, but they are
    no longer the evidence: ``_builders_conductor_scenario`` now executes the
    real producer -> spine -> observer boundary, and
    ``test_builders_required_scenario_emits_strict_closeout_evidence`` runs it
    through the closeout machinery. This test stays as the cheap seam check
    that fails before the scenario ever runs if the public surface regresses.
    """
    require_dependencies(BUILDERS, CONDUCTOR_INSPECTION, REAL_BUILDERS_CONDUCTOR_SCENARIO)


def test_builders_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 1 through the closeout machinery (#1069).

    The Builders -> Conductor scenario is a real execution now, so it must
    record PASSED evidence in development mode: a regression back to an
    abstaining scaffold (or any parity break in the real producer/observer
    boundary) shows up here as BLOCKED/FAILED instead of a green check.
    """
    evidence = execute_scenario_sync(BUILDERS_SCENARIO)
    assert evidence.status == "PASSED"
    assert evidence.executed is True


def test_schedule_fire_has_canonical_admission_and_shared_inspection_seams() -> None:
    """Scenario 2 activation contract for the live schedule fire path.

    See ``REAL_SCHEDULE_CONDUCTOR_SCENARIO`` in harness.py: source-token checks
    alone do not prove a real schedule occurrence was observed through Conductor.
    """
    dependency = dependency_assessment(
        SCHEDULER, CONDUCTOR_INSPECTION, REAL_SCHEDULE_CONDUCTOR_SCENARIO
    )
    if not dependency.ready:
        assert dependency.blockers
        return

    scheduler_source = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "hive-conductor"
        / "backend"
        / "services"
        / "scheduler.py"
    ).read_text(encoding="utf-8")
    assert "ScheduleRunAdmitter" in scheduler_source
    assert "_canonical_admitter" in scheduler_source


def test_schedule_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 2 through the closeout machinery (#1069); see scenario 1.

    The schedule -> Conductor boundary is a real execution now, so it must
    record PASSED evidence in development mode: a regression to an abstaining
    scaffold -- or any break in the real configured-lifespan, restart, or
    projection-authority contract (#1199/#2467) -- shows up here as
    BLOCKED/FAILED instead of a green check.
    """
    evidence = execute_scenario_sync(SCHEDULER_SCENARIO)
    assert evidence.status == "PASSED"
    assert evidence.executed is True


def test_evolve_has_canonical_run_identity_and_shared_inspection_seams() -> None:
    """Scenario 3 activation contract for the shipped Evolve cycle path.

    See ``REAL_EVOLVE_CONDUCTOR_SCENARIO`` in harness.py: source-token checks
    alone do not prove a real Evolve cycle was observed through Conductor.
    """
    dependency = dependency_assessment(EVOLVE, CONDUCTOR_INSPECTION, REAL_EVOLVE_CONDUCTOR_SCENARIO)
    if not dependency.ready:
        assert dependency.blockers
        return

    evolution_source = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "hive-conductor"
        / "backend"
        / "services"
        / "evolution.py"
    ).read_text(encoding="utf-8")
    assert "run_canonical_evolution_cycle" in evolution_source
    assert "last_run_id" in evolution_source


def test_evolve_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 3 through the closeout machinery (#1069); see scenario 1.

    The Evolve -> Conductor scenario is a real execution now (with #1064's
    durable publication ledger as part of the observation), so it must record
    PASSED evidence in development mode; a regression back to an abstaining
    scaffold or any parity break in the producer/observer boundary shows up
    here as BLOCKED/FAILED instead of a green check.
    """
    evidence = execute_scenario_sync(EVOLVE_SCENARIO)
    assert evidence.status == "PASSED"
    assert evidence.executed is True


def test_shared_identity_contract_consumes_executable_ontology() -> None:
    """Scenario 4 uses #458 as authority for shared identity field names."""
    require_dependencies(ONTOLOGY)
    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "invocation_id": "invocation-1",
        "event_id": "event-1",
        "artifact_id": "artifact-1",
        "status": "completed",
    }
    projected = {**canonical, "terminal_state": "completed"}

    assert_ontology_identity_projection(canonical, projected)


def test_463_golden_fixtures_are_consumed_as_independent_oracle() -> None:
    """Scenario 6 consumes, rather than duplicates, the locked #463 matcher.

    ``REAL_GOLDEN_PRODUCT_OBSERVATION`` keeps this an evidenced blocker until a
    converged product's own observation replaces the fixture's own
    ``example_observation`` below -- feeding a fixture its own example only
    proves oracle wiring, not product behavior (#459).
    """
    dependency = dependency_assessment(GOLDEN_BASELINES, REAL_GOLDEN_PRODUCT_OBSERVATION)
    if not dependency.ready:
        assert dependency.blockers
        return

    # The fixture's own example is only an oracle wiring proof. Product
    # observations replace it in the executable scenarios after their active
    # dependencies land; the expectations remain owned by #463.
    from tests.cross_product_parity.harness import load_golden_scenario

    scenario, _ = load_golden_scenario("builders", "retry_keeps_logical_run")
    assert_matches_golden("builders", "retry_keeps_logical_run", scenario["example_observation"])


def test_golden_real_observation_emits_strict_closeout_evidence() -> None:
    """Scenario 6 through the closeout machinery (#1069); see scenario 1."""
    evidence = execute_scenario_sync(GOLDEN_SCENARIO)
    if evidence.status == "BLOCKED":
        assert evidence.error or evidence.blockers


def test_golden_closeout_requires_every_manifest_scenario() -> None:
    """A lone Builders observation cannot register golden parity (#463).

    The manifest requires Builders, Conductor, Evolve, and schedules, so the
    golden validator must fail closed naming every uncovered product scenario
    before a closeout report can declare the golden baseline satisfied.
    """
    required = _required_golden_scenarios()
    assert {product for product, _ in required} == {"builders", "conductor", "evolve", "schedules"}
    assert len(required) == 15
    with pytest.raises(ParityContractError, match="lacks required product scenarios"):
        _validate_golden_observation({"builders/retry_keeps_logical_run": {}})


def test_strict_mode_fails_unavailable_dependencies_and_emits_json(capsys) -> None:
    """Source probes cannot turn a missing real product seam into green evidence."""
    dependency = Dependency(
        key="unshipped producer",
        issue=49,
        pr=None,
        description="A real producer boundary owned by the product issue.",
        probes=(SourceProbe("tests/cross_product_parity/no-such-closeout-seam.py"),),
    )
    called = False

    def execute() -> ScenarioExecution:
        nonlocal called
        called = True
        return ScenarioExecution({"run_id": "never"})

    scenario = ParityScenario("strict-unavailable", (dependency,), execute)
    with pytest.raises(DependencyUnavailable):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)

    assert not called
    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record["scenario"] == "strict-unavailable"
    assert record["status"] == "FAILED"
    assert record["executed"] is False
    assert record["blockers"]


def test_strict_mode_fails_a_real_seam_that_abstains() -> None:
    """A ready source probe is not evidence that the producer actually ran."""
    dependency = Dependency(
        key="ready-looking producer",
        issue=49,
        pr=None,
        description="A source token is not a product execution.",
        probes=(),
    )

    def abstain() -> ScenarioExecution:
        raise ScenarioAbstained("producer did not execute")

    scenario = ParityScenario("strict-abstention", (dependency,), abstain)
    with pytest.raises(ScenarioAbstained):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)


def test_executed_scenario_emits_passed_evidence(capsys) -> None:
    """An executed scenario is machine-readable PASSED evidence (#1069).

    The FAILED and abstention paths are pinned above; this pins the success
    half of the EXECUTED/PASSED-or-FAILED contract, so a regression in the
    success-path classification (or its JSON record) cannot silently turn a
    really-executed scenario into any other recorded state.
    """

    def execute() -> ScenarioExecution:
        return ScenarioExecution({"run_id": "run-real"})

    def validate(observation: Mapping[str, object]) -> None:
        assert observation["run_id"] == "run-real"

    scenario = ParityScenario(
        "strict-executed",
        (Dependency(key="landed producer", issue=49, pr=None, description="", probes=()),),
        execute,
        validate_observation=validate,
    )

    evidence = execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)

    assert evidence.status == "PASSED"
    assert evidence.executed is True
    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record == {
        "scenario": "strict-executed",
        "status": "PASSED",
        "executed": True,
        "blockers": [],
        "error": None,
    }


@pytest.mark.asyncio
async def test_closeout_report_passes_only_after_real_execution() -> None:
    """A green aggregate closeout requires the scenario to have executed."""

    def execute() -> ScenarioExecution:
        return ScenarioExecution({"run_id": "run-real"})

    def validate(observation: Mapping[str, object]) -> None:
        assert observation["run_id"] == "run-real"

    scenario = ParityScenario(
        "only-required",
        (Dependency(key="landed producer", issue=49, pr=None, description="", probes=()),),
        execute,
        validate_observation=validate,
    )

    report = await execute_closeout((scenario,))

    assert report.passed is True
    payload = report.as_dict()
    assert payload["mode"] == "m1-closeout"
    assert payload["scenarios"] == [
        {
            "scenario": "only-required",
            "status": "PASSED",
            "executed": True,
            "blockers": [],
            "error": None,
        }
    ]


def test_strict_passed_requires_real_observation_and_invariant(capsys) -> None:
    """A strict PASSED must carry observation evidence and an invariant.

    Codex review (PR #2210): previously the observation was required only when
    a validator was configured, so a degenerate ``ScenarioExecution()`` — no
    observation, no ``validate_observation`` — was recorded as
    ``executed=true, PASSED`` in strict release mode, and a scenario could
    satisfy the closeout while proving nothing. The Builders/scheduler/Evolve
    scenarios abstain until their product seams land; this pin keeps whatever
    replaces them honest.
    """
    dependency = Dependency(key="landed producer", issue=49, pr=None, description="", probes=())

    def degenerate() -> ScenarioExecution:
        return ScenarioExecution()

    scenario = ParityScenario("strict-degenerate", (dependency,), degenerate)
    with pytest.raises(ScenarioAbstained, match="no product observation"):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)
    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record["scenario"] == "strict-degenerate"
    assert record["status"] == "FAILED"
    assert record["executed"] is False
    assert "no product observation" in record["error"]

    def observed() -> ScenarioExecution:
        return ScenarioExecution({"run_id": "run-real"})

    # Observation alone is not enough in strict mode: an invariant over the
    # real producer/observer records must be named, or the closeout cannot
    # distinguish an executed scenario from one that merely returned.
    invariantless = ParityScenario("strict-invariantless", (dependency,), observed)
    with pytest.raises(ScenarioAbstained, match="no observation invariant"):
        execute_scenario_sync(invariantless, mode=ParityMode.M1_CLOSEOUT)
    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record["scenario"] == "strict-invariantless"
    assert record["status"] == "FAILED"
    assert record["executed"] is False
    assert "no observation invariant" in record["error"]

    # Development mode keeps the two-mode contract: it reports named blockers
    # without failing closed, and does not require the invariant spelling —
    # only strict (release) mode demands an invariant for PASSED. The mode is
    # pinned explicitly because the strict invocation exports the closeout
    # environment into the whole suite, including this test.
    evidence = execute_scenario_sync(invariantless, mode=ParityMode.DEVELOPMENT)
    assert evidence.status == "PASSED"
    assert evidence.executed is True


def test_strict_mode_records_validation_failure_as_failed_evidence(capsys) -> None:
    """A real parity regression in strict mode is FAILED evidence, not a bare crash."""

    def execute() -> ScenarioExecution:
        return ScenarioExecution({"run_id": "run-real", "terminal_state": "completed"})

    def reject(observation: Mapping[str, object]) -> None:
        raise ParityContractError("terminal state diverged")

    scenario = ParityScenario(
        "strict-diverged",
        (Dependency(key="landed producer", issue=49, pr=None, description="", probes=()),),
        execute,
        validate_observation=reject,
    )

    with pytest.raises(ParityContractError, match="terminal state diverged"):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)

    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record["status"] == "FAILED"
    assert record["executed"] is False
    assert "ParityContractError" in record["error"]


@pytest.mark.asyncio
async def test_strict_closeout_reports_every_required_scenario() -> None:
    """The aggregate closeout does not stop after the first unavailable seam."""
    missing = Dependency(
        key="missing closeout owner",
        issue=49,
        pr=None,
        description="A required producer boundary.",
        probes=(SourceProbe("tests/cross_product_parity/no-such-closeout-seam.py"),),
    )
    scenarios = (
        ParityScenario("first-required", (missing,), _abstaining_scenario),
        ParityScenario("second-required", (missing,), _abstaining_scenario),
    )

    with pytest.raises(CloseoutFailure) as raised:
        await execute_closeout(scenarios)

    report = json.loads(str(raised.value))
    assert report["passed"] is False
    assert [item["scenario"] for item in report["scenarios"]] == [
        "first-required",
        "second-required",
    ]
    assert all(item["status"] == "FAILED" for item in report["scenarios"])


def test_dependency_handling_contains_no_test_suppression_escape_hatch() -> None:
    """Unavailable product scenarios stay assertion-backed and merge-policy clean."""
    suite_dir = Path(__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (suite_dir / "harness.py", suite_dir / "test_cross_product_parity.py")
    )
    forbidden = (
        "pytest." + "skip(",
        "pytest." + "importorskip(",
        "pytest.mark." + "xfail",
        "pytest.mark." + "skip",
    )
    for token in forbidden:
        assert token not in source


def test_strict_mode_turns_synthetic_unavailable_dependency_into_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1 closeout mode (#459): a blocker cannot register as a pass.

    ``dependency_assessment`` normally reports an unavailable dependency as a
    named blocker so development-mode scenarios can assert it and return.
    Under ``MAISTRO_PARITY_STRICT=1`` the same unavailable dependency must
    instead raise, so a strict-closeout scenario that only proved its
    dependency missing fails the suite rather than passing it.
    """
    monkeypatch.setenv("MAISTRO_PARITY_STRICT", "1")
    synthetic = Dependency(
        key="synthetic unavailable dependency",
        issue=1036,
        pr=None,
        description="A SourceProbe pointed at a path that does not exist.",
        probes=(SourceProbe("tests/cross_product_parity/__does_not_exist__.py"),),
    )

    with pytest.raises(DependencyUnavailable, match="synthetic unavailable dependency"):
        dependency_assessment(synthetic)


def test_conflicting_strict_and_mode_env_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review: MAISTRO_PARITY_STRICT=1 must not be silently downgraded.

    The two spellings name one strict concept, so inheriting
    ``MAISTRO_PARITY_MODE=development`` alongside ``MAISTRO_PARITY_STRICT=1``
    is a configuration error and must fail loudly instead of selecting
    development mode (which would return blockers for callers to early-return
    past rather than raising).
    """
    monkeypatch.setenv("MAISTRO_PARITY_STRICT", "1")
    monkeypatch.setenv("MAISTRO_PARITY_MODE", "development")

    with pytest.raises(ValueError, match="conflicts"):
        parity_mode()


def test_strict_spelling_agrees_with_explicit_m1_closeout_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run-m1-closeout.py combination stays a valid strict invocation."""
    monkeypatch.setenv("MAISTRO_PARITY_STRICT", "1")
    monkeypatch.setenv("MAISTRO_PARITY_MODE", "m1-closeout")

    assert parity_mode() is ParityMode.M1_CLOSEOUT


def test_non_strict_mode_still_reports_named_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development mode (#459) keeps naming blockers instead of failing closed."""
    monkeypatch.delenv("MAISTRO_PARITY_STRICT", raising=False)
    monkeypatch.delenv("MAISTRO_PARITY_MODE", raising=False)
    synthetic = Dependency(
        key="synthetic unavailable dependency",
        issue=1036,
        pr=None,
        description="A SourceProbe pointed at a path that does not exist.",
        probes=(SourceProbe("tests/cross_product_parity/__does_not_exist__.py"),),
    )

    assessment = dependency_assessment(synthetic)

    assert not assessment.ready
    assert len(assessment.blockers) == 1
    assert "synthetic unavailable dependency" in assessment.blockers[0]
    assert "issue #1036" in assessment.blockers[0]


def test_scaffold_only_scenarios_stay_blocked_until_real_execution_lands() -> None:
    """A source-probe-only scenario must not read as M1 closure evidence.

    Codex review (PR #1641): once a scenario's named product dependency lands,
    an import/source-token check alone is not proof the scenario executed a
    real cross-product Run through the product's own path. Scenario 6
    still carries its permanent, evidence-backed blocker (``REAL_*`` in
    harness.py) precisely so the compound ``dependency_assessment`` call stays
    unavailable -- and strict mode stays red -- until each scaffold is replaced
    with a real execution. Scenario 1 (Builders -> Conductor) and scenario 2
    (schedule occurrence -> Conductor, #1199) made that replacement, so their
    ``REAL_*`` markers must now read as available: each blocker is cleared by
    construction once the real scenario exists, and the real execution itself
    is what the matching strict-closeout test proves.
    Scenario 3 (Evolve -> Conductor, with #1064's durable publication
    ledger in its observation) made that replacement as well; the
    matching evolve strict-closeout test pins its real execution.
    """
    assert REAL_BUILDERS_CONDUCTOR_SCENARIO.available(), (
        "the Builders -> Conductor real-scenario marker regressed to unavailable: "
        "the real scenario execution was lost"
    )
    assert REAL_EVOLVE_CONDUCTOR_SCENARIO.available(), (
        "the Evolve -> Conductor real-scenario marker regressed to unavailable: "
        "the real scenario execution was lost"
    )
    assert REAL_SCHEDULE_CONDUCTOR_SCENARIO.available(), (
        "the schedule -> Conductor real-scenario marker regressed to unavailable: "
        "the real configured-lifespan scenario execution was lost (#1199)"
    )
    for dependency in (REAL_GOLDEN_PRODUCT_OBSERVATION,):
        assert not dependency.available(), (
            f"{dependency.key} reads as available -- its scaffold-only scenario "
            "would now pass as if it were real execution evidence"
        )

    # Scenario 6 concretely, right now: GOLDEN_BASELINES alone is already
    # satisfied on this branch, so REAL_GOLDEN_PRODUCT_OBSERVATION is the only
    # thing keeping that scenario from reading as closure evidence. Checked via
    # `.available()`, not `dependency_assessment()`, so this assertion holds
    # regardless of MAISTRO_PARITY_STRICT in the ambient test environment.
    assert GOLDEN_BASELINES.available()
    assert not REAL_GOLDEN_PRODUCT_OBSERVATION.available()
