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
from maistro_registry.validator import validate_file  # noqa: E402


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
    sorted(
        (status for status in Status if status not in ACTIVE_AUTHORITY_STATUSES),
        key=str,
    ),
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


@pytest.mark.parametrize("source_status", sorted(Status, key=str))
@pytest.mark.parametrize("target_status", sorted(Status, key=str))
def test_only_active_sources_claim_live_authority(
    source_status: Status, target_status: Status
) -> None:
    # Independent policy oracle: changing production's status sets must not
    # silently change the expected answers in this exhaustive truth table.
    active_source = source_status in {
        Status.ACCEPTED,
        Status.FULLY_SPECCED,
        Status.AC_DEFINED,
        Status.IN_PROGRESS,
        Status.TESTS_PASSING,
        Status.IMPLEMENTED,
    }
    active_target = target_status in {Status.ACCEPTED, Status.IMPLEMENTED}

    target = _doc("ADR-002", target_status)
    source = _doc("ADR-001", source_status, substrate=[_ref("ADR-002")])

    problems = check_citations([source, target])

    assert bool(problems) is (active_source and not active_target)


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


@pytest.mark.parametrize("replacement_status", [Status.ACCEPTED, Status.IMPLEMENTED])
def test_contradictory_active_replacements_with_same_status_are_refused(
    replacement_status: Status,
) -> None:
    """Two live claimants remain contradictory even when their statuses match."""
    forked = _doc(
        "ADR-002",
        Status.SUPERSEDED,
        superseded_by=[_ref("ADR-003"), _ref("ADR-004")],
    )
    one = _doc("ADR-003", replacement_status)
    two = _doc("ADR-004", replacement_status)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, forked, one, two])

    assert "more than one active replacement" in problems[0].reason


def test_contradictory_active_replacements_are_refused() -> None:
    """Two live claimants to the same superseded decision are a fork."""
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


