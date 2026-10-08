"""M8-A9 (#889): metamorphic-testing research harness over real seams.

Epic #880 (initiative #879) leaf #889 asked whether metamorphic relations can
test semantic stability where MAIstro has no single exact expected output.
Unlike the sibling M8-C1 harness (``tests/memory/test_m8c1_hybrid_retrieval_
research.py``, deliberately import-free), this leaf's contract is to run
*against the current implementations*, so every relation here is wired to a
real seam:

* **MR-A1 / MR-A2 — retrieval** (`maistro.memory.working.recall`): injecting
  irrelevant log entries must not move the top relevant hits beyond a stated
  tolerance, and a write under a foreign Workspace id must stay invisible to
  another Workspace's recall.
* **MR-B1 / MR-B2 — provider selection** (`maistro.router.selector`): adding
  ineligible providers/models must not change the selected eligible provider,
  and permuting catalogue insertion order must not change the selection
  outside the documented rounding-window tie-break.
* **MR-C1 — Graph identity** (`maistro.graph.dag_validator`): a consistent
  bijection renaming node identifiers must preserve validation semantics.

The reusable pattern this module delivers (research record:
``docs/research/889-metamorphic-testing.md``):

1. a *pure relation oracle* — a function from baseline/transformed observation
   records to a list of concrete violations, with the tolerance written into
   the code, not the prose;
2. a *seam adapter* that produces those observation records from the real
   implementation;
3. *generated cases* (Hypothesis, derandomized for deterministic CI) feeding
   adapter → oracle;
4. *seeded-mutant probes* — deliberate violations fed to each oracle — proving
   the oracle can fail, and measuring false-positive rate (violations on the
   real, unmutated seams) separately from detection power.

No production code is changed by this module. Defects (if any relation ever
reports a violation on a real seam) route to the seam's canonical owner, not
to this harness.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, ClassVar

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from maistro.graph.dag_validator import ValidationReport, validate_dag
from maistro.graph.nodes import BaseNode, NodeContext, get_node, register_node
from maistro.memory.working import (
    InMemoryWorkspaceLogStore,
    ObservationKind,
    WorkingMemoryManager,
    WorkingMemoryRecall,
    WorkingResult,
    WorkspaceLogStore,
    make_result_id,
    observation,
)
from maistro.router.selector import RouterEngine
from maistro.types.config import RoutingConfig
from maistro.types.intent import TIER_ORDER, Intent
from maistro.types.model import ModelConfig, ModelSelection, ProviderConfig

# --------------------------------------------------------------------------
# Disjoint token pools: whole-token disjointness guarantees injected texts can
# never share a >=3-char term with a query, which is what "irrelevant" means
# for this lexical seam.
# --------------------------------------------------------------------------

_RELEVANT_WORDS: tuple[str, ...] = ("deploy", "pipeline", "status", "report", "outage", "rollback")
_IRRELEVANT_WORDS: tuple[str, ...] = ("zebra", "quartz", "xylophone", "plugh", "thistle", "walrus")

_WS_A = "ws-m8a9-a"
_WS_B = "ws-m8a9-b"

#: The retrieval relation's stated tolerance. The seam adds a recency bonus of
#: at most ``0.01 * (position / total)`` to every non-zero-scored entry, so
#: injecting irrelevant entries can shift any relevant hit's score by at most
#: 0.01. Every assertion in MR-A1 is stated against this bound, never against
#: exact scores.
_RANK_TOLERANCE = 0.01 + 1e-9


# --------------------------------------------------------------------------
# The reusable pattern, part 1: verdict records and their contract.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationVerdict:
    """What one relation oracle concluded about one case."""

    relation: str
    target: str
    violations: tuple[str, ...] = ()

    @property
    def held(self) -> bool:
        """Whether the metamorphic relation held for the case."""
        return not self.violations

    @property
    def detected(self) -> bool:
        """Whether the oracle saw a violation (used by mutant probes)."""
        return bool(self.violations)


def assert_held(verdict: RelationVerdict) -> None:
    """Fail with the concrete violations when a relation must hold."""
    assert verdict.held, (
        f"{verdict.relation} violated on {verdict.target}: {list(verdict.violations)}"
    )


def assert_detects(verdict: RelationVerdict) -> None:
    """Fail when a mutant probe escapes the oracle that must catch it."""
    assert verdict.detected, f"{verdict.relation} failed to detect its seeded mutant"


# --------------------------------------------------------------------------
# The reusable pattern, part 2: pure relation oracles. Each takes observation
# records (never live objects), states its tolerance in code, and returns
# concrete violation strings.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedHit:
    """Observation record for one ranked retrieval hit."""

    entry_id: str
    score: float
    matched: tuple[str, ...]


def check_ranking_stability(
    baseline: list[RankedHit],
    transformed: list[RankedHit],
    *,
    tolerance: float,
) -> RelationVerdict:
    """MR-A1 oracle: injection may not move hits beyond ``tolerance``.

    The relation: the transformed run must return the same hits, in the same
    order, with per-hit scores shifted by no more than ``tolerance``. The
    tolerance is the seam's own recency-bonus bound — stated here, not in a
    comment.
    """
    violations: list[str] = []
    if len(baseline) != len(transformed):
        violations.append(f"hit count changed: {len(baseline)} -> {len(transformed)}")
    # Lengths may differ (that is itself a violation, recorded above); the
    # pairwise checks then cover the common prefix only.
    for i, (base, after) in enumerate(zip(baseline, transformed, strict=False)):
        if base.entry_id != after.entry_id:
            violations.append(f"rank {i}: entry {base.entry_id} -> {after.entry_id}")
            continue
        if base.matched != after.matched:
            violations.append(
                f"rank {i} ({base.entry_id}): matched {base.matched} -> {after.matched}"
            )
        drift = abs(base.score - after.score)
        if drift > tolerance:
            violations.append(
                f"rank {i} ({base.entry_id}): score drifted {base.score} -> "
                f"{after.score} (|d|={drift:.6f} > tolerance {tolerance:.6f})"
            )
    return RelationVerdict("MR-A1", "memory.working.recall", tuple(violations))


def check_workspace_isolation(
    baseline_ids: tuple[str, ...],
    transformed_ids: tuple[str, ...],
    foreign_ids: Iterable[str],
) -> RelationVerdict:
    """MR-A2 oracle: writes under a foreign Workspace stay invisible.

    The relation: recall in Workspace A is invariant to writes whose
    workspace_id names a different Workspace — the seam's only isolation
    mechanism — so the transformed run returns exactly the baseline ids.
    """
    foreign = set(foreign_ids)
    violations: list[str] = []
    leaked = [eid for eid in transformed_ids if eid in foreign]
    if leaked:
        violations.append(f"foreign entries leaked into recall: {leaked}")
    if baseline_ids != transformed_ids:
        violations.append(
            f"recall changed without a local write: {baseline_ids} -> {transformed_ids}"
        )
    return RelationVerdict("MR-A2", "memory.working store scoping", tuple(violations))


def check_selection_invariance(
    baseline: ModelSelection, transformed: ModelSelection
) -> RelationVerdict:
    """MR-B1 oracle: ineligible additions may not change the selection.

    The relation: the whole selection — winner, score, reason and candidate
    list — is a function of the eligible set only. Any observable difference
    is a violation; there is no tolerance.
    """
    violations: list[str] = []
    if baseline.model_id != transformed.model_id:
        violations.append(f"winner changed: {baseline.model_id} -> {transformed.model_id}")
    if baseline.score != transformed.score:
        violations.append(f"winner score changed: {baseline.score} -> {transformed.score}")
    if baseline.candidates != transformed.candidates:
        violations.append("candidate list changed under ineligible additions")
    if baseline.reason != transformed.reason:
        violations.append("selection reason changed under ineligible additions")
    return RelationVerdict("MR-B1", "router.selector.select_with_usage", tuple(violations))


def tied_at_max(selection: ModelSelection) -> set[str]:
    """Candidate ids sharing the top rounded score of a selection."""
    if not selection.candidates:
        return set()
    top = max(c.score for c in selection.candidates)
    return {c.model_id for c in selection.candidates if c.score == top}


def check_permutation_tolerance(
    baseline: ModelSelection, permuted: ModelSelection
) -> RelationVerdict:
    """MR-B2 oracle: insertion order decides only inside the rounding window.

    The relation with its tolerance: permuting catalogue insertion order must
    not change the winner *unless* the winner changed to another candidate
    tied at the same rounded score — the seam rounds scores to 4 decimals and
    its sort is stable, so an exact rounded tie is broken by insertion order
    by construction (documented in the research record and routed to the
    router owner). Outside that window the winner must be identical.
    """
    base_ties = tied_at_max(baseline)
    perm_ties = tied_at_max(permuted)
    violations: list[str] = []
    if base_ties != perm_ties:
        violations.append(
            f"tied-at-max set changed under permutation: {sorted(base_ties)} -> {sorted(perm_ties)}"
        )
    if permuted.model_id not in base_ties:
        violations.append(
            f"winner moved outside the rounding-window tie set: {baseline.model_id} -> "
            f"{permuted.model_id} (tied set {sorted(base_ties)})"
        )
    base_multiset = sorted((c.model_id, c.score) for c in baseline.candidates)
    perm_multiset = sorted((c.model_id, c.score) for c in permuted.candidates)
    if base_multiset != perm_multiset:
        violations.append("candidate (model_id, score) multiset changed under permutation")
    return RelationVerdict("MR-B2", "router.selector.select_with_usage", tuple(violations))


# --------------------------------------------------------------------------
# The reusable pattern, part 2 (cont.): the Graph rename relation.
# --------------------------------------------------------------------------


def rename_dag(dag: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Apply a node-id bijection everywhere the validator can see one."""
    return {
        "nodes": [
            {**spec, "id": mapping.get(str(spec.get("id")), str(spec.get("id")))}
            for spec in dag.get("nodes", [])
        ],
        "edges": [
            {
                **edge,
                "from_node": mapping.get(str(edge.get("from_node")), str(edge.get("from_node"))),
                "to_node": mapping.get(str(edge.get("to_node")), str(edge.get("to_node"))),
            }
            for edge in dag.get("edges", [])
        ],
        "entry_node": mapping.get(str(dag.get("entry_node")), str(dag.get("entry_node"))),
    }


