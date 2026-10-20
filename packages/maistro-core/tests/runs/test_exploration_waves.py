"""Explore-wave contract tests (M7-A8).

The wave contract lives on the canonical ``Goal -> Graph -> Run -> NodeRun ->
Attempt`` spine: one design Run fans an explore node out to ``width`` thesis
NodeRuns, each thesis durable on its NodeRun's provenance, each scored against
the same Rubric revision (eval-on-Run, #792), losers queryable after a winner
is named, and a later wave on the *same* Run unable to persist a thesis an
earlier wave already rejected.

Two source-level contracts ride along:

- design exploration must never store its candidates in DesignProject /
  CreativeBrief / UI state — the Run store is the system of record;
- the design loop must never import ``maistro.orchestrator.waves`` (ADR-052 /
  SPEC-255) as its owner — that island is unreachable pending C6 and stays
  that way here.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs import (
    PROVENANCE_KEY,
    NodeRun,
    Run,
    RunStatus,
    ThesisSettledError,
    WaveWinnerAlreadyNamedError,
)
from maistro.runs.exploration import (
    DuplicateThesisError,
    ExplorationPlan,
    ExplorationPolicy,
    RubricRevisionMismatchError,
    ThesisNotInWaveError,
    ThesisProvenance,
    ThesisWidthMismatchError,
    exploration_plan_of,
    fan_out_wave,
    merge_thesis_record,
    name_wave_winner,
    record_thesis_score,
    rejected_thesis_texts,
    thesis_provenance_of,
    wave_records,
)
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

EXPLORE_NODE_ID = "explore"

#: The storage-identity field names whose appearance on a design-side project
#: object would mean candidates are being kept in UI/design state instead of
#: on the Run spine (M7-A8 forbidden list).
_FORBIDDEN_DESIGN_STORAGE_FIELDS = frozenset(
    {"variants", "variant", "candidates", "candidate", "theses", "thesis_list", "waves"}
)


def _explore_graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Explore wave graph",
        nodes=[
            Node(node_id=EXPLORE_NODE_ID, node_type="agent", name="Explore"),
            Node(node_id="settle", node_type="agent", name="Settle"),
        ],
        edges=[],
    )


def _plan(policy: ExplorationPolicy = ExplorationPolicy.WIDE_THEN_CONVERGE, width: int = 3):
    return ExplorationPlan(
        policy=policy,
        width=width,
        goal_revision="goal-rev-1",
        rubric_revision="rubric-rev-1",
    )


async def _wave_one(store: Any, run: Run, *, plan: ExplorationPlan | None = None) -> list[NodeRun]:
    return await fan_out_wave(
        store,
        run,
        plan=plan or _plan(),
        wave_index=1,
        parent_node_id=EXPLORE_NODE_ID,
        theses=[
            "A serif-forward editorial layout",
            "A dense dashboard-first console",
            "A single-canvas storytelling page",
        ],
    )


async def _new_run(store: Any, workspace: str, project_id: str, *, plan: ExplorationPlan) -> Run:
    return await store.create_run(
        _explore_graph(workspace, project_id),
        provenance=plan.run_provenance(),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )


# ── Wave 1: fan-out on one Run ────────────────────────────────────────────────


async def test_wave_one_fans_out_width_child_thesis_node_runs_on_one_run(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))

    node_runs = await _wave_one(store, run)

    assert len(node_runs) == 3
    # Child NodeRuns of ONE Run: no new Run identity per thesis.
    assert {node_run.run_id for node_run in node_runs} == {run.run_id}
    stored = await store.list_node_runs(run.run_id)
    assert [node_run.node_run_id for node_run in stored] == [
        node_run.node_run_id for node_run in node_runs
    ]
    records = wave_records(stored, wave_index=1)
    assert [record.thesis.slot for record in records] == [0, 1, 2]


async def test_thesis_node_runs_record_thesis_wave_and_revisions_durably(spine) -> None:
    store, workspace, project_id = spine
    plan = _plan(width=2)
    run = await _new_run(store, workspace, project_id, plan=plan)
    node_runs = await fan_out_wave(
        store,
        run,
        plan=plan,
        wave_index=1,
        parent_node_id=EXPLORE_NODE_ID,
        theses=["Brutalist grid", "Soft pastel cards"],
    )

    for node_run in node_runs:
        # Durable: read back through the store's payload, not the in-hand object.
        reloaded = await store.get_node_run(node_run.node_run_id)
        assert reloaded is not None
        provenance = thesis_provenance_of(reloaded)
        assert provenance is not None
        assert isinstance(provenance, ThesisProvenance)
        assert provenance.thesis == node_run.provenance[PROVENANCE_KEY]["thesis"]["thesis"]
        assert provenance.wave_index == 1
        assert provenance.goal_revision == "goal-rev-1"
        assert provenance.rubric_revision == "rubric-rev-1"
        assert provenance.policy is ExplorationPolicy.WIDE_THEN_CONVERGE
        assert provenance.parent_node_id == EXPLORE_NODE_ID
        thesis_record = reloaded.provenance[PROVENANCE_KEY]["thesis"]
        assert thesis_record["goal_revision"] == "goal-rev-1"
        assert thesis_record["rubric_revision"] == "rubric-rev-1"
        assert reloaded.provenance[PROVENANCE_KEY]["disposition"] == "proposed"


# ── Eval-on-Run: scoring and queryable losers ────────────────────────────────


async def test_scoring_uses_the_waves_rubric_revision_and_losers_remain_queryable(
    spine,
) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    node_runs = await _wave_one(store, run)

    # Scoring against any other Rubric revision is a contract failure.
    with pytest.raises(RubricRevisionMismatchError):
        await record_thesis_score(
            store, node_runs[0].node_run_id, rubric_revision="rubric-rev-2", score=0.9
        )

    scores = [0.4, 0.9, 0.1]
    for node_run, score in zip(node_runs, scores, strict=True):
        record = await record_thesis_score(
            store,
            node_run.node_run_id,
            rubric_revision="rubric-rev-1",
            score=score,
        )
        assert record.score is not None
        assert record.score.rubric_revision == "rubric-rev-1"

    winner = await name_wave_winner(
        store, run.run_id, wave_index=1, node_run_id=node_runs[1].node_run_id
    )
    assert winner.disposition.value == "winner"

    # Losers remain queryable after the winner is named.
    records = wave_records(await store.list_node_runs(run.run_id), wave_index=1)
    assert len(records) == 3
    by_id = {record.node_run_id: record for record in records}
    assert by_id[node_runs[1].node_run_id].disposition.value == "winner"
    losers = [record for record in records if record.disposition.value == "loser"]
    assert {record.node_run_id for record in losers} == {
        node_runs[0].node_run_id,
        node_runs[2].node_run_id,
    }
    assert rejected_thesis_texts(await store.list_node_runs(run.run_id)) == (
        "A serif-forward editorial layout",
        "A single-canvas storytelling page",
    )


# ── Wave 2: same Run, rejected theses are forbidden input ────────────────────


async def test_wave_two_on_same_run_consumes_rejected_and_cannot_repeat_one(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    wave_one = await _wave_one(store, run)
    for node_run in wave_one:
        await record_thesis_score(
            store, node_run.node_run_id, rubric_revision="rubric-rev-1", score=0.5
        )
    await name_wave_winner(store, run.run_id, wave_index=1, node_run_id=wave_one[0].node_run_id)

    rejected = rejected_thesis_texts(await store.list_node_runs(run.run_id))
    assert len(rejected) == 2

    with pytest.raises(DuplicateThesisError):
        await fan_out_wave(
            store,
            run,
            plan=_plan(width=2),
            wave_index=2,
            parent_node_id=EXPLORE_NODE_ID,
            theses=[
                "a dense DASHBOARD-first console",  # rejected, formatting aside
                "A cartographic navigation shell",
            ],
            rejected_theses=rejected,
        )
    # The refused wave left nothing behind.
    assert len(await store.list_node_runs(run.run_id)) == 3

    before = {
        node_run.node_run_id: node_run.provenance[PROVENANCE_KEY]
        for node_run in await store.list_node_runs(run.run_id)
    }
    wave_two = await fan_out_wave(
        store,
        run,
        plan=_plan(width=2),
        wave_index=2,
        parent_node_id=EXPLORE_NODE_ID,
        theses=["A cartographic navigation shell", "A typographic poster wall"],
        rejected_theses=rejected,
    )
    # Same Run, later ordinals — a later wave is never a new Run identity.
    assert {node_run.run_id for node_run in wave_two} == {run.run_id}
    stored = await store.list_node_runs(run.run_id)
    assert len(stored) == 5
    assert {record.thesis.wave_index for record in wave_records(stored)} == {1, 2}
    # Historical wave 1 stayed immutable.
    after = {node_run.node_run_id: node_run.provenance[PROVENANCE_KEY] for node_run in stored}
    for node_run_id, record in before.items():
        assert after[node_run_id] == record


# ── Policies: pack-declared, visible on the Run, not three products ──────────


@pytest.mark.parametrize("policy", list(ExplorationPolicy))
async def test_policies_are_pack_declared_and_visible_on_the_run(spine, policy) -> None:
    store, workspace, project_id = spine
    plan = _plan(policy=policy, width=2)
    run = await _new_run(store, workspace, project_id, plan=plan)

    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert exploration_plan_of(reloaded) == plan
    assert exploration_plan_of(reloaded) is not None
    if exploration_plan_of(reloaded) is not None:
        assert exploration_plan_of(reloaded).policy is policy  # type: ignore[union-attr]


def test_policy_is_one_enum_not_three_products() -> None:
    assert {policy.value for policy in ExplorationPolicy} == {
        "wide-then-converge",
        "tight",
        "tournament",
    }


async def test_tightening_width_does_not_change_goal_identity(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=5))
    tightened = ExplorationPlan(
        policy=ExplorationPolicy.TIGHT,
        width=2,
        goal_revision="goal-rev-1",
        rubric_revision="rubric-rev-1",
    )
    revised = await store.create_run(
        _explore_graph(workspace, project_id),
        provenance=tightened.run_provenance(),
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    assert exploration_plan_of(revised) == tightened
    assert exploration_plan_of(revised) is not None
    if exploration_plan_of(revised) is not None:
        assert exploration_plan_of(revised).goal_revision == "goal-rev-1"  # type: ignore[union-attr]
    # The original Run keeps its own plan; tightening happened per Run.
    original = await store.get_run(run.run_id)
    assert original is not None
    assert original.provenance["exploration"]["width"] == 5
    assert original.status is RunStatus.CREATED


# ── Width and divergence contracts ───────────────────────────────────────────


async def test_wave_width_must_match_the_thesis_count(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    with pytest.raises(ThesisWidthMismatchError):
        await fan_out_wave(
            store,
            run,
            plan=_plan(width=3),
            wave_index=1,
            parent_node_id=EXPLORE_NODE_ID,
            theses=["Only one bet", "Only two bets"],
        )
    assert await store.list_node_runs(run.run_id) == []


async def test_duplicate_within_one_wave_is_refused_without_persisting(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    with pytest.raises(DuplicateThesisError):
        await fan_out_wave(
            store,
            run,
            plan=_plan(width=3),
            wave_index=1,
            parent_node_id=EXPLORE_NODE_ID,
            theses=["Same bet", "same  bet", "Different bet"],
        )
    assert await store.list_node_runs(run.run_id) == []


async def test_fan_out_requires_the_explore_node_in_the_graph_snapshot(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=2))
    with pytest.raises(ThesisNotInWaveError):
        await fan_out_wave(
            store,
            run,
            plan=_plan(width=2),
            wave_index=1,
            parent_node_id="not-in-graph",
            theses=["One", "Two"],
        )


async def test_winner_can_be_named_only_once(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    wave_one = await _wave_one(store, run)
    await name_wave_winner(store, run.run_id, wave_index=1, node_run_id=wave_one[0].node_run_id)
    with pytest.raises(WaveWinnerAlreadyNamedError):
        await name_wave_winner(store, run.run_id, wave_index=1, node_run_id=wave_one[1].node_run_id)
    # Naming the same winner again is idempotent.
    again = await name_wave_winner(
        store, run.run_id, wave_index=1, node_run_id=wave_one[0].node_run_id
    )
    assert again.disposition.value == "winner"


async def test_settled_thesis_cannot_be_rescored_or_have_identity_rewritten(spine) -> None:
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=2))
    wave_one = await fan_out_wave(
        store,
        run,
        plan=_plan(width=2),
        wave_index=1,
        parent_node_id=EXPLORE_NODE_ID,
        theses=["First bet", "Second bet"],
    )
    await name_wave_winner(store, run.run_id, wave_index=1, node_run_id=wave_one[0].node_run_id)

    with pytest.raises(ThesisSettledError):
        await record_thesis_score(
            store, wave_one[1].node_run_id, rubric_revision="rubric-rev-1", score=0.7
        )
    # Identity is immutable once recorded: every domain write composes its
    # record through merge_thesis_record, which refuses identity rewrites.
    loser = await store.get_node_run(wave_one[1].node_run_id)
    assert loser is not None
    record = loser.provenance[PROVENANCE_KEY]
    forged_thesis = dict(record["thesis"])
    forged_thesis["thesis"] = "A very different late bet"
    with pytest.raises(ThesisSettledError):
        merge_thesis_record(record, {"thesis": forged_thesis})
    # Progressing a disposition is not an identity rewrite.
    progressed = merge_thesis_record(record, {"disposition": "parked"})
    assert progressed["thesis"] == record["thesis"]
    assert progressed["disposition"] == "parked"


# ── Source-level contracts ───────────────────────────────────────────────────


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def _design_source_root() -> Path:
    local = _repo_root() / "packages" / "maistro-design" / "src" / "maistro_design"
    if local.is_dir():
        return local
    import importlib.util

    spec = importlib.util.find_spec("maistro_design")
    if spec is None or spec.submodule_search_locations is None:
        raise FileNotFoundError("maistro_design source tree not found")
    return Path(next(iter(spec.submodule_search_locations)))


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _waves_island_reference(text: str) -> str | None:
    patterns = [
        r"^\s*from\s+maistro\.orchestrator(\.waves)?\s+import\s+.*\bwaves\b",
        r"^\s*from\s+maistro\.orchestrator\.waves\s+import\s+",
        r"^\s*import\s+maistro\.orchestrator\.waves\b",
        r"import_module\(\s*[\"']maistro\.orchestrator\.waves",
    ]
    for line in text.splitlines():
        if any(re.search(pattern, line) for pattern in patterns):
            return line.strip()
    return None


@lru_cache(maxsize=1)
def _design_loop_island_violations() -> tuple[str, ...]:
    """Scan the design-loop source trees once per session.

    The scan is a contract, not a benchmark: every violation names the file
    and the offending line so a repair knows exactly what to remove.
    """
    import maistro.graph
    import maistro.runs

    scopes = {
        "maistro.runs": Path(maistro.runs.__file__).resolve().parent,
        "maistro.graph": Path(maistro.graph.__file__).resolve().parent,
        "maistro_design": _design_source_root(),
    }
    violations: list[str] = []
    for package, root in scopes.items():
        for path in _python_files(root):
            hit = _waves_island_reference(path.read_text(encoding="utf-8"))
            if hit is not None:
                violations.append(f"{package}:{path.name}: {hit}")
    return tuple(violations)


def test_design_loop_never_imports_the_orchestrator_waves_island() -> None:
    """The ADR-052/SPEC-255 island is not the design-loop owner (M7-A8)."""
    violations = _design_loop_island_violations()
    assert not violations, (
        f"the design loop imports maistro.orchestrator.waves as its owner: {violations}"
    )


@lru_cache(maxsize=1)
def _design_project_candidate_fields() -> tuple[tuple[str, str], ...]:
    """Candidate-storage fields found on design-side project objects."""
    design_root = _design_source_root()
    type_files = [design_root / "types.py"]
    if not type_files[0].is_file():
        type_files = _python_files(design_root)
    found: list[tuple[str, str]] = []
    saw_project_class = False
    for path in type_files:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"^class\s+(DesignProject|CreativeBrief)\b[^:]*:", text, re.MULTILINE
        ):
            saw_project_class = True
            name = match.group(1)
            body = text[match.end() : text.find("\nclass ", match.end())]
            fields = re.findall(r"^    ([a-zA-Z_][a-zA-Z0-9_]*)\s*:", body, re.MULTILINE)
            for field in fields:
                if field in _FORBIDDEN_DESIGN_STORAGE_FIELDS:
                    found.append((name, field))
    if not saw_project_class:
        raise AssertionError("DesignProject/CreativeBrief source was not found")
    return tuple(found)


def test_wave_candidates_are_not_stored_in_design_project_or_brief_state() -> None:
    """The Run spine is the system of record; design-side objects stay dumb.

    A `variants`/`candidates`/`theses` container on DesignProject (or a
    CreativeBrief) would mean wave candidates live in design/UI state and only
    there — the forbidden system of record. This fails if one is added.
    """
    offenders = _design_project_candidate_fields()
    assert not offenders, (
        f"design-side project objects grew candidate-storage fields {offenders}: "
        "design exploration candidates must live on Run NodeRuns, not design state"
    )


async def test_wave_history_is_queryable_from_the_run_store_alone(spine) -> None:
    """Winner + losers are all retrievable from the Run spine, with no
    design-side state involved in the read path."""
    store, workspace, project_id = spine
    run = await _new_run(store, workspace, project_id, plan=_plan(width=3))
    wave_one = await _wave_one(store, run)
    for node_run in wave_one:
        await record_thesis_score(
            store, node_run.node_run_id, rubric_revision="rubric-rev-1", score=0.5
        )
    await name_wave_winner(store, run.run_id, wave_index=1, node_run_id=wave_one[1].node_run_id)

    # A fresh read of the Run reconstructs the full wave — winner and losers.
    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    records = wave_records(await store.list_node_runs(run.run_id))
    assert exploration_plan_of(reloaded) is not None
    assert len(records) == 3
    assert [record.disposition.value for record in records].count("winner") == 1
    assert [record.disposition.value for record in records].count("loser") == 2
    assert all(record.thesis.goal_revision == "goal-rev-1" for record in records)
