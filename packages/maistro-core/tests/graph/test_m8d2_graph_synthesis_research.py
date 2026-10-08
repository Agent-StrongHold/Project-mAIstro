"""M8-D2 research harness — automatic canonical Graph synthesis from Goals.

Issue #926 (leaf of epic #903, initiative #879). Hypothesis under study: a
planner can synthesize valid, useful canonical Graphs directly from
Goal/rubric/capability constraints, with fewer manual templates and better
reuse than ad hoc action loops.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #926 experiment demands: candidate planners that
emit Graph *definitions only* (DAGFile dicts, the shape ``validate_dag``
consumes), the canonical legality gate applied to every candidate, a
validator-feedback repair loop, and the issue's measure list — graph
validity, goal success (fidelity), missing/extra nodes against a reference
decomposition, illegal dependencies, repair iterations, planned execution
cost, reuse potential, and human review burden — as deterministic,
hand-checkable arithmetic over a fixture Goal grid.

Relationship to the canonical seams — this harness deliberately reuses the
shipped read-only test seam (M8 guardrail 2) instead of mirroring it, because
the leaf's core measure is validity *against canonical schema/legality*; a
re-implemented validator would grade candidates against a drift-prone copy
(benchmark theater, M8 guardrail 5). It imports exactly four maistro
surfaces, all pure/read-only, pinned by an AST allowlist test:

- ``maistro.graph.dag_validator.validate_dag`` — the canonical legality gate
  (structure, kinds, cycles, per-edge schema compatibility), the same gate a
  saved DAG must pass at ``PUT /v1/dags/{id}`` and again at run time;
- ``maistro.graph.nodes`` — the real capability catalog (``list_kinds`` /
  ``get_node``) with the real input/output schemas planners must respect;
- ``maistro.graph.policies.resolve_max_cycles`` — the real execution-budget
  policy (#1184): a declared cycle budget must cover the candidate's depth;
- ``maistro.graph.seeds.daily_status_seed`` — the one shipped representative
  DAG, used as the manual-template baseline's library entry and as a legality
  sanity oracle.

Nothing here executes. The harness never imports an executor, a Run store,
durable-run machinery, or any other authority surface, never creates a Run,
and never mutates a Goal: generated Graphs are *candidates* for human-gated
admission, never a parallel execution model (the leaf's binding constraint).
Planner "LLM" arms are deterministic scripted stand-ins encoding
characteristic failure modes; they are fixtures for validating the
machinery and must never be quoted as evidence about real models (M8
guardrail 3). The real experiment — provider-backed planners over a
representative Goal corpus with accepted candidates executed through the
normal runtime — is recorded as the next required evidence in
``docs/research/926-graph-synthesis-from-goals.md``.

The experiment record and terminal disposition live in
``docs/research/926-graph-synthesis-from-goals.md``.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from maistro.graph.dag_validator import validate_dag
from maistro.graph.nodes import get_node, list_kinds
from maistro.graph.policies import resolve_max_cycles
from maistro.graph.seeds import daily_status_seed

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-D2 output as
#: authorization. Admission authority remains the canonical DAG registry
#: (validate + register) behind its human gate; execution authority remains
#: the canonical Graph runtime. Generated Graphs are candidates, never a
#: parallel execution model.
ADVISORY_ONLY = True

#: The complete allowlist of maistro surfaces this research module may import.
#: Everything else — especially ``maistro.graph.executor``, ``maistro.runs``,
#: ``maistro.graph.durable_runs``, stores and orchestrators — is forbidden:
#: a synthesis benchmark that can reach an executor could drift into becoming
#: a second execution model, which the leaf forbids outright.
MAISTRO_IMPORT_ALLOWLIST = frozenset(
    {
        "maistro.graph.dag_validator",
        "maistro.graph.nodes",
        "maistro.graph.policies",
        "maistro.graph.seeds",
    }
)

#: Repair-loop budget: how many validator-feedback iterations a planner gets
#: before the candidate is declared unrepairable and refused at admission.
MAX_REPAIR_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Local mirror units — the few derivations the harness owns itself
# ---------------------------------------------------------------------------


def node_fields(kind: str) -> tuple[set[str], set[str]]:
    """(output fields, required input fields) for a catalog kind.

    Mirrors the two ``model_fields`` derivations the canonical validator
    performs (``_fields_of`` / ``_required_fields_of``); the agreement is
    checked against the real gate on every fixture edge, so drift here is
    loud, not silent.
    """
    node_cls = get_node(kind)
    out = set(node_cls.output_schema.model_fields.keys())
    required = {
        name for name, info in node_cls.input_schema.model_fields.items() if info.is_required()
    }
    return out, required


def edge_is_schema_legal(dag: Mapping[str, Any], from_node: str, to_node: str) -> bool:
    """Local form of the canonical rule: B's required inputs must be covered
    by A's output schema or B's own static inputs/config. The real gate
    (``validate_dag``) remains the authority; this exists so planners can
    *build* toward legality and tests can prove the two agree."""
    kind_by_id = {str(n.get("id")): str(n.get("kind")) for n in dag.get("nodes", []) or []}
    if from_node not in kind_by_id or to_node not in kind_by_id:
        return False
    provided, _ = node_fields(kind_by_id[from_node])
    _, required = node_fields(kind_by_id[to_node])
    static: set[str] = set()
    for spec in dag.get("nodes", []) or []:
        if str(spec.get("id")) == to_node:
            static = set((spec.get("inputs") or spec.get("config") or {}).keys())
            break
    return required <= (provided | static)


def dag_depth(dag: Mapping[str, Any]) -> int:
    """Traversal waves the canonical executor would walk: longest node chain.

    The budget contract (#1184) counts waves; a declared ``max_cycles`` below
    the depth fails the Run with the shortfall named, so a synthesizer that
    declares less than its own depth ships a graph that cannot run.
    """
    nodes = [str(n.get("id")) for n in dag.get("nodes", []) or []]
    if not nodes:
        return 0
    adjacency: dict[str, list[str]] = {nid: [] for nid in nodes}
    for edge in dag.get("edges", []) or []:
        fn, tn = str(edge.get("from_node")), str(edge.get("to_node"))
        if fn in adjacency and tn in adjacency:
            adjacency[fn].append(tn)

    longest: dict[str, int] = {}

    def walk(nid: str) -> int:
        if nid in longest:
            return longest[nid]
        longest[nid] = 1  # set before recursing: the graph must be acyclic
        best = 1
        for nxt in adjacency[nid]:
            best = max(best, 1 + walk(nxt))
        longest[nid] = best
        return best

    return max(walk(nid) for nid in nodes)


def budget_covers_depth(dag: Mapping[str, Any]) -> bool:
    """Canonical budget legality: resolved declared ``max_cycles`` >= depth.

    Uses the real policy resolver (``resolve_max_cycles``): an undeclared or
    unreadable budget resolves to ``MIN_DAG_CYCLES``, so a synthesizer that
    declares nothing ships a one-wave budget under a deeper graph.
    """
    return resolve_max_cycles(dag.get("max_cycles")) >= dag_depth(dag)


def candidate_is_legal(dag: Mapping[str, Any]) -> bool:
    """The full canonical legality gate a candidate must pass to be admitted:
    the real validator's schema/structure report AND the real budget policy."""
    if not validate_dag(dict(dag)).is_valid:
        return False
    return budget_covers_depth(dag)


def canonical_form(dag: Mapping[str, Any]) -> str:
    """Canonical JSON of a candidate: byte-identical graphs collide, so reuse
    detection is exact-shape reuse (the strongest reuse claim a synthesizer
    can make) rather than fuzzy similarity."""
    return json.dumps(dag, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Fixture Goals — representative Goals + capability constraints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureGoal:
    """One representative Goal for the synthesis grid.

    ``capability_needs`` is the Goal's ordered capability decomposition (the
    ordered-tuple form a rubric/capability constraint layer would hand a
    planner); ``parameters`` are the Goal-supplied static node inputs
    (binding ids, filters, templates). ``reference_kinds`` is the ground-truth
    decomposition a human would accept — the yardstick for missing/extra
    nodes. A Goal with empty ``reference_kinds`` is by construction not
    faithfully synthesizable (it demands capabilities outside the catalog);
    it participates in the refusal/repair/validity measures only.
    """

    goal_id: str
    statement: str
    capability_needs: tuple[str, ...]
    parameters: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    reference_kinds: tuple[str, ...] = ()
    max_nodes: int = 8

    def __post_init__(self) -> None:
        if not self.goal_id:
            raise ValueError("FixtureGoal.goal_id must be non-empty")
        if not self.statement.strip():
            raise ValueError(f"FixtureGoal {self.goal_id!r}: statement must be non-empty")
        if not self.capability_needs:
            raise ValueError(f"FixtureGoal {self.goal_id!r}: capability_needs must be non-empty")


_DAILY_STATUS_NEEDS = (
    "jira.poll",
    "transform.alias_keys",
    "transform.filter_by_type",
    "transform.format_markdown",
    "dashboard.append_section",
)

_RESEARCH_BRIEF_NEEDS = (
    "jira.poll",
    "transform.filter_by_type",
    "transform.extract_field",
    "transform.format_markdown",
    "dashboard.append_section",
)

_HUMAN_SIGNOFF_NEEDS = (
    "jira.poll",
    "transform.format_markdown",
    "human.review_and_edit",
    "dashboard.append_section",
)

_DAILY_STATUS_PARAMS: Mapping[str, Mapping[str, Any]] = {
    "jira.poll": {"binding_id": "", "jql": "updated >= -24h", "max_results": 20},
    "transform.alias_keys": {"mapping": {"items": "issues"}},
    "transform.filter_by_type": {"types": ["Epic"], "type_path": "issuetype"},
    "transform.format_markdown": {
        "template": "- {key}: {summary}",
        "header": "## Jira Epics updated (last 24h)",
    },
    "dashboard.append_section": {
        "dashboard_id": "daily-status",
        "section_title": "Jira Epics (last 24h)",
    },
}

_RESEARCH_BRIEF_PARAMS: Mapping[str, Mapping[str, Any]] = {
    "jira.poll": {"binding_id": "", "jql": "created >= -7d"},
    "transform.filter_by_type": {"types": ["Story"], "type_path": "issuetype"},
    "transform.extract_field": {"field_path": "summary"},
    "transform.format_markdown": {"template": "- {summary}", "header": "## Weekly brief"},
    "dashboard.append_section": {
        "dashboard_id": "weekly-brief",
        "section_title": "Stories (last 7d)",
    },
}

_HUMAN_SIGNOFF_PARAMS: Mapping[str, Mapping[str, Any]] = {
    "jira.poll": {"binding_id": "", "jql": "updated >= -24h"},
    "transform.format_markdown": {"template": "- {summary}", "header": "## Draft for review"},
    "human.review_and_edit": {"document": "draft: weekly status", "title": "Weekly status"},
    "dashboard.append_section": {
        "dashboard_id": "weekly-status",
        "section_title": "Reviewed status",
    },
}

FIXTURE_GOALS: tuple[FixtureGoal, ...] = (
    FixtureGoal(
        goal_id="daily-status",
        statement=(
            "Poll Jira for issues updated in the last 24h, rename the item key, "
            "filter to Epics, format a markdown section, append it to the "
            "daily-status dashboard."
        ),
        capability_needs=_DAILY_STATUS_NEEDS,
        parameters=_DAILY_STATUS_PARAMS,
        reference_kinds=_DAILY_STATUS_NEEDS,
    ),
    FixtureGoal(
        goal_id="daily-status-refresh",
        statement=(
            "Same daily-status composition again tomorrow: poll Jira, rename, "
            "filter Epics, format, append to the dashboard."
        ),
        capability_needs=_DAILY_STATUS_NEEDS,
        parameters=_DAILY_STATUS_PARAMS,
        reference_kinds=_DAILY_STATUS_NEEDS,
    ),
    FixtureGoal(
        goal_id="research-brief",
        statement=(
            "Poll Jira for stories created this week, filter to Stories, extract "
            "each summary, format a markdown brief, append it to the weekly-brief "
            "dashboard."
        ),
        capability_needs=_RESEARCH_BRIEF_NEEDS,
        parameters=_RESEARCH_BRIEF_PARAMS,
        reference_kinds=_RESEARCH_BRIEF_NEEDS,
    ),
    FixtureGoal(
        goal_id="human-signoff",
        statement=(
            "Poll Jira, format a draft status section, route the draft through "
            "human review, and append the reviewed status to the dashboard."
        ),
        capability_needs=_HUMAN_SIGNOFF_NEEDS,
        parameters=_HUMAN_SIGNOFF_PARAMS,
        reference_kinds=_HUMAN_SIGNOFF_NEEDS,
    ),
    # The unsynthesizable Goal: it demands capabilities the catalog does not
    # have. A planner that cannot say no ships an illegal or unfaithful
    # candidate — the degenerate path the machinery must expose loudly.
    FixtureGoal(
        goal_id="slack-blast",
        statement=("Poll Jira and blast every updated issue to Slack and Teams channels."),
        capability_needs=("jira.poll", "slack.post", "teams.post"),
        parameters={"jira.poll": {"binding_id": "", "jql": "updated >= -1h"}},
        reference_kinds=(),  # no faithful decomposition exists
    ),
)

GOALS_BY_ID: Mapping[str, FixtureGoal] = {g.goal_id: g for g in FIXTURE_GOALS}


def _connect_edge(nodes: list[dict[str, Any]], edges: list[dict[str, str]], i: int) -> None:
    """Choose node i's incoming edge deterministically: the latest earlier
    node whose output covers node i's *uncovered-by-static* required inputs;
    when no earlier output covers them, fan out from the entry (its
    parameters are Goal-supplied). The catalog's schema graph is mostly
    disconnected, so Goal-supplied parameters carry most real compositions.
    """
    if i == 0:
        return
    node_id = nodes[i]["id"]
    _, required = node_fields(str(nodes[i]["kind"]))
    static = set(nodes[i].get("config", {}).keys())
    uncovered = required - static
    chosen: str | None = None
    for j in range(i - 1, -1, -1):
        out_fields, _ = node_fields(str(nodes[j]["kind"]))
        if uncovered <= out_fields:
            chosen = nodes[j]["id"]
            break
    if chosen is None:
        chosen = nodes[0]["id"]
    edges.append({"from_node": chosen, "to_node": node_id})


def _reference_dag(goal_id: str) -> dict[str, Any]:
    """Reference decomposition for one synthesizable fixture: the shape a
    human would accept. Kinds are the yardstick for missing/extra; edges are
    the schema-legal composition the catalog actually supports."""
    goal = GOALS_BY_ID[goal_id]
    nodes = [
        {
            "id": f"ref_{i}_{kind.replace('.', '_')}",
            "kind": kind,
            "config": dict(goal.parameters.get(kind, {})),
        }
        for i, kind in enumerate(goal.capability_needs)
    ]
    edges: list[dict[str, str]] = []
    for i in range(1, len(nodes)):
        _connect_edge(nodes, edges, i)
    depth = dag_depth({"nodes": nodes, "edges": edges})
    return {
        "id": f"ref-{goal_id}",
        "nodes": nodes,
        "edges": edges,
        "entry_node": nodes[0]["id"],
        "max_cycles": depth,
    }


REFERENCE_DAGS: Mapping[str, Mapping[str, Any]] = {
    goal.goal_id: _reference_dag(goal.goal_id) for goal in FIXTURE_GOALS if goal.reference_kinds
}

#: The manual-template world's whole library: the one DAG the tree actually
#: ships. This scarcity IS the baseline's story.
TEMPLATE_LIBRARY: tuple[Mapping[str, Any], ...] = (daily_status_seed(),)


# ---------------------------------------------------------------------------
# Candidate planners — the arms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerCandidate:
    """What one planner produced for one Goal: a candidate DAGFile, or a
    recorded refusal. ``llm_calls`` bills planner invocations (the initial
    emission plus one per repair iteration) — the synthesis-cost proxy a
    token-metered planner would pay."""

    planner: str
    goal_id: str
    dag: Mapping[str, Any] | None
    llm_calls: int = 0

    @property
    def refused(self) -> bool:
        return self.dag is None

    @property
    def refusal_reason(self) -> str:
        if self.dag is not None:
            return ""
        return f"{self.planner} refused {self.goal_id}"


class ManualTemplateBaseline:
    """The status quo arm: reuse the closest saved template, never synthesize.

    Serves a Goal only when a library template's kinds cover every needed
    capability, verbatim; otherwise refuses. This is the "manual templates"
    world the hypothesis claims synthesis can beat — its coverage ceiling is
    the library, and its reuse is exact by construction.
    """

    def __init__(self, library: Sequence[Mapping[str, Any]]) -> None:
        self._library = tuple(library)

    @property
    def name(self) -> str:
        return "manual-template"

    def _template_kinds(self, template: Mapping[str, Any]) -> set[str]:
        return {str(n.get("kind")) for n in template.get("nodes", []) or []}

    def plan(self, goal: FixtureGoal) -> PlannerCandidate:
        needed = set(goal.capability_needs)
        best: Mapping[str, Any] | None = None
        best_overlap = -1.0
        for template in self._library:
            kinds = self._template_kinds(template)
            overlap = len(kinds & needed) / max(1, len(kinds | needed))  # Jaccard
            if overlap > best_overlap:
                best, best_overlap = template, overlap
        if best is None or not needed <= self._template_kinds(best):
            return PlannerCandidate(self.name, goal.goal_id, None)
        return PlannerCandidate(self.name, goal.goal_id, dict(best))


class CapabilitySynthesisPlanner:
    """The rule-based synthesis arm: emit a candidate from the Goal's
    capability needs plus the real catalog's schemas.

    Deterministic construction:
    - refuse loudly if any needed kind is not in the real catalog (a planner
      that cannot say no ships hallucinated capability);
    - emit one node per needed kind, in the Goal's stated order, with the
      Goal's static parameters as the node's ``config``; node ids derive from
      the composition, not the Goal, so identical needs+parameters yield
      byte-identical candidates (content-addressed identity — the substrate
      on which exact-shape reuse detection rests);
    - wire each node from the latest upstream node whose output covers the
      node's required inputs that its own parameters do not; when no upstream
      output covers them, fan the node out from the entry (the catalog's
      schema graph is mostly disconnected, so Goal-supplied parameters carry
      most real compositions);
    - declare ``max_cycles`` = the candidate's own depth (the budget policy
      counts waves; under-declaring ships a graph that cannot run).
    """

    def __init__(self, catalog_kinds: frozenset[str] | None = None) -> None:
        self._catalog = frozenset(catalog_kinds) if catalog_kinds is not None else None

    @property
    def name(self) -> str:
        return "synthesis"

    def _known_kinds(self) -> frozenset[str]:
        return self._catalog if self._catalog is not None else frozenset(list_kinds())

    def plan(self, goal: FixtureGoal) -> PlannerCandidate:
        known = self._known_kinds()
        missing_from_catalog = [k for k in goal.capability_needs if k not in known]
        if missing_from_catalog:
            # Refusal is the faithful output: no candidate, reason recorded.
            return PlannerCandidate(self.name, goal.goal_id, None)
        if len(goal.capability_needs) > goal.max_nodes:
            return PlannerCandidate(self.name, goal.goal_id, None)
        composition = json.dumps(
            {"needs": list(goal.capability_needs), "params": dict(goal.parameters)},
            sort_keys=True,
        )
        digest = hashlib.sha256(composition.encode()).hexdigest()[:12]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        for i, kind in enumerate(goal.capability_needs):
            node_id = f"n{i}_{kind.replace('.', '_')}"
            nodes.append(
                {"id": node_id, "kind": kind, "config": dict(goal.parameters.get(kind, {}))}
            )
            _connect_edge(nodes, edges, i)
        depth = dag_depth({"nodes": nodes, "edges": edges})
        dag = {
            "id": f"synth-{digest}",
            "nodes": nodes,
            "edges": edges,
            "entry_node": nodes[0]["id"],
            "max_cycles": depth,
        }
        return PlannerCandidate(self.name, goal.goal_id, dag)


class ScriptedLLMPlanner:
    """Deterministic stand-in for a provider LLM planner.

    Each fixture Goal maps to a scripted raw answer (the JSON text an LLM
    planner might emit) encoding one characteristic failure mode. The scripts
    exist to validate the legality gate, the repair loop, and the scoring —
    they are NOT evidence about real models, and every report row carries the
    ``scripted`` planner name so none can be misread as one.
    """

    def __init__(self, scripted: Mapping[str, str]) -> None:
        self._scripted = dict(scripted)

    @property
    def name(self) -> str:
        return "llm-stub-scripted"

    def plan(self, goal: FixtureGoal) -> PlannerCandidate:
        raw = self._scripted.get(goal.goal_id)
        if raw is None:
            return PlannerCandidate(self.name, goal.goal_id, None)
        return PlannerCandidate(self.name, goal.goal_id, json.loads(raw), llm_calls=1)


def _node(node_id: str, kind: str, **config: Any) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "config": config}


def scripted_llm_answers() -> dict[str, str]:
    """The scripted raw candidates, one per fixture Goal.

    Failure modes encoded, one each:
    - ``daily-status``: correct chain plus a legal-but-extra review node and
      TWO back-edges (format→entry, append→entry) — a cycle needing two
      repair iterations — under an under-declared budget (3 < depth).
    - ``daily-status-refresh``: the clean synthesis-shaped candidate (raw
      valid; shows a raw arm can sometimes serve).
    - ``research-brief``: a hallucinated kind spliced mid-chain plus a
      dangling edge to a node that does not exist, under-declared budget.
    - ``human-signoff``: a downstream node whose required input (``document``)
      is covered neither by upstream output nor static config, and no
      declared budget at all (resolves to the one-wave floor).
    - ``slack-blast``: every demanded but nonexistent capability emitted
      anyway (the planner that cannot say no).
    """
    ds = {
        "id": "stub-daily-status",
        "nodes": [
            _node("n0_jira_poll", "jira.poll", binding_id="", jql="updated >= -24h"),
            _node("n1_alias", "transform.alias_keys", mapping={"items": "issues"}),
            _node("n2_filter", "transform.filter_by_type", types=["Epic"]),
            _node("n3_format", "transform.format_markdown", template="- {key}: {summary}"),
            _node("n4_append", "dashboard.append_section", section_title="Jira Epics"),
            _node("n5_extra_review", "human.ask_question", question="Anything to add?"),
        ],
        "edges": [
            {"from_node": "n0_jira_poll", "to_node": "n1_alias"},
            {"from_node": "n1_alias", "to_node": "n2_filter"},
            {"from_node": "n2_filter", "to_node": "n3_format"},
            {"from_node": "n3_format", "to_node": "n4_append"},
            {"from_node": "n0_jira_poll", "to_node": "n5_extra_review"},
            {"from_node": "n3_format", "to_node": "n0_jira_poll"},
            {"from_node": "n4_append", "to_node": "n0_jira_poll"},
        ],
        "entry_node": "n0_jira_poll",
        "max_cycles": 3,
    }
    refresh = {
        "id": "stub-refresh",
        "nodes": [
            _node(f"n{i}_{k.replace('.', '_')}", k, **dict(_DAILY_STATUS_PARAMS[k]))
            for i, k in enumerate(_DAILY_STATUS_NEEDS)
        ],
        "edges": [],
        "entry_node": "n0_jira_poll",
        "max_cycles": 5,
    }
    for i in range(1, 5):
        prev = f"n{i - 1}_{_DAILY_STATUS_NEEDS[i - 1].replace('.', '_')}"
        cur = f"n{i}_{_DAILY_STATUS_NEEDS[i].replace('.', '_')}"
        refresh["edges"].append({"from_node": prev, "to_node": cur})
    rb = {
        "id": "stub-research-brief",
        "nodes": [
            _node("r0_jira_poll", "jira.poll", binding_id="", jql="created >= -7d"),
            _node("r1_filter", "transform.filter_by_type", types=["Story"]),
            _node("r2_extract", "transform.extract_field", field_path="summary"),
            _node("r3_slack_splice", "slack.post", channel="#brief"),
            _node("r4_format", "transform.format_markdown", template="- {summary}"),
            _node("r5_append", "dashboard.append_section", section_title="Weekly brief"),
        ],
        "edges": [
            {"from_node": "r0_jira_poll", "to_node": "r1_filter"},
            {"from_node": "r1_filter", "to_node": "r2_extract"},
            {"from_node": "r2_extract", "to_node": "r3_slack_splice"},
            {"from_node": "r3_slack_splice", "to_node": "r4_format"},
            {"from_node": "r4_format", "to_node": "r5_append"},
            {"from_node": "r4_format", "to_node": "r_ghost"},
        ],
        "entry_node": "r0_jira_poll",
        "max_cycles": 3,
    }
    hs = {
        "id": "stub-human-signoff",
        "nodes": [
            _node("h0_jira_poll", "jira.poll", binding_id="", jql="updated >= -24h"),
            _node("h1_format", "transform.format_markdown", template="- {summary}"),
            _node("h2_review", "human.review_and_edit"),
            _node("h3_append", "dashboard.append_section", section_title="Reviewed status"),
        ],
        "edges": [
            {"from_node": "h0_jira_poll", "to_node": "h1_format"},
            {"from_node": "h1_format", "to_node": "h2_review"},
            {"from_node": "h0_jira_poll", "to_node": "h3_append"},
        ],
        "entry_node": "h0_jira_poll",
    }
    sb = {
        "id": "stub-slack-blast",
        "nodes": [
            _node("s0_slack", "slack.post", channel="#updates"),
            _node("s1_teams", "teams.post", channel="Updates"),
        ],
        "edges": [{"from_node": "s0_slack", "to_node": "s1_teams"}],
        "entry_node": "s0_slack",
        "max_cycles": 2,
    }
    return {
        "daily-status": json.dumps(ds),
        "daily-status-refresh": json.dumps(refresh),
        "research-brief": json.dumps(rb),
        "human-signoff": json.dumps(hs),
        "slack-blast": json.dumps(sb),
    }


# ---------------------------------------------------------------------------
# Validator-feedback repair loop
# ---------------------------------------------------------------------------

#: Static-placeholder value the repair loop writes when a required input is
#: covered neither by upstream output nor static config. It restores
#: *legality*, never fidelity: every placeholder is an admission-time
#: parameter a human must supply, and each one is billed to review burden.
REPAIR_PLACEHOLDER = "<admission-parameter>"


@dataclass(frozen=True)
class RepairOutcome:
    """Result of the repair loop over one raw candidate."""

    dag: Mapping[str, Any] | None  # None when unrepairable within budget
    iterations: int
    residual_error_count: int
    placeholder_statics: tuple[str, ...]  # "node_id.field" fills a human must make
    exhausted: bool  # True when MAX_REPAIR_ITERATIONS ran out with errors left
    iterations_log: tuple[str, ...] = field(default_factory=tuple)


def _drop_edge(dag: dict[str, Any], index: int) -> None:
    dag["edges"].pop(index)


def _cycle_edges(dag: Mapping[str, Any]) -> list[int]:
    """Indices of edges that close a cycle (deterministic: full DFS back-edge
    set, computed locally so the repair can name the highest-index one)."""
    ids = [str(n.get("id")) for n in dag.get("nodes", []) or []]
    adjacency: dict[str, list[str]] = {nid: [] for nid in ids}
    edges = dag.get("edges", []) or []
    for i, edge in enumerate(edges):
        fn, tn = str(edge.get("from_node")), str(edge.get("to_node"))
        if fn in adjacency and tn in adjacency:
            adjacency[fn].append((tn, i))
    back: list[int] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(ids, WHITE)

    def dfs(u: str) -> None:
        color[u] = GRAY
        for v, i in adjacency[u]:
            if color.get(v) == GRAY:
                back.append(i)
            elif color.get(v) == WHITE:
                dfs(v)
        color[u] = BLACK

    for nid in ids:
        if color[nid] == WHITE:
            dfs(nid)
    return sorted(back)


def _repair_unknown_kind(work: dict[str, Any], node_id: str, log: list[str]) -> None:
    work["nodes"] = [n for n in work["nodes"] if str(n.get("id")) != node_id]
    work["edges"] = [
        e for e in work["edges"] if node_id not in (str(e.get("from_node")), str(e.get("to_node")))
    ]
    log.append(f"drop unknown node {node_id}")


def _repair_cycle(work: dict[str, Any], log: list[str]) -> bool:
    backs = _cycle_edges(work)
    if not backs:
        return False
    _drop_edge(work, backs[-1])  # highest index: deterministic
    log.append(f"drop back-edge index {backs[-1]}")
    return True


def _repair_placeholders(
    work: dict[str, Any], node_id: str, field_path: str, placeholders: list[str], log: list[str]
) -> bool:
    for spec in work["nodes"]:
        if str(spec.get("id")) != node_id:
            continue
        static = spec.setdefault("config", {})
        if field_path in static:
            return False
        static[field_path] = REPAIR_PLACEHOLDER
        placeholders.append(f"{node_id}.{field_path}")
        log.append(f"placeholder {node_id}.{field_path}")
        return True
    return False


def _apply_finding_repairs(
    work: dict[str, Any],
    report: Any,
    placeholders: list[str],
    log: list[str],
) -> bool:
    """Apply the deterministic repair for each finding; True when any applied."""
    applied = False
    for finding in report.findings:
        if finding.code == "unknown_kind" and finding.node_id:
            _repair_unknown_kind(work, finding.node_id, log)
            applied = True
        elif finding.code == "cycle" and _repair_cycle(work, log):
            applied = True
        elif finding.code == "edge_missing_endpoint" and finding.edge_index is not None:
            _drop_edge(work, finding.edge_index)
            log.append(f"drop dangling edge index {finding.edge_index}")
            applied = True
        elif finding.code == "schema_mismatch" and finding.node_id and finding.field_path:
            if _repair_placeholders(work, finding.node_id, finding.field_path, placeholders, log):
                applied = True
        elif finding.code == "no_entry":
            applied = False  # nothing left to anchor; unrepairable
    # entry may have been dropped above; re-point to a survivor
    if work["nodes"] and work["entry_node"] not in {str(n.get("id")) for n in work["nodes"]}:
        work["entry_node"] = str(work["nodes"][0]["id"])
    return applied


def apply_validator_repairs(
    raw: Mapping[str, Any], *, max_iterations: int = MAX_REPAIR_ITERATIONS
) -> RepairOutcome:
    """Repair loop: real validator findings in, deterministic repairs out.

    One iteration = one full re-validation plus the repairs for what it
    found, billing one planner call. Repair rules (each restores canonical
    legality, documented here because the repair is the part a production
    admission gate would own):
    - ``unknown_kind`` → drop the node and every edge touching it;
    - cycle → drop the highest-index cycle-closing edge;
    - ``edge_missing_endpoint`` → drop that edge;
    - ``schema_mismatch`` → write the missing field as an admission-time
      placeholder static input (billed to review burden);
    - budget under depth → raise the declaration to the resolved depth;
    - ``no_entry`` with no nodes left → unrepairable, stop.

    Never mutates the raw candidate. Never invents a kind: nodes are only
    ever dropped or left alone.
    """
    work = json.loads(json.dumps(raw))  # deep copy: the raw candidate is frozen evidence
    iterations = 0
    placeholders: list[str] = []
    log: list[str] = []
    while True:
        report = validate_dag(work)
        # Budget legality rides the same loop: the real resolver decides.
        if not budget_covers_depth(work):
            depth = dag_depth(work)
            work["max_cycles"] = max(depth, 1)
            log.append(f"budget->max_cycles={work['max_cycles']}")
            if report.is_valid:
                continue
        if report.is_valid:
            break
        if iterations >= max_iterations:
            break
        iterations += 1
        applied = _apply_finding_repairs(work, report, placeholders, log)
        if not applied:
            break
    final_report = validate_dag(work)
    legal = final_report.is_valid and budget_covers_depth(work)
    exhausted = not legal  # gave up with canonical errors remaining
    return RepairOutcome(
        dag=work if legal else None,
        iterations=iterations,
        residual_error_count=0 if legal else (final_report.error_count or 1),
        placeholder_statics=tuple(placeholders),
        exhausted=exhausted,
        iterations_log=tuple(log),
    )


# ---------------------------------------------------------------------------
# Grid runner + scoring — the issue's measure list
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalOutcome:
    """Every measure for one (arm, Goal) cell. Aggregates are sums over the
    grid of these rows — hand-checkable, no hidden weighting."""

    arm: str
    goal_id: str
    served: bool  # a candidate reached admission
    refused: bool  # planner refused (pre-emission) or admission refused it
    refusal_kind: str  # "" | "planner_refused" | "admission_refused"
    valid: bool  # final candidate passes the full canonical legality gate
    goal_success: bool  # valid AND covers every needed kind AND nothing extra
    missing_kinds: tuple[str, ...]  # needed kinds absent from the final candidate
    extra_kinds: tuple[str, ...]  # final kinds absent from the reference
    illegal_dependency_count: int  # validator error findings on the RAW candidate
    raw_budget_legal: bool
    repair_iterations: int
    repair_exhausted: bool
    llm_calls: int
    planned_nodes: int
    planned_waves: int
    planned_llm_nodes: int  # kinds whose execution needs a model
    planned_hitl_nodes: int  # human.* kinds: execution pauses for a person
    reuse_hit: bool
    review_burden: int  # placeholder statics + residual findings at admission

    def to_row(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "goal_id": self.goal_id,
            "served": self.served,
            "refused": self.refused,
            "refusal_kind": self.refusal_kind,
            "valid": self.valid,
            "goal_success": self.goal_success,
            "missing_kinds": sorted(self.missing_kinds),
            "extra_kinds": sorted(self.extra_kinds),
            "illegal_dependency_count": self.illegal_dependency_count,
            "raw_budget_legal": self.raw_budget_legal,
            "repair_iterations": self.repair_iterations,
            "repair_exhausted": self.repair_exhausted,
            "llm_calls": self.llm_calls,
            "planned_nodes": self.planned_nodes,
            "planned_waves": self.planned_waves,
            "planned_llm_nodes": self.planned_llm_nodes,
            "planned_hitl_nodes": self.planned_hitl_nodes,
            "reuse_hit": self.reuse_hit,
            "review_burden": self.review_burden,
        }


def _llm_backed_kind(kind: str) -> bool:
    """A kind whose Attempt needs a model call. The transform.* family is
    deterministic in-process work; human.* is HITL (a person, not a model)."""
    return kind.startswith(("llm.", "agent.", "jira.", "airtable.", "rsi."))


def _hitl_kind(kind: str) -> bool:
    return kind.startswith("human.")


@dataclass(frozen=True)
class ArmRecord:
    arm: str
    outcomes: tuple[GoalOutcome, ...]

    def total(self, attr: str) -> int:
        """Sum a count field, or the length sum of a tuple field."""
        return sum(
            len(value) if isinstance(value, tuple) else value
            for value in (getattr(o, attr) for o in self.outcomes)
        )

    def count(self, attr: str) -> int:
        return sum(1 for o in self.outcomes if getattr(o, attr))


@dataclass(frozen=True)
class SynthesisReport:
    """The experiment grid: every (arm, Goal) measure, frozen and sortable."""

    arms: tuple[ArmRecord, ...]

    def arm(self, name: str) -> ArmRecord:
        matches = [a for a in self.arms if a.arm == name]
        if not matches:
            raise KeyError(f"no arm named {name!r} in this report")
        return matches[0]

    def to_json(self) -> str:
        return json.dumps(
            {
                "advisory_only": ADVISORY_ONLY,
                "arms": [
                    {"arm": a.arm, "outcomes": [o.to_row() for o in a.outcomes]} for a in self.arms
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def run_grid(
    goals: Sequence[FixtureGoal],
    planners: Sequence[Any],  # objects with .name and .plan(goal)
    *,
    arm_name: str | None = None,
    template_library: Sequence[Mapping[str, Any]] = TEMPLATE_LIBRARY,
    repair: bool = False,
    reference_dags: Mapping[str, Mapping[str, Any]] = REFERENCE_DAGS,
) -> ArmRecord:
    """Run one planner arm over the Goal grid and score every measure.

    ``reuse`` semantics: the arm's library starts as the shipped templates;
    every *admitted* candidate is added to it, and a later Goal whose
    candidate canonicalizes byte-identically to any library entry is a reuse
    hit — exact-shape reuse, the strongest reuse claim available.
    """
    name = arm_name or (planners[0].name if planners else "empty")
    library = [dict(t) for t in template_library]
    library_forms = {canonical_form(t) for t in library}
    outcomes: list[GoalOutcome] = []
    for goal in goals:
        planner = next(p for p in planners if p.name.startswith(_arm_prefix(planners, goal)))
        candidate = planner.plan(goal)
        raw = candidate.dag
        raw_illegal = 0
        raw_budget_ok = True
        if raw is not None:
            raw_report = validate_dag(dict(raw))
            raw_illegal = raw_report.error_count
            raw_budget_ok = budget_covers_depth(raw)

        final: Mapping[str, Any] | None = raw
        placeholders: tuple[str, ...] = ()
        iterations = 0
        exhausted = False
        residual = 0
        if raw is not None and repair:
            outcome = apply_validator_repairs(raw)
            final = outcome.dag
            placeholders = outcome.placeholder_statics
            iterations = outcome.iterations
            exhausted = outcome.exhausted
            residual = outcome.residual_error_count
        elif raw is not None:
            # Without repair, every raw finding IS admission-time human work,
            # including a budget the human must redeclare to cover depth.
            residual = raw_illegal + (0 if raw_budget_ok else 1)

        served = final is not None
        refusal_kind = ""
        if candidate.refused:
            refusal_kind = "planner_refused"
        elif not served:
            refusal_kind = "admission_refused"

        missing: tuple[str, ...] = ()
        extra: tuple[str, ...] = ()
        success = False
        valid = False
        planned_nodes = planned_waves = planned_llm = planned_hitl = 0
        reuse_hit = False
        if served and final is not None:
            valid = candidate_is_legal(final)
            kinds = [str(n.get("kind")) for n in final.get("nodes", []) or []]
            kind_set = set(kinds)
            if goal.reference_kinds:
                missing = tuple(k for k in goal.capability_needs if k not in kind_set)
                extra = tuple(k for k in kind_set if k not in goal.reference_kinds)
                success = valid and not missing and not extra
            planned_nodes = len(kinds)
            planned_waves = dag_depth(final)
            planned_llm = sum(1 for k in kinds if _llm_backed_kind(k))
            planned_hitl = sum(1 for k in kinds if _hitl_kind(k))
            form = canonical_form(final)
            reuse_hit = form in library_forms
            if valid and form not in library_forms:
                library.append(dict(final))
                library_forms.add(form)

        review_burden = len(placeholders) + residual
        outcomes.append(
            GoalOutcome(
                arm=name,
                goal_id=goal.goal_id,
                served=served,
                refused=not served,
                refusal_kind=refusal_kind,
                valid=valid,
                goal_success=success,
                missing_kinds=missing,
                extra_kinds=extra,
                illegal_dependency_count=raw_illegal,
                raw_budget_legal=raw_budget_ok,
                repair_iterations=iterations,
                repair_exhausted=exhausted,
                llm_calls=candidate.llm_calls + (iterations if repair else 0),
                planned_nodes=planned_nodes,
                planned_waves=planned_waves,
                planned_llm_nodes=planned_llm,
                planned_hitl_nodes=planned_hitl,
                reuse_hit=reuse_hit,
                review_burden=review_burden,
            )
        )
    return ArmRecord(arm=name, outcomes=tuple(outcomes))


def _arm_prefix(planners: Sequence[Any], goal: FixtureGoal) -> str:
    """Single-planner grids: the arm is that planner. (The grid runner takes
    the sequence so arms stay named and comparable in one report.)"""
    return planners[0].name if planners else ""


def full_report() -> SynthesisReport:
    """The frozen four-arm experiment grid over the fixture Goals."""
    arms = (
        run_grid(FIXTURE_GOALS, [ManualTemplateBaseline(TEMPLATE_LIBRARY)]),
        run_grid(FIXTURE_GOALS, [CapabilitySynthesisPlanner()]),
        run_grid(FIXTURE_GOALS, [ScriptedLLMPlanner(scripted_llm_answers())]),
        run_grid(
            FIXTURE_GOALS,
            [ScriptedLLMPlanner(scripted_llm_answers())],
            arm_name="llm-stub-scripted+repair",
            repair=True,
        ),
    )
    return SynthesisReport(arms=arms)


# ---------------------------------------------------------------------------
# Tests — contract guards first, then the measures
# ---------------------------------------------------------------------------


class TestEvidenceContract:
    """The boundary that keeps this harness evidence, not authority."""

    def test_advisory_only_marker_is_present(self) -> None:
        assert ADVISORY_ONLY is True

    def test_module_imports_stay_within_the_readonly_canonical_allowlist(self) -> None:
        """AST scan: every ``maistro*`` import is one of the four pure,
        read-only surfaces. No executor, run store, durable-run machinery,
        orchestrator, or store may be reachable from this module — a
        synthesis benchmark that can reach an executor could become a second
        execution model, which the leaf forbids outright."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        maistro_imports = {name for name in imported if name.startswith("maistro")}
        assert maistro_imports, "harness must pin its canonical seam imports"
        assert maistro_imports <= MAISTRO_IMPORT_ALLOWLIST
        forbidden_markers = ("executor", "run_store", "durable_runs", "orchestrator", "runs")
        for name in maistro_imports:
            for marker in forbidden_markers:
                assert marker not in name, f"authority surface imported: {name}"

    def test_empty_goal_statement_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="statement"):
            FixtureGoal(
                goal_id="blank",
                statement="   ",
                capability_needs=("llm.summarize",),
            )

    def test_goal_without_capability_needs_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="capability_needs"):
            FixtureGoal(goal_id="empty", statement="do something", capability_needs=())

    def test_reports_are_frozen(self) -> None:
        import dataclasses

        report = full_report()
        assert isinstance(report, SynthesisReport)
        for arm in report.arms:
            assert dataclasses.is_dataclass(arm)
            with pytest.raises(dataclasses.FrozenInstanceError):
                arm.arm = "mutated"  # type: ignore[misc]
            for outcome in arm.outcomes:
                with pytest.raises(dataclasses.FrozenInstanceError):
                    outcome.valid = True  # type: ignore[misc]


class TestCanonicalSeamReuse:
    """The harness grades against the real gate; these tests keep that
    claim honest — if the catalog or the seed drifts, these fail loudly."""

    def test_real_node_catalog_contains_every_fixture_kind(self) -> None:
        known = set(list_kinds())
        for goal in FIXTURE_GOALS:
            for kind in goal.capability_needs:
                # slack.post / teams.post are the deliberate outsiders.
                if goal.goal_id == "slack-blast" and kind not in ("jira.poll",):
                    continue
                assert kind in known, f"catalog drift: {kind!r} no longer registered"

    def test_daily_status_seed_passes_the_real_legality_gate(self) -> None:
        seed = daily_status_seed()
        report = validate_dag(seed)
        assert report.is_valid, report.to_dict()
        assert budget_covers_depth(seed)

    def test_seed_declared_budget_covers_its_five_wave_depth(self) -> None:
        seed = daily_status_seed()
        assert dag_depth(seed) == 5
        assert resolve_max_cycles(seed.get("max_cycles")) == 5

    def test_local_schema_predicate_agrees_with_the_real_validator(self) -> None:
        """Every reference edge judged legal locally must survive the real
        gate, and the real gate must accept the whole reference — the local
        predicate only ever builds toward legality the canonical gate then
        confirms."""
        for goal_id, dag in REFERENCE_DAGS.items():
            for edge in dag["edges"]:
                assert edge_is_schema_legal(dag, edge["from_node"], edge["to_node"]), (
                    f"{goal_id}: local predicate accepted an edge the real gate would flag: {edge}"
                )
            report = validate_dag(dict(dag))
            assert report.is_valid, (goal_id, report.to_dict())


class TestPlannerBehavior:
    def test_synthesis_planner_refuses_goals_demanding_unknown_kinds(self) -> None:
        """The unsynthesizable Goal: refusal, no candidate, reason recorded —
        a planner that cannot say no ships hallucinated capability."""
        planner = CapabilitySynthesisPlanner()
        candidate = planner.plan(GOALS_BY_ID["slack-blast"])
        assert candidate.refused
        assert candidate.dag is None
        assert "slack-blast" in candidate.refusal_reason

    def test_synthesis_planner_emits_only_catalog_kinds(self) -> None:
        planner = CapabilitySynthesisPlanner()
        known = set(list_kinds())
        for goal in FIXTURE_GOALS:
            candidate = planner.plan(goal)
            if candidate.refused:
                continue
            for node in candidate.dag["nodes"]:  # type: ignore[index]
                assert node["kind"] in known

    def test_synthesis_candidates_pass_the_real_legality_gate(self) -> None:
        planner = CapabilitySynthesisPlanner()
        for goal in FIXTURE_GOALS:
            candidate = planner.plan(goal)
            if candidate.refused:
                continue
            dag = candidate.dag
            assert dag is not None
            report = validate_dag(dict(dag))
            assert report.is_valid, (goal.goal_id, report.to_dict())
            assert budget_covers_depth(dag), goal.goal_id

    def test_synthesis_candidates_cover_every_needed_kind(self) -> None:
        planner = CapabilitySynthesisPlanner()
        for goal in FIXTURE_GOALS:
            candidate = planner.plan(goal)
            if candidate.refused:
                continue
            kinds = {n["kind"] for n in candidate.dag["nodes"]}  # type: ignore[index]
            assert set(goal.capability_needs) <= kinds, goal.goal_id

    def test_synthesis_planner_respects_max_nodes_by_refusing(self) -> None:
        crowded = FixtureGoal(
            goal_id="crowded",
            statement="too many needs for the declared node budget",
            capability_needs=_DAILY_STATUS_NEEDS,
            parameters=_DAILY_STATUS_PARAMS,
            reference_kinds=_DAILY_STATUS_NEEDS,
            max_nodes=3,
        )
        candidate = CapabilitySynthesisPlanner().plan(crowded)
        assert candidate.refused

    def test_baseline_serves_only_goals_its_single_template_covers(self) -> None:
        """The manual-template world's coverage ceiling: of five Goals it can
        serve exactly the two the shipped seed already covers."""
        baseline = ManualTemplateBaseline(TEMPLATE_LIBRARY)
        served = [g.goal_id for g in FIXTURE_GOALS if not baseline.plan(g).refused]
        assert served == ["daily-status", "daily-status-refresh"]

    def test_baseline_reuse_is_exact_by_construction(self) -> None:
        """When the baseline serves, it serves the template verbatim — its
        reuse is real but bounded by what humans already authored."""
        baseline = ManualTemplateBaseline(TEMPLATE_LIBRARY)
        candidate = baseline.plan(GOALS_BY_ID["daily-status"])
        assert candidate.dag is not None
        assert canonical_form(candidate.dag) == canonical_form(daily_status_seed())


class TestScriptedDefectModes:
    """Each scripted raw candidate's characteristic defect must be flagged by
    the REAL canonical gate — fixtures validate the machinery, not models."""

    def test_stub_hallucinated_kind_is_flagged_unknown(self) -> None:
        raw = json.loads(scripted_llm_answers()["research-brief"])
        report = validate_dag(raw)
        codes = [f.code for f in report.findings]
        assert "unknown_kind" in codes
        assert not report.is_valid

    def test_stub_backedge_is_flagged_cycle(self) -> None:
        raw = json.loads(scripted_llm_answers()["daily-status"])
        report = validate_dag(raw)
        cycles = [f for f in report.findings if f.code == "cycle"]
        # The gate names the first cycle its DFS meets; a second back-edge
        # only surfaces after the first is dropped — which is why the repair
        # loop enumerates back-edges itself and re-validates each iteration.
        assert len(cycles) == 1
        assert not report.is_valid

    def test_stub_dangling_edge_is_flagged(self) -> None:
        raw = json.loads(scripted_llm_answers()["research-brief"])
        report = validate_dag(raw)
        dangling = [f for f in report.findings if f.code == "edge_missing_endpoint"]
        assert len(dangling) == 1
        assert dangling[0].edge_index == 5

    def test_stub_missing_required_input_is_flagged_schema_mismatch(self) -> None:
        raw = json.loads(scripted_llm_answers()["human-signoff"])
        report = validate_dag(raw)
        mismatches = [f for f in report.findings if f.code == "schema_mismatch"]
        # Two forgotten data wirings: the review node's `document` and the
        # append node's `markdown` are covered neither by upstream output nor
        # static config. A real planner forgets the data plane, not just kinds.
        assert {(m.node_id, m.field_path) for m in mismatches} == {
            ("h2_review", "document"),
            ("h3_append", "markdown"),
        }

    def test_stub_undeclared_budget_resolves_to_the_one_wave_floor(self) -> None:
        """The human-signoff stub declares no budget: the real resolver floors
        it to MIN_DAG_CYCLES, under a three-wave graph — budget-illegal."""
        raw = json.loads(scripted_llm_answers()["human-signoff"])
        assert "max_cycles" not in raw
        assert resolve_max_cycles(raw.get("max_cycles")) == 1
        assert dag_depth(raw) == 3
        assert not budget_covers_depth(raw)


class TestRepairLoop:
    def test_every_defect_mode_is_repaired_to_real_legality(self) -> None:
        """After repair, every scripted candidate except the all-hallucinated
        one passes the real gate; exact iteration counts are asserted in the
        grid tests."""
        answers = scripted_llm_answers()
        for goal_id in ("daily-status", "daily-status-refresh", "research-brief", "human-signoff"):
            outcome = apply_validator_repairs(json.loads(answers[goal_id]))
            assert outcome.dag is not None, goal_id
            assert not outcome.exhausted, goal_id
            report = validate_dag(dict(outcome.dag))
            assert report.is_valid, (goal_id, report.to_dict())
            assert budget_covers_depth(outcome.dag), goal_id

    def test_cycle_needs_exactly_two_iterations_for_two_back_edges(self) -> None:
        outcome = apply_validator_repairs(json.loads(scripted_llm_answers()["daily-status"]))
        assert outcome.iterations == 2
        assert outcome.dag is not None and validate_dag(dict(outcome.dag)).is_valid

    def test_placeholder_fill_is_billed_to_review_burden(self) -> None:
        outcome = apply_validator_repairs(json.loads(scripted_llm_answers()["human-signoff"]))
        assert outcome.placeholder_statics == (
            "h2_review.document",
            "h3_append.markdown",
        )
        assert outcome.dag is not None
        static_by_id = {
            n["id"]: n.get("config", {})
            for n in outcome.dag["nodes"]  # type: ignore[index]
        }
        assert static_by_id["h2_review"]["document"] == REPAIR_PLACEHOLDER
        assert static_by_id["h3_append"]["markdown"] == REPAIR_PLACEHOLDER

    def test_repair_never_invents_kinds_outside_the_catalog(self) -> None:
        known = set(list_kinds())
        answers = scripted_llm_answers()
        for goal_id in ("daily-status", "research-brief", "human-signoff"):
            outcome = apply_validator_repairs(json.loads(answers[goal_id]))
            assert outcome.dag is not None
            for node in outcome.dag["nodes"]:  # type: ignore[index]
                assert node["kind"] in known, (goal_id, node["kind"])

    def test_all_hallucinated_candidate_is_unrepairable_and_refused(self) -> None:
        """Repair can restore legality, not existence: dropping both
        hallucinated nodes leaves nothing to anchor — the loop gives up with
        the residual named instead of shipping an empty graph."""
        outcome = apply_validator_repairs(json.loads(scripted_llm_answers()["slack-blast"]))
        assert outcome.dag is None
        assert outcome.exhausted
        assert outcome.residual_error_count >= 1

    def test_repair_never_mutates_the_raw_candidate(self) -> None:
        raw_text = scripted_llm_answers()["research-brief"]
        raw = json.loads(raw_text)
        before = json.dumps(raw, sort_keys=True)
        apply_validator_repairs(raw)
        assert json.dumps(raw, sort_keys=True) == before

    def test_repair_of_an_already_legal_candidate_is_a_no_op(self) -> None:
        clean = CapabilitySynthesisPlanner().plan(GOALS_BY_ID["research-brief"])
        assert clean.dag is not None
        outcome = apply_validator_repairs(clean.dag)
        assert outcome.iterations == 0
        assert canonical_form(outcome.dag) == canonical_form(clean.dag)  # type: ignore[arg-type]


class TestGridMeasures:
    """The measure list, as hand-checked grid arithmetic."""

    @pytest.fixture()
    def report(self) -> SynthesisReport:
        return full_report()

    def test_baseline_coverage_ceiling(self, report: SynthesisReport) -> None:
        baseline = report.arm("manual-template")
        assert baseline.count("served") == 2
        assert baseline.count("refused") == 3
        assert all(o.refusal_kind == "planner_refused" for o in baseline.outcomes if o.refused)
        assert baseline.count("valid") == 2
        assert baseline.count("goal_success") == 2
        assert baseline.total("missing_kinds") == 0 and baseline.total("extra_kinds") == 0

    def test_synthesis_arm_full_fidelity_on_representative_goals(
        self, report: SynthesisReport
    ) -> None:
        synthesis = report.arm("synthesis")
        assert synthesis.count("served") == 4
        assert synthesis.count("refused") == 1  # slack-blast, before emission
        assert synthesis.count("valid") == 4
        assert synthesis.count("goal_success") == 4
        assert synthesis.total("missing_kinds") == 0
        assert synthesis.total("extra_kinds") == 0
        assert synthesis.total("illegal_dependency_count") == 0
        assert synthesis.total("repair_iterations") == 0

    def test_raw_stub_arm_legality_is_poor_and_measured(self, report: SynthesisReport) -> None:
        raw = report.arm("llm-stub-scripted")
        # 5 served (the stub never refuses), 1 raw-legal (the clean refresh).
        assert raw.count("served") == 5
        assert raw.count("valid") == 1
        assert raw.count("goal_success") == 1
        assert raw.total("illegal_dependency_count") == 7  # 1+0+2+2+2, per goal below
        by_goal = {o.goal_id: o for o in raw.outcomes}
        assert by_goal["daily-status"].illegal_dependency_count == 1  # first cycle named
        assert by_goal["research-brief"].illegal_dependency_count == 2
        assert by_goal["human-signoff"].illegal_dependency_count == 2  # document + markdown
        assert by_goal["daily-status-refresh"].illegal_dependency_count == 0
        assert by_goal["slack-blast"].illegal_dependency_count == 2
        # Budget legality of the raw candidates: only the clean candidate and
        # the (shallow, already-declared) slack candidate declare enough.
        assert [o.raw_budget_legal for o in raw.outcomes] == [
            False,
            True,
            False,
            False,
            True,
        ]

    def test_repair_restores_legality_but_not_always_fidelity(
        self, report: SynthesisReport
    ) -> None:
        """The recorded insight: legality is repairable, fidelity is not.
        The daily-status stub ships a legal-but-extra review node; repair
        makes it valid but goal_success stays false — only human review
        catches usefulness."""
        repaired = report.arm("llm-stub-scripted+repair")
        by_goal = {o.goal_id: o for o in repaired.outcomes}
        assert by_goal["daily-status"].valid is True
        assert by_goal["daily-status"].goal_success is False
        assert by_goal["daily-status"].extra_kinds == ("human.ask_question",)
        assert by_goal["research-brief"].goal_success is True
        assert by_goal["research-brief"].repair_iterations == 1
        assert by_goal["human-signoff"].repair_iterations == 1
        assert by_goal["daily-status"].repair_iterations == 2
        assert repaired.count("goal_success") == 3

    def test_unsynthesizable_goal_is_refused_not_shipped_by_the_repair_arm(
        self, report: SynthesisReport
    ) -> None:
        by_goal = {o.goal_id: o for o in report.arm("llm-stub-scripted+repair").outcomes}
        cell = by_goal["slack-blast"]
        assert cell.served is False
        assert cell.refusal_kind == "admission_refused"
        assert cell.repair_exhausted is True
        assert cell.repair_iterations == 2  # one repair pass, then no progress

    def test_repair_iterations_are_billed_as_planner_calls(self, report: SynthesisReport) -> None:
        repaired = report.arm("llm-stub-scripted+repair")
        for outcome in repaired.outcomes:
            expected = 1 + outcome.repair_iterations
            assert outcome.llm_calls == expected, outcome.goal_id
        assert repaired.total("llm_calls") == 11  # 3+2+2+1+3
        raw = report.arm("llm-stub-scripted")
        assert raw.total("llm_calls") == 5  # one emission each, no repair

    def test_planned_cost_accounting_is_exact(self, report: SynthesisReport) -> None:
        synthesis = report.arm("synthesis")
        by_goal = {o.goal_id: o for o in synthesis.outcomes}
        daily = by_goal["daily-status"]
        assert (daily.planned_nodes, daily.planned_waves) == (5, 5)
        assert daily.planned_llm_nodes == 1  # jira.poll
        assert daily.planned_hitl_nodes == 0
        signoff = by_goal["human-signoff"]
        assert (signoff.planned_nodes, signoff.planned_waves) == (4, 3)  # fan-out
        assert signoff.planned_hitl_nodes == 1  # human.review_and_edit
        assert synthesis.total("planned_hitl_nodes") == 1

    def test_reuse_hits_require_byte_identical_canonical_form(
        self, report: SynthesisReport
    ) -> None:
        baseline = report.arm("manual-template")
        assert baseline.total("reuse_hit") == 2  # serves the seed verbatim, twice
        synthesis = report.arm("synthesis")
        by_goal = {o.goal_id: o for o in synthesis.outcomes}
        # The refresh Goal synthesizes to exactly the already-accepted shape.
        assert by_goal["daily-status"].reuse_hit is False  # first synthesis: new shape
        assert by_goal["daily-status-refresh"].reuse_hit is True
        assert synthesis.total("reuse_hit") == 1
        # Neither stub arm ever gets two Goals to the same accepted shape.
        assert report.arm("llm-stub-scripted").total("reuse_hit") == 0
        assert report.arm("llm-stub-scripted+repair").total("reuse_hit") == 0

    def test_review_burden_counts_placeholders_and_residuals(self, report: SynthesisReport) -> None:
        repaired = report.arm("llm-stub-scripted+repair")
        by_goal = {o.goal_id: o for o in repaired.outcomes}
        assert by_goal["human-signoff"].review_burden == 2  # document + markdown fills
        assert by_goal["slack-blast"].review_burden == 1  # residual no_entry finding
        # Clean arms ship zero admission-time human work.
        assert report.arm("synthesis").total("review_burden") == 0
        assert report.arm("manual-template").total("review_burden") == 0
        raw = report.arm("llm-stub-scripted")
        # Findings + a budget redeclaration per budget-illegal candidate:
        # daily 1+1, refresh 0, research 2+1, signoff 2+1, slack 2+0.
        assert raw.total("review_burden") == 10

    def test_frozen_report_is_byte_identical_across_runs(self) -> None:
        """The grid is a deterministic fixture: same inputs, byte-identical
        report. Two fresh runs must agree exactly, key order included."""
        first = full_report().to_json()
        second = full_report().to_json()
        assert first == second
        assert json.loads(first)["advisory_only"] is True
        # And the recorded row count is stable: 4 arms x 5 goals.
        assert sum(len(a["outcomes"]) for a in json.loads(first)["arms"]) == 20


class TestReferenceDagSanity:
    def test_human_signoff_reference_routes_data_from_the_covering_upstream(
        self,
    ) -> None:
        """Nothing in the catalog outputs ``document`` for human review and
        nothing consumes its ``verdict``: the reference routes the append's
        ``markdown`` from the format node (the latest output that covers it),
        never through the review node — three waves, all legal."""
        dag = REFERENCE_DAGS["human-signoff"]
        assert dag_depth(dag) == 3
        kind_by_id = {n["id"]: n["kind"] for n in dag["nodes"]}
        format_id = next(i for i, k in kind_by_id.items() if k == "transform.format_markdown")
        review_id = next(i for i, k in kind_by_id.items() if k == "human.review_and_edit")
        append_id = next(i for i, k in kind_by_id.items() if k == "dashboard.append_section")
        pairs = {(e["from_node"], e["to_node"]) for e in dag["edges"]}
        assert (format_id, append_id) in pairs  # markdown flows from format
        assert (review_id, append_id) not in pairs  # never through review
        report = validate_dag(dict(dag))
        assert report.is_valid, report.to_dict()

    def test_every_synthesizable_fixture_has_a_legal_reference(self) -> None:
        assert set(REFERENCE_DAGS) == {
            "daily-status",
            "daily-status-refresh",
            "research-brief",
            "human-signoff",
        }
        for goal_id, dag in REFERENCE_DAGS.items():
            assert validate_dag(dict(dag)).is_valid, goal_id
            assert budget_covers_depth(dag), goal_id
