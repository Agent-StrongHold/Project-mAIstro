"""M7-A13 pack fixtures: one inspectable book Run, one inspectable game Run.

Issue #989. #795 proves the loop on a live product-pack scenario; this module
makes `book` and `game` visible as the *same* loop on canonical objects, so a
reviewer can open a completed (book) and a parked (game) Run in Design Studio
without running explore/judge at all.

## Seeding a real store (documented seed command)

Tests seed through the same calls an operator does. To provision a durable
store so Design Studio can list and open the fixtures, run the documented seed
command — it constructs the canonical SQLite stores and invokes these seeders
and nothing else:

    maistro fixtures seed --db ./pack-fixtures.db [--json]

The printed Run identities are canonical and durable: refresh, reconnect, and
restart all show the same ids. Opening a fixture is a read (see
``open_pack_fixture``); it never executes explore/judge.

## What gets written, and through which APIs

Every identity here is written through the canonical spine only:

    ProjectScopeStore.create_root / create      (Workspace -> Project)
    RunStore.create_run                         (Graph snapshot + Run)
    RunStore.create_node_run / create_attempt   (NodeRun / Attempt)
    RunStore.transition_run / transition_node_run /
    transition_attempt                          (lifecycle)

There is no fixture JSON file, no frontend store, and no seed-by-direct-insert:
a fixture that bypassed the lifecycle machine would be a second identity
scheme, which is exactly what this issue forbids.

## Documented reconciliation with the not-yet-merged M7 stores

The issue's fixture contract names Goal revisions (#791), eval-on-Run records
(#792), and fence decisions (#794). On this branch those concepts exist in the
ontology contract (``maistro.interop.contract``: Project -> Goal -> Run) but
have no durable stores of their own yet. The fixtures therefore record them in
the evidence fields the canonical lifecycle APIs already own, under explicit
keys, so the stores can re-parent them without renaming anything:

- ``goal_id`` / ``goal_revision`` / ``rubric_id`` / ``rubric_revision`` /
  ``redirect`` live in ``Run.provenance`` (``goal_revision`` is the revision
  field name the interop contract already gives the Goal concept).
- per-attempt eval records live in ``Attempt.result["eval_record"]``.
- the fence decision lives in the fence NodeRun's attempt evidence
  (``fence_decision``) and is summarised in ``Run.result``.

## Two modelling decisions worth restating

- Wave-1 rejected theses are *completed* NodeRuns. A rejected thesis is not a
  crashed node: the explore node did its work, and the judge record rejected
  its output. Recording rejection as a failed lifecycle would contradict
  ``check_completion_is_earned`` — an accepted Run may not complete over a
  failed node — and would mis-state what happened.
- The game Run parks as ``WAITING`` with its fence NodeRun ``WAITING`` beside
  it (RUNNING -> WAITING is a legal transition for both). Park is a non-terminal
  pause awaiting a decision, per ADR-082426-f170; resume is the canonical
  WAITING -> RUNNING move on the same identities, which is what makes it
  restart-safe: a reloaded store shows the same Run and the same waiting
  NodeRun, and continues from there.

Fixture content is original to this repo. The pack node kinds
(``book.*`` / ``game.*`` / ``fence.review``) are #985 catalog definitions, not
registered executors — that is the point: opening the fixture must not execute
explore/judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maistro.graph.definitions import Edge, Graph, Node
from maistro.projects.scope import Project
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.model import (
    AcceptedNodeOutcome,
    AttemptResult,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.store import RunNotFound, RunStore

PACK_FIXTURE_WORKSPACE_ID = "m7-pack-fixtures"
"""Workspace every M7 pack fixture (book, game, and the #795 product proof)
shares. One Workspace/Project ontology — not a second identity scheme."""

PACK_FIXTURES_PROJECT_NAME = "M7 pack fixtures"
"""Child Project under the Workspace root where the fixture Runs are filed."""

PACK_FIXTURE_PROVENANCE_KEY = "pack_fixture"
"""Run.provenance key marking a Run as an M7 pack fixture (value: pack name)."""

BOOK_PACK = "book"
GAME_PACK = "game"

BOOK_GRAPH_ID = "book-picture-book-read-aloud-v1"
GAME_GRAPH_ID = "game-session-feel-heuristics-v1"

# Public fixture API: hosts (Design Studio run list, #986) import the seeders
# and the read-only open path; tests pin the lineage through them. Declaring
# the exports keeps package-local dead-code scans from misreading
# host-consumed surface as unused (same pattern as seeds/__init__.py).
__all__ = [
    "BOOK_GRAPH_ID",
    "GAME_GRAPH_ID",
    "PACK_FIXTURE_PROVENANCE_KEY",
    "PACK_FIXTURE_WORKSPACE_ID",
    "PackFixtureSeed",
    "open_pack_fixture",
    "seed_book_fixture",
    "seed_game_fixture",
]

BOOK_CATALOG: dict[str, Any] = {
    "catalog_id": "picture-book-read-aloud",
    "title": "Picture-book read-aloud",
    "version": 1,
    "artifact_kind": "BookPages",
}
GAME_CATALOG: dict[str, Any] = {
    "catalog_id": "session-feel-heuristics",
    "title": "Session-feel heuristics",
    "version": 1,
    "artifact_kind": "GameLoop",
}

BOOK_GOAL_ID = "book-read-aloud-fixture"
BOOK_RUBRIC_ID = "picture-book-read-aloud-rubric"
GAME_GOAL_ID = "game-session-toy-fixture"
GAME_RUBRIC_ID = "session-feel-heuristics-rubric"

#: Node ids inside the fixture graphs. Stable names, so lineage queries
#: ("which NodeRun was the wave-2 winner?") read the same on every seed.
BOOK_WAVE1_THESIS_CONVENTIONAL = "wave1-thesis-conventional"
BOOK_WAVE1_THESIS_WORDLESS = "wave1-thesis-almost-wordless"
BOOK_WAVE2_WINNER = "wave2-book-pages"
FENCE_REVIEW_NODE = "fence-review"
GAME_EXPLORE_THESIS = "thesis-session-toy"


@dataclass(frozen=True)
class PackFixtureSeed:
    """Identity handles a host needs to open one seeded fixture Run."""

    pack: str
    run_id: str
    workspace_id: str
    project_id: str
    graph_id: str
    node_run_ids: dict[str, str] = field(default_factory=dict)

    def node_run_id(self, role: str) -> str:
        return self.node_run_ids[role]


async def open_pack_fixture(run_store: RunStore, run_id: str) -> dict[str, Any]:
    """Render one fixture Run from canonical reads — the host's open path.

    This is what a Design Studio run list needs to *open* a fixture: identity,
    Goal/Rubric revisions, per-node dispositions and eval verdicts, and the
    fence decision, assembled from ``get_run`` / ``list_node_runs`` /
    ``list_attempts`` and nothing else. Nothing here executes explore/judge;
    a host that cannot read a fixture through these reads has a fixture that
    exists outside the spine, which is the thing #989 forbids.
    """
    run = await run_store.get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    pack = run.provenance.get(PACK_FIXTURE_PROVENANCE_KEY)
    if not pack:
        raise ValueError(f"Run {run_id!r} is not a pack fixture")

    waves: list[dict[str, Any]] = []
    for node_run in await run_store.list_node_runs(run_id):
        result = node_run.result if isinstance(node_run.result, dict) else {}
        eval_record = result.get("eval_record")
        fence = result.get("fence_decision")
        attempts = await run_store.list_attempts(node_run.node_run_id)
        waves.append(
            {
                "node_run_id": node_run.node_run_id,
                "node_id": node_run.node_id,
                "ordinal": node_run.ordinal,
                "status": node_run.status.value,
                "artifact_kind": result.get("artifact_kind"),
                "eval_verdict": (
                    eval_record.get("verdict") if isinstance(eval_record, dict) else None
                ),
                "fence_decision": (fence.get("decision") if isinstance(fence, dict) else None),
                "attempt_count": len(attempts),
                "attempt_statuses": [attempt.status.value for attempt in attempts],
            }
        )

    run_fence = run.result.get("fence_decision") if isinstance(run.result, dict) else None
    return {
        "run_id": run.run_id,
        "pack": pack,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "graph_id": run.graph.graph_id,
        "status": run.status.value,
        "goal_id": run.provenance.get("goal_id"),
        "goal_revision": run.provenance.get("goal_revision"),
        "rubric_id": run.provenance.get("rubric_id"),
        "rubric_revision": run.provenance.get("rubric_revision"),
        "redirect": run.provenance.get("redirect"),
        "fence_decision": run_fence,
        "artifact_kind": (
            run.result.get("artifact_kind") if isinstance(run.result, dict) else None
        ),
        "waves": waves,
    }


async def ensure_pack_fixture_project(project_store: ProjectScopeStore) -> Project:
    """Create (or return) the canonical Workspace/Project fixtures are filed in.

    Both fixture Runs and the #795 product proof share this Workspace/Project
    ontology: the same Workspace id, the same Project tree, resolved through
    the canonical scope store — never invented per-fixture.
    """
    root = await project_store.create_root(PACK_FIXTURE_WORKSPACE_ID)
    for child in await project_store.list_children(root.project_id):
        if child.name == PACK_FIXTURES_PROJECT_NAME:
            return child
    return await project_store.create(
        workspace_id=PACK_FIXTURE_WORKSPACE_ID,
        parent_project_id=root.project_id,
        name=PACK_FIXTURES_PROJECT_NAME,
    )


def _provenance(
    *,
    pack: str,
    catalog: dict[str, Any],
    goal_id: str,
    goal_revision: int,
    rubric_id: str,
    rubric_revision: int,
    redirect: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        PACK_FIXTURE_PROVENANCE_KEY: pack,
        "pack": pack,
        "catalog": dict(catalog),
        "goal_id": goal_id,
        "goal_revision": goal_revision,
        "rubric_id": rubric_id,
        "rubric_revision": rubric_revision,
    }
    if redirect is not None:
        provenance["redirect"] = redirect
    return provenance


def _eval_record(
    *,
    rubric_id: str,
    rubric_revision: int,
    verdict: str,
    dimensions: list[dict[str, Any]],
    note: str,
) -> dict[str, Any]:
    """One eval-on-Run record in the shape #792's store is expected to own."""
    return {
        "rubric_id": rubric_id,
        "rubric_revision": rubric_revision,
        "verdict": verdict,
        "dimensions": dimensions,
        "note": note,
    }


async def _run_through(
    run_store: RunStore,
    run_id: str,
    *targets: RunStatus,
) -> None:
    """Walk a Run along its legal lifecycle path, one transition at a time."""
    for target in targets:
        await run_store.transition_run(run_id, target)


async def _complete_node(
    run_store: RunStore,
    run_id: str,
    node_id: str,
    *,
    attempt_results: list[tuple[Any | None, str | None]],
    final_result: Any,
) -> str:
    """Create one NodeRun and walk it through its Attempts to COMPLETED.

    ``attempt_results`` is the ordered Attempt history: each entry is the
    evidence/result recorded when that Attempt terminalized and the error text
    for a failed one (``None`` marks a completed Attempt). The last entry's
    Attempt must be completed; its evidence is accepted as the NodeRun outcome.
    """
    node_run = await run_store.create_node_run(run_id, node_id=node_id)
    await run_store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await run_store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    for result, error in attempt_results:
        attempt = await run_store.create_attempt(node_run.node_run_id)
        await run_store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
        if error is None:
            attempt = await run_store.transition_attempt(
                attempt.attempt_id, AttemptStatus.COMPLETED, result=result
            )
        else:
            await run_store.transition_attempt(
                attempt.attempt_id, AttemptStatus.FAILED, result=result, error=error
            )
    final_attempt = (await run_store.list_attempts(node_run.node_run_id))[-1]
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(final_attempt),
        result=final_result,
    )
    await run_store.transition_node_run(
        node_run.node_run_id,
        RunStatus.COMPLETED,
        result=final_result,
        accepted_outcome=outcome,
    )
    return node_run.node_run_id