def _map_message(message: str, mapping: dict[str, str]) -> str:
    """Rewrite every old id inside a validator message to its new id.

    Word-boundary substitution (longest first) so ``mid`` never eats ``mid_2``.
    """
    mapped = message
    for old in sorted(mapping, key=len, reverse=True):
        mapped = re.sub(rf"\b{re.escape(old)}\b", mapping[old], mapped)
    return mapped


def check_rename_isomorphism(
    baseline: ValidationReport,
    renamed: ValidationReport,
    mapping: dict[str, str],
) -> RelationVerdict:
    """MR-C1 oracle: a consistent rename must preserve validation semantics.

    Findings are equal as multisets of (code, severity, mapped node_id,
    edge_index, field_path, mapped message), with the baseline's rows mapped
    forward into the renamed id space. Messages are id-bearing text, so
    the oracle maps them too — a rename that changed *which* findings fire, or
    where they point, is a semantic change and a violation.
    """

    def records(
        report: ValidationReport, live_mapping: dict[str, str] | None
    ) -> list[tuple[str, ...]]:
        rows: list[tuple[str, ...]] = []
        for f in report.findings:
            node = f.node_id
            if live_mapping is not None and node is not None:
                node = live_mapping.get(node, node)
            message = f.message if live_mapping is None else _map_message(f.message, live_mapping)
            rows.append(
                (f.code, f.severity, str(node), str(f.edge_index), str(f.field_path), message)
            )
        return sorted(rows)

    base_rows = records(baseline, mapping)
    renamed_rows = records(renamed, None)
    violations: list[str] = []
    if base_rows != renamed_rows:
        only_base = [r for r in base_rows if r not in renamed_rows]
        only_new = [r for r in renamed_rows if r not in base_rows]
        violations.append(f"validation findings differ: lost={only_base} gained={only_new}")
    return RelationVerdict("MR-C1", "graph.dag_validator", tuple(violations))


def kind_labeled_shape(dag: dict[str, Any]) -> tuple[Any, ...]:
    """The rename-invariant structural fingerprint of a DAG.

    Node kind multiset, edge kind-pair multiset and entry kind — everything
    that survives a bijection on ids and nothing that depends on the ids
    themselves.
    """
    kind_of = {str(spec.get("id")): str(spec.get("kind")) for spec in dag.get("nodes", [])}
    node_kinds = tuple(sorted(kind_of.values()))
    edge_pairs = tuple(
        sorted(
            (kind_of.get(str(e.get("from_node")), "?"), kind_of.get(str(e.get("to_node")), "?"))
            for e in dag.get("edges", [])
        )
    )
    entry_kind = kind_of.get(str(dag.get("entry_node")), "?")
    return (node_kinds, edge_pairs, entry_kind)


# --------------------------------------------------------------------------
# Seam adapters: retrieval.
# --------------------------------------------------------------------------


async def seed_retrieval(
    store: WorkspaceLogStore,
    workspace_id: str,
    texts: list[str],
    *,
    cycle: int = 1,
    kind: ObservationKind = ObservationKind.OBSERVATION,
) -> list[str]:
    """Append one entry per text; return the entry ids in append order.

    Direct-store seeding is only valid *before* the first recall of a
    projection (hydration reads the store); post-hydration writes must go
    through ``WorkingMemoryManager.observe``, which keeps the hot projection
    coherent. Each caller below uses the path its scenario needs.
    """
    ids: list[str] = []
    for text in texts:
        entry = await store.append(
            observation(workspace_id=workspace_id, cycle=cycle, text=text, kind=kind)
        )
        ids.append(entry.entry_id)
    return ids


async def recall_ranked(
    manager: WorkingMemoryManager,
    recall: WorkingMemoryRecall,
    workspace_id: str,
    query: str,
    *,
    limit: int = 5,
) -> list[RankedHit]:
    """Run the real recall seam and record observation-only hit records."""
    hits = await recall.recall(workspace_id, query, limit=limit)
    return [
        RankedHit(entry_id=hit.entry.entry_id, score=hit.score, matched=hit.matched) for hit in hits
    ]


