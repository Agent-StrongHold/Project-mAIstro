"""M8-B5 research harness — prompt-model co-routing and per-role specialization.

Issue #919 (leaf of epic #900, initiative #879). Hypothesis under study: the
best model may depend on the prompt/role/tool contract as much as the task
label, so *jointly* selecting (model, prompt template) — co-routing — and
specializing pairs per Agent/capability role may beat model-only routing.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #919 benchmark demands — pair-level cost and
latency accounting in ``ModelMetadata`` units (cents per 1k tokens, p50
milliseconds) with the template's added input tokens priced and its prefill
latency charged, a fixed (model, template) baseline pair as the only judge,
model-only / prompt-only / role-specific / bounded co-routing arms,
structured-output and tool-call validity as a first-class measure, prompt
maintenance burden, overfitting across disjoint benchmark families, and
portability regret across a model-version bump — so the real experiment is
reproducible the moment a paired grid corpus exists. The synthetic corpora
below are deterministic fixtures for validating the accounting and the policy
mechanics; they are NOT experimental results and must never be quoted as
evidence about real models.

Relationship to the canonical seams: production routing authority is
``CostAwareRouter`` (``packages/maistro-core/src/maistro/providers/router.py``);
its ``RoutingTask`` carries only ``task_type``/``description``, and prompt
selection (``InMemoryPromptManager`` label lookup) is a separate, model-blind
seam — the two selections are orthogonal today, which is exactly the gap
co-routing studies. Per-capability specialization partially exists as a
hand-pinned ``Binding.provider_name``; co-routing would be a policy for
deriving such pins (plus the template label) from evidence. Per the epic
exit, production adoption belongs to the routing/prompt owners, not to M8.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a routing decision, or a Warden/HITL/delegation
  control. The module imports no maistro module at all, so it cannot become
  an authority by accident (M8 guardrails 1-2). Production adoption of any
  mapping found here routes to the canonical owners (``CostAwareRouter`` for
  the model axis, the prompt library for the template axis), never through
  this harness.
- Quality is judged only by the observed outcome of the pair actually served
  on the same item — the fixed baseline pair's rows are never relabeled onto
  another arm (the fixed-baseline judge rule).
- Evidence is never fabricated: a corpus cell the arms need but the corpus
  does not contain is a loud error, and a role without a fitted choice falls
  back to the baseline pair and says so (M8 guardrail 3).
- The co-routing fit obeys the #904 leakage rule: the mapping is fitted on a
  strictly prior-period calibration slice only; the evaluation slice is a
  disjoint parameter of the comparison, never an input to the fit.
- Records are frozen: measurements cannot be mutated into authorization
  after the fact.

The experiment record and terminal disposition live in
``docs/research/919-prompt-model-co-routing.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-B5 output as
#: authorization. Routing authority remains CostAwareRouter (ADR-038);
#: prompt content/labels remain the prompt library; human-escalation
#: authority remains Warden/HITL (ADR-068).
ADVISORY_ONLY = True

#: Share of a model's p50 latency attributed to prefill, charged per extra
#: template input token: extra_ms = added_tokens / 1000 * p50 * PREFILL_SHARE.
#: A stated, deterministic rule — a real experiment replaces it with measured
#: prefill timings, not with silence about the assumption.
PREFILL_SHARE = 0.5

#: Stated utility weights for the bounded co-routing fit: per-role mean
#: utility = W_SUCCESS*success + W_VALIDITY*structured_valid
#:           - LAMBDA_COST*cost_cents - MU_LATENCY*latency_ms.
W_SUCCESS = 1.0
W_VALIDITY = 0.5
LAMBDA_COST = 0.02
MU_LATENCY = 0.0000


# ---------------------------------------------------------------------------
# Serving units — deliberately mirror ModelMetadata (providers/types.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelProfile:
    """Serving profile of one model.

    Units mirror ``ModelMetadata``: costs in cents per 1k input/output
    tokens, latency p50 in milliseconds — so a real experiment populates
    profiles straight from the provider registry without conversion.
    """

    name: str
    provider: str
    cost_per_1k_input: float
    cost_per_1k_output: float
    latency_p50_ms: int


@dataclass(frozen=True)
class TemplateProfile:
    """Serving profile of one prompt-template asset.

    ``added_input_tokens`` is priced on every call (templates are real input
    tokens). ``active_versions`` is the maintenance axis: the number of
    template versions that must stay correct, reviewed, and label-promoted
    while the mapping serves them.
    """

    name: str
    added_input_tokens: int
    active_versions: int


@dataclass(frozen=True)
class Pair:
    """The joint (model, template) unit a co-routing policy selects."""

    model: str
    template: str

    def key(self) -> str:
        return f"{self.model}+{self.template}"


@dataclass(frozen=True)
class Catalog:
    """A bounded pair catalog — the co-routing policy's whole action space."""

    pairs: tuple[Pair, ...]
    max_pairs: int

    def __post_init__(self) -> None:
        if not self.pairs:
            msg = "catalog must contain at least one pair"
            raise ValueError(msg)
        if len(self.pairs) > self.max_pairs:
            msg = (
                f"catalog has {len(self.pairs)} pairs but the bounded policy "
                f"allows at most {self.max_pairs}"
            )
            raise ValueError(msg)
        keys = [p.key() for p in self.pairs]
        if len(set(keys)) != len(keys):
            msg = f"catalog contains duplicate pairs: {keys}"
            raise ValueError(msg)


@dataclass(frozen=True)
class WorkItem:
    """One workload item answered under one (model, template) pair.

    ``role`` is the Agent/capability role (e.g. summarizer, extractor,
    tool_agent); ``family`` is the benchmark family, the overfitting axis.
    A paired grid corpus carries one row per (item, pair) cell actually
    observed — this module consumes such exports and never manufactures a
    missing cell.
    """

    item_id: str
    role: str
    family: str
    model: str
    template: str
    payload_input_tokens: int
    output_tokens: int
    success: bool
    structured_valid: bool
    latency_ms: int


Corpus = tuple[WorkItem, ...]


# ---------------------------------------------------------------------------
# Deterministic accounting — stated rules, hand-checkable
# ---------------------------------------------------------------------------