async def seed_book_fixture(
    run_store: RunStore,
    project_store: ProjectScopeStore,
) -> PackFixtureSeed:
    """Seed the accepted book fixture: two wave-1 rejects, refine, accept.

    Wave 1 explores two theses the judge rejects (conventional plot with a
    moral ending; an almost-wordless flip that the read-aloud audience cannot
    use). A redirect-rubric moves the rubric from revision 1 to 2 between the
    waves. Wave 2 composes the winning ``BookPages`` artifact; its first
    Attempt fails eval (the fear is not yet contained) and its refined second
    Attempt is accepted. The fence node accepts, and the Run completes.
    """
    project = await ensure_pack_fixture_project(project_store)
    graph = _book_graph(project)
    run = await run_store.create_run(
        graph,
        provenance=_provenance(
            pack=BOOK_PACK,
            catalog=BOOK_CATALOG,
            goal_id=BOOK_GOAL_ID,
            goal_revision=2,
            rubric_id=BOOK_RUBRIC_ID,
            rubric_revision=2,
            redirect={
                "kind": "redirect-rubric",
                "from_revision": 1,
                "to_revision": 2,
                "brief": (
                    "After wave 1: contain the fear to the dark-hallway spread, "
                    "state the rule through the object (never as a moral), end "
                    "on the object. Historical attempts keep rubric revision 1."
                ),
            },
        ),
        initial_status=RunStatus.QUEUED,
    )
    await _run_through(run_store, run.run_id, RunStatus.RUNNING)

    # Wave 1, thesis one: conventional plot — rejected, rubric rev 1.
    conventional = await _complete_node(
        run_store,
        run.run_id,
        BOOK_WAVE1_THESIS_CONVENTIONAL,
        attempt_results=[
            (
                {
                    "artifact_kind": "ThesisDraft",
                    "thesis": {
                        "title": "The Lost Sock's Big Journey",
                        "shape": "conventional quest plot: a lost sock tours the "
                        "house, polite helpers appear on every spread, and the "
                        "lost sock finds its twin",
                        "ending": "moral stated outright: friends help friends",
                    },
                    "eval_record": _eval_record(
                        rubric_id=BOOK_RUBRIC_ID,
                        rubric_revision=1,
                        verdict="rejected",
                        dimensions=[
                            {
                                "dimension": "rule_not_moral",
                                "score": 1,
                                "verdict": "fail",
                                "note": "ending is a spoken moral, which the goal forbids",
                            },
                            {
                                "dimension": "contained_fear",
                                "score": 2,
                                "verdict": "fail",
                                "note": "no fear at all: nothing is ever at stake",
                            },
                            {
                                "dimension": "audience_fit",
                                "score": 3,
                                "verdict": "pass",
                                "note": "sentence lengths suit a 4-7 read-aloud",
                            },
                        ],
                        note="conventional plot; reject",
                    ),
                },
                None,
            ),
        ],
        final_result={
            "artifact_kind": "ThesisDraft",
            "disposition": "rejected",
            "eval_record": _eval_record(
                rubric_id=BOOK_RUBRIC_ID,
                rubric_revision=1,
                verdict="rejected",
                dimensions=[],
                note="conventional plot with a moral ending; rejected at wave 1",
            ),
        },
    )

    # Wave 1, thesis two: almost-wordless — rejected, rubric rev 1.
    wordless = await _complete_node(
        run_store,
        run.run_id,
        BOOK_WAVE1_THESIS_WORDLESS,
        attempt_results=[
            (
                {
                    "artifact_kind": "ThesisDraft",
                    "thesis": {
                        "title": "Dark Hallway, Twelve Flips",
                        "shape": "almost-wordless: the fear lives entirely in the "
                        "pictures; text is a single recurring word per spread",
                        "ending": "the hallway light clicks on by itself",
                    },
                    "eval_record": _eval_record(
                        rubric_id=BOOK_RUBRIC_ID,
                        rubric_revision=1,
                        verdict="rejected",
                        dimensions=[
                            {
                                "dimension": "audience_fit",
                                "score": 1,
                                "verdict": "fail",
                                "note": "a read-aloud for 4-7 needs read-aloud text; "
                                "an adult reader has almost nothing to read",
                            },
                            {
                                "dimension": "print_survivable",
                                "score": 2,
                                "verdict": "fail",
                                "note": "meaning collapses without full-bleed art, "
                                "which two-spot print and honest missing art (#768) "
                                "cannot carry",
                            },
                        ],
                        note="almost-wordless; reject",
                    ),
                },
                None,
            ),
        ],
        final_result={
            "artifact_kind": "ThesisDraft",
            "disposition": "rejected",
            "eval_record": _eval_record(
                rubric_id=BOOK_RUBRIC_ID,
                rubric_revision=1,
                verdict="rejected",
                dimensions=[],
                note="almost-wordless flip; rejected at wave 1",
            ),
        },
    )

    # Redirect recorded in provenance sits between the waves; wave 2 runs
    # against rubric revision 2.
    winner = await _complete_node(
        run_store,
        run.run_id,
        BOOK_WAVE2_WINNER,
        attempt_results=[
            # Attempt 1: the planted earlier failure — the fear is not yet
            # contained (it leaks across the final third). Still queryable.
            (
                {
                    "artifact_kind": "BookPages",
                    "artifact": {"title": "The Small Brass Ship", "spreads": []},
                    "eval_record": _eval_record(
                        rubric_id=BOOK_RUBRIC_ID,
                        rubric_revision=2,
                        verdict="rejected",
                        dimensions=[
                            {
                                "dimension": "contained_fear",
                                "score": 2,
                                "verdict": "fail",
                                "note": "fear spreads across the last third instead "
                                "of staying in the hallway spread",
                            },
                        ],
                        note="refine: pull the fear back into one spread",
                    ),
                },
                "eval rejected: contained_fear below bar at rubric revision 2",
            ),
            # Attempt 2: the refined winner, accepted at rubric revision 2.
            (
                {
                    "artifact_kind": "BookPages",
                    "artifact": _book_pages_artifact(),
                    "eval_record": _eval_record(
                        rubric_id=BOOK_RUBRIC_ID,
                        rubric_revision=2,
                        verdict="accepted",
                        dimensions=[
                            {
                                "dimension": "contained_fear",
                                "score": 5,
                                "verdict": "pass",
                                "note": "the fear lives in the hallway spread and "
                                "its one page-turn",
                            },
                            {
                                "dimension": "rule_not_moral",
                                "score": 5,
                                "verdict": "pass",
                                "note": "the rule is the door left open a hand's "
                                "width, shown by the object, never spoken as a "
                                "lesson",
                            },
                            {
                                "dimension": "object_ending",
                                "score": 5,
                                "verdict": "pass",
                                "note": "ends on the brass ship catching porch light",
                            },
                            {
                                "dimension": "print_survivable",
                                "score": 4,
                                "verdict": "pass",
                                "note": "night spreads hold in spot black plus one spot color",
                            },
                            {
                                "dimension": "audience_fit",
                                "score": 5,
                                "verdict": "pass",
                                "note": "short read-aloud sentences; an adult "
                                "reader has a part on every spread",
                            },
                        ],
                        note="refined spread plan accepted",
                    ),
                },
                None,
            ),
        ],
        final_result={
            "artifact_kind": "BookPages",
            "artifact": _book_pages_artifact(),
            "disposition": "accepted",
        },
    )

    fence = await _complete_node(
        run_store,
        run.run_id,
        FENCE_REVIEW_NODE,
        attempt_results=[
            (
                {
                    "fence_decision": {
                        "decision": "accept",
                        "rubric_revision": 2,
                        "artifact_kind": "BookPages",
                        "note": "accepted after refine: wave-2 attempt 2 is the "
                        "accepted Attempt; attempt 1 stays on the record",
                    },
                },
                None,
            ),
        ],
        final_result={
            "fence_decision": {
                "decision": "accept",
                "rubric_revision": 2,
                "artifact_kind": "BookPages",
            },
        },
    )

    await run_store.transition_run(
        run.run_id,
        RunStatus.COMPLETED,
        result={
            "artifact_kind": "BookPages",
            "artifact": _book_pages_artifact(),
            "fence_decision": "accept",
            "rubric_revision": 2,
        },
    )
    return PackFixtureSeed(
        pack=BOOK_PACK,
        run_id=run.run_id,
        workspace_id=PACK_FIXTURE_WORKSPACE_ID,
        project_id=project.project_id,
        graph_id=BOOK_GRAPH_ID,
        node_run_ids={
            "wave1_thesis_conventional": conventional,
            "wave1_thesis_wordless": wordless,
            "wave2_winner": winner,
            "fence": fence,
        },
    )


