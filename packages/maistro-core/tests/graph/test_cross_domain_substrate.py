"""Cross-domain substrate tests.

The DAG substrate (Node protocol, registry, durable runs, executor,
Project model) is supposed to be **domain-neutral** — PM Fleet is one
use case riding on top of it, not part of its definition. These tests
prove that by composing DAGs for *non-PM* domains and running them
through the same `canonical durable Graph executor without any PM-specific
hooks.

If a future change accidentally couples the substrate to PM (e.g. a
hardcoded jira-only assumption, a PM-role-only branch, an
agent.yaml-only path), one of these tests will break first.
"""

from __future__ import annotations

import contextlib
from typing import ClassVar

from pydantic import BaseModel

from maistro.graph.durable_runs import (
    InMemoryDurableRunStore,
    RunStatus,
)
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.projects import InMemoryProjectStore

from ._canonical_helpers import run_legacy_dag_fixture as run_durable_dag

# --- Creative-team (canvas_creative) DAG fixtures -------------------------


class _BriefIn(BaseModel):
    campaign_name: str
    audience: str


class _BriefOut(BaseModel):
    title: str
    headline: str


class _CreativeBriefNode(BaseNode):
    """Stand-in for what `llm.summarize` would produce on a real creative-
    brief prompt. We don't hit an LLM here — substrate generality, not the
    LLM call shape, is what we're proving."""

    kind: ClassVar[str] = "test.creative.brief"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _BriefIn
    output_schema: ClassVar[type[BaseModel]] = _BriefOut
    cost_hint: ClassVar[float] = 1.0
    display_name: ClassVar[str] = "Creative: brief"

    async def _execute(self, inputs: _BriefIn, ctx: NodeContext) -> _BriefOut:
        return _BriefOut(
            title=f"{inputs.campaign_name} — {inputs.audience}",
            headline=f"Reach {inputs.audience} with {inputs.campaign_name}",
        )


class _ImagePromptIn(BaseModel):
    title: str
    headline: str


class _ImagePromptOut(BaseModel):
    image_url: str
    prompt: str


class _StubImageGenerateNode(BaseNode):
    """Stand-in for an `image.generate` node — the real Canvas Studio image
    generator (P40-backed) plugs in here in v0.3. The substrate doesn't
    care that this is image-domain instead of text-domain."""

    kind: ClassVar[str] = "test.creative.image_generate"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = _ImagePromptIn
    output_schema: ClassVar[type[BaseModel]] = _ImagePromptOut
    cost_hint: ClassVar[float] = 5.0  # image gen is expensive
    external_io: ClassVar[bool] = True

    async def _execute(self, inputs: _ImagePromptIn, ctx: NodeContext) -> _ImagePromptOut:
        prompt = f"{inputs.title}: {inputs.headline}, cinematic, brand-safe"
        return _ImagePromptOut(
            image_url=f"https://fake-canvas.local/render/{abs(hash(prompt))}",
            prompt=prompt,
        )


# --- Engineering-RFC DAG fixtures -----------------------------------------


class _RfcIn(BaseModel):
    rfc_title: str
    body_markdown: str


class _RfcReviewOut(BaseModel):
    score: float
    concerns: list[str]
    approved: bool


class _StubRfcReviewerNode(BaseNode):
    """Stand-in for a code-review-style node. Same shape as `llm.summarize`
    architecturally; different domain."""

    kind: ClassVar[str] = "test.eng.rfc_review"
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = _RfcIn
    output_schema: ClassVar[type[BaseModel]] = _RfcReviewOut

    async def _execute(self, inputs: _RfcIn, ctx: NodeContext) -> _RfcReviewOut:
        # Deterministic verdict: longer RFCs get higher scores; explicit
        # "BREAKING" gets flagged.
        score = min(10.0, max(1.0, len(inputs.body_markdown) / 80.0))
        concerns = ["breaking change flagged"] if "BREAKING" in inputs.body_markdown else []
        return _RfcReviewOut(score=score, concerns=concerns, approved=score >= 5 and not concerns)


for _cls in (_CreativeBriefNode, _StubImageGenerateNode, _StubRfcReviewerNode):
    # re-registration in same pytest session is fine
    with contextlib.suppress(ValueError):
        register_node(_cls)


def _resolver(node_id: str, dag: dict) -> BaseNode:
    for n in dag.get("nodes", []):
        if str(n.get("id")) == node_id:
            return get_node(n["kind"])()
    raise KeyError(node_id)


# --- Project: use_case is domain-neutral ----------------------------------