def pair_cost_cents(
    item: WorkItem,
    model: ModelProfile,
    template: TemplateProfile,
) -> float:
    """Cost of serving one item under one pair, in cents.

    Rule: input tokens are the payload PLUS the template's added tokens —
    a template is real input the provider bills. Output tokens are as
    observed. Negative token counts are impossible evidence and rejected.
    """
    if item.payload_input_tokens < 0 or item.output_tokens < 0:
        msg = f"item {item.item_id}: token counts must be non-negative"
        raise ValueError(msg)
    if template.added_input_tokens < 0:
        msg = f"template {template.name}: added_input_tokens must be non-negative"
        raise ValueError(msg)
    input_tokens = item.payload_input_tokens + template.added_input_tokens
    return (
        input_tokens / 1000.0 * model.cost_per_1k_input
        + item.output_tokens / 1000.0 * model.cost_per_1k_output
    )


def template_latency_ms(model: ModelProfile, template: TemplateProfile) -> int:
    """Extra prefill latency the template's added tokens cost, in ms.

    Rule (stated): extra_ms = added_tokens / 1000 * p50 * PREFILL_SHARE,
    rounded to the nearest millisecond.
    """
    extra = template.added_input_tokens / 1000.0 * model.latency_p50_ms * PREFILL_SHARE
    return round(extra)


def _p95(ordered: Sequence[int]) -> int:
    """Nearest-rank p95 over an ascending-sorted sample; n=1 -> that value."""
    if not ordered:
        msg = "p95 of an empty sample is not defined"
        raise ValueError(msg)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True)
class MaintenanceBurden:
    """Prompt-side maintenance cost of a served mapping.

    ``distinct_templates`` must be kept correct as assets; ``active_versions``
    is the total version surface that must survive review and label
    promotion while the mapping serves. This is the issue's "prompt
    maintenance burden" measure.
    """

    distinct_templates: int
    active_versions: int


@dataclass(frozen=True)
class ArmResult:
    """Measured outcome of one arm over one item slice."""

    arm: str
    items: int
    success_rate: float
    structured_validity_rate: float
    total_cost_cents: float
    mean_latency_ms: float
    p95_latency_ms: int
    maintenance: MaintenanceBurden
    #: Roles served via the bounded policy's no-fit fallback, with the
    #: baseline pair they fell back to. A fully-fitted arm records {}.
    fallback_roles: Mapping[str, str] = dataclasses.field(default_factory=dict)


def measure_arm(
    arm: str,
    rows: Sequence[WorkItem],
    mapping: Mapping[str, Pair],
    models: Mapping[str, ModelProfile],
    templates: Mapping[str, TemplateProfile],
    baseline_pair: Pair,
) -> ArmResult:
    """Score a paired grid under ``mapping`` (role -> pair).

    The corpus is a paired grid: every item carries one row per observed
    (model, template) pair. For each item, this reads exactly the row of the
    pair its role maps to (the baseline pair for unmapped roles) — quality
    comes from the served pair's observed outcome, never from another pair's
    row. A missing cell, a duplicated cell, or an item with inconsistent
    role/family labels is a loud error: absent evidence is never fabricated.
    """
    if not rows:
        msg = "cannot measure an arm over an empty slice"
        raise ValueError(msg)
    by_item: dict[str, WorkItem] = {}
    seen_cells: set[tuple[str, str, str]] = set()
    for row in rows:
        cell = (row.item_id, row.model, row.template)
        if cell in seen_cells:
            msg = f"corpus duplicates cell {cell}"
            raise ValueError(msg)
        seen_cells.add(cell)
        prior = by_item.get(row.item_id)
        if prior is not None and (prior.role, prior.family) != (row.role, row.family):
            msg = f"item {row.item_id} carries inconsistent role/family labels"
            raise ValueError(msg)
        by_item[row.item_id] = row

    served: list[WorkItem] = []
    fallbacks: dict[str, str] = {}
    for item_id in sorted(by_item):
        meta = by_item[item_id]
        pair = mapping.get(meta.role, baseline_pair)
        if (item_id, pair.model, pair.template) not in seen_cells:
            msg = f"corpus has no observed outcome for item {item_id} under pair {pair.key()}"
            raise ValueError(msg)
        row = next(
            r
            for r in rows
            if r.item_id == item_id and r.model == pair.model and r.template == pair.template
        )
        served.append(row)
        if meta.role not in mapping and meta.role not in fallbacks:
            fallbacks[meta.role] = pair.key()

    latencies = sorted(
        r.latency_ms + template_latency_ms(models[r.model], templates[r.template]) for r in served
    )
    total_cost = sum(pair_cost_cents(r, models[r.model], templates[r.template]) for r in served)
    used_templates = {r.template for r in served}
    return ArmResult(
        arm=arm,
        items=len(served),
        success_rate=sum(1 for r in served if r.success) / len(served),
        structured_validity_rate=(sum(1 for r in served if r.structured_valid) / len(served)),
        total_cost_cents=round(total_cost, 4),
        mean_latency_ms=round(sum(latencies) / len(latencies), 4),
        p95_latency_ms=_p95(latencies),
        maintenance=MaintenanceBurden(
            distinct_templates=len(used_templates),
            active_versions=sum(templates[t].active_versions for t in used_templates),
        ),
        fallback_roles=fallbacks,
    )


def arm_utility(
    result: ArmResult,
    *,
    w_success: float = W_SUCCESS,
    w_validity: float = W_VALIDITY,
    lambda_cost: float = LAMBDA_COST,
) -> float:
    """Stated-utility score of a measured arm (per-item means)."""
    return round(
        w_success * result.success_rate
        + w_validity * result.structured_validity_rate
        - lambda_cost * result.total_cost_cents / result.items,
        6,
    )


# ---------------------------------------------------------------------------
# Arms — the benchmark's comparison set
# ---------------------------------------------------------------------------


def fixed_baseline_mapping(baseline_pair: Pair) -> dict[str, Pair]:
    """One (model, template) pair for every role — the judge and the floor.

    The returned mapping is deliberately empty: unmapped roles fall back to
    ``baseline_pair`` at measurement time, so the fixed baseline arm and the
    fallback path share one code path and cannot drift apart.
    """
    del baseline_pair
    return {}


def model_only_mapping(
    role_models: Mapping[str, str],
    shared_template: str,
) -> dict[str, Pair]:
    """Route the model by task label; keep one template everywhere.

    This is today's shape: a task-conditioned model choice with a
    model-blind prompt seam.
    """
    return {role: Pair(model, shared_template) for role, model in role_models.items()}


def prompt_only_mapping(
    shared_model: str,
    role_templates: Mapping[str, str],
) -> dict[str, Pair]:
    """One model everywhere; specialize the template per role."""
    return {role: Pair(shared_model, t) for role, t in role_templates.items()}