def _book_pages_artifact() -> dict[str, Any]:
    """The winning ``BookPages`` artifact: 16 spreads, each with a turn note."""
    spreads: list[dict[str, Any]] = []
    for index in range(1, 17):
        spreads.append(
            {
                "spread": index,
                "turn": _book_turn_note(index),
            }
        )
    return {
        "title": "The Small Brass Ship",
        "pages": 32,
        "format": "16 spreads",
        "spot_colors": 2,
        "spreads": spreads,
    }


def _book_turn_note(spread: int) -> str:
    """Original per-spread `turn` note: what the page-turn does to the reader."""
    notes = {
        1: "turn from bedtime goodnight into the hallway — the door is open a "
        "hand's width and nobody says why",
        2: "turn from the hall's long dark into the child's room — the night "
        "is already there, waiting",
        3: "turn from the wide dark page into a small pale shape on the windowsill: the brass ship",
        4: "turn before the child can touch it — the ship is warm",
        5: "turn from the warm ship into the first creak of the hallway",
        6: "turn mid-creak, so the reader turns the sound too",
        7: "turn from the hallway's dark to the ship's tiny porthole: one grain of light",
        8: "turn from the porthole out the window — porch light across the street, same color",
        9: "turn from the porch light to the child holding the ship at the bedroom door",
        10: "turn from the door (open a hand's width) into the hallway again, one step in",
        11: "turn before the second step — the longest dark in the book",
        12: "turn out of the dark onto the hallway light switch, small and reachable",
        13: "turn from the switch to the child's hand, not yet on it",
        14: "turn from the lit hallway back to the windowsill: the ship holding its grain of light",
        15: "turn from the ship to the door again — still a hand's width, still open, on purpose",
        16: "turn from the door to the windowsill: porch light and porthole "
        "light in one spread, and the child asleep. The rule stays with the "
        "object; nobody says it",
    }
    return notes[spread]


