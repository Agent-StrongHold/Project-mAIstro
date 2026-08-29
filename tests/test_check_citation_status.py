"""A governing citation must resolve to active authority (#374).

The registry linter asks whether a cited document exists. That is the weaker
question, and the gap is populated: at the time this was written, 47 governing
citations in the corpus named Superseded, Deprecated or merely Proposed
decisions as live authority, and nothing noticed.

The asymmetry these tests pin down is the substance. A `Proposed` document may
rest on anything — it has not shipped, so it governs nothing. An `Accepted` one
may not, because a reader takes it as describing what the system does now.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-citation-status.py"
LEDGER = ROOT / "quality" / "citation-baseline.json"

sys.path.insert(0, str(ROOT / "packages" / "maistro-registry" / "src"))

from maistro_registry.citations import (  # noqa: E402
    ACTIVE_AUTHORITY_STATUSES,
    GOVERNING_FIELDS,
    CitationBaseline,
    CitationProblem,
    check_citations,
)
from maistro_registry.schema import FrontMatter, Status  # noqa: E402


def _doc(
    doc_id: str,
    status: Status,
    *,
    kind: str = "adr",
    substrate: list[str] | None = None,
    implements: list[str] | None = None,
    related: list[str] | None = None,
    superseded_by: list[str] | None = None,
) -> FrontMatter:
    payload = {
        "id": doc_id,
        "title": f"Doc {doc_id}",
        "repo": "maistro-engine",
        "kind": kind,
        "status": status.value,
        "created": "2026-01-01",
        "history": [{"status": status.value, "date": "2026-01-01"}],
        "substrate": substrate or [],
        "implements": implements or [],
        "related": related or [],
        "superseded-by": superseded_by or [],
        "owners": ["@someone"],
        "layer": "Governance",
    }
    if status.value in {"Accepted", "Implemented", "Superseded", "Deprecated"}:
        payload["accepted"] = "2026-01-01"
    if status.value == "Implemented":
        payload["implemented"] = "2026-01-02"
    return FrontMatter.model_validate(payload)


def _ref(doc_id: str) -> str:
    return f"maistro-engine#{doc_id}"


# --- the rule, across the status combinations --------------------------------


@pytest.mark.parametrize("target_status", sorted(ACTIVE_AUTHORITY_STATUSES, key=str))
def test_active_authority_is_accepted(target_status: Status) -> None:
    target = _doc("ADR-002", target_status)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    assert check_citations([source, target]) == []


@pytest.mark.parametrize(
    "target_status",
    [Status.PROPOSED, Status.DEPRECATED, Status.DEFERRED, Status.DENIED],
)
def test_inactive_authority_is_refused(target_status: Status) -> None:
    target = _doc("ADR-002", target_status)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, target])

    assert len(problems) == 1
    assert target_status.value in problems[0].reason


def test_a_proposed_source_may_rest_on_a_proposed_decision() -> None:
    """The asymmetry, and the reason the check is not simply "both must be
    Accepted": a decision still being worked out governs nothing yet, so it is
    not making a false claim by citing another."""
    target = _doc("ADR-002", Status.PROPOSED)
    source = _doc("ADR-001", Status.PROPOSED, substrate=[_ref("ADR-002")])

    assert check_citations([source, target]) == []


@pytest.mark.parametrize("field_name", GOVERNING_FIELDS)
def test_both_governing_fields_are_checked(field_name: str) -> None:
    target = _doc("ADR-002", Status.PROPOSED)
    source = _doc("ADR-001", Status.ACCEPTED, **{field_name: [_ref("ADR-002")]})

    problems = check_citations([source, target])

    assert [p.field_name for p in problems] == [field_name]


def test_a_related_reference_to_an_inactive_decision_is_fine() -> None:
    """`related` orders work and points at neighbours; it claims no authority.
    Holding it to this rule would make it impossible to reference history at
    all, which is the escape hatch the error message recommends."""
    target = _doc("ADR-002", Status.DEPRECATED)
    source = _doc("ADR-001", Status.ACCEPTED, related=[_ref("ADR-002")])

    assert check_citations([source, target]) == []


def test_supersedes_is_not_held_to_the_rule() -> None:
    """Requiring the target of `supersedes` to be active would make every
    supersession self-contradictory: you supersede what is no longer live."""
    old = _doc("ADR-001", Status.SUPERSEDED, superseded_by=[_ref("ADR-002")])
    new = _doc("ADR-002", Status.ACCEPTED)

    assert check_citations([old, new]) == []


# --- supersession chains -----------------------------------------------------


def test_a_superseded_citation_names_its_active_replacement() -> None:
    """ "Superseded citations identify the active replacement" — so the error
    has to do the lookup, not just report that the target is Superseded."""
    old = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    new = _doc("ADR-003", Status.ACCEPTED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, old, new])

    assert len(problems) == 1
    assert "ADR-003" in problems[0].reason


def test_a_chain_is_followed_to_its_active_end() -> None:
    first = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    second = _doc("ADR-003", Status.SUPERSEDED, superseded_by=[_ref("ADR-004")])
    third = _doc("ADR-004", Status.ACCEPTED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, first, second, third])

    assert "ADR-004" in problems[0].reason


def test_a_supersession_cycle_is_reported_rather_than_looped() -> None:
    """A cycle has no depth at which it becomes legitimate, so the walk is
    bounded by a seen-set rather than a limit."""
    first = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    second = _doc("ADR-003", Status.SUPERSEDED, superseded_by=[_ref("ADR-002")])
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, first, second])

    assert "cycles" in problems[0].reason


def test_a_superseded_decision_naming_no_replacement_is_reported() -> None:
    orphan = _doc("ADR-002", Status.SUPERSEDED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, orphan])

    assert "names no replacement" in problems[0].reason


def test_a_chain_ending_somewhere_inactive_is_reported_at_its_end() -> None:
    """Reported where it actually broke, so the reader is not sent to the
    citation when the problem is three links away."""
    first = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    dead_end = _doc("ADR-003", Status.DEPRECATED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, first, dead_end])

    assert "ADR-003" in problems[0].reason
    assert "Deprecated" in problems[0].reason


def test_contradictory_active_replacements_are_refused() -> None:
    """ "Fails contradictory active authority": two live claimants to the same
    superseded decision is not a chain, it is a fork nobody can follow."""
    forked = _doc(
        "ADR-002",
        Status.SUPERSEDED,
        superseded_by=[_ref("ADR-003"), _ref("ADR-004")],
    )
    one = _doc("ADR-003", Status.ACCEPTED)
    two = _doc("ADR-004", Status.IMPLEMENTED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, forked, one, two])

    assert "more than one active replacement" in problems[0].reason


def test_a_citation_to_a_document_that_does_not_exist_is_left_to_the_linker() -> None:
    """One defect, one voice. `linker.check_links` already reports dangling
    references, and reporting them here too would double every such finding."""
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-999")])

    assert check_citations([source]) == []


# --- the ratchet -------------------------------------------------------------


def _problem(
    source: str = "a", field_name: str = "substrate", target: str = "b"
) -> CitationProblem:
    return CitationProblem(source=source, field_name=field_name, target=target, reason="why")


def test_a_baselined_citation_does_not_fail_the_gate() -> None:
    problem = _problem()
    baseline = CitationBaseline.of([problem])

    new, stale = baseline.partition([problem])

    assert new == []
    assert stale == []


def test_a_new_citation_fails_the_gate() -> None:
    baseline = CitationBaseline.of([_problem(target="b")])

    new, _stale = baseline.partition([_problem(target="b"), _problem(target="c")])

    assert [p.target for p in new] == ["c"]


def test_a_fixed_citation_must_shrink_the_ledger() -> None:
    """A stale entry silently absorbs the next regression at that citation,
    which is the failure mode every ledger here is shaped to avoid."""
    baseline = CitationBaseline.of([_problem(target="b"), _problem(target="c")])

    _new, stale = baseline.partition([_problem(target="b")])

    assert stale == ["a.substrate -> c"]


def test_the_baseline_is_keyed_on_the_citation_not_its_wording() -> None:
    """The reason is prose and will be reworded; keying on it would turn every
    improvement to an error message into a wave of phantom findings."""
    baseline = CitationBaseline.of([_problem()])
    reworded = CitationProblem(source="a", field_name="substrate", target="b", reason="different")

    new, stale = baseline.partition([reworded])

    assert new == []
    assert stale == []


# --- the gate as CI runs it --------------------------------------------------


def _gate_module():
    """Load the hyphenated script as a module, so its own lines are measured.

    A subprocess run proves the gate works and measures none of it — the diff
    gate treats `scripts/` as a coverage producer, and a new gate sitting at 0%
    is the same "written but never exercised" shape these ledgers exist to find.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_citation_status", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity_of(problem: CitationProblem) -> str:
    return f"{problem.source}.{problem.field_name} -> {problem.target}"