async def test_project_supports_arbitrary_use_cases() -> None:
    """Project.use_case is just a string — any frontend can claim a value."""
    store = InMemoryProjectStore()
    pm_proj = await store.create(
        owner_user_id="alice",
        name="ACME Streaming payments",
        profile_markdown="Q3 payments-engine launch",
    )
    # Default is generic; users can flip it.
    assert pm_proj.use_case == "generic"
    pm_proj = await store.update(pm_proj.model_copy(update={"use_case": "pm_fleet"}))
    assert pm_proj.use_case == "pm_fleet"

    art_proj = await store.create(
        owner_user_id="alice",
        name="Halloween Horror Nights 2026 campaign",
        profile_markdown="Brand-safe horror creative; PG-13 ceiling; Universal IP only",
    )
    art_proj = await store.update(art_proj.model_copy(update={"use_case": "canvas_creative"}))
    assert art_proj.use_case == "canvas_creative"

    eng_proj = await store.create(
        owner_user_id="alice",
        name="maistro architecture review",
        profile_markdown="MAISTRO v0.2 → v0.3 architecture RFCs, focus on optimizer + projects",
    )
    eng_proj = await store.update(eng_proj.model_copy(update={"use_case": "engineering_rfc"}))
    assert eng_proj.use_case == "engineering_rfc"

    # All three exist independently for the same user.
    all_alice = await store.list_for_user("alice")
    use_cases = sorted(p.use_case for p in all_alice)
    assert use_cases == ["canvas_creative", "engineering_rfc", "pm_fleet"]


# --- Same executor, three different domains ------------------------------


async def test_creative_team_canvas_dag_runs_through_durable_executor() -> None:
    """Ad-art workflow: campaign brief → image generate → (human approve).
    No PM-specific nodes, no Jira, no Airtable — just the substrate.
    """
    dag = {
        "id": "ad-art-shot-001",
        "name": "HHN 2026 hero shot",
        "nodes": [
            {
                "id": "brief",
                "kind": "test.creative.brief",
                "inputs": {
                    "campaign_name": "HHN 2026",
                    "audience": "thrill-seeking adults 21-35",
                },
            },
            {"id": "img", "kind": "test.creative.image_generate"},
        ],
        "edges": [{"from_node": "brief", "to_node": "img"}],
        "entry_node": "brief",
    }
    store = InMemoryDurableRunStore()
    result = await run_durable_dag(
        dag,
        store=store,
        node_resolver=_resolver,
        user_id="art_director_1",
        project_id="art_proj_1",
    )
    assert result.status == RunStatus.COMPLETED
    by_id = {nr.node_id: nr for nr in result.node_runs}
    # Brief produced the title/headline.
    assert by_id["brief"].result is not None
    assert by_id["brief"].result["title"].startswith("HHN 2026")
    assert "thrill-seeking" in by_id["brief"].result["headline"]
    # Image-gen consumed brief's output and produced a URL + prompt.
    assert by_id["img"].result is not None
    assert by_id["img"].result["image_url"].startswith("https://fake-canvas.local/")
    assert "cinematic" in by_id["img"].result["prompt"]
    # The substrate carried project_id through unchanged.
    assert result.project_id == "art_proj_1"
    assert result.run.actor_principal_id == "art_director_1"


async def test_engineering_rfc_review_dag_runs_through_durable_executor() -> None:
    """RFC review workflow: stub reviewer evaluates an RFC, returns
    structured verdict. Different domain shape (scores + concerns vs.
    image URLs vs. Jira issues) — same executor."""
    dag = {
        "id": "rfc-eval-001",
        "name": "Review the durable-run-state RFC",
        "nodes": [
            {
                "id": "review",
                "kind": "test.eng.rfc_review",
                "inputs": {
                    "rfc_title": "Durable DAG runs",
                    "body_markdown": (
                        "## Goal\nPersist DAG runs across container restarts. " * 10  # ~600 chars
                    ),
                },
            }
        ],
        "edges": [],
        "entry_node": "review",
    }
    store = InMemoryDurableRunStore()
    result = await run_durable_dag(
        dag, store=store, node_resolver=_resolver, project_id="eng_proj_1"
    )
    assert result.status == RunStatus.COMPLETED
    review = result.node_runs[0].result
    assert review is not None
    # Long RFC → high score, no "BREAKING" → approved.
    assert review["score"] >= 5.0
    assert review["approved"] is True
    assert review["concerns"] == []


