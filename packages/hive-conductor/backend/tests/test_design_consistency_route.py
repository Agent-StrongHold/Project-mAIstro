"""The Design Studio's consistency inspection route (#779).

`POST /v1/design/projects/{id}/consistency` is the synchronous inspection
surface over the same pure evaluator the canonical graph node
(``design.consistency_eval``) runs inside a Run. These tests pin the route's
own end of the issue's contract:

- a planted Persona violation comes back as a failed evaluation whose
  refinement names only the affected branch;
- a shared factual contradiction names every consumer of the bad decision;
- a locked accepted artifact is reported (``requires_unlock``) and nothing in
  the response is a mutation — the evaluator proposes, it never rewrites;
- the result cites the exact brief/decision/artifact versions evaluated;
- a snapshot naming a different project than the path is refused, mirroring
  the graph node's canonical-provenance guard;
- the design service's startup outcome gates the route (503, not 500).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import HTTPException  # noqa: E402
from routes import design as design_routes  # noqa: E402

from maistro_design.consistency import (  # noqa: E402
    BriefSnapshot,
    ClaimRule,
    ContradictionRule,
    CreativeProjectSnapshot,
    EvidenceItem,
    FamilyArtifact,
    PersonaSnapshot,
    SharedDecision,
    TermRule,
)

pytestmark = [pytest.mark.contract("boundary")]

PROJECT_ID = "proj-aurora"


@pytest.fixture(autouse=True)
def ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """The design service's startup outcome, as the scope tests set it.

    The route reads the recorded status rather than reaching into the engine,
    so a test pins that status directly (the same seam test_design_scope.py
    uses); the 503 test re-pins it to a failed startup.
    """

    class _Status:
        ready = True
        cause = ""

    monkeypatch.setattr(design_routes, "get_design_status", lambda: _Status())


def _snapshot(project_id: str = PROJECT_ID, **overrides: Any) -> CreativeProjectSnapshot:
    """The Aurora family from the evaluator's own suite, route-sized.

    Two artifacts that consume the shared delivery-promise decision D1, one
    accepted+locked hero that consumes D1 too. ``d1_statement`` plants (or
    clears) the shared factual contradiction; the poster always carries the
    persona violation so tests can plant or clear defects independently.
    """
    d1_statement = overrides.pop("d1_statement", "All plans include 24-hour delivery.")
    fields: dict[str, Any] = {
        "project_id": project_id,
        "brief": BriefSnapshot(
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
        ),
        "persona": PersonaSnapshot(
            persona_id="persona-meridian",
            name="Meridian",
            banned_markers=(r"guaranteed results",),
            required_markers=(),
        ),
        "decisions": (
            SharedDecision(
                decision_id="D1",
                version=2,
                kind="delivery-promise",
                statement=d1_statement,
            ),
        ),
        "artifacts": (
            FamilyArtifact(
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
            ),
            FamilyArtifact(
                artifact_id="social_copy",
                version=1,
                kind="social",
                title="Launch social copy",
                content=(
                    "Launch week is here. Start your free trial. "
                    "All plans include 24-hour delivery."
                ),
                consumes=("D1",),
            ),
            FamilyArtifact(
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
            ),
        ),
        "evidence": (
            EvidenceItem(
                evidence_id="ev-turnaround",
                statement="All plans include 48-hour turnaround.",
            ),
        ),
    }
    fields.update(overrides)
    return CreativeProjectSnapshot(**fields)


async def _evaluate(snapshot: CreativeProjectSnapshot) -> dict[str, Any]:
    return await design_routes.evaluate_project_consistency(snapshot.project_id, snapshot)


def _target_ids(result: dict[str, Any]) -> list[str]:
    refinement = result.get("refinement")
    if refinement is None:
        return []
    return [target["artifact_id"] for target in refinement["targets"]]


# ─── A local defect routes only its own branch ───────────────────────────────


@pytest.mark.contract("behavioral")
@pytest.mark.ac("SPEC-100126-b779/AC-1")
async def test_persona_violation_proposes_only_the_affected_branch() -> None:
    """Clean shared decision, persona violation only in the poster: the
    refinement names exactly the poster branch — never the accepted hero or
    the sibling that shares no defect."""
    result = await _evaluate(_snapshot(d1_statement="All plans include 48-hour turnaround."))

    assert result["passed"] is False
    assert _target_ids(result) == ["poster"]
    assert result["refinement"]["root_cause"] == "local"
    assert result["refinement"]["shared_decision_ids"] == []
    persona_findings = [f for f in result["findings"] if f["dimension"] == "persona_voice"]
    assert [f["artifact_id"] for f in persona_findings] == ["poster"]
    assert all("guaranteed results" in f["evidence"] for f in persona_findings)


# ─── A shared defect invalidates every consumer ──────────────────────────────


@pytest.mark.ac("SPEC-100126-b779/AC-2")
async def test_shared_factual_contradiction_names_all_consumers_of_the_decision() -> None:
    """The contradiction lives in D1, which all three artifacts consume, so
    the refinement is rooted in the shared decision and names every consumer
    — impact from real ``consumes`` edges, not artifact kinds."""
    result = await _evaluate(_snapshot())

    assert result["passed"] is False
    assert result["refinement"]["root_cause"] == "shared"
    assert result["refinement"]["shared_decision_ids"] == ["D1"]
    assert set(_target_ids(result)) == {"poster", "social_copy", "landing_hero"}


# ─── Locked accepted work is reported, never rewritten ───────────────────────


@pytest.mark.ac("SPEC-100126-b779/AC-3")
async def test_locked_accepted_artifact_is_reported_and_not_rewritten() -> None:
    """The locked hero conflicts with the persona, so it is reported with an
    explicit unlock requirement — and the response is a proposal only: no
    rewritten content, no apply/execute action, and the snapshot the caller
    holds is untouched (the route never even opens a store)."""
    snapshot = _snapshot()
    before = snapshot.model_dump()
    result = await _evaluate(snapshot)

    hero_targets = [
        t
        for t in (result.get("refinement") or {}).get("targets", [])
        if t["artifact_id"] == "landing_hero"
    ]
    assert hero_targets, "the conflicting locked artifact must be a refinement target"
    assert all(target["requires_unlock"] for target in hero_targets)
    locked_findings = [
        f
        for f in result["findings"]
        if f["artifact_id"] == "landing_hero" and f["dimension"] == "locked_decisions"
    ]
    assert locked_findings, "the conflict must be reported, not silently skipped"
    # Proposal, never mutation: nothing in the contract carries rewritten
    # artifact content or an execution action.
    assert "content" not in (result.get("refinement") or {})
    assert snapshot.model_dump() == before


# ─── Results stay interpretable: exact versions are cited ────────────────────


@pytest.mark.ac("SPEC-100126-b779/AC-4")
async def test_result_cites_the_exact_versions_it_evaluated() -> None:
    result = await _evaluate(_snapshot())

    provenance = result["provenance"]
    assert provenance["brief_id"] == "brief-aurora"
    assert provenance["brief_version"] == 3
    assert provenance["goal_revision"] == "goal-rev-7"
    assert provenance["decision_versions"] == {"D1": 2}
    assert provenance["artifact_versions"] == {
        "poster": 1,
        "social_copy": 1,
        "landing_hero": 4,
    }
    assert provenance["evidence_ids"] == ["ev-turnaround"]


@pytest.mark.ac("SPEC-100126-b779/AC-4")
async def test_evaluation_is_inspectable_and_stable_across_calls() -> None:
    """Same snapshot in, same verdict out, so a later edit cannot silently
    reinterpret a stored result. The comparison projects away the two fields
    that are identities of the evaluation instance itself (evaluation_id and
    the per-finding ids) — every interpretable field must match exactly."""
    snapshot = _snapshot()
    first = await _evaluate(snapshot)
    second = await _evaluate(snapshot)

    def _stable(result: dict[str, Any]) -> dict[str, Any]:
        refinement = result["refinement"]
        if refinement is not None:
            refinement = {
                **refinement,
                "proposal_id": "<instance>",
                "targets": [
                    {k: v for k, v in target.items() if k != "finding_ids"}
                    for target in refinement["targets"]
                ],
            }
        return {
            "passed": result["passed"],
            "project_id": result["project_id"],
            "provenance": result["provenance"],
            "dimension_results": [
                {k: v for k, v in item.items() if k != "finding_ids"}
                for item in result["dimension_results"]
            ],
            "findings": [
                {k: v for k, v in finding.items() if k != "finding_id"}
                for finding in result["findings"]
            ],
            "refinement": refinement,
        }

    assert _stable(first) == _stable(second)
    assert first["evaluation_id"] != second["evaluation_id"]


# ─── A consistent family passes with no proposal ─────────────────────────────


@pytest.mark.ac("SPEC-100126-b779/AC-1")
async def test_consistent_family_passes_without_a_refinement_proposal() -> None:
    result = await _evaluate(
        _snapshot(
            d1_statement="All plans include 48-hour turnaround.",
            artifacts=(
                FamilyArtifact(
                    artifact_id="poster",
                    version=2,
                    kind="poster",
                    title="Launch poster",
                    content=(
                        '<html lang="en"><title>Aurora</title><body>'
                        "<h1>Launch week is here</h1>"
                        '<img src="aurora.png" alt="Aurora wordmark">'
                        "<p>Start your free trial — all plans include 48-hour turnaround.</p>"
                        "</body></html>"
                    ),
                    consumes=("D1",),
                ),
            ),
        )
    )

    assert result["passed"] is True
    assert result["refinement"] is None
    assert all(item["passed"] for item in result["dimension_results"])


# ─── The route's own guards ──────────────────────────────────────────────────


@pytest.mark.ac("SPEC-100126-b779/AC-6")
async def test_snapshot_for_another_project_is_refused_not_misfiled() -> None:
    """The graph node refuses a snapshot naming a different project than the
    Run's canonical project; the route applies the same guard against the
    path, so a result can never be inspected under the wrong project."""
    with pytest.raises(HTTPException) as excinfo:
        await design_routes.evaluate_project_consistency("proj-other", _snapshot())

    assert excinfo.value.status_code == 400
    assert "proj-other" in str(excinfo.value.detail)
    assert PROJECT_ID in str(excinfo.value.detail)


async def test_unready_design_service_answers_503(
    monkeypatch: pytest.MonkeyPatch, ready: None
) -> None:
    """The route asks the design service's startup outcome first, so a broken
    install reads "unavailable" (503) with its recorded cause — not a 500
    from a half-initialized dependency."""

    class _Status:
        ready = False
        cause = "design engine not initialized"

    monkeypatch.setattr(design_routes, "get_design_status", lambda: _Status())

    with pytest.raises(HTTPException) as excinfo:
        await design_routes.evaluate_project_consistency(PROJECT_ID, _snapshot())

    assert excinfo.value.status_code == 503
    assert "design engine not initialized" in str(excinfo.value.detail)