def role_pair_mapping(role_pairs: Mapping[str, Pair]) -> dict[str, Pair]:
    """A prescribed (model, template) pair per role — static specialization."""
    return dict(role_pairs)


def fit_corouting_mapping(
    calibration_rows: Sequence[WorkItem],
    roles: Sequence[str],
    catalog: Catalog,
    models: Mapping[str, ModelProfile],
    templates: Mapping[str, TemplateProfile],
    baseline_pair: Pair,
    *,
    w_success: float = W_SUCCESS,
    w_validity: float = W_VALIDITY,
    lambda_cost: float = LAMBDA_COST,
    mu_latency: float = MU_LATENCY,
) -> dict[str, Pair]:
    """Fit the bounded co-routing mapping on a PRIOR-period slice only.

    For each role: among catalog pairs with calibration rows for that role,
    pick the pair maximizing stated utility (mean success/validity minus
    stated cost/latency weights). Ties break lexicographically on
    (model, template) — deterministic. A role with no calibration rows gets
    NO inferred choice: it falls back to the baseline pair and the caller
    sees it in ``fallback_roles``. The fit never sees the evaluation slice.
    """
    if not calibration_rows:
        msg = "cannot fit co-routing on an empty calibration slice"
        raise ValueError(msg)
    by_role: dict[str, dict[Pair, list[WorkItem]]] = {}
    for row in calibration_rows:
        pair = Pair(row.model, row.template)
        if pair in catalog.pairs:
            by_role.setdefault(row.role, {}).setdefault(pair, []).append(row)

    mapping: dict[str, Pair] = {}
    for role in roles:
        cells = by_role.get(role)
        if not cells:
            continue  # fallback happens at measurement time, loudly recorded
        best: Pair | None = None
        best_u = -math.inf
        for pair in sorted(catalog.pairs, key=lambda p: (p.model, p.template)):
            rows = cells.get(pair)
            if not rows:
                continue
            n = len(rows)
            cost = (
                sum(pair_cost_cents(r, models[pair.model], templates[pair.template]) for r in rows)
                / n
            )
            lat = (
                sum(
                    r.latency_ms + template_latency_ms(models[pair.model], templates[pair.template])
                    for r in rows
                )
                / n
            )
            u = (
                w_success * sum(1 for r in rows if r.success) / n
                + w_validity * sum(1 for r in rows if r.structured_valid) / n
                - lambda_cost * cost
                - mu_latency * lat
            )
            if u > best_u + 1e-12:
                best_u = u
                best = pair
        assert best is not None  # by_role cells only hold catalog pairs
        mapping[role] = best
    return mapping


# ---------------------------------------------------------------------------
# Sensitivity analyses the issue names
# ---------------------------------------------------------------------------


def served_rows(
    rows: Sequence[WorkItem],
    mapping: Mapping[str, Pair],
    baseline_pair: Pair,
) -> list[WorkItem]:
    """The rows an arm would serve: per item, the mapped pair's row."""
    if not rows:
        msg = "cannot serve rows from an empty slice"
        raise ValueError(msg)
    cells: dict[tuple[str, str, str], WorkItem] = {}
    meta_by_item: dict[str, WorkItem] = {}
    for row in rows:
        cells[(row.item_id, row.model, row.template)] = row
        prior = meta_by_item.get(row.item_id)
        if prior is not None and (prior.role, prior.family) != (row.role, row.family):
            msg = f"item {row.item_id} carries inconsistent role/family labels"
            raise ValueError(msg)
        meta_by_item.setdefault(row.item_id, row)
    out: list[WorkItem] = []
    for item_id in sorted(meta_by_item):
        meta = meta_by_item[item_id]
        pair = mapping.get(meta.role, baseline_pair)
        row = cells.get((item_id, pair.model, pair.template))
        if row is None:
            msg = f"corpus has no observed outcome for item {item_id} under {pair.key()}"
            raise ValueError(msg)
        out.append(row)
    return out


def generalization_gap(
    mapping: Mapping[str, Pair],
    fit_slice: Sequence[WorkItem],
    heldout_slice: Sequence[WorkItem],
    models: Mapping[str, ModelProfile],
    templates: Mapping[str, TemplateProfile],
    baseline_pair: Pair,
) -> float:
    """Per-item mean utility on the fit slice minus on the held-out family.

    Positive gap = the mapping carried family-specific tuning; the issue's
    overfitting-across-benchmark-families measure. Both slices are scored
    under the SAME mapping with the same judge rule as the arms.
    """

    def slice_utility(rows: Sequence[WorkItem]) -> float:
        res = measure_arm("gap_slice", rows, mapping, models, templates, baseline_pair)
        return arm_utility(res)

    return round(slice_utility(fit_slice) - slice_utility(heldout_slice), 6)


def version_bump_regret(
    stale_mapping: Mapping[str, Pair],
    refit_mapping: Mapping[str, Pair],
    bumped_rows: Sequence[WorkItem],
    models: Mapping[str, ModelProfile],
    templates: Mapping[str, TemplateProfile],
    baseline_pair: Pair,
) -> float:
    """Portability cost of a model-version bump: utility(refit) - utility(stale).

    Both mappings are evaluated on the SAME post-bump grid rows with the
    same judge rule. Positive regret = the stale specialization lost value
    when a model version changed under it; refitting recovers it. This is
    the issue's portability-across-model-versions measure.
    """
    stale_res = measure_arm(
        "stale",
        bumped_rows,
        stale_mapping,
        models,
        templates,
        baseline_pair,
    )
    refit_res = measure_arm(
        "refit",
        bumped_rows,
        refit_mapping,
        models,
        templates,
        baseline_pair,
    )
    return round(arm_utility(refit_res) - arm_utility(stale_res), 6)


def dominated_pairs(
    catalog: Catalog,
    calibration_rows: Sequence[WorkItem],
    models: Mapping[str, ModelProfile],
    templates: Mapping[str, TemplateProfile],
) -> set[str]:
    """Catalog pairs never optimal for ANY role under the stated utility.

    "Never optimal" on the calibration slice is weaker than dominated on
    every axis, but it is the operationally dead set: no role's fit ever
    selects these pairs. The baseline pair may appear here — a fixture's
    calibration slice cannot see tail risk, so curation must retain the
    baseline regardless (the trust boundary keeps this advisory).
    """
    by_role: dict[str, set[Pair]] = {}
    for row in calibration_rows:
        by_role.setdefault(row.role, set()).add(Pair(row.model, row.template))
    optimal: set[Pair] = set()
    for role, available in by_role.items():
        best: Pair | None = None
        best_u = -math.inf
        for pair in sorted(catalog.pairs, key=lambda p: (p.model, p.template)):
            if pair not in available:
                continue
            rows = [
                r
                for r in calibration_rows
                if r.role == role and r.model == pair.model and r.template == pair.template
            ]
            n = len(rows)
            cost = (
                sum(pair_cost_cents(r, models[pair.model], templates[pair.template]) for r in rows)
                / n
            )
            u = (
                W_SUCCESS * sum(1 for r in rows if r.success) / n
                + W_VALIDITY * sum(1 for r in rows if r.structured_valid) / n
                - LAMBDA_COST * cost
            )
            if u > best_u + 1e-12:
                best_u = u
                best = pair
        if best is not None:
            optimal.add(best)
    return {p.key() for p in catalog.pairs} - {p.key() for p in optimal}