def _book_graph(project: Project) -> Graph:
    return Graph(
        graph_id=BOOK_GRAPH_ID,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        name="Book pack: picture-book read-aloud v1",
        description=(
            "M7-A13 book fixture graph. Catalog: Picture-book read-aloud v1. "
            "Wave 1 explores theses, wave 2 composes BookPages, then the fence "
            "reviews. Definition snapshot for inspection — the pack node kinds "
            "are catalog entries, not registered executors."
        ),
        nodes=[
            Node(
                node_id=BOOK_WAVE1_THESIS_CONVENTIONAL,
                node_type="book.explore_thesis",
                name="Wave 1 thesis: conventional plot",
            ),
            Node(
                node_id=BOOK_WAVE1_THESIS_WORDLESS,
                node_type="book.explore_thesis",
                name="Wave 1 thesis: almost-wordless",
            ),
            Node(
                node_id=BOOK_WAVE2_WINNER,
                node_type="book.compose_book_pages",
                name="Wave 2: compose BookPages",
            ),
            Node(
                node_id=FENCE_REVIEW_NODE,
                node_type="fence.review",
                name="Fence: review and accept",
            ),
        ],
        edges=[
            Edge(from_node=BOOK_WAVE1_THESIS_CONVENTIONAL, to_node=BOOK_WAVE2_WINNER),
            Edge(from_node=BOOK_WAVE1_THESIS_WORDLESS, to_node=BOOK_WAVE2_WINNER),
            Edge(from_node=BOOK_WAVE2_WINNER, to_node=FENCE_REVIEW_NODE),
        ],
        metadata={"pack": BOOK_PACK, "catalog": BOOK_CATALOG["catalog_id"]},
    )