def test_all_supersession_branches_are_checked_for_contradictory_authority() -> None:
    """An immediate active replacement must not hide an active grandchild."""
    forked = _doc(
        "ADR-002",
        Status.SUPERSEDED,
        superseded_by=[_ref("ADR-003"), _ref("ADR-004")],
    )
    direct = _doc("ADR-003", Status.ACCEPTED)
    indirect = _doc("ADR-004", Status.SUPERSEDED, superseded_by=[_ref("ADR-005")])
    grandchild = _doc("ADR-005", Status.ACCEPTED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    problems = check_citations([source, forked, direct, indirect, grandchild])

    assert len(problems) == 1
    assert "more than one active replacement" in problems[0].reason
    assert "ADR-003" in problems[0].reason
    assert "ADR-005" in problems[0].reason


def test_supersession_transition_requires_the_new_active_replacement() -> None:
    """A replacement is invalid while Proposed and valid once Accepted."""
    superseded = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    proposed = _doc("ADR-003", Status.PROPOSED)
    source = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-002")])

    before = check_citations([source, superseded, proposed])
    after = check_citations([source, superseded, _doc("ADR-003", Status.ACCEPTED)])

    assert len(before) == 1
    assert "Proposed" in before[0].reason
    assert after[0].target == _ref("ADR-002")
    assert "ADR-003" in after[0].reason

    retargeted = _doc("ADR-001", Status.ACCEPTED, substrate=[_ref("ADR-003")])
    assert check_citations([retargeted, superseded, proposed])
    assert check_citations([retargeted, superseded, _doc("ADR-003", Status.ACCEPTED)]) == []


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


def test_the_matrix_governing_column_rejects_a_proposed_authority(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-002 | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    problems = module._matrix_problems([_doc("ADR-002", Status.PROPOSED)])

    assert len(problems) == 1
    assert problems[0].source == "matrix#Demo"
    assert problems[0].field_name == "governing"
    assert "Proposed" in problems[0].reason


def test_the_matrix_historical_supersession_note_is_not_governing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-003 (supersedes ADR-002) | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    old = _doc("ADR-002", Status.SUPERSEDED)
    new = _doc("ADR-003", Status.ACCEPTED)

    assert module._matrix_problems([old, new]) == []


def test_the_matrix_authority_after_historical_parenthetical_is_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-002 (historical ADR-001), ADR-003 | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    historical = _doc("ADR-002", Status.ACCEPTED)
    proposed = _doc("ADR-003", Status.PROPOSED)

    problems = module._matrix_problems([historical, proposed])

    assert len(problems) == 1
    assert problems[0].target == _ref("ADR-003")
    assert "Proposed" in problems[0].reason


def test_the_matrix_unqualified_parenthetical_is_governing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bare ``(ADR-002)`` asserts no historical relation, so its ID is held
    to the same authority rule as the rest of the governing column. Dropping
    it silently would let a Proposed decision govern from behind punctuation."""
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-001 (ADR-002) | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    accepted = _doc("ADR-001", Status.ACCEPTED)
    proposed = _doc("ADR-002", Status.PROPOSED)

    problems = module._matrix_problems([accepted, proposed])

    assert len(problems) == 1
    assert problems[0].target == _ref("ADR-002")
    assert "Proposed" in problems[0].reason


def test_the_matrix_unqualified_parenthetical_with_active_target_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-001 (ADR-002) | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    assert (
        module._matrix_problems(
            [_doc("ADR-001", Status.ACCEPTED), _doc("ADR-002", Status.ACCEPTED)]
        )
        == []
    )


@pytest.mark.parametrize(
    ("note", "qualifier"),
    [
        ("supersedes ADR-002", "supersession"),
        ("historical ADR-002", "historical"),
        ("formerly ADR-002", "former name"),
        ("proposed in ADR-002", "provenance"),
    ],
)
def test_the_matrix_explicitly_qualified_notes_stay_exempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, note: str, qualifier: str
) -> None:
    """Historical and provenance notes remain possible -- but only when they
    name their own relation, so they cannot be mistaken for normative."""
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        f"| Demo | entry | `none` | KEEP | ADR-001 ({note}) | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    accepted = _doc("ADR-001", Status.ACCEPTED)
    proposed = _doc("ADR-002", Status.PROPOSED)

    assert module._matrix_problems([accepted, proposed]) == [], qualifier


@pytest.mark.parametrize(
    "note",
    [
        "historical ADR-002; ADR-003",
        "ADR-003; historical ADR-002",
        "historical ADR-002; governs ADR-003",
        "historical ADR-002, governing ADR-003",
        "historical ADR-002 (ADR-003)",
        "(historical ADR-002) ADR-003",
        "historical ADR-002 and ADR-003",
        "ADR-003 with historical context",
        "historical background for ADR-003",
    ],
)
@pytest.mark.parametrize(
    "target_status", [Status.PROPOSED, Status.DEPRECATED, Status.SUPERSEDED, Status.ACCEPTED]
)
def test_matrix_relation_does_not_exempt_unqualified_neighbor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    note: str,
    target_status: Status,
) -> None:
    """Drive the CI entry point, not just the parser, with mixed relation scopes."""
    module = _gate_module()
    matrix = tmp_path / "matrix.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Governing ADR/spec |\n"
        "|---|---|\n"
        f"| Demo | ADR-001 ({note}) |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)
    monkeypatch.setattr(module, "LEDGER", tmp_path / "absent-ledger.json")
    corpus = [
        _doc("ADR-001", Status.ACCEPTED),
        _doc("ADR-002", Status.PROPOSED),
        _doc("ADR-003", target_status, superseded_by=[_ref("ADR-004")]),
        _doc("ADR-004", Status.ACCEPTED),
    ]
    monkeypatch.setattr(module, "_corpus", lambda: corpus)

    problems = module._matrix_problems(corpus)
    if target_status is Status.ACCEPTED:
        assert problems == []
        assert module.main([]) == 0
    else:
        assert [p.target for p in problems] == [_ref("ADR-003")]
        assert target_status.value in problems[0].reason
        assert module.main([]) == 1
        output = capsys.readouterr().out
        assert "matrix#Demo.governing -> maistro-engine#ADR-003" in output
        if target_status is Status.SUPERSEDED:
            assert "ADR-004" in output


@pytest.mark.parametrize(
    "note",
    [
        "historical ADR-002; proposed in SPEC-003",
        "historical ADR-002 (proposed in SPEC-003)",
        "tournament contracts Proposed in ADR-002, SPEC-003",
    ],
)
def test_matrix_explicit_relations_and_comma_lists_remain_historical(note: str) -> None:
    """A comma-only list shares its relation; new clauses need their own."""
    assert _gate_module()._governing_ids(f"ADR-001 ({note})") == ["ADR-001"]


def test_the_matrix_unqualified_parenthetical_superseded_names_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-001 (ADR-002) | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    old = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    accepted = _doc("ADR-001", Status.ACCEPTED)
    new = _doc("ADR-003", Status.ACCEPTED)

    problems = module._matrix_problems([accepted, old, new])

    assert len(problems) == 1
    assert problems[0].target == _ref("ADR-002")
    assert "ADR-003" in problems[0].reason


def test_the_matrix_superseded_authority_names_the_active_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _gate_module()
    matrix = tmp_path / "CONVERGENCE-MATRIX.md"
    matrix.write_text(
        "<!-- matrix:disposition -->\n"
        "| Subsystem | Real entry point | Unreachable | Disposition | Governing ADR/spec | Acceptance evidence | Dependencies |\n"
        "|---|---|---|---|---|---|---|\n"
        "| Demo | entry | `none` | KEEP | ADR-002 | evidence | — |\n"
    )
    monkeypatch.setattr(module, "MATRIX", matrix)

    old = _doc("ADR-002", Status.SUPERSEDED, superseded_by=[_ref("ADR-003")])
    new = _doc("ADR-003", Status.ACCEPTED)

    problems = module._matrix_problems([old, new])

    assert len(problems) == 1
    assert "ADR-003" in problems[0].reason


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
    monkeypatch.setattr(module, "check_citations", lambda _corpus: [_problem()])

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


@pytest.mark.parametrize(
    ("spec_name", "target_id", "in_related", "status_note"),
    [
        ("SPEC-070226-af02-p1-resilience-control.md", "ADR-066", False, "remains Proposed"),
        ("SPEC-070226-2b70-observability-replay-pii-tiers.md", "ADR-055", True, "remains Proposed"),
        (
            "SPEC-062126-d421-medley-import-sanitization-pipeline.md",
            "ADR-083",
            True,
            "remains Proposed",
        ),
        ("SPEC-070226-6489-identity-lifecycle.md", "ADR-084", True, "remains Proposed"),
        ("SPEC-070226-82ea-builders-dag.md", "ADR-099", True, "remains Proposed"),
        ("SPEC-070226-b234-events-triggers-reactor.md", "ADR-086", True, "remains Proposed"),
        ("SPEC-070226-b624-orchestrator-waves.md", "ADR-071", True, "remains Proposed"),
        ("SPEC-070226-c4f8-hierarchical-orchestration.md", "ADR-101", True, "remains Proposed"),
        ("SPEC-070226-cb8d-llm-provider-registry.md", "ADR-079", True, "remains Proposed"),
        ("SPEC-070226-fbe3-deployment-topology.md", "ADR-081", True, "remains Proposed"),
        # Fourth wave: the same laundering shape with Deprecated ADR and Proposed
        # SPEC targets — the front-matter move silenced the gate, the prose had
        # to carry the status honestly too.
        ("SPEC-254-shadow-git-workspace.md", "ADR-049", True, "is Deprecated"),
        ("SPEC-255-parallel-wave-fan-in.md", "ADR-052", True, "is Deprecated"),
        (
            "SPEC-062126-d421-medley-import-sanitization-pipeline.md",
            "SPEC-005",
            True,
            "remains Proposed",
        ),
        ("SPEC-182-a2a-delegation-implementation.md", "ADR-058", True, "remains Proposed"),
    ],
)
def test_proposed_related_design_is_marked_historical_not_governing(
    spec_name: str, target_id: str, in_related: bool, status_note: str
) -> None:
    """A related link cannot smuggle a non-active decision into shipped prose.

    Moving a governing citation to `related` silences the front-matter check,
    so the prose has to carry the status honestly: the citation stays (history
    remains citable) but the body must say the authority is not live. Each
    entry here is a document where an active spec treated a Proposed or
    Deprecated decision as realised, governing fact — the exact laundering
    #374 names. The status language must name the target's actual state
    (`status_note`), and no present-tense governing verb may attach to it.
    """
    path = ROOT / "docs" / "specs" / spec_name
    result = validate_file(path)

    assert result.front_matter is not None
    assert (_ref(target_id) in result.front_matter.related) is in_related

    body = " ".join(path.read_text().split("\n---", 2)[-1].split())
    assert f"{target_id} {status_note}" in body
    assert "design context only" in body
    assert "not shipped authority" in body
    for normative in ("says", "specifies", "mandates", "requires", "defines", "governs"):
        assert f"{target_id} {normative}" not in body


def test_the_committed_baseline_records_a_reason_for_every_entry() -> None:
    """The ledger may be empty after cleanup, but its identity/reason maps stay aligned."""
    payload = json.loads(LEDGER.read_text())

    assert set(payload["known"]) == set(payload["reasons"])