# ---------------------------------------------------------------------------
# The frozen benchmark run
# ---------------------------------------------------------------------------


def run_benchmark() -> dict[str, object]:
    """Execute the full fixture benchmark and return the frozen record.

    Deterministic end to end: no randomness, no clocks, no environment
    reads — two invocations return byte-identical JSON.
    """
    models = {
        "nimbus-fast": ModelProfile(
            name="nimbus-fast",
            provider="nimbus",
            cost_per_1k_input=0.08,
            cost_per_1k_output=0.24,
            latency_p50_ms=900,
        ),
        "helios-fast": ModelProfile(
            name="helios-fast",
            provider="helios",
            cost_per_1k_input=0.06,
            cost_per_1k_output=0.18,
            latency_p50_ms=1100,
        ),
        "titan-strong": ModelProfile(
            name="titan-strong",
            provider="titan",
            cost_per_1k_input=1.20,
            cost_per_1k_output=3.60,
            latency_p50_ms=2400,
        ),
    }
    templates = {
        "plain": TemplateProfile(name="plain", added_input_tokens=120, active_versions=1),
        "role_rich": TemplateProfile(name="role_rich", added_input_tokens=900, active_versions=3),
    }
    baseline_pair = Pair(model="titan-strong", template="plain")
    roles = ("summarizer", "extractor", "tool_agent")
    catalog = Catalog(
        pairs=(
            baseline_pair,
            Pair(model="nimbus-fast", template="role_rich"),
            Pair(model="helios-fast", template="plain"),
            Pair(model="nimbus-fast", template="plain"),
        ),
        max_pairs=4,
    )

    corpus = build_fixture_grid()
    fit_slice = [r for r in corpus if r.family == "family-a"]
    heldout_slice = [r for r in corpus if r.family == "family-b"]

    baseline_result = measure_arm(
        "fixed_baseline",
        corpus,
        fixed_baseline_mapping(baseline_pair),
        models,
        templates,
        baseline_pair,
    )
    model_only = measure_arm(
        "model_only",
        corpus,
        model_only_mapping(
            {"summarizer": "helios-fast", "extractor": "helios-fast", "tool_agent": "nimbus-fast"},
            "plain",
        ),
        models,
        templates,
        baseline_pair,
    )
    prompt_only = measure_arm(
        "prompt_only",
        corpus,
        prompt_only_mapping(
            "titan-strong",
            {"summarizer": "role_rich", "extractor": "role_rich", "tool_agent": "role_rich"},
        ),
        models,
        templates,
        baseline_pair,
    )
    role_pairs = measure_arm(
        "role_specific",
        corpus,
        role_pair_mapping(
            {
                "summarizer": Pair("helios-fast", "plain"),
                "extractor": Pair("nimbus-fast", "role_rich"),
                "tool_agent": Pair("titan-strong", "plain"),
            }
        ),
        models,
        templates,
        baseline_pair,
    )
    fitted = fit_corouting_mapping(fit_slice, roles, catalog, models, templates, baseline_pair)
    corouting = measure_arm(
        "corouting_bounded",
        corpus,
        fitted,
        models,
        templates,
        baseline_pair,
    )
    corouting_heldout = measure_arm(
        "corouting_bounded_heldout",
        heldout_slice,
        fitted,
        models,
        templates,
        baseline_pair,
    )
    baseline_heldout = measure_arm(
        "fixed_baseline_heldout",
        heldout_slice,
        {},
        models,
        templates,
        baseline_pair,
    )

    gap = generalization_gap(fitted, fit_slice, heldout_slice, models, templates, baseline_pair)

    # Model-version bump: nimbus-fast is replaced by a v2 whose role_rich
    # scaffold handling regresses to plain-level validity (post-bump grid).
    bumped_rows = build_fixture_grid(nimbus_role_rich_regression=True)
    refit = fit_corouting_mapping(
        [r for r in bumped_rows if r.family == "family-a"],
        roles,
        catalog,
        models,
        templates,
        baseline_pair,
    )
    regret = version_bump_regret(fitted, refit, bumped_rows, models, templates, baseline_pair)

    return {
        "issue": "919",
        "leaf": "M8-B5 prompt-model co-routing",
        "baseline_pair": baseline_pair.key(),
        "catalog_bound": catalog.max_pairs,
        "utility_weights": {
            "w_success": W_SUCCESS,
            "w_validity": W_VALIDITY,
            "lambda_cost": LAMBDA_COST,
            "mu_latency": MU_LATENCY,
            "prefill_share": PREFILL_SHARE,
        },
        "fitted_corouting_mapping": {r: fitted[r].key() for r in sorted(fitted)},
        "corouting_fallback_roles": dict(corouting.fallback_roles),
        "arms": {
            "fixed_baseline": dataclasses.asdict(baseline_result),
            "model_only": dataclasses.asdict(model_only),
            "prompt_only": dataclasses.asdict(prompt_only),
            "role_specific": dataclasses.asdict(role_pairs),
            "corouting_bounded": dataclasses.asdict(corouting),
        },
        "heldout_family": {
            "fixed_baseline": dataclasses.asdict(baseline_heldout),
            "corouting_bounded": dataclasses.asdict(corouting_heldout),
        },
        "overfitting_generalization_gap": gap,
        "version_bump": {
            "regret_stale_vs_refit": regret,
            "stale_mapping": {r: fitted[r].key() for r in sorted(fitted)},
            "refit_mapping": {r: refit[r].key() for r in sorted(refit)},
        },
        "dead_catalog_pairs_on_calibration": sorted(
            dominated_pairs(catalog, fit_slice, models, templates)
        ),
    }


# ---------------------------------------------------------------------------
# Deterministic fixture grid — arithmetic validation ONLY, never evidence
# ---------------------------------------------------------------------------