async def seed_game_fixture(
    run_store: RunStore,
    project_store: ProjectScopeStore,
) -> PackFixtureSeed:
    """Seed the parked game fixture: a scored thesis with a failing dimension.

    The explore node scores one thesis against Session-feel heuristics v1;
    ``taught_by_play`` fails (the draft teaches by text cards instead of
    discovery). The fence parks instead of accepting: the Run and its fence
    NodeRun go WAITING, and resume is the canonical WAITING -> RUNNING move on
    the same identities.
    """
    project = await ensure_pack_fixture_project(project_store)
    graph = _game_graph(project)
    run = await run_store.create_run(
        graph,
        provenance=_provenance(
            pack=GAME_PACK,
            catalog=GAME_CATALOG,
            goal_id=GAME_GOAL_ID,
            goal_revision=1,
            rubric_id=GAME_RUBRIC_ID,
            rubric_revision=1,
        ),
        initial_status=RunStatus.QUEUED,
    )
    await _run_through(run_store, run.run_id, RunStatus.RUNNING)

    thesis = await _complete_node(
        run_store,
        run.run_id,
        GAME_EXPLORE_THESIS,
        attempt_results=[
            (
                {
                    "artifact_kind": "ThesisDraft",
                    "thesis": {
                        "title": "Lantern Corner",
                        "verb": "tip",
                        "shape": "one-session toy: tip your lantern to pour "
                        "light into the shed's dark corners before the wick "
                        "gives out",
                        "failure": "a corner stays dim; nothing breaks, nothing "
                        "scolds, the lantern simply gives what it has",
                        "not_a_combat_loop": True,
                    },
                    "eval_record": _eval_record(
                        rubric_id=GAME_RUBRIC_ID,
                        rubric_revision=1,
                        verdict="rejected",
                        dimensions=[
                            {
                                "dimension": "readable_verb",
                                "score": 5,
                                "verdict": "pass",
                                "note": "tip is one word, one motion",
                            },
                            {
                                "dimension": "one_session",
                                "score": 4,
                                "verdict": "pass",
                                "note": "a wick that runs out is a clock a child can feel",
                            },
                            {
                                "dimension": "failure_without_spite",
                                "score": 5,
                                "verdict": "pass",
                                "note": "dim corners wait; nothing is destroyed",
                            },
                            {
                                "dimension": "taught_by_play",
                                "score": 2,
                                "verdict": "fail",
                                "note": "current draft teaches pouring rules on "
                                "text cards; play itself never teaches the tip",
                            },
                            {
                                "dimension": "session_shape",
                                "score": 3,
                                "verdict": "pass",
                                "note": "one shed, four corners, ten minutes",
                            },
                        ],
                        note="scored thesis: taught_by_play below bar; fence to decide",
                    ),
                },
                None,
            ),
        ],
        final_result={
            "artifact_kind": "ThesisDraft",
            "thesis": {
                "title": "Lantern Corner",
                "verb": "tip",
            },
            "disposition": "scored",
            "eval_record": _eval_record(
                rubric_id=GAME_RUBRIC_ID,
                rubric_revision=1,
                verdict="rejected",
                dimensions=[],
                note="taught_by_play fails; parked at the fence for rework",
            ),
        },
    )

    # The fence parks: the NodeRun goes RUNNING -> WAITING carrying the park
    # decision, and the Run goes WAITING beside it. Non-terminal on purpose.
    fence_node_run = await run_store.create_node_run(run.run_id, node_id=FENCE_REVIEW_NODE)
    await run_store.transition_node_run(fence_node_run.node_run_id, RunStatus.QUEUED)
    await run_store.transition_node_run(fence_node_run.node_run_id, RunStatus.RUNNING)
    await run_store.transition_node_run(
        fence_node_run.node_run_id,
        RunStatus.WAITING,
        result={
            "fence_decision": {
                "decision": "park",
                "reason": "thesis fails taught_by_play at rubric revision 1; "
                "rework belongs to a later session",
                "resumes": GAME_EXPLORE_THESIS,
                "awaits_human": True,
            },
        },
    )
    await run_store.transition_run(run.run_id, RunStatus.WAITING)

    return PackFixtureSeed(
        pack=GAME_PACK,
        run_id=run.run_id,
        workspace_id=PACK_FIXTURE_WORKSPACE_ID,
        project_id=project.project_id,
        graph_id=GAME_GRAPH_ID,
        node_run_ids={
            "explore_thesis": thesis,
            "fence": fence_node_run.node_run_id,
        },
    )


def _game_graph(project: Project) -> Graph:
    return Graph(
        graph_id=GAME_GRAPH_ID,
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        name="Game pack: session-feel heuristics v1",
        description=(
            "M7-A13 game fixture graph. Catalog: Session-feel heuristics v1. "
            "One scored thesis, then a fence that parks. Definition snapshot "
            "for inspection — the pack node kinds are catalog entries, not "
            "registered executors."
        ),
        nodes=[
            Node(
                node_id=GAME_EXPLORE_THESIS,
                node_type="game.explore_thesis",
                name="Thesis: one-session toy",
            ),
            Node(
                node_id=FENCE_REVIEW_NODE,
                node_type="fence.review",
                name="Fence: park or accept",
            ),
        ],
        edges=[
            Edge(from_node=GAME_EXPLORE_THESIS, to_node=FENCE_REVIEW_NODE),
        ],
        metadata={"pack": GAME_PACK, "catalog": GAME_CATALOG["catalog_id"]},
    )