@dataclass
class RetrievalCase:
    """One generated MR-A1 case, with its records filled in when it runs."""

    query: str
    relevant: list[str]
    injections: list[str]
    injected_ids: tuple[str, ...] = ()
    baseline_hits: list[RankedHit] = field(default_factory=list)
    after_hits: list[RankedHit] = field(default_factory=list)


async def run_mr_a1_case(case: RetrievalCase, *, limit: int = 5) -> RelationVerdict:
    """Run one MR-A1 case against the real retrieval seam and judge it.

    Every write goes through ``manager.observe`` — the production write path —
    so the injected entries really reach the hot projection the recall reads.
    """
    manager = WorkingMemoryManager(InMemoryWorkspaceLogStore())
    recall = WorkingMemoryRecall(manager, manager.store)
    for text in case.relevant:
        await manager.observe(_WS_A, cycle=1, text=text)
    case.baseline_hits = await recall_ranked(manager, recall, _WS_A, case.query, limit=limit)
    injected: list[str] = []
    for text in case.injections:
        stored = await manager.observe(_WS_A, cycle=2, text=text)
        injected.append(stored.entry_id)
    case.injected_ids = tuple(injected)

    case.after_hits = await recall_ranked(manager, recall, _WS_A, case.query, limit=limit)
    verdict = check_ranking_stability(
        case.baseline_hits, case.after_hits, tolerance=_RANK_TOLERANCE
    )

    # The injections are irrelevant by construction: none may rank at all.
    ranked_ids = {hit.entry_id for hit in case.after_hits}
    leaked = [eid for eid in case.injected_ids if eid in ranked_ids]
    if leaked:
        violations = (*verdict.violations, f"injected entries ranked: {leaked}")
        return RelationVerdict(verdict.relation, verdict.target, violations)
    return verdict


def run_mr_a1_case_sync(case: RetrievalCase, *, limit: int = 5) -> RelationVerdict:
    """Synchronous wrapper for the async case runner (Hypothesis-friendly)."""
    return asyncio.run(run_mr_a1_case(case, limit=limit))


# --------------------------------------------------------------------------
# Seam adapters: provider selection.
# --------------------------------------------------------------------------


def base_catalog(
    quality_a: float, quality_b: float
) -> tuple[Intent, dict[str, ModelConfig], dict[str, ProviderConfig], dict[str, float]]:
    """A minimal all-eligible catalogue: two providers, one model each."""
    intent = Intent(task_type="chat", tier="P2", min_tier="small", max_tier="large")
    models = {
        "alpha-model": ModelConfig(
            provider="alpha", tier="small", quality=quality_a, modality="text", strengths=("chat",)
        ),
        "beta-model": ModelConfig(
            provider="beta", tier="small", quality=quality_b, modality="text", strengths=("chat",)
        ),
    }
    providers = {
        "alpha": ProviderConfig(status="active", free_tokens=1_000_000),
        "beta": ProviderConfig(status="active", free_tokens=1_000_000),
    }
    return intent, models, providers, {"alpha": 0.0, "beta": 0.0}


def ineligible_additions(
    *,
    inactive_quality: float,
    wrong_modality_quality: float,
    out_of_band_tier: str,
    burned_quality: float,
    tier_band_top: str | None,
) -> tuple[dict[str, ModelConfig], dict[str, ProviderConfig], dict[str, float]]:
    """One catalogue addition per documented ineligibility axis.

    Every added model would win on quality if the filter let it — that is what
    makes the relation non-vacuous.
    """
    models: dict[str, ModelConfig] = {
        "inactive-model": ModelConfig(
            provider="inactive", tier="small", quality=inactive_quality, modality="text"
        ),
        "image-model": ModelConfig(
            provider="alpha", tier="small", quality=wrong_modality_quality, modality="image_gen"
        ),
        "out-of-band-model": ModelConfig(
            provider="alpha", tier=out_of_band_tier, quality=0.99, modality="text"
        ),
        "burned-model": ModelConfig(
            provider="burned", tier="small", quality=burned_quality, modality="text"
        ),
    }
    providers: dict[str, ProviderConfig] = {
        "inactive": ProviderConfig(status="inactive", free_tokens=1_000_000),
        "burned": ProviderConfig(status="active", free_tokens=1_000),
    }
    usage = {"alpha": 0.0, "beta": 0.0, "burned": 1.0}
    if tier_band_top is not None:
        # Keep the baseline intent's band honest: an out-of-band tier must be
        # genuinely outside [small, band_top].
        assert TIER_ORDER[out_of_band_tier] > TIER_ORDER[tier_band_top]
    return models, providers, usage


def selection_of(
    engine: RouterEngine,
    intent: Intent,
    models: dict[str, ModelConfig],
    providers: dict[str, ProviderConfig],
    usage: dict[str, float],
) -> ModelSelection:
    """Run the real selection seam once."""
    return engine.select_with_usage(intent, models, providers, RoutingConfig(), usage)


# --------------------------------------------------------------------------
# Seam adapters: Graph identity — real registered probe node kinds.
# --------------------------------------------------------------------------


class _ProbeValue(BaseModel):
    value: str


class _ProbeOther(BaseModel):
    other: str


@register_node
class ProbeSourceNode(BaseNode[_ProbeValue, _ProbeValue]):
    """Chain head whose output feeds compatible and incompatible sinks."""

    kind: ClassVar[str] = "test.m8a9_probe_source"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ProbeValue
    output_schema: ClassVar[type[BaseModel]] = _ProbeValue

    async def _execute(self, inputs: _ProbeValue, ctx: NodeContext) -> _ProbeValue:
        return _ProbeValue(value=inputs.value)


@register_node
class ProbeSinkNode(BaseNode[_ProbeValue, _ProbeValue]):
    """Compatible downstream kind (required field matches the source output)."""

    kind: ClassVar[str] = "test.m8a9_probe_sink"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ProbeValue
    output_schema: ClassVar[type[BaseModel]] = _ProbeValue

    async def _execute(self, inputs: _ProbeValue, ctx: NodeContext) -> _ProbeValue:
        return _ProbeValue(value=inputs.value)


@register_node
class ProbeDemandingNode(BaseNode[_ProbeOther, _ProbeOther]):
    """Incompatible downstream kind: requires a field the source never emits."""

    kind: ClassVar[str] = "test.m8a9_probe_demanding"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ProbeOther
    output_schema: ClassVar[type[BaseModel]] = _ProbeOther

    async def _execute(self, inputs: _ProbeOther, ctx: NodeContext) -> _ProbeOther:
        return _ProbeOther(other=inputs.other)


_PROBE_IDS = ("src-1", "mid-1", "bad-1")


def probe_dag() -> dict[str, Any]:
    """The fixed probe DAG: one compatible edge, one schema-mismatch edge."""
    return {
        "nodes": [
            {"id": "src-1", "kind": "test.m8a9_probe_source"},
            {"id": "mid-1", "kind": "test.m8a9_probe_sink"},
            {"id": "bad-1", "kind": "test.m8a9_probe_demanding"},
        ],
        "edges": [
            {"from_node": "src-1", "to_node": "mid-1"},
            {"from_node": "src-1", "to_node": "bad-1"},
        ],
        "entry_node": "src-1",
    }


_FRESH_IDS = ("renamed-alpha", "renamed-beta", "renamed-gamma")


def rename_map(ids: Iterable[str], fresh: Iterable[str]) -> dict[str, str]:
    """Zip original ids onto fresh ids — a bijection when lengths match."""
    return dict(zip(sorted(ids), fresh, strict=True))