_ITEM_SEQ = count(1)


def _row(
    role: str,
    family: str,
    model: str,
    template: str,
    *,
    success: bool,
    valid: bool,
    latency_ms: int,
    item_id: str | None = None,
) -> WorkItem:
    """Build one grid cell with deterministic token counts per role."""
    payload = {"summarizer": 3000, "extractor": 1500, "tool_agent": 2000}[role]
    out = {"summarizer": 400, "extractor": 600, "tool_agent": 500}[role]
    return WorkItem(
        item_id=item_id or f"i{next(_ITEM_SEQ)}",
        role=role,
        family=family,
        model=model,
        template=template,
        payload_input_tokens=payload,
        output_tokens=out,
        success=success,
        structured_valid=valid,
        latency_ms=latency_ms,
    )


def build_fixture_grid(
    *,
    nimbus_role_rich_regression: bool = False,
) -> Corpus:
    """The paired (role x model x template x family) outcome grid.

    Encoded interaction structure (fixture arithmetic, NOT real-model
    evidence):

    - ``titan-strong`` + ``plain``: high success/validity everywhere, expensive.
    - ``nimbus-fast`` (follows scaffolds): ``role_rich`` recovers structured
      validity on extractor/tool_agent; ``plain`` drops it.
    - ``helios-fast`` (chokes on long scaffolds): fine at plain prose
      (summarizer in family-a), ``role_rich`` *hurts* — the provider-specific
      prompt sensitivity the issue asks to include, and the interaction that
      model-only and prompt-only routing both misroute.
    - ``family-b``: helios summarizer prose regresses (embedded drift) so the
      overfitting measure has something true to find.
    - ``nimbus_role_rich_regression``: the post-bump world where the v2 of
      nimbus-fast loses the scaffold benefit (portability axis).
    """
    rows: list[WorkItem] = []
    for family in ("family-a", "family-b"):
        helios_prose_ok = family == "family-a"
        for role in ("summarizer", "extractor", "tool_agent"):
            rich_valid = not nimbus_role_rich_regression
            for rep in range(4):
                item_id = f"{family}-{role}-{rep}"
                # titan-strong + plain: the strong floor, both families.
                rows.append(
                    _row(
                        role,
                        family,
                        "titan-strong",
                        "plain",
                        success=True,
                        valid=True,
                        latency_ms=2400,
                        item_id=item_id,
                    )
                )
                # titan-strong + role_rich: the strong model does not need
                # the scaffold but is not hurt by it — pure input-token
                # overhead, the trap prompt-only specialization falls into.
                rows.append(
                    _row(
                        role,
                        family,
                        "titan-strong",
                        "role_rich",
                        success=True,
                        valid=True,
                        latency_ms=2400,
                        item_id=item_id,
                    )
                )
                # nimbus-fast + plain: cheap but structurally unreliable
                # except at prose (summarizer) where it succeeds.
                rows.append(
                    _row(
                        role,
                        family,
                        "nimbus-fast",
                        "plain",
                        success=role == "summarizer",
                        valid=role == "summarizer",
                        latency_ms=900,
                        item_id=item_id,
                    )
                )
                # nimbus-fast + role_rich: scaffold recovers structure —
                # unless the post-bump regression is in effect.
                rows.append(
                    _row(
                        role,
                        family,
                        "nimbus-fast",
                        "role_rich",
                        success=True,
                        valid=rich_valid or role == "summarizer",
                        latency_ms=1050,
                        item_id=item_id,
                    )
                )
                # helios-fast + plain: good prose in family-a, drifted away
                # in family-b; mediocre structure everywhere.
                rows.append(
                    _row(
                        role,
                        family,
                        "helios-fast",
                        "plain",
                        success=role == "summarizer" and helios_prose_ok,
                        valid=role == "summarizer",
                        latency_ms=1100,
                        item_id=item_id,
                    )
                )
                # helios-fast + role_rich: the scaffold chokes it — worse
                # than its own plain on structure AND success.
                rows.append(
                    _row(
                        role,
                        family,
                        "helios-fast",
                        "role_rich",
                        success=False,
                        valid=False,
                        latency_ms=1500,
                        item_id=item_id,
                    )
                )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Tests — arithmetic, policy mechanics, contract
# ---------------------------------------------------------------------------

MODULE_PATH = Path(__file__)


def test_advisory_only_marker_is_true() -> None:
    assert ADVISORY_ONLY is True


