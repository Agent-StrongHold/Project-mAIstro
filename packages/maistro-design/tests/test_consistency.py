"""Cross-artifact consistency evaluation and targeted refinement (#779).

Each test maps to one acceptance criterion of the issue:

1. planted Persona violation in one artifact → only that branch proposed;
2. planted shared factual contradiction → every descendant that consumed the
   bad decision is identified;
3. a locked accepted artifact is reported as conflicting but never rewritten;
4. the evaluator cites exact brief/decision/artifact versions;
5. claim evaluation distinguishes provided evidence from model assertions;
6. evaluation is a canonical graph node (Run/NodeRun/Attempt provenance);
7. retrying/refining creates fresh Run evidence and preserves the failed
   evaluation record;
8. impact routing walks real relationships — two artifacts of the SAME kind
   where only one consumes the bad decision get different verdicts (a
   kind-based rule could not do this).
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_design.consistency import (
    AccessibilityConstraint,
    BriefSnapshot,
    ChannelRequirement,
    ClaimRule,
    ConsistencyDimension,
    ContradictionRule,
    CreativeProjectSnapshot,
    EvidenceItem,
    FamilyArtifact,
    FindingOrigin,
    PersonaSnapshot,
    RequiredMessage,
    Severity,
    SharedDecision,
    TermRule,
    evaluate_project_snapshot,
)


def _snapshot(**overrides: Any) -> CreativeProjectSnapshot:
    """A small but real creative family: one campaign, four artifacts.

    `poster` and `social_copy` consume the shared delivery-promise decision
    D1; `landing_hero` (locked, accepted) consumes D1 too; `promo_banner`
    references the poster and so inherits its defects transitively;
    `website_copy` consumes only the unrelated naming decision D2.

    By default D1 carries the planted shared factual contradiction; pass
    ``d1_statement="All plans include 48-hour turnaround."`` for a clean
    shared decision, e.g. to isolate a purely local defect.
    """
    d1_statement = overrides.pop("d1_statement", "All plans include 24-hour delivery.")
    brief = BriefSnapshot(
        brief_id="brief-aurora",
        version=3,
        goal_revision="goal-rev-7",
        audience="indie studio founders",
        objective="drive launch-week signups",
        objective_keywords=(r"sign ?ups?", r"launch"),
        allowed_claims=(
            ClaimRule(
                claim_id="turnaround",
                pattern=r"48-hour turnaround",
                source="provided_evidence",
                evidence_id="ev-turnaround",
            ),
            ClaimRule(
                claim_id="express-promise",
                pattern=r"24-hour delivery",
                source="model_asserted",
            ),
        ),
        contradiction_rules=(
            ContradictionRule(
                rule_id="rule-turnaround",
                description="delivery promise conflict",
                pattern_a=r"24-hour delivery",
                pattern_b=r"48-hour turnaround",
            ),
        ),
        terminology=(TermRule(preferred="workspace", banned_aliases=(r"\bapp\b",)),),
        required_messages=(
            RequiredMessage(
                message_id="cta-signup",
                pattern=r"start your (free )?trial",
                required_in=("*",),
            ),
        ),
        channel_requirements=(
            ChannelRequirement(
                artifact_kind="poster",
                required_elements=(r"<title>",),
                forbidden_elements=(r"lorem ipsum",),
            ),
        ),
        accessibility_constraints=(
            AccessibilityConstraint(constraint_id="acc-alt", check="image_alt_text"),
        ),
    )
    persona = PersonaSnapshot(
        persona_id="persona-meridian",
        name="Meridian",
        banned_markers=(r"guaranteed results",),
        required_markers=(),
    )
    d1 = SharedDecision(
        decision_id="D1",
        version=2,
        kind="delivery-promise",
        statement=d1_statement,
    )
    d2 = SharedDecision(
        decision_id="D2",
        version=1,
        kind="naming",
        statement="Call the product a workspace, never an app.",
    )
    poster = FamilyArtifact(
        artifact_id="poster",
        version=1,
        kind="poster",
        title="Launch poster",
        content=(
            '<html lang="en"><title>Aurora</title><body>'
            "<h1>Launch week is here</h1>"
            '<img src="aurora.png">'
            "<p>Start your free trial — 24-hour delivery, guaranteed results.</p>"
            "</body></html>"
        ),
        consumes=("D1",),
    )
    social = FamilyArtifact(
        artifact_id="social_copy",
        version=1,
        kind="social",
        title="Launch social copy",
        content=("Launch week is here. Start your free trial. All plans include 24-hour delivery."),
        consumes=("D1",),
    )
    hero = FamilyArtifact(
        artifact_id="landing_hero",
        version=4,
        kind="webpage",
        title="Landing hero",
        content=(
            '<html lang="en"><body><h1>Aurora</h1>'
            "<p>Start your free trial. All plans include 24-hour delivery.</p>"
            "</body></html>"
        ),
        status="accepted",
        locked=True,
        consumes=("D1",),
    )
    banner = FamilyArtifact(
        artifact_id="promo_banner",
        version=1,
        kind="banner",
        title="Promo banner",
        content="<p>Start your free trial — derived from the poster copy.</p>",
        references=("poster",),
    )
    website = FamilyArtifact(
        artifact_id="website_copy",
        version=2,
        kind="webpage",
        title="Website copy",
        content=(
            '<html lang="en"><body><h1>Meet your new workspace</h1>'
            "<p>Start your free trial. The workspace keeps everything together.</p>"
            "</body></html>"
        ),
        status="accepted",
        consumes=("D2",),
    )
    fields: dict[str, Any] = {
        "project_id": "proj-aurora",
        "brief": brief,
        "persona": persona,
        "decisions": (d1, d2),
        "artifacts": (poster, social, hero, banner, website),
        "evidence": (
            EvidenceItem(
                evidence_id="ev-turnaround",
                statement="All plans include 48-hour turnaround.",
            ),
        ),
    }
    fields.update(overrides)
    return CreativeProjectSnapshot(**fields)


def errors_by_dimension(evaluation: Any, dimension: ConsistencyDimension) -> list[Any]:
    return [
        f for f in evaluation.findings if f.dimension is dimension and f.severity is Severity.ERROR
    ]


def target_ids(evaluation: Any) -> list[str]:
    if evaluation.refinement is None:
        return []
    return [t.artifact_id for t in evaluation.refinement.targets]


def _eval_graph(snapshot: CreativeProjectSnapshot) -> Any:
    import maistro_design.nodes  # noqa: F401 — registers design.* node kinds
    from maistro.graph.definitions import Graph, Node

    return Graph(
        workspace_id="ws-1",
        project_id="proj-aurora",
        name="creative-consistency-eval",
        nodes=[
            Node(
                node_id="eval-1",
                node_type="design.consistency_eval",
                inputs=snapshot.model_dump(),
            )
        ],
    )


def _resolver(_node_id: str, graph: Any) -> Any:
    from maistro.graph.nodes import get_node

    return get_node(graph.nodes[0].node_type)()


# ─── 1. A planted Persona violation routes only its own branch ───────────────


def test_persona_violation_proposes_only_the_affected_branch() -> None:
    # Clean shared decision; the ONLY planted defect is the persona violation
    # in the poster, so the proposal must name exactly the poster branch.
    evaluation = evaluate_project_snapshot(
        _snapshot(d1_statement="All plans include 48-hour turnaround.")
    )

    persona_errors = errors_by_dimension(evaluation, ConsistencyDimension.PERSONA_VOICE)
    assert len(persona_errors) == 1
    finding = persona_errors[0]
    assert finding.artifact_id == "poster"
    assert finding.origin is FindingOrigin.LOCAL
    assert "guaranteed results" in finding.evidence
    # Only the poster's branch: the artifact itself plus transitive dependents.
    assert set(finding.affected_artifact_ids) == {"poster", "promo_banner"}

    # The proposal regenerates the broken branch only — never accepted
    # website copy that shares no defect.
    assert target_ids(evaluation) == ["poster", "promo_banner"]
    assert evaluation.refinement is not None
    assert evaluation.refinement.root_cause is FindingOrigin.LOCAL
    assert evaluation.refinement.shared_decision_ids == ()
    assert evaluation.passed is False
    hero_target = next(
        (t for t in evaluation.refinement.targets if t.artifact_id == "landing_hero"),
        None,
    )
    assert hero_target is None


# ─── 2. A shared factual contradiction identifies every consumer ─────────────


def test_shared_factual_contradiction_identifies_all_descendants() -> None:
    evaluation = evaluate_project_snapshot(_snapshot())

    shared_errors = errors_by_dimension(evaluation, ConsistencyDimension.FACTUAL_CLAIMS)
    decision_errors = [f for f in shared_errors if f.decision_id == "D1"]
    assert len(decision_errors) == 1
    finding = decision_errors[0]
    assert finding.origin is FindingOrigin.SHARED
    # Evidence vs decision are quoted side by side.
    assert "24-hour delivery" in finding.evidence
    assert "48-hour turnaround" in finding.evidence

    # Every artifact that consumed D1 — plus transitive dependents — is
    # affected; the website copy that consumed only D2 is not.
    assert set(finding.affected_artifact_ids) == {
        "poster",
        "social_copy",
        "landing_hero",
        "promo_banner",
    }
    assert "website_copy" not in finding.affected_artifact_ids

    assert evaluation.refinement is not None
    assert evaluation.refinement.root_cause is FindingOrigin.SHARED
    assert evaluation.refinement.shared_decision_ids == ("D1",)
    assert set(target_ids(evaluation)) == {
        "poster",
        "social_copy",
        "landing_hero",
        "promo_banner",
    }


def test_sibling_contradiction_probes_each_side_it_actually_carries() -> None:
    """Reversed orientation: the left sibling carries pattern_b while the
    right carries pattern_a from a shared decision. The origin probe must
    pair each artifact with the side it actually carries — otherwise the
    shared decision is missed, the finding degrades to LOCAL, and the other
    consumers of that decision are dropped from the refinement closure."""
    left = FamilyArtifact(
        artifact_id="flyer",
        version=1,
        kind="social",
        title="Launch flyer",
        content=(
            "Launch week is here. Start your free trial. All plans include 48-hour turnaround."
        ),
    )
    right = FamilyArtifact(
        artifact_id="social_copy",
        version=1,
        kind="social",
        title="Launch social copy",
        content=("Launch week is here. Start your free trial. All plans include 24-hour delivery."),
        consumes=("D1",),
    )
    evaluation = evaluate_project_snapshot(_snapshot(artifacts=(left, right), evidence=()))

    sibling_errors = errors_by_dimension(evaluation, ConsistencyDimension.SIBLING_CONTRADICTION)
    assert len(sibling_errors) == 1
    finding = sibling_errors[0]
    assert finding.rule_id == "rule-turnaround"
    assert finding.origin is FindingOrigin.SHARED
    assert finding.decision_id == "D1"
    # The closure follows the shared decision, not just the two siblings.
    assert "social_copy" in finding.affected_artifact_ids

    assert evaluation.refinement is not None
    assert evaluation.refinement.root_cause is FindingOrigin.SHARED
    assert evaluation.refinement.shared_decision_ids == ("D1",)


def test_impact_follows_relationships_not_artifact_kinds() -> None:
    """Two artifacts of the SAME kind; only one consumes the bad decision.

    A hard-coded artifact-type rule would flag or spare both; the real
    consumption edge separates them.
    """
    base = _snapshot()
    same_kind_pair = (
        FamilyArtifact(
            artifact_id="poster",
            version=1,
            kind="poster",
            title="Poster with the bad promise",
            content="<title>Aurora</title><p>Start your free trial — 24-hour delivery.</p>",
            consumes=("D1",),
        ),
        FamilyArtifact(
            artifact_id="other_poster",
            version=1,
            kind="poster",
            title="Poster without it",
            content="<title>Aurora</title><p>Start your free trial — ships in two days.</p>",
            consumes=(),
        ),
    )
    artifacts = (
        tuple(
            a
            for a in base.artifacts
            if a.artifact_id not in {"poster", "social_copy", "landing_hero", "promo_banner"}
        )
        + same_kind_pair
    )
    evaluation = evaluate_project_snapshot(base.model_copy(update={"artifacts": artifacts}))

    shared_errors = [
        f
        for f in errors_by_dimension(evaluation, ConsistencyDimension.FACTUAL_CLAIMS)
        if f.decision_id == "D1"
    ]
    assert len(shared_errors) == 1
    assert set(shared_errors[0].affected_artifact_ids) == {"poster"}
    assert target_ids(evaluation) == ["poster"]


# ─── 3. A locked accepted artifact is reported, never rewritten ──────────────


def test_locked_accepted_artifact_conflicts_but_is_not_rewritten() -> None:
    snapshot = _snapshot()
    evaluation = evaluate_project_snapshot(snapshot)

    locked = errors_by_dimension(evaluation, ConsistencyDimension.LOCKED_DECISIONS) + [
        f for f in evaluation.findings if f.dimension is ConsistencyDimension.LOCKED_DECISIONS
    ]
    assert locked, "the locked artifact conflict must be reported"
    assert any("never silently" in f.evidence or "silently" in f.evidence for f in locked)

    # The locked artifact is a refinement target, but flagged as requiring an
    # explicit unlock before canonical Run logic may touch it.
    assert evaluation.refinement is not None
    hero_target = next(t for t in evaluation.refinement.targets if t.artifact_id == "landing_hero")
    assert hero_target.locked is True
    assert hero_target.requires_unlock is True

    # Proposal only: the evaluator has no write path, and the frozen snapshot
    # it consumed is bit-for-bit unchanged afterwards.
    assert snapshot.artifacts[2].content == (
        '<html lang="en"><body><h1>Aurora</h1>'
        "<p>Start your free trial. All plans include 24-hour delivery.</p>"
        "</body></html>"
    )
    assert snapshot.artifacts[2].status == "accepted"
    assert snapshot.artifacts[2].locked is True


def test_unlocked_accepted_artifact_does_not_require_unlock() -> None:
    snapshot = _snapshot()
    clean_website = snapshot.artifacts[4].model_copy(
        update={
            # Accepted but NOT locked, and it consumes the bad shared decision.
            "content": "<p>Start your free trial. 24-hour delivery.</p>",
            "consumes": ("D1",),
        }
    )
    # Only the decision-evidence contradiction remains; the accepted but
    # unlocked website copy is proposed for normal refinement.
    minimal = snapshot.model_copy(
        update={
            "artifacts": (clean_website,),
            "persona": None,
        }
    )
    evaluation = evaluate_project_snapshot(minimal)
    assert evaluation.refinement is not None
    assert evaluation.refinement.root_cause is FindingOrigin.SHARED
    target = next(t for t in evaluation.refinement.targets if t.artifact_id == "website_copy")
    assert target.locked is False
    assert target.requires_unlock is False


# ─── 4. Exact versions are cited ─────────────────────────────────────────────


def test_evaluation_cites_exact_brief_decision_artifact_versions() -> None:
    evaluation = evaluate_project_snapshot(_snapshot())

    provenance = evaluation.provenance
    assert provenance.brief_id == "brief-aurora"
    assert provenance.brief_version == 3
    assert provenance.goal_revision == "goal-rev-7"
    assert provenance.persona_id == "persona-meridian"
    assert provenance.decision_versions == {"D1": 2, "D2": 1}
    assert provenance.artifact_versions == {
        "poster": 1,
        "social_copy": 1,
        "landing_hero": 4,
        "promo_banner": 1,
        "website_copy": 2,
    }
    assert provenance.evidence_ids == ("ev-turnaround",)


def test_historical_evaluation_stays_interpretable_after_later_edits() -> None:
    first = evaluate_project_snapshot(_snapshot())

    # The project moves on: the bad decision is fixed as v3, the poster is
    # regenerated as v2. The earlier evaluation must still cite what it saw.
    edited = _snapshot(
        decisions=(
            SharedDecision(
                decision_id="D1",
                version=3,
                kind="delivery-promise",
                statement="All plans include 48-hour turnaround.",
            ),
            SharedDecision(
                decision_id="D2",
                version=1,
                kind="naming",
                statement="Call the product a workspace, never an app.",
            ),
        ),
    )
    second = evaluate_project_snapshot(edited)

    assert first.provenance.decision_versions["D1"] == 2
    assert second.provenance.decision_versions["D1"] == 3
    assert first.evaluation_id != second.evaluation_id
    # The earlier result still carries the failing findings verbatim, citing
    # the versions it actually saw.
    assert first.passed is False
    assert any(f.decision_id == "D1" and f.origin is FindingOrigin.SHARED for f in first.findings)
    # The decision fix removes the shared contradiction from the new result.
    assert not any(
        f.dimension is ConsistencyDimension.FACTUAL_CLAIMS and f.origin is FindingOrigin.SHARED
        for f in second.findings
    )


# ─── 5. Evidence vs model-generated assertions ───────────────────────────────


def test_provided_evidence_is_distinguished_from_model_assertions() -> None:
    evaluation = evaluate_project_snapshot(_snapshot())

    factual = [f for f in evaluation.findings if f.dimension is ConsistencyDimension.FACTUAL_CLAIMS]

    # The evidence-backed claim ("48-hour turnaround") appears in no artifact,
    # so it produces no finding; the model-asserted promise ("24-hour
    # delivery") appears everywhere and is warned about as unverified — a
    # distinct, weaker verdict than the contradiction error.
    assertion_warnings = [
        f for f in factual if f.severity is Severity.WARNING and f.claim_id == "express-promise"
    ]
    assert assertion_warnings, "model-asserted claims must be reported as unverified"
    assert all(f.severity is Severity.WARNING for f in assertion_warnings)

    contradiction = [f for f in factual if f.claim_id is None and f.rule_id == "rule-turnaround"]
    assert contradiction, "the decision-vs-evidence contradiction must be an error"
    assert all(f.severity is Severity.ERROR for f in contradiction)


def test_evidence_backed_claim_passes_while_assertion_is_flagged() -> None:
    # Clean shared decision: the card repeats exactly the provided evidence.
    base = _snapshot(d1_statement="All plans include 48-hour turnaround.")
    honest = FamilyArtifact(
        artifact_id="honest_card",
        version=1,
        kind="card",
        title="Honest card",
        content="<p>Start your free trial. All plans include 48-hour turnaround.</p>",
        consumes=("D1",),
    )
    evaluation = evaluate_project_snapshot(base.model_copy(update={"artifacts": (honest,)}))
    assert evaluation.passed is True
    claim_findings = [
        f for f in evaluation.findings if f.dimension is ConsistencyDimension.FACTUAL_CLAIMS
    ]
    assert claim_findings == [], "an evidence-backed claim must not be flagged"


def test_claim_rule_shape_is_enforced() -> None:
    # A provided_evidence claim must name its evidence; an asserted claim must
    # not cite one.
    with pytest.raises(Exception, match="provided_evidence"):
        ClaimRule(claim_id="no-evidence", pattern=r"anything", source="provided_evidence")
    with pytest.raises(Exception, match="model_asserted"):
        ClaimRule(
            claim_id="with-evidence",
            pattern=r"anything",
            source="model_asserted",
            evidence_id="ev-turnaround",
        )

    # A claim citing evidence the snapshot does not contain is reported as an
    # evaluation error, not silently treated as truth.
    base = _snapshot()
    broken_brief = base.brief.model_copy(
        update={
            "allowed_claims": (
                ClaimRule(
                    claim_id="orphan",
                    pattern=r"free trial",
                    source="provided_evidence",
                    evidence_id="does-not-exist",
                ),
            ),
            "contradiction_rules": (),
            "terminology": (),
            "required_messages": (),
            "channel_requirements": (),
            "accessibility_constraints": (),
            "objective_keywords": (),
        }
    )
    minimal = base.model_copy(
        update={
            "brief": broken_brief,
            "artifacts": (base.artifacts[4],),
            "decisions": (base.decisions[1],),
            "persona": None,
        }
    )
    evaluation = evaluate_project_snapshot(minimal)
    orphan = errors_by_dimension(evaluation, ConsistencyDimension.FACTUAL_CLAIMS)
    assert orphan and "does-not-exist" in orphan[0].evidence


# ─── Remaining dimensions smoke coverage ─────────────────────────────────────


def test_terminology_message_channel_accessibility_dimensions_fire() -> None:
    evaluation = evaluate_project_snapshot(_snapshot())

    # "app" banned alias does not appear in any artifact → terminology passes.
    # The poster is missing the CTA? No: it has it. Check real planted ones:
    terms = errors_by_dimension(evaluation, ConsistencyDimension.TERMINOLOGY)
    assert terms == []

    # The poster lacks <title>? It has one. Use the planted channel violation:
    # none planted → channel passes for poster, but promo_banner (kind
    # banner) has no requirements. So assert dimension presence via a failure:
    violating = _snapshot()
    poster = violating.artifacts[0].model_copy(
        update={
            "content": (
                '<html lang="en"><body><h1>Launch</h1>'
                '<img src="x.png">'
                "<p>lorem ipsum filler without a trial CTA</p></body></html>"
            )
        }
    )
    dirty = evaluate_project_snapshot(
        violating.model_copy(
            update={
                "artifacts": tuple(
                    poster if a.artifact_id == "poster" else a for a in violating.artifacts
                )
            }
        )
    )
    dims = {r.dimension: r for r in dirty.dimension_results}
    assert dims[ConsistencyDimension.CHANNEL_REQUIREMENTS].passed is False
    assert dims[ConsistencyDimension.MESSAGE_COVERAGE].passed is False
    # <img> without alt → accessibility fails; html has lang → that check passes.
    assert dims[ConsistencyDimension.ACCESSIBILITY].passed is False
    access = errors_by_dimension(dirty, ConsistencyDimension.ACCESSIBILITY)
    assert access and "alt" in access[0].evidence


def test_prohibitive_decision_mention_is_not_shared_origin() -> None:
    # D2 says "never an app" — a prohibition. An artifact that uses "app" is
    # a local defect of that artifact only; classifying it as shared with D2
    # would wrongly route refinement to every consumer of a correct decision.
    base = _snapshot()
    violating = base.artifacts[4].model_copy(
        update={
            "content": (
                '<html lang="en"><body><h1>Meet your new workspace</h1>'
                "<p>Start your free trial with the Aurora app.</p></body></html>"
            )
        }
    )
    evaluation = evaluate_project_snapshot(
        base.model_copy(
            update={
                "artifacts": tuple(
                    violating if a.artifact_id == "website_copy" else a for a in base.artifacts
                )
            }
        )
    )
    terms = errors_by_dimension(evaluation, ConsistencyDimension.TERMINOLOGY)
    assert terms and "website_copy" in terms[0].evidence
    assert all(f.origin is FindingOrigin.LOCAL for f in terms)
    assert all(f.decision_id is None for f in terms)
    # Impact is the artifact's own local closure — never D2's other consumers.
    assert all("website_copy" in f.affected_artifact_ids for f in terms)
    assert all(not f.affected_decision_ids for f in terms)
    assert evaluation.refinement is not None
    assert "D2" not in evaluation.refinement.shared_decision_ids


def test_affirmative_decision_mention_is_still_shared_origin() -> None:
    # Positive control: when a decision *asserts* the marker (no negation),
    # origin detection must still classify the violation as shared.
    base = _snapshot()
    d3 = SharedDecision(
        decision_id="D3",
        version=1,
        kind="naming",
        statement="The product is the Aurora app.",
    )
    violating = base.artifacts[4].model_copy(
        update={
            "consumes": ("D3",),
            "content": (
                '<html lang="en"><body><h1>Meet the Aurora app</h1>'
                "<p>Start your free trial.</p></body></html>"
            ),
        }
    )
    evaluation = evaluate_project_snapshot(
        base.model_copy(
            update={
                "decisions": (*base.decisions, d3),
                "artifacts": tuple(
                    violating if a.artifact_id == "website_copy" else a for a in base.artifacts
                ),
            }
        )
    )
    terms = errors_by_dimension(evaluation, ConsistencyDimension.TERMINOLOGY)
    assert terms and terms[0].origin is FindingOrigin.SHARED
    assert terms[0].decision_id == "D3"


def test_design_system_compliance_flags_offpalette_colour() -> None:
    from maistro_design.consistency import DesignSystemSnapshot

    base = _snapshot()
    system = DesignSystemSnapshot(
        slug="aurora-brand",
        palette_hex=("#101010", "#f0f0f0"),
        banned_fonts=("Comic Sans",),
    )
    poster = base.artifacts[0].model_copy(
        update={
            "content": (
                '<html lang="en"><title>Aurora</title>'
                "<body style=\"color:#123456;font-family:'Comic Sans'\">"
                "<p>Start your free trial</p></body></html>"
            )
        }
    )
    evaluation = evaluate_project_snapshot(
        base.model_copy(
            update={
                "design_system": system,
                "artifacts": tuple(
                    poster if a.artifact_id == "poster" else a for a in base.artifacts
                ),
            }
        )
    )
    ds_errors = errors_by_dimension(evaluation, ConsistencyDimension.DESIGN_SYSTEM_COMPLIANCE)
    assert any("Comic Sans" in f.evidence for f in ds_errors)
    warnings = [
        f
        for f in evaluation.findings
        if f.dimension is ConsistencyDimension.DESIGN_SYSTEM_COMPLIANCE
        and f.severity is Severity.WARNING
    ]
    assert any("#123456" in f.evidence for f in warnings)


def test_clean_project_passes_every_dimension() -> None:
    base = _snapshot()
    fixed_decision = SharedDecision(
        decision_id="D1",
        version=3,
        kind="delivery-promise",
        statement="All plans include 48-hour turnaround.",
    )
    persona = PersonaSnapshot(
        persona_id="persona-meridian",
        name="Meridian",
        banned_markers=(r"guaranteed results",),
    )
    fixed_poster = base.artifacts[0].model_copy(
        update={
            "content": (
                '<html lang="en"><title>Aurora</title><body>'
                '<h1>Launch week signups</h1><img src="aurora.png" alt="Aurora launch">'
                "<p>Start your free trial — 48-hour turnaround.</p></body></html>"
            )
        }
    )
    fixed_social = base.artifacts[1].model_copy(
        update={"content": "Start your free trial — 48-hour turnaround for launch signups."}
    )
    fixed_hero = base.artifacts[2].model_copy(
        update={
            "content": (
                '<html lang="en"><body><h1>Aurora launch</h1>'
                "<p>Start your free trial. 48-hour turnaround.</p></body></html>"
            )
        }
    )
    evaluation = evaluate_project_snapshot(
        base.model_copy(
            update={
                "decisions": (fixed_decision, base.decisions[1]),
                "persona": persona,
                "artifacts": (
                    fixed_poster,
                    fixed_social,
                    fixed_hero,
                    base.artifacts[3],
                    base.artifacts[4],
                ),
            }
        )
    )
    assert evaluation.passed is True
    assert evaluation.refinement is None
    assert all(r.passed for r in evaluation.dimension_results)


# ─── 6/7. Canonical Run/NodeRun/Attempt provenance ───────────────────────────


async def test_evaluation_runs_as_canonical_graph_node_with_provenance() -> None:
    import maistro_design.nodes  # noqa: F401 — registers design.* node kinds
    from maistro.graph.durable_runs import (
        InMemoryDurableRunStore,
        RunStatus,
        run_durable_graph,
    )

    store = InMemoryDurableRunStore()
    graph = _eval_graph(_snapshot())

    record = await run_durable_graph(graph, store=store, node_resolver=_resolver)

    # The run itself succeeded: a failing *evaluation* is a successful
    # evaluation run. The verdict failure lives in the evaluation result.
    assert record.run.status is RunStatus.COMPLETED
    assert len(record.node_runs) == 1
    node_run = record.node_runs[0]
    assert node_run.node_id == "eval-1"
    assert node_run.status is RunStatus.COMPLETED
    assert len(record.attempts) == 1
    attempt = record.attempts[0]
    assert attempt.node_run_id == node_run.node_run_id
    assert attempt.result is not None

    result = attempt.result["output"]
    assert result["passed"] is False
    evaluation = result["evaluation"]
    assert evaluation["provenance"]["brief_version"] == 3
    assert evaluation["refinement"]["root_cause"] == "shared"
    assert evaluation["refinement"]["shared_decision_ids"] == ["D1"]
    assert set(result["proposed_refinement_artifact_ids"]) == {
        "poster",
        "social_copy",
        "landing_hero",
        "promo_banner",
    }
    # The evaluation node never mutated project state: the graph definition's
    # node inputs are the same snapshot we put in.
    assert graph.nodes[0].inputs["artifacts"][2]["locked"] is True


async def test_foreign_project_snapshot_is_rejected_not_misfiled() -> None:
    """A snapshot naming a different project must not be evaluated under this
    Run's project: the NodeRun/Attempt provenance would file project X's
    evaluation under project Y. The mismatch fails the node instead."""
    import maistro_design.nodes  # noqa: F401 — registers design.* node kinds
    from maistro.graph.durable_runs import (
        InMemoryDurableRunStore,
        RunStatus,
        run_durable_graph,
    )

    foreign = _snapshot().model_copy(update={"project_id": "proj-other"})
    store = InMemoryDurableRunStore()

    record = await run_durable_graph(_eval_graph(foreign), store=store, node_resolver=_resolver)

    assert record.run.status is RunStatus.FAILED
    assert record.node_runs[0].status is RunStatus.FAILED
    attempt = record.attempts[0]
    error_text = str(attempt.error or "") + str(attempt.result or "")
    assert "proj-other" in error_text
    assert "proj-aurora" in error_text
    # No evaluation output was produced, so nothing misfiled under proj-aurora.
    assert attempt.result is None or not (attempt.result.get("output") or {})


async def test_retry_after_refinement_preserves_failed_evaluation_record() -> None:
    import maistro_design.nodes  # noqa: F401 — registers design.* node kinds
    from maistro.graph.durable_runs import (
        InMemoryDurableRunStore,
        RunStatus,
        run_durable_graph,
    )

    store = InMemoryDurableRunStore()

    # First pass: evaluation fails on the shared contradiction.
    first = await run_durable_graph(_eval_graph(_snapshot()), store=store, node_resolver=_resolver)
    assert first.run.status is RunStatus.COMPLETED
    failed_evaluation = first.attempts[0].result["output"]["evaluation"]
    assert failed_evaluation["passed"] is False
    first_run_id = first.run.run_id
    first_node_run_id = first.node_runs[0].node_run_id
    first_attempt_id = first.attempts[0].attempt_id

    # Refinement happens through normal canonical Runs of the creative DAG
    # (here: fixed decision v3 and regenerated artifacts), then the project
    # is re-evaluated in a fresh Run.
    base = _snapshot()
    fixed = _snapshot(
        decisions=(
            SharedDecision(
                decision_id="D1",
                version=3,
                kind="delivery-promise",
                statement="All plans include 48-hour turnaround.",
            ),
            SharedDecision(
                decision_id="D2",
                version=1,
                kind="naming",
                statement="Call the product a workspace, never an app.",
            ),
        ),
        artifacts=(
            base.artifacts[0].model_copy(
                update={
                    # Poster regenerated as v2: persona marker gone, alt text
                    # added, evidence-backed promise only.
                    "version": 2,
                    "content": (
                        '<html lang="en"><title>Aurora</title><body>'
                        "<h1>Launch week signups</h1>"
                        '<img src="aurora.png" alt="Aurora launch">'
                        "<p>Start your free trial — 48-hour turnaround.</p>"
                        "</body></html>"
                    ),
                }
            ),
            base.artifacts[1].model_copy(
                update={"content": "Start your free trial — 48-hour turnaround for launch signups."}
            ),
            base.artifacts[2].model_copy(
                update={
                    "content": (
                        '<html lang="en"><body><h1>Aurora launch</h1>'
                        "<p>Start your free trial. 48-hour turnaround.</p>"
                        "</body></html>"
                    )
                }
            ),
            base.artifacts[3],
            base.artifacts[4],
        ),
    )
    second = await run_durable_graph(_eval_graph(fixed), store=store, node_resolver=_resolver)

    # Fresh execution identity for the retry — never a replay of the old one.
    assert second.run.run_id != first_run_id
    assert second.node_runs[0].node_run_id != first_node_run_id
    assert second.attempts[0].attempt_id != first_attempt_id
    assert second.run.status is RunStatus.COMPLETED
    assert second.attempts[0].result["output"]["passed"] is True

    # The failed evaluation record survives, retrievable by its own run id.
    preserved = await store.get(first_run_id)
    assert preserved is not None
    assert preserved.run.run_id == first_run_id
    assert preserved.attempts[0].attempt_id == first_attempt_id
    preserved_result = preserved.attempts[0].result["output"]
    assert preserved_result is not None
    assert preserved_result["passed"] is False
    assert preserved_result["evaluation"]["provenance"]["decision_versions"]["D1"] == 2