def partially_renamed_dag(dag: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """A consistent rename with one edge endpoint left on its old identity.

    This is the realistic inconsistent-rename shape: a definition edited in
    two places where one reference was missed. The validator must flag it.
    """
    renamed = rename_dag(dag, mapping)
    renamed["edges"][1]["to_node"] = "bad-1"  # the missed reference
    return renamed


# --------------------------------------------------------------------------
# Seeded mutants: deliberate violations that prove each oracle can fail.
# --------------------------------------------------------------------------


class LeakyWorkspaceStore:
    """The classic missing-WHERE regression shape, as a store wrapper.

    ``list_entries`` forgets the workspace filter and unions in every entry of
    a second workspace. Every other operation delegates unchanged, so the only
    behavioral delta is the leak the MR-A2 oracle must catch.
    """

    def __init__(self, inner: WorkspaceLogStore, leak_from: str) -> None:
        self._inner = inner
        self._leak_from = leak_from

    async def list_entries(self, workspace_id: str, **kwargs: Any) -> list[Any]:
        leaked = await self._inner.list_entries(self._leak_from, **kwargs)
        return await self._inner.list_entries(workspace_id, **kwargs) + leaked

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def shifted_scores(hits: list[RankedHit], delta: float) -> list[RankedHit]:
    """A transformed run whose scores drift by more than any legal tolerance."""
    return [RankedHit(h.entry_id, h.score + delta, h.matched) for h in hits]


def lost_member(hits: list[RankedHit]) -> list[RankedHit]:
    """A transformed run that dropped its last hit."""
    return hits[:-1]


def substituted_selection(selection: ModelSelection) -> ModelSelection:
    """A selection whose winner was silently replaced by the runner-up."""
    if len(selection.candidates) < 2:
        raise ValueError("substitution mutant needs at least two candidates")
    runner_up = selection.candidates[1]
    return ModelSelection(
        model_id=runner_up.model_id,
        litellm_id=runner_up.litellm_id,
        provider=runner_up.provider,
        score=runner_up.score,
        reason=selection.reason,
        candidates=selection.candidates,
    )


def _normalized_hits(hits: list[RankedHit]) -> list[RankedHit]:
    """Relabel uuid-backed entry ids to first-seen position surrogates.

    The seam's entry ids come from ``make_entry_id`` (uuid4), so two runs of
    the *same* deterministic computation never share literal ids. Normalizing
    each id to the rank of its first appearance lets record equality mean
    "same ranking structure, scores, and matched terms" — any real
    nondeterminism in ordering, scoring, or matching still breaks equality.
    """
    surrogates: dict[str, str] = {}
    normalized: list[RankedHit] = []
    for hit in hits:
        surrogate = surrogates.setdefault(hit.entry_id, f"hit-{len(surrogates)}")
        normalized.append(replace(hit, entry_id=surrogate))
    return normalized


# --------------------------------------------------------------------------
# Evidence battery: fixed representative cases over the real seams, timed.
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def run_evidence_battery() -> dict[str, Any]:
    """Run every relation once (plus every mutant probe) and record costs.

    This is the module's evidence record: per-relation case counts, violation
    counts (false positives on the real seams) and wall time (CI cost), plus
    per-mutant detection. Cached — the battery is deterministic, so the tests
    share one run.
    """
    relations: dict[str, dict[str, float]] = {}
    start = time.perf_counter()

    # MR-A1 — fixed representative injection case, run twice for a
    # determinism check (the seams here claim to be deterministic; the
    # relation must produce identical records across runs). Determinism is
    # judged on the *observation records* (normalized, since entry ids are
    # uuid-backed), not on the verdicts: two empty RelationVerdicts are equal
    # even when the runs ranked different hits.
    case_first = RetrievalCase(
        query="deploy pipeline status",
        relevant=["deploy pipeline status report", "deploy outage", "rollback report"],
        injections=["zebra quartz xylophone", "plugh thistle walrus", "zebra plugh"],
    )
    case_second = replace(
        case_first, relevant=list(case_first.relevant), injections=list(case_first.injections)
    )
    t0 = time.perf_counter()
    first = run_mr_a1_case_sync(case_first, limit=3)
    second = run_mr_a1_case_sync(case_second, limit=3)
    relations["MR-A1"] = {
        "cases": 2,
        "violations": len(first.violations) + len(second.violations),
        "seconds": time.perf_counter() - t0,
    }
    determinism = first == second and (
        _normalized_hits(case_first.baseline_hits),
        _normalized_hits(case_first.after_hits),
    ) == (
        _normalized_hits(case_second.baseline_hits),
        _normalized_hits(case_second.after_hits),
    )

    # MR-A2 — fixed foreign-write case over two queries. The projection is
    # dropped before the post-write recall so the store is genuinely re-read.
    t0 = time.perf_counter()
    a2_cases = 0
    a2_violations = 0
    store = InMemoryWorkspaceLogStore()
    manager = WorkingMemoryManager(store)
    recall = WorkingMemoryRecall(manager, store)
    asyncio.run(seed_retrieval(store, _WS_A, case_first.relevant))
    moved = asyncio.run(seed_retrieval(store, _WS_B, [case_first.relevant[0]]))
    for query in ("deploy status", "rollback report"):
        before = asyncio.run(recall_ranked(manager, recall, _WS_A, query))
        asyncio.run(manager.dispose(_WS_A))
        after = asyncio.run(recall_ranked(manager, recall, _WS_A, query))
        verdict = check_workspace_isolation(
            tuple(h.entry_id for h in before), tuple(h.entry_id for h in after), moved
        )
        a2_cases += 1
        a2_violations += len(verdict.violations)
    relations["MR-A2"] = {
        "cases": a2_cases,
        "violations": a2_violations,
        "seconds": time.perf_counter() - t0,
    }

    # MR-B1 — fixed ineligible addition.
    t0 = time.perf_counter()
    engine = RouterEngine()
    intent, models, providers, usage = base_catalog(0.9, 0.7)
    base_selection = selection_of(engine, intent, models, providers, usage)
    extra_models, extra_providers, extra_usage = ineligible_additions(
        inactive_quality=0.99,
        wrong_modality_quality=0.99,
        out_of_band_tier="frontier",
        burned_quality=0.99,
        tier_band_top="large",
    )
    grown_selection = selection_of(
        engine,
        intent,
        {**models, **extra_models},
        {**providers, **extra_providers},
        {**usage, **extra_usage},
    )
    b1 = check_selection_invariance(base_selection, grown_selection)
    relations["MR-B1"] = {
        "cases": 1,
        "violations": len(b1.violations),
        "seconds": time.perf_counter() - t0,
    }

    # MR-B2 — both catalogue orders through the real engine.
    t0 = time.perf_counter()
    permuted_selection = selection_of(
        engine, intent, dict(reversed(list(models.items()))), providers, usage
    )
    b2 = check_permutation_tolerance(base_selection, permuted_selection)
    relations["MR-B2"] = {
        "cases": 1,
        "violations": len(b2.violations),
        "seconds": time.perf_counter() - t0,
    }

    # MR-C1 — fixed probe DAG under a fixed rename.
    t0 = time.perf_counter()
    dag = probe_dag()
    base_report = validate_dag(dag)
    mapping = rename_map(_PROBE_IDS, _FRESH_IDS)
    renamed_report = validate_dag(rename_dag(dag, mapping))
    c1 = check_rename_isomorphism(base_report, renamed_report, mapping)
    relations["MR-C1"] = {
        "cases": 1,
        "violations": len(c1.violations),
        "seconds": time.perf_counter() - t0,
    }

    # Mutant probes — every oracle must detect its seeded violation.
    probes: dict[str, bool] = {}
    probes["ranking-score-drift"] = check_ranking_stability(
        case_first.baseline_hits,
        shifted_scores(case_first.baseline_hits, _RANK_TOLERANCE * 10),
        tolerance=_RANK_TOLERANCE,
    ).detected
    probes["ranking-member-loss"] = check_ranking_stability(
        case_first.baseline_hits,
        lost_member(case_first.baseline_hits),
        tolerance=_RANK_TOLERANCE,
    ).detected

    clean_hits = asyncio.run(recall_ranked(manager, recall, _WS_A, "deploy status"))
    leaky = LeakyWorkspaceStore(store, _WS_B)
    # A fresh manager over the leaky wrapper re-hydrates through it — exactly
    # how the leak would surface in production.
    leaky_manager = WorkingMemoryManager(leaky)  # type: ignore[arg-type]
    leaky_recall = WorkingMemoryRecall(leaky_manager, leaky)  # type: ignore[arg-type]
    leaky_hits = asyncio.run(recall_ranked(leaky_manager, leaky_recall, _WS_A, "deploy status"))
    probes["workspace-scope-leak"] = check_workspace_isolation(
        tuple(h.entry_id for h in clean_hits), tuple(h.entry_id for h in leaky_hits), moved
    ).detected
    probes["selection-substitution"] = check_selection_invariance(
        base_selection, substituted_selection(base_selection)
    ).detected
    probes["out-of-window-winner-flip"] = check_permutation_tolerance(
        base_selection, substituted_selection(base_selection)
    ).detected
    probes["inconsistent-rename"] = check_rename_isomorphism(
        base_report, validate_dag(partially_renamed_dag(dag, mapping)), mapping
    ).detected
    colliding = {"src-1": "renamed-alpha", "mid-1": "renamed-alpha", "bad-1": "renamed-gamma"}
    probes["rename-to-duplicate"] = check_rename_isomorphism(
        base_report, validate_dag(rename_dag(dag, colliding)), colliding
    ).detected

    return {
        "relations": relations,
        "mutant_probes": probes,
        "determinism_across_runs": determinism,
        "total_seconds": time.perf_counter() - start,
    }


# --------------------------------------------------------------------------
# Tests — pattern contract.
# --------------------------------------------------------------------------


def test_verdict_helpers_contract() -> None:
    """held/detected are complement properties of the same violations."""
    clean = RelationVerdict("R", "T", ())
    dirty = RelationVerdict("R", "T", ("x",))
    assert clean.held and not clean.detected
    assert dirty.detected and not dirty.held


def test_relation_summary_accounting() -> None:
    """Every declared relation appears in the battery with positive cost."""
    battery = run_evidence_battery()
    assert set(battery["relations"]) == {"MR-A1", "MR-A2", "MR-B1", "MR-B2", "MR-C1"}
    for name, record in battery["relations"].items():
        assert record["cases"] >= 1, name
        assert record["seconds"] >= 0.0, name
        assert set(record) == {"cases", "violations", "seconds"}, name


def test_harness_targets_real_implementations() -> None:
    """The harness guards its own premise: the seams are the real modules."""
    assert WorkingMemoryRecall.__module__ == "maistro.memory.working.recall"
    assert RouterEngine.__module__ == "maistro.router.selector"
    assert validate_dag.__module__ == "maistro.graph.dag_validator"
    # The probe kinds are registered in the real node registry.
    assert get_node("test.m8a9_probe_source") is ProbeSourceNode
    assert get_node("test.m8a9_probe_sink") is ProbeSinkNode
    assert get_node("test.m8a9_probe_demanding") is ProbeDemandingNode


# --------------------------------------------------------------------------
# Tests — MR-A1: irrelevant-content injection over retrieval.
# --------------------------------------------------------------------------


@settings(max_examples=15, deadline=None, derandomize=True, database=None)
@given(
    query_words=st.lists(st.sampled_from(_RELEVANT_WORDS), min_size=2, max_size=4, unique=True),
    relevant=st.lists(
        st.lists(st.sampled_from(_RELEVANT_WORDS), min_size=2, max_size=3),
        min_size=2,
        max_size=6,
    ),
    injections=st.lists(
        st.lists(st.sampled_from(_IRRELEVANT_WORDS), min_size=2, max_size=3),
        min_size=1,
        max_size=12,
    ),
    limit=st.integers(min_value=1, max_value=5),
)
def test_mr_a1_irrelevant_injection_holds_generated(
    query_words: list[str], relevant: list[list[str]], injections: list[list[str]], limit: int
) -> None:
    """Generated case: injection leaves top hits stable within tolerance."""
    case = RetrievalCase(
        query=" ".join(query_words),
        relevant=[" ".join(words) for words in relevant],
        injections=[" ".join(words) for words in injections],
    )
    assert_held(run_mr_a1_case_sync(case, limit=limit))


def test_mr_a1_injected_entries_never_rank() -> None:
    """Zero-score filtering is the mechanism: injections appear in no rank."""
    case = RetrievalCase(
        query="deploy pipeline status",
        relevant=["deploy pipeline status report", "deploy outage rollback"],
        injections=["zebra quartz", "xylophone plugh", "thistle walrus zebra"],
    )
    assert_held(run_mr_a1_case_sync(case, limit=5))
    ranked_ids = {hit.entry_id for hit in case.after_hits}
    assert not (set(case.injected_ids) & ranked_ids)


def test_mr_a1_lineage_expansion_admits_no_injected_neighbor() -> None:
    """Injections sharing no lineage (digest/result) cannot be expanded in."""
    manager = WorkingMemoryManager(InMemoryWorkspaceLogStore())
    recall = WorkingMemoryRecall(manager, manager.store)
    query = "deploy pipeline"
    seeded = asyncio.run(
        seed_retrieval(manager.store, _WS_A, ["deploy pipeline status", "deploy report"])
    )
    baseline = asyncio.run(recall_ranked(manager, recall, _WS_A, query, limit=5))
    # Both relevant seeds rank in the baseline run.
    assert {hit.entry_id for hit in baseline} >= set(seeded)

    # Injections go through the real write path with their own full results:
    # unique digests, unique result_refs, so no edge exists between them and
    # the relevant set — and ``observe`` applies them to the hot projection.
    async def _inject() -> list[str]:
        injected: list[str] = []
        for i, text in enumerate(("zebra quartz xylophone", "plugh thistle walrus")):
            entry = await manager.observe(
                _WS_A,
                cycle=2,
                text=f"irrelevant tool result {i} recorded",
                source=f"irrelevant-{i}",
                content=text * 3,
            )
            injected.append(entry.entry_id)
        return injected

    injected_ids = asyncio.run(_inject())

    after = asyncio.run(recall_ranked(manager, recall, _WS_A, query, limit=5))
    assert_held(check_ranking_stability(baseline, after, tolerance=_RANK_TOLERANCE))
    ranked_ids = {hit.entry_id for hit in after}
    assert not (set(injected_ids) & ranked_ids)


def test_mr_a1_empty_query_excluded_from_relation_domain() -> None:
    """The empty query returns the whole working set — relation does not apply.

    Recorded as the tolerance boundary it is: the relation's statement needs
    the non-empty-query domain restriction, and this pins the restriction to
    observed behavior rather than prose. The projection is re-hydrated after
    the injection (``dispose`` is the documented coherence boundary for a
    raw-store writer) so the working set genuinely changes.
    """
    store = InMemoryWorkspaceLogStore()
    manager = WorkingMemoryManager(store)
    recall = WorkingMemoryRecall(manager, store)
    asyncio.run(seed_retrieval(store, _WS_A, ["deploy pipeline status"]))
    before = asyncio.run(recall_ranked(manager, recall, _WS_A, "", limit=8))
    injected = asyncio.run(seed_retrieval(store, _WS_A, ["zebra quartz"], cycle=2))
    asyncio.run(manager.dispose(_WS_A))
    after = asyncio.run(recall_ranked(manager, recall, _WS_A, "", limit=8))
    assert injected[0] in {hit.entry_id for hit in after}
    assert injected[0] not in {hit.entry_id for hit in before}


def test_mr_a1_oracle_detects_seeded_score_shift() -> None:
    """A transformed run drifting past tolerance is flagged."""
    hits = [RankedHit("e1", 0.5, ("deploy",)), RankedHit("e2", 0.25, ("deploy",))]
    verdict = check_ranking_stability(
        hits, shifted_scores(hits, _RANK_TOLERANCE * 10), tolerance=_RANK_TOLERANCE
    )
    assert_detects(verdict)


def test_mr_a1_oracle_detects_seeded_member_loss() -> None:
    """A transformed run that loses a hit is flagged."""
    hits = [RankedHit("e1", 0.5, ("deploy",)), RankedHit("e2", 0.25, ("deploy",))]
    verdict = check_ranking_stability(hits, lost_member(hits), tolerance=_RANK_TOLERANCE)
    assert_detects(verdict)


def test_mr_a1_detects_ranking_regression_on_real_seam(monkeypatch: Any) -> None:
    """A realistic ranking regression is caught against the real seam.

    The mutant is a plausible regression — scoring stops rejecting irrelevant
    content — applied to the real ``score_entry`` while the real ``_rank``
    keeps running. Baseline is recorded pre-mutation; the post-mutation run
    must be flagged. This is production-path detection power, not a fixture.
    """
    from maistro.memory.working import recall as recall_module

    case = RetrievalCase(
        query="deploy pipeline status",
        relevant=["deploy pipeline status report", "deploy outage"],
        injections=["zebra quartz xylophone", "plugh thistle walrus"],
    )
    assert_held(run_mr_a1_case_sync(case, limit=5))  # clean run holds

    real_score_entry = recall_module.score_entry

    def mutant_score_entry(entry: Any, query_terms: Any) -> tuple[float, tuple[str, ...]]:
        """Regression: irrelevant tokens suddenly match every query."""
        if any(word in entry.text.split() for word in _IRRELEVANT_WORDS):
            return 0.5, ("deploy",)
        return real_score_entry(entry, query_terms)

    monkeypatch.setattr(recall_module, "score_entry", mutant_score_entry)
    regressed = run_mr_a1_case_sync(case, limit=5)
    monkeypatch.undo()
    assert_detects(regressed)


# --------------------------------------------------------------------------
# Tests — MR-A2: cross-Workspace write invariance.
# --------------------------------------------------------------------------


@settings(max_examples=10, deadline=None, derandomize=True, database=None)
@given(
    query=st.sampled_from(["deploy status", "rollback report", "deploy pipeline outage"]),
    extra=st.lists(st.sampled_from(_RELEVANT_WORDS), min_size=0, max_size=3),
)
def test_mr_a2_cross_workspace_write_invariance_generated(query: str, extra: list[str]) -> None:
    """Generated case: a foreign-Workspace write is invisible to recall.

    Workspace A's projection is dropped after the foreign write so its recall
    re-hydrates through the store — the relation probes the store's scoping,
    not a stale cache.
    """
    store = InMemoryWorkspaceLogStore()
    manager = WorkingMemoryManager(store)
    recall = WorkingMemoryRecall(manager, store)
    seeds = ["deploy pipeline status report", "rollback report"]
    if extra:
        seeds.append(" ".join(extra))
    asyncio.run(seed_retrieval(store, _WS_A, seeds))
    before = asyncio.run(recall_ranked(manager, recall, _WS_A, query))
    moved = asyncio.run(seed_retrieval(store, _WS_B, ["deploy pipeline status"]))
    asyncio.run(manager.dispose(_WS_A))
    after = asyncio.run(recall_ranked(manager, recall, _WS_A, query))
    assert_held(
        check_workspace_isolation(
            tuple(h.entry_id for h in before), tuple(h.entry_id for h in after), moved
        )
    )


def test_mr_a2_result_store_stays_workspace_scoped() -> None:
    """Full results are addressable only inside their own Workspace."""
    store = InMemoryWorkspaceLogStore()
    result = WorkingResult(
        workspace_id=_WS_B,
        result_id=make_result_id(_WS_B, "moved-tool", "payload"),
        source="moved-tool",
        content="payload",
    )
    asyncio.run(store.put_result(result))
    assert asyncio.run(store.get_result(_WS_B, result.result_id)) is not None
    assert asyncio.run(store.get_result(_WS_A, result.result_id)) is None


def test_mr_a2_positive_control_second_workspace_reads_its_write() -> None:
    """The foreign write is real: Workspace B's own recall sees it."""
    store = InMemoryWorkspaceLogStore()
    manager = WorkingMemoryManager(store)
    recall = WorkingMemoryRecall(manager, store)
    moved = asyncio.run(seed_retrieval(store, _WS_B, ["deploy pipeline status"]))
    hits = asyncio.run(recall_ranked(manager, recall, _WS_B, "deploy status"))
    assert moved[0] in {hit.entry_id for hit in hits}


def test_mr_a2_oracle_detects_seeded_scope_leak() -> None:
    """A store that forgets the workspace filter is caught by the oracle."""
    store = InMemoryWorkspaceLogStore()
    manager = WorkingMemoryManager(store)
    recall = WorkingMemoryRecall(manager, store)
    asyncio.run(seed_retrieval(store, _WS_A, ["deploy pipeline status report"]))
    moved = asyncio.run(seed_retrieval(store, _WS_B, ["deploy pipeline status"]))
    clean = asyncio.run(recall_ranked(manager, recall, _WS_A, "deploy status"))
    leaky = LeakyWorkspaceStore(store, _WS_B)
    leaky_manager = WorkingMemoryManager(leaky)  # type: ignore[arg-type]
    leaky_recall = WorkingMemoryRecall(leaky_manager, leaky)  # type: ignore[arg-type]
    leaked = asyncio.run(recall_ranked(leaky_manager, leaky_recall, _WS_A, "deploy status"))
    assert_detects(
        check_workspace_isolation(
            tuple(h.entry_id for h in clean), tuple(h.entry_id for h in leaked), moved
        )
    )


# --------------------------------------------------------------------------
# Tests — MR-B1: ineligible-catalogue additions.
# --------------------------------------------------------------------------


@settings(max_examples=15, deadline=None, derandomize=True, database=None)
@given(
    quality_a=st.floats(min_value=0.5, max_value=0.95),
    quality_b=st.floats(min_value=0.5, max_value=0.95),
    ineligible_quality=st.floats(min_value=0.96, max_value=1.0),
    band_top=st.sampled_from(["large", "medium"]),
)
def test_mr_b1_ineligible_additions_preserve_selection_generated(
    quality_a: float, quality_b: float, ineligible_quality: float, band_top: str
) -> None:
    """Generated case: every ineligibility axis preserves the selection."""
    intent = Intent(task_type="chat", tier="P2", min_tier="small", max_tier=band_top)
    engine = RouterEngine()
    _, models, providers, usage = base_catalog(quality_a, quality_b)
    base = selection_of(engine, intent, models, providers, usage)
    extra_models, extra_providers, extra_usage = ineligible_additions(
        inactive_quality=ineligible_quality,
        wrong_modality_quality=ineligible_quality,
        out_of_band_tier="frontier",
        burned_quality=ineligible_quality,
        tier_band_top=band_top,
    )
    grown = selection_of(
        engine,
        intent,
        {**models, **extra_models},
        {**providers, **extra_providers},
        {**usage, **extra_usage},
    )
    assert_held(check_selection_invariance(base, grown))


def test_mr_b1_every_ineligibility_axis_exercised() -> None:
    """Each added model is really filtered — the relation is not vacuous."""
    from maistro.router.filter import filter_candidates

    extra_models, extra_providers, extra_usage = ineligible_additions(
        inactive_quality=0.99,
        wrong_modality_quality=0.99,
        out_of_band_tier="frontier",
        burned_quality=0.99,
        tier_band_top="large",
    )
    intent = Intent(task_type="chat", tier="P2", min_tier="small", max_tier="large")
    survived = filter_candidates(intent, extra_models, extra_providers, usage_pcts=extra_usage)
    assert survived == [], f"ineligible additions survived the filter: {survived}"


def test_mr_b1_eligible_addition_changes_selection_control() -> None:
    """Control: an *eligible* better model must move the selection."""
    engine = RouterEngine()
    intent, models, providers, usage = base_catalog(0.9, 0.7)
    base = selection_of(engine, intent, models, providers, usage)
    grown = selection_of(
        engine,
        intent,
        {
            **models,
            "gamma-model": ModelConfig(
                provider="beta", tier="small", quality=0.99, modality="text", strengths=("chat",)
            ),
        },
        providers,
        usage,
    )
    assert base.model_id == "alpha-model"
    assert grown.model_id == "gamma-model"
    assert_detects(check_selection_invariance(base, grown))


def test_mr_b1_oracle_detects_seeded_substitution() -> None:
    """A silently substituted winner is flagged."""
    engine = RouterEngine()
    intent, models, providers, usage = base_catalog(0.9, 0.7)
    base = selection_of(engine, intent, models, providers, usage)
    assert_detects(check_selection_invariance(base, substituted_selection(base)))


def test_mr_b1_detects_filter_regression_on_real_seam(monkeypatch: Any) -> None:
    """A realistic filter regression is caught against the real seam.

    The mutant drops the provider-status check — the exact shape of a plausible
    ``filter_candidates`` regression — while the real scoring and ranking keep
    running. The selection must move to the (otherwise winning) inactive
    model, and the oracle must flag it.
    """
    import maistro.router.selector as selector_module

    engine = RouterEngine()
    intent, models, providers, usage = base_catalog(0.9, 0.7)
    base = selection_of(engine, intent, models, providers, usage)
    extra_models, extra_providers, extra_usage = ineligible_additions(
        inactive_quality=1.5,  # above the 0.9*1.15 strength-adjusted baseline
        wrong_modality_quality=0.99,
        out_of_band_tier="frontier",
        burned_quality=0.99,
        tier_band_top="large",
    )

    real_filter = selector_module.filter_candidates

    def mutant_filter(intent_arg: Any, models_arg: Any, providers_arg: Any, **kwargs: Any) -> Any:
        """Regression: inactive providers are no longer excluded."""
        repaired = {
            name: (cfg if cfg.status != "inactive" else replace(cfg, status="active"))
            for name, cfg in providers_arg.items()
        }
        return real_filter(intent_arg, models_arg, repaired, **kwargs)

    monkeypatch.setattr(selector_module, "filter_candidates", mutant_filter)
    grown = selection_of(
        engine,
        intent,
        {**models, **extra_models},
        {**providers, **extra_providers},
        {**usage, **extra_usage},
    )
    monkeypatch.undo()
    assert grown.model_id == "inactive-model", "mutant did not move the winner"
    assert_detects(check_selection_invariance(base, grown))


# --------------------------------------------------------------------------
# Tests — MR-B2: catalogue insertion-order permutation.
# --------------------------------------------------------------------------


@settings(max_examples=25, deadline=None, derandomize=True, database=None)
@given(
    quality=st.lists(st.sampled_from([0.5, 0.6, 0.75, 0.9]), min_size=2, max_size=4),
    order=st.permutations([0, 1, 2, 3]),
    cost_weight=st.sampled_from([0.0, 0.4, 1.0]),
)
def test_mr_b2_permutation_preserves_selection_generated(
    quality: list[float], order: list[int], cost_weight: float
) -> None:
    """Generated case: permutation changes the winner only within ties."""
    engine = RouterEngine()
    names = ["m0", "m1", "m2", "m3"][: len(quality)]
    base_models = {
        name: ModelConfig(provider="alpha", tier="small", quality=q, modality="text")
        for name, q in zip(names, quality, strict=True)
    }
    providers = {"alpha": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(task_type="chat", tier="P2")
    config = RoutingConfig(cost_weight=cost_weight)

    base = engine.select_with_usage(intent, base_models, providers, config, {})
    # The drawn permutation is over 4 positions; its first len(names) values,
    # ranked among themselves, give a genuine permutation of the names.
    prefix = order[: len(names)]
    ranked = sorted(range(len(prefix)), key=lambda k: prefix[k])
    permuted_models = {names[k]: base_models[names[k]] for k in ranked}
    permuted = engine.select_with_usage(intent, permuted_models, providers, config, {})
    assert_held(check_permutation_tolerance(base, permuted))


def test_mr_b2_rounding_window_ties_are_the_documented_tolerance() -> None:
    """Identical candidates tie exactly; insertion order decides, legally.

    This pins the tolerance boundary the oracle encodes: the flip is real and
    observable, the tie set is order-invariant, and the oracle must accept it.
    """
    engine = RouterEngine()
    providers = {"alpha": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(task_type="chat", tier="P2")
    twin_a = ModelConfig(provider="alpha", tier="small", quality=0.9, modality="text")
    twin_b = ModelConfig(provider="alpha", tier="small", quality=0.9, modality="text")

    first = engine.select_with_usage(
        intent, {"twin-a": twin_a, "twin-b": twin_b}, providers, RoutingConfig(), {}
    )
    second = engine.select_with_usage(
        intent, {"twin-b": twin_b, "twin-a": twin_a}, providers, RoutingConfig(), {}
    )
    assert first.model_id == "twin-a"
    assert second.model_id == "twin-b"
    assert tied_at_max(first) == {"twin-a", "twin-b"}
    assert_held(check_permutation_tolerance(first, second))


def test_mr_b2_oracle_detects_out_of_tolerance_winner_flip() -> None:
    """A winner that moves outside the tied set is flagged."""
    engine = RouterEngine()
    intent, models, providers, usage = base_catalog(0.9, 0.7)
    base = selection_of(engine, intent, models, providers, usage)
    assert len(tied_at_max(base)) == 1, "control expects a unique winner"
    assert_detects(check_permutation_tolerance(base, substituted_selection(base)))


def test_mr_b2_fallback_exact_tie_order_sensitivity_documented() -> None:
    """The fallback path breaks exact quality ties by insertion order.

    Recorded finding, not a failure: ``RouterEngine._fallback`` keeps the
    first maximum it sees, so a degraded path with two equal-quality models is
    order-sensitive. The relation explicitly excludes this path (its
    tolerance names the scored-candidate window, not the fallback), and the
    sensitivity is routed to the router owner in the research record.
    """
    models = {
        "first": ModelConfig(provider="alpha", tier="small", quality=0.9, modality="image_gen"),
        "second": ModelConfig(provider="alpha", tier="small", quality=0.9, modality="image_gen"),
    }
    providers = {"alpha": ProviderConfig(status="active", free_tokens=1_000_000)}
    engine = RouterEngine()
    forward = engine.select(Intent(task_type="chat"), models, providers, RoutingConfig())
    backward = engine.select(
        Intent(task_type="chat"),
        {"second": models["second"], "first": models["first"]},
        providers,
        RoutingConfig(),
    )
    assert forward.model_id == "first"
    assert backward.model_id == "second"


def test_mr_b2_candidates_multiset_invariant_under_permutation() -> None:
    """The candidate multiset is order-invariant even when ranking is not."""
    engine = RouterEngine()
    providers = {"alpha": ProviderConfig(status="active", free_tokens=1_000_000)}
    intent = Intent(task_type="chat", tier="P2")
    models = {
        "a": ModelConfig(provider="alpha", tier="small", quality=0.9, modality="text"),
        "b": ModelConfig(provider="alpha", tier="small", quality=0.75, modality="text"),
        "c": ModelConfig(provider="alpha", tier="small", quality=0.6, modality="text"),
    }
    forward = engine.select_with_usage(intent, models, providers, RoutingConfig(), {})
    backward = engine.select_with_usage(
        intent, dict(reversed(list(models.items()))), providers, RoutingConfig(), {}
    )
    assert sorted((c.model_id, c.score) for c in forward.candidates) == sorted(
        (c.model_id, c.score) for c in backward.candidates
    )


# --------------------------------------------------------------------------
# Tests — MR-C1: consistent identifier renaming over the DAG validator.
# --------------------------------------------------------------------------


@settings(max_examples=15, deadline=None, derandomize=True, database=None)
@given(fresh=st.permutations(_FRESH_IDS))
def test_mr_c1_consistent_rename_preserves_validation_generated(fresh: list[str]) -> None:
    """Generated case: any bijection preserves the validator's verdict."""
    dag = probe_dag()
    mapping = rename_map(_PROBE_IDS, fresh)
    renamed = rename_dag(dag, mapping)
    assert_held(check_rename_isomorphism(validate_dag(dag), validate_dag(renamed), mapping))
    assert kind_labeled_shape(dag) == kind_labeled_shape(renamed)


def test_mr_c1_rename_preserves_kind_labeled_structure() -> None:
    """The structural fingerprint is rename-invariant."""
    dag = probe_dag()
    mapping = rename_map(_PROBE_IDS, _FRESH_IDS)
    assert kind_labeled_shape(dag) == kind_labeled_shape(rename_dag(dag, mapping))


def test_mr_c1_schema_findings_survive_rename() -> None:
    """The schema-mismatch finding fires identically under a rename."""
    dag = probe_dag()
    mapping = rename_map(_PROBE_IDS, _FRESH_IDS)
    base_report = validate_dag(dag)
    renamed_report = validate_dag(rename_dag(dag, mapping))
    mismatched = [f for f in base_report.findings if f.code == "schema_mismatch"]
    assert len(mismatched) == 1
    renamed_mismatched = [f for f in renamed_report.findings if f.code == "schema_mismatch"]
    assert len(renamed_mismatched) == 1
    assert renamed_mismatched[0].node_id == mapping[mismatched[0].node_id or ""]
    assert renamed_mismatched[0].field_path == mismatched[0].field_path
    assert_held(check_rename_isomorphism(base_report, renamed_report, mapping))


def test_mr_c1_oracle_detects_inconsistent_rename() -> None:
    """Leaving one edge endpoint on its old identity changes semantics — flagged."""
    dag = probe_dag()
    base_report = validate_dag(dag)
    mapping = rename_map(_PROBE_IDS, _FRESH_IDS)
    renamed_report = validate_dag(partially_renamed_dag(dag, mapping))
    assert any(f.code == "edge_missing_endpoint" for f in renamed_report.findings)
    assert_detects(check_rename_isomorphism(base_report, renamed_report, mapping))


def test_mr_c1_rename_to_duplicate_id_is_flagged() -> None:
    """A rename that maps two ids onto one is not a bijection — flagged."""
    dag = probe_dag()
    base_report = validate_dag(dag)
    colliding = {"src-1": "renamed-alpha", "mid-1": "renamed-alpha", "bad-1": "renamed-gamma"}
    renamed_report = validate_dag(rename_dag(dag, colliding))
    assert any(
        f.code == "missing_node" and "Duplicate" in f.message for f in renamed_report.findings
    )
    assert_detects(check_rename_isomorphism(base_report, renamed_report, colliding))


# --------------------------------------------------------------------------
# Tests — the evidence record itself.
# --------------------------------------------------------------------------


def test_evidence_battery_zero_violations_on_real_seams() -> None:
    """False-positive rate on the unmutated seams: zero across the battery."""
    battery = run_evidence_battery()
    for name, record in battery["relations"].items():
        assert record["violations"] == 0, f"{name} reported violations on the real seam"


def test_evidence_battery_detects_every_seeded_mutant() -> None:
    """Detection power: every seeded mutant is caught by its oracle."""
    battery = run_evidence_battery()
    assert battery["determinism_across_runs"] is True
    expected = {
        "ranking-score-drift",
        "ranking-member-loss",
        "workspace-scope-leak",
        "selection-substitution",
        "out-of-window-winner-flip",
        "inconsistent-rename",
        "rename-to-duplicate",
    }
    assert set(battery["mutant_probes"]) == expected
    for name, detected in battery["mutant_probes"].items():
        assert detected, f"mutant probe {name} escaped its oracle"


def test_evidence_ci_cost_measured_and_bounded() -> None:
    """CI cost is recorded; the battery stays a smoke-cost, not a soak."""
    battery = run_evidence_battery()
    assert battery["total_seconds"] < 120.0, "battery exceeded its smoke-cost bound"
    for name, record in battery["relations"].items():
        per_case = record["seconds"] / record["cases"]
        assert per_case < 5.0, f"{name} per-case cost {per_case:.3f}s is not smoke-cost"