def test_module_imports_no_maistro_module() -> None:
    """AST-level contract: the harness cannot become an authority by accident."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            assert root != "maistro", f"forbidden maistro import: {name}"


def test_pair_cost_prices_template_tokens_exactly() -> None:
    model = ModelProfile(
        "m", "p", cost_per_1k_input=0.08, cost_per_1k_output=0.24, latency_p50_ms=900
    )
    tpl = TemplateProfile("t", added_input_tokens=900, active_versions=3)
    item = _row("extractor", "family-a", "m", "t", success=True, valid=True, latency_ms=900)
    # (1500 payload + 900 template)/1000 * 0.08 + 600/1000 * 0.24
    expected = (2400 / 1000 * 0.08) + (600 / 1000 * 0.24)
    assert pair_cost_cents(item, model, tpl) == pytest.approx(expected)


def test_template_latency_prefill_rule_is_exact() -> None:
    model = ModelProfile("m", "p", 0.1, 0.1, latency_p50_ms=900)
    tpl = TemplateProfile("t", added_input_tokens=900, active_versions=1)
    # 900/1000 * 900 * 0.5 = 405 ms
    assert template_latency_ms(model, tpl) == 405


def test_template_latency_rounds_to_nearest_ms() -> None:
    model = ModelProfile("m", "p", 0.1, 0.1, latency_p50_ms=901)
    tpl = TemplateProfile("t", added_input_tokens=1, active_versions=1)
    # 1/1000 * 901 * 0.5 = 0.4505 -> 0
    assert template_latency_ms(model, tpl) == 0


def test_negative_tokens_are_impossible_evidence() -> None:
    model = ModelProfile("m", "p", 0.1, 0.1, 100)
    tpl = TemplateProfile("t", 0, 1)
    bad = dataclasses.replace(
        _row("summarizer", "f", "m", "t", success=True, valid=True, latency_ms=1),
        payload_input_tokens=-1,
    )
    with pytest.raises(ValueError, match="non-negative"):
        pair_cost_cents(bad, model, tpl)


def test_catalog_rejects_bound_violation_and_duplicates() -> None:
    p = Pair("m", "t")
    with pytest.raises(ValueError, match="at most"):
        Catalog((p, p, Pair("m2", "t")), max_pairs=2)
    with pytest.raises(ValueError, match="duplicate"):
        Catalog((p, p), max_pairs=4)
    with pytest.raises(ValueError, match="at least one"):
        Catalog((), max_pairs=4)


def test_measure_arm_rejects_empty_slice_and_missing_cells() -> None:
    models = {"m": ModelProfile("m", "p", 0.1, 0.1, 100)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    with pytest.raises(ValueError, match="empty slice"):
        measure_arm("a", [], {}, models, templates, Pair("m", "t"))
    row = _row("summarizer", "f", "m", "t", success=True, valid=True, latency_ms=1)
    with pytest.raises(ValueError, match="no observed outcome"):
        measure_arm(
            "a", [row], {"summarizer": Pair("other", "t")}, models, templates, Pair("m", "t")
        )


def test_measure_arm_rejects_duplicate_cells_and_inconsistent_items() -> None:
    models = {"m": ModelProfile("m", "p", 0.1, 0.1, 100)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    dup = _row("summarizer", "f", "m", "t", success=True, valid=True, latency_ms=1, item_id="x")
    with pytest.raises(ValueError, match="duplicates cell"):
        measure_arm("a", [dup, dup], {}, models, templates, Pair("m", "t"))
    # A DIFFERENT cell for the same item id: not a duplicate, an item
    # carrying two conflicting role/family labels.
    conflicting = _row(
        "extractor", "f", "m", "u", success=True, valid=True, latency_ms=1, item_id="x"
    )
    with pytest.raises(ValueError, match="inconsistent role/family"):
        measure_arm("a", [dup, conflicting], {}, models, templates, Pair("m", "t"))


def test_no_evidence_role_falls_back_to_baseline_and_is_recorded() -> None:
    models = {
        "m": ModelProfile("m", "p", 0.1, 0.1, 100),
        "b": ModelProfile("b", "p", 1.0, 1.0, 200),
    }
    templates = {"t": TemplateProfile("t", 0, 1)}
    base = Pair("b", "t")
    rows = [_row("summarizer", "f", "b", "t", success=True, valid=True, latency_ms=5)]
    res = measure_arm("a", rows, {}, models, templates, base)
    assert res.fallback_roles == {"summarizer": "b+t"}
    # A mapped role is not a fallback.
    res2 = measure_arm("a", rows, {"summarizer": base}, models, templates, base)
    assert res2.fallback_roles == {}


def test_judge_reads_served_pair_rows_not_baseline_rows() -> None:
    """The fixed baseline's outcomes are never relabeled onto another arm."""
    models = {
        "m": ModelProfile("m", "p", 0.1, 0.1, 100),
        "b": ModelProfile("b", "p", 1.0, 1.0, 200),
    }
    templates = {"t": TemplateProfile("t", 0, 1)}
    base = Pair("b", "t")
    rows = [
        _row("summarizer", "f", "m", "t", success=False, valid=False, latency_ms=5, item_id="x1"),
        _row("summarizer", "f", "b", "t", success=True, valid=True, latency_ms=5, item_id="x1"),
        _row("summarizer", "f", "m", "t", success=False, valid=False, latency_ms=5, item_id="x2"),
        _row("summarizer", "f", "b", "t", success=True, valid=True, latency_ms=5, item_id="x2"),
    ]
    res = measure_arm("a", rows, {"summarizer": Pair("m", "t")}, models, templates, base)
    assert res.items == 2
    assert res.success_rate == 0.0  # the served pair failed, baseline's win ignored
    res_b = measure_arm("a", rows, {}, models, templates, base)
    assert res_b.success_rate == 1.0


def test_p95_is_nearest_rank_and_handles_single_item() -> None:
    assert _p95(range(1, 20)) == 19  # ceil(0.95*19) = 19th of 19
    assert _p95([7]) == 7
    with pytest.raises(ValueError, match="empty sample"):
        _p95([])