def test_the_gate_passes_on_the_committed_baseline() -> None:
    assert _gate_module().main([]) == 0


def test_the_gate_runs_as_a_script_too() -> None:
    """The in-process tests above measure it; this one proves the entry point
    a workflow actually invokes still works."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "active authority" in result.stdout


def test_the_gate_fails_when_a_new_citation_appears(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _gate_module()
    monkeypatch.setattr(module, "_load_baseline", lambda: CitationBaseline(entries=frozenset()))

    assert module.main([]) != 0
    assert "do not resolve to active authority" in capsys.readouterr().out


def test_the_gate_fails_when_the_ledger_is_stale(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _gate_module()
    current = module.check_citations(module._corpus())
    entries = frozenset({_identity_of(p) for p in current} | {"gone#A.substrate -> gone#B"})
    monkeypatch.setattr(module, "_load_baseline", lambda: CitationBaseline(entries=entries))

    assert module.main([]) != 0
    assert "no longer found" in capsys.readouterr().out


def test_updating_the_ledger_rewrites_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _gate_module()
    target = tmp_path / "citation-baseline.json"
    monkeypatch.setattr(module, "LEDGER", target)

    assert module.main(["--update"]) == 0

    written = json.loads(target.read_text())
    assert set(written["known"]) == set(written["reasons"])


def test_the_committed_baseline_records_a_reason_for_every_entry() -> None:
    """A ledger of bare identities would say what is wrong without saying why,
    and each of these is a governance judgement someone still has to make."""
    payload = json.loads(LEDGER.read_text())

    assert payload["known"], "the baseline is expected to be non-empty until #374 is burned down"
    assert set(payload["known"]) == set(payload["reasons"])