async def test_engineering_rfc_with_breaking_change_gets_flagged() -> None:
    """Same DAG, different content — the substrate doesn't constrain
    domain logic. The node's _execute decides the verdict."""
    dag = {
        "id": "rfc-eval-breaking",
        "name": "Review a BREAKING RFC",
        "nodes": [
            {
                "id": "review",
                "kind": "test.eng.rfc_review",
                "inputs": {
                    "rfc_title": "Switch to a new graph schema",
                    "body_markdown": "BREAKING: change AgentRole to plain str. " * 30,
                },
            }
        ],
        "edges": [],
        "entry_node": "review",
    }
    store = InMemoryDurableRunStore()
    result = await run_durable_dag(dag, store=store, node_resolver=_resolver)
    assert result.status == RunStatus.COMPLETED
    review = result.node_runs[0].result
    assert review is not None
    assert review["approved"] is False
    assert "breaking change flagged" in review["concerns"]


# --- Cross-domain isolation in the durable store --------------------------


async def test_three_domain_runs_coexist_in_one_store() -> None:
    """Substrate-level proof: a single InMemoryDurableRunStore handles runs
    from three different domains side-by-side without confusion. This is
    what `Project + use_case` enables — one maistro deployment, many fronts.
    """
    store = InMemoryDurableRunStore()

    # PM-style DAG (just brief, treated as a generic transform for this test).
    pm_dag = {
        "id": "pm-trivial",
        "name": "pm",
        "nodes": [
            {
                "id": "n",
                "kind": "test.creative.brief",
                "inputs": {"campaign_name": "QBR", "audience": "leadership"},
            }
        ],
        "edges": [],
        "entry_node": "n",
    }
    # Canvas-style DAG.
    art_dag = {
        "id": "art-trivial",
        "name": "art",
        "nodes": [
            {
                "id": "n",
                "kind": "test.creative.image_generate",
                "inputs": {"title": "Halloween", "headline": "Scary fun"},
            }
        ],
        "edges": [],
        "entry_node": "n",
    }
    # Engineering DAG.
    eng_dag = {
        "id": "eng-trivial",
        "name": "eng",
        "nodes": [
            {
                "id": "n",
                "kind": "test.eng.rfc_review",
                "inputs": {"rfc_title": "Tiny", "body_markdown": "x"},
            }
        ],
        "edges": [],
        "entry_node": "n",
    }

    pm_run = await run_durable_dag(
        pm_dag, store=store, node_resolver=_resolver, project_id="pm_proj_1"
    )
    art_run = await run_durable_dag(
        art_dag, store=store, node_resolver=_resolver, project_id="art_proj_1"
    )
    eng_run = await run_durable_dag(
        eng_dag, store=store, node_resolver=_resolver, project_id="eng_proj_1"
    )

    # All three completed independently.
    for run in (pm_run, art_run, eng_run):
        assert run.status == RunStatus.COMPLETED

    # Each run only appears in its own project's listing.
    pm_listing = await store.list_for_project("pm_proj_1")
    art_listing = await store.list_for_project("art_proj_1")
    eng_listing = await store.list_for_project("eng_proj_1")
    assert [r.run_id for r in pm_listing] == [pm_run.run_id]
    assert [r.run_id for r in art_listing] == [art_run.run_id]
    assert [r.run_id for r in eng_listing] == [eng_run.run_id]


# --- Project resource bindings reflect domain ----------------------------


async def test_creative_project_can_skip_jira_bindings_entirely() -> None:
    """A creative-team project doesn't have to declare Jira/repo bindings
    if those don't apply. Only the fields the use case needs get populated.
    """
    store = InMemoryProjectStore()
    art_proj = await store.create(
        owner_user_id="art_director_1",
        name="HHN 2026 art board",
        profile_markdown="Brand-safe horror; Universal IP only",
    )
    art_proj = await store.update(art_proj.model_copy(update={"use_case": "canvas_creative"}))
    # Artists only care about asset trackers, not Jira projects.
    from maistro.projects import AirtableResourceBinding

    art_proj = await store.update(
        art_proj.model_copy(
            update={
                "airtable_bindings": [
                    AirtableResourceBinding(
                        base_id="appHHN26",
                        base_name="HHN 2026 Asset Board",
                        table_descriptions={
                            "Shots": "Hero shots + B-roll, one row per concept",
                            "Approvals": "Brand + Legal sign-offs",
                        },
                    )
                ]
            }
        )
    )
    assert len(art_proj.jira_bindings) == 0
    assert len(art_proj.repo_bindings) == 0
    assert art_proj.airtable_bindings[0].base_name == "HHN 2026 Asset Board"
    assert "Hero shots" in art_proj.airtable_bindings[0].table_descriptions["Shots"]