def test_utility_prefers_structured_validity_when_success_ties() -> None:
    models = {"a": ModelProfile("a", "p", 0.0, 0.0, 1), "b": ModelProfile("b", "p", 0.0, 0.0, 1)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    base = Pair("a", "t")
    rows = []
    for m in ("a", "b"):
        for rep in range(4):
            rows.append(
                _row(
                    "extractor",
                    "f",
                    m,
                    "t",
                    success=True,
                    valid=m == "b",
                    latency_ms=1,
                    item_id=f"x{rep}",
                )
            )
    fitted = fit_corouting_mapping(
        rows, ["extractor"], Catalog((Pair("a", "t"), Pair("b", "t")), 4), models, templates, base
    )
    assert fitted["extractor"] == Pair("b", "t")


def test_cost_weight_flips_the_choice_deterministically() -> None:
    models = {
        "cheap": ModelProfile("cheap", "p", 0.0, 0.0, 1),
        "strong": ModelProfile("strong", "p", 10.0, 0.0, 1),
    }
    templates = {"t": TemplateProfile("t", 0, 1)}
    base = Pair("strong", "t")
    rows = []
    for m in ("cheap", "strong"):
        for rep in range(4):
            rows.append(
                _row(
                    "summarizer",
                    "f",
                    m,
                    "t",
                    success=True,
                    valid=False,
                    latency_ms=1,
                    item_id=f"x{rep}",
                )
            )
    catalog = Catalog((Pair("cheap", "t"), Pair("strong", "t")), 4)
    quality_first = fit_corouting_mapping(
        rows, ["summarizer"], catalog, models, templates, base, lambda_cost=0.0
    )
    cost_first = fit_corouting_mapping(
        rows, ["summarizer"], catalog, models, templates, base, lambda_cost=0.02
    )
    # Success and validity tie, so both weights leave the lex-cheaper pick.
    assert quality_first["summarizer"] == Pair("cheap", "t")
    assert cost_first["summarizer"] == Pair("cheap", "t")
    # With strong strictly better on success, the zero-cost-weight pick flips.
    rows2 = [r if r.model != "cheap" else dataclasses.replace(r, success=False) for r in rows]
    assert fit_corouting_mapping(
        rows2,
        ["summarizer"],
        catalog,
        models,
        templates,
        base,
        lambda_cost=0.0,
    )["summarizer"] == Pair("strong", "t")


def test_lexicographic_tie_break_is_deterministic() -> None:
    models = {"a": ModelProfile("a", "p", 0.0, 0.0, 1), "b": ModelProfile("b", "p", 0.0, 0.0, 1)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    rows = []
    for m in ("b", "a"):  # insertion order opposite to lex order
        for rep in range(4):
            rows.append(
                _row(
                    "summarizer",
                    "f",
                    m,
                    "t",
                    success=True,
                    valid=True,
                    latency_ms=1,
                    item_id=f"x{rep}",
                )
            )
    fitted = fit_corouting_mapping(
        rows,
        ["summarizer"],
        Catalog((Pair("b", "t"), Pair("a", "t")), 4),
        models,
        templates,
        Pair("a", "t"),
    )
    assert fitted["summarizer"] == Pair("a", "t")


def test_fit_rejects_empty_calibration_slice() -> None:
    models = {"m": ModelProfile("m", "p", 0.1, 0.1, 1)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    with pytest.raises(ValueError, match="empty calibration"):
        fit_corouting_mapping(
            [], ["r"], Catalog((Pair("m", "t"),), 2), models, templates, Pair("m", "t")
        )


def test_catalog_bound_of_one_degenerates_to_fixed_baseline() -> None:
    models = {
        "titan-strong": ModelProfile("titan-strong", "p", 1.2, 3.6, 2400),
        "nimbus-fast": ModelProfile("nimbus-fast", "p", 0.08, 0.24, 900),
    }
    templates = {"plain": TemplateProfile("plain", 120, 1)}
    base = Pair("titan-strong", "plain")
    corpus = build_fixture_grid()
    bounded = fit_corouting_mapping(
        [r for r in corpus if r.family == "family-a"],
        ["summarizer", "extractor", "tool_agent"],
        Catalog((base,), 1),
        models,
        templates,
        base,
    )
    # The bound-1 catalog's only pair IS the baseline pair, so the fit is
    # forced onto it for every role it covers: the mapping degenerates to
    # the fixed baseline.
    assert bounded == {"summarizer": base, "extractor": base, "tool_agent": base}
    res_bounded = measure_arm("bounded", corpus, bounded, models, templates, base)
    res_fixed = measure_arm("fixed", corpus, {}, models, templates, base)
    # Identical measurements; the only differences are the arm label and
    # fallback bookkeeping, because the bound-1 catalog's only pair IS the
    # baseline pair.
    assert res_bounded.items == res_fixed.items
    assert res_bounded.success_rate == res_fixed.success_rate
    assert res_bounded.structured_validity_rate == res_fixed.structured_validity_rate
    assert res_bounded.total_cost_cents == res_fixed.total_cost_cents
    assert res_bounded.mean_latency_ms == res_fixed.mean_latency_ms
    assert res_bounded.p95_latency_ms == res_fixed.p95_latency_ms
    assert res_bounded.maintenance == res_fixed.maintenance
    # Bookkeeping still differs: a fully-fitted arm records no fallback,
    # while the fixed baseline arm records every role as fallback.
    assert res_bounded.fallback_roles == {}
    assert res_fixed.fallback_roles == {
        "summarizer": "titan-strong+plain",
        "extractor": "titan-strong+plain",
        "tool_agent": "titan-strong+plain",
    }


def test_dominated_pairs_identifies_never_optimal_catalog_weight() -> None:
    """Added template tokens are priced, so the token-heavy pair loses."""
    models = {"m": ModelProfile("m", "p", 0.1, 0.1, 1)}
    templates = {
        "light": TemplateProfile("light", 0, 1),
        "heavy": TemplateProfile("heavy", 1000, 1),
    }
    rows = []
    for tpl in ("light", "heavy"):
        for rep in range(4):
            rows.append(
                _row(
                    "extractor",
                    "f",
                    "m",
                    tpl,
                    success=True,
                    valid=True,
                    latency_ms=1,
                    item_id=f"x{rep}",
                )
            )
    catalog = Catalog((Pair("m", "light"), Pair("m", "heavy")), 4)
    dead = dominated_pairs(catalog, rows, models, templates)
    assert dead == {"m+heavy"}


def test_maintenance_burden_counts_templates_and_versions() -> None:
    models = {
        "m": ModelProfile("m", "p", 0.1, 0.1, 100),
        "n": ModelProfile("n", "p", 0.1, 0.1, 100),
    }
    templates = {"t": TemplateProfile("t", 0, 1), "u": TemplateProfile("u", 0, 3)}
    rows = [
        _row("summarizer", "f", "m", "t", success=True, valid=True, latency_ms=1, item_id="x1"),
        _row("summarizer", "f", "n", "u", success=True, valid=True, latency_ms=1, item_id="x1"),
        _row("extractor", "f", "n", "u", success=True, valid=True, latency_ms=1, item_id="x2"),
        _row("extractor", "f", "m", "t", success=True, valid=True, latency_ms=1, item_id="x2"),
    ]
    specialized = measure_arm(
        "spec",
        rows,
        {"summarizer": Pair("m", "t"), "extractor": Pair("n", "u")},
        models,
        templates,
        Pair("m", "t"),
    )
    uniform = measure_arm(
        "uni",
        rows,
        {"summarizer": Pair("m", "t"), "extractor": Pair("m", "t")},
        models,
        templates,
        Pair("m", "t"),
    )
    assert specialized.maintenance == MaintenanceBurden(2, 4)
    assert uniform.maintenance == MaintenanceBurden(1, 1)


def test_generalization_gap_is_zero_when_families_match() -> None:
    models = {"m": ModelProfile("m", "p", 0.1, 0.1, 1)}
    templates = {"t": TemplateProfile("t", 0, 1)}
    rows = [
        _row("summarizer", "fa", "m", "t", success=True, valid=True, latency_ms=1, item_id="x1"),
        _row("summarizer", "fb", "m", "t", success=True, valid=True, latency_ms=1, item_id="x2"),
    ]
    gap = generalization_gap({}, rows, rows, models, templates, Pair("m", "t"))
    assert gap == 0.0


def test_full_run_is_byte_identical_across_invocations() -> None:
    first = json.dumps(run_benchmark(), sort_keys=True)
    second = json.dumps(run_benchmark(), sort_keys=True)
    assert first == second


def test_full_run_record_contract() -> None:
    record = run_benchmark()
    assert record["issue"] == "919"
    arms = record["arms"]
    assert set(arms) == {
        "fixed_baseline",
        "model_only",
        "prompt_only",
        "role_specific",
        "corouting_bounded",
    }
    for arm in arms.values():
        # 24 grid items (2 families x 3 roles x 4 reps); every arm sees all.
        assert arm["items"] == 24
        assert 0.0 <= arm["success_rate"] <= 1.0
        assert 0.0 <= arm["structured_validity_rate"] <= 1.0
        assert arm["total_cost_cents"] > 0.0
        assert arm["maintenance"]["distinct_templates"] >= 1
    assert record["heldout_family"]["fixed_baseline"]["items"] == 12


def test_baseline_arm_serves_exactly_the_baseline_pair() -> None:
    record = run_benchmark()
    base = record["arms"]["fixed_baseline"]
    # Per summarizer item: (3000+120)/1000*1.2 + 400/1000*3.6 = 5.184;
    # extractor: (1500+120)/1000*1.2 + 600/1000*3.6 = 4.104;
    # tool_agent: (2000+120)/1000*1.2 + 500/1000*3.6 = 4.344.
    # 8 items each -> 8*(5.184 + 4.104 + 4.344) = 109.056 cents.
    assert base["total_cost_cents"] == pytest.approx(109.056)
    assert base["maintenance"] == {"distinct_templates": 1, "active_versions": 1}
    assert base["fallback_roles"] == {
        "summarizer": "titan-strong+plain",
        "extractor": "titan-strong+plain",
        "tool_agent": "titan-strong+plain",
    }


def test_corouting_fits_the_provider_template_interaction() -> None:
    """The core hypothesis arithmetic: co-routing routes the interaction.

    summarizer -> helios-fast+plain (prose, no scaffold); extractor and
    tool_agent -> nimbus-fast+role_rich (scaffold recovers structure).
    Model-only (all plain) and prompt-only (all rich) both misroute one side
    of that interaction.
    """
    record = run_benchmark()
    mapping = record["fitted_corouting_mapping"]
    assert mapping["summarizer"] == "helios-fast+plain"
    assert mapping["extractor"] == "nimbus-fast+role_rich"
    assert mapping["tool_agent"] == "nimbus-fast+role_rich"
    assert record["corouting_fallback_roles"] == {}

    arms = record["arms"]
    # Model-only keeps one template: helios+plain for summarizer/extractor,
    # nimbus+plain for tool_agent — structure survives only on summarizer
    # rows (1/3), and only family-a summarizer succeeds (1/6).
    assert arms["model_only"]["structured_validity_rate"] == pytest.approx(1 / 3)
    assert arms["model_only"]["success_rate"] == pytest.approx(1 / 6)
    # Prompt-only scaffolds everything on the strong model: validity holds
    # but pays role_rich input tokens at titan prices — worse than baseline.
    assert arms["prompt_only"]["structured_validity_rate"] == pytest.approx(1.0)
    assert arms["prompt_only"]["total_cost_cents"] > arms["fixed_baseline"]["total_cost_cents"]
    # Co-routing: only the family-b summarizer drift ships (4/24 items).
    assert arms["corouting_bounded"]["success_rate"] == pytest.approx(20 / 24)
    assert arms["corouting_bounded"]["structured_validity_rate"] == pytest.approx(1.0)
    assert (
        arms["corouting_bounded"]["total_cost_cents"] < arms["fixed_baseline"]["total_cost_cents"]
    )


def test_corouting_cost_advantage_is_material_on_the_fixture() -> None:
    arms = run_benchmark()["arms"]
    base = arms["fixed_baseline"]["total_cost_cents"]
    co = arms["corouting_bounded"]["total_cost_cents"]
    static = arms["role_specific"]["total_cost_cents"]
    assert base > static > co > 0
    # Quoted in the note: bounded co-routing cuts fixture cost ~94%, and it
    # also beats hand-picked static role pairs by dropping tool_agent to the
    # scaffolded cheap pair.
    assert base / co > 10.0
    assert static / co > 2.0


def test_overfitting_gap_is_detected_on_the_drifted_family() -> None:
    record = run_benchmark()
    gap = record["overfitting_generalization_gap"]
    # family-b regresses helios summarizer prose; the mapping fitted on
    # family-a carries a positive gap.
    assert gap > 0.0
    heldout = record["heldout_family"]
    assert heldout["corouting_bounded"]["arm"] == "corouting_bounded_heldout"
    # The damage is visible: co-routing's held-out success drops below the
    # fixed baseline's on the drifted family — the stale helios choice now
    # ships failures.
    assert heldout["corouting_bounded"]["success_rate"] == pytest.approx(8 / 12)
    assert heldout["fixed_baseline"]["success_rate"] == pytest.approx(1.0)
    assert heldout["corouting_bounded"]["fallback_roles"] == {}


def test_version_bump_regret_is_positive_and_refit_recovers() -> None:
    record = run_benchmark()
    bump = record["version_bump"]
    assert bump["regret_stale_vs_refit"] > 0.0
    # The refit actually moves off the regressed pair: post-bump, the
    # scaffold no longer recovers validity, so the fit returns to the
    # strong pair for structure-bearing roles.
    assert bump["stale_mapping"]["extractor"] == "nimbus-fast+role_rich"
    assert bump["refit_mapping"]["extractor"] == "titan-strong+plain"
    assert bump["refit_mapping"]["tool_agent"] == "titan-strong+plain"


def test_prompt_only_specialization_raises_maintenance_burden() -> None:
    arms = run_benchmark()["arms"]
    assert arms["fixed_baseline"]["maintenance"]["active_versions"] == 1
    assert arms["prompt_only"]["maintenance"]["active_versions"] == 3
    assert arms["prompt_only"]["maintenance"]["distinct_templates"] == 1
    # Co-routing serves two templates (plain + role_rich).
    assert arms["corouting_bounded"]["maintenance"]["distinct_templates"] == 2
    assert arms["corouting_bounded"]["maintenance"]["active_versions"] == 4


def test_calibration_slice_reports_dead_catalog_pairs() -> None:
    record = run_benchmark()
    # On the family-a slice, helios+plain (summarizer) and nimbus+rich
    # (extractor, tool_agent) win every argmax; the strong pair and the
    # unscaffolded nimbus+plain are never optimal — advisory curation
    # evidence only (the baseline pair is retained by policy regardless).
    assert record["dead_catalog_pairs_on_calibration"] == [
        "nimbus-fast+plain",
        "titan-strong+plain",
    ]


def test_served_rows_rule_matches_measure_arm_judge() -> None:
    """The sensitivity helper and measure_arm select identical rows."""
    corpus = build_fixture_grid()
    mapping = {"summarizer": Pair("helios-fast", "plain")}
    base = Pair("titan-strong", "plain")
    served = served_rows(corpus, mapping, base)
    assert len(served) == 24
    for row in served:
        pair = mapping.get(row.role, base)
        assert (row.model, row.template) == (pair.model, pair.template)
