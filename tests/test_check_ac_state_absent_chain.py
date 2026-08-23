"""The ADR → spec → AC chain, measured where it is *absent* (#164).

Every other check in this repository verifies a link that exists. The registry
refuses dangling references, duplicate ids and `supersedes`/`blocks` cycles, so
every link in the corpus is real — and `implements: []` is valid front matter,
nothing asks whether an ADR has any spec implementing it, and nothing asks
whether a spec has any criteria. A spec implementing nothing and a decision
nothing implements were both perfectly clean. "Specs map to ADRs" read as
"specs do not *mis*-map to ADRs", which is a much weaker claim.

These pin the four acceptance bullets of #164. The counters are enforced by the
existing ratchet rather than by a gate of their own, so "fails CI" means
"raises a counter past its ceiling" — `test_check_ac_state_ratchet.py` owns the
ratchet's own behaviour, and the cases here own what it is handed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_ac_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def corpus(gate, tmp_path, monkeypatch):
    """A throwaway docs tree, so a case describes only the documents it names."""
    spec_dir = tmp_path / "specs"
    adr_dir = tmp_path / "adr"
    spec_dir.mkdir()
    adr_dir.mkdir()
    monkeypatch.setattr(gate, "SPEC_DIR", spec_dir)
    monkeypatch.setattr(gate, "ADR_DIR", adr_dir)
    # `collect_specs` records each document's path relative to ROOT, which
    # raises for anything outside it. The real dirs always sit under the repo;
    # a throwaway one has to move ROOT with them.
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    def write_spec(
        spec_id: str,
        *,
        implements: list[str] | None = None,
        non_measurable: str | None = None,
        criteria: int = 0,
        ac_heading: bool = True,
    ) -> None:
        # Built line by line rather than with a dedented f-string: interpolating
        # a multi-line block into a dedented literal destroys the common indent
        # and silently produces front matter that parses as something else.
        lines = [
            "---",
            f"id: {spec_id}",
            'title: "t"',
            "repo: maistro-engine",
            "kind: spec",
            "status: Proposed",
            "created: 2026-08-23",
        ]
        if implements:
            lines.append("implements:")
            lines += [f"  - maistro-engine#{ref}" for ref in implements]
        else:
            lines.append("implements: []")
        if non_measurable:
            lines.append(f"non-measurable: {non_measurable}")
        lines += ["layer: Foundation", "---", "", f"# {spec_id}", ""]
        if ac_heading:
            lines += ["## Acceptance criteria", ""]
            lines += (
                [f"- [ ] **AC-{n}** it does the thing" for n in range(1, criteria + 1)]
                if criteria
                else ["Prose, no ids yet."]
            )
            lines.append("")
        (spec_dir / f"{spec_id}.md").write_text("\n".join(lines), encoding="utf-8")

    def write_adr(adr_id: str, *, status: str = "Accepted") -> None:
        (adr_dir / f"{adr_id}.md").write_text(
            "\n".join(
                [
                    "---",
                    f"id: {adr_id}",
                    'title: "t"',
                    "repo: maistro-engine",
                    "kind: adr",
                    f"status: {status}",
                    "created: 2026-08-23",
                    "layer: Foundation",
                    "---",
                    "",
                    f"# {adr_id}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def measure() -> dict[str, list]:
        specs = gate.collect_specs(markers={}, unreachable=set(), passing=None)
        adrs = gate.collect_adrs(specs, markers={}, unreachable=set(), passing=None)
        return gate.absent_chain(specs, adrs)

    corpus.spec = write_spec
    corpus.adr = write_adr
    corpus.measure = measure
    return corpus


# --------------------------------------------------------------------------
# "A new spec that names no ADR fails CI"
# --------------------------------------------------------------------------


def test_a_spec_naming_no_adr_is_counted(corpus):
    corpus.adr("ADR-001")
    corpus.spec("SPEC-001", implements=[])

    assert corpus.measure()["specs_implementing_nothing"] == ["SPEC-001"]


def test_a_spec_naming_an_adr_is_not_counted(corpus):
    corpus.adr("ADR-001")
    corpus.spec("SPEC-001", implements=["ADR-001"])

    assert corpus.measure()["specs_implementing_nothing"] == []


# --------------------------------------------------------------------------
# "A newly Accepted ADR with no implementing spec fails CI"
# --------------------------------------------------------------------------


def test_an_accepted_adr_nothing_implements_is_counted(corpus):
    corpus.adr("ADR-001", status="Accepted")
    corpus.spec("SPEC-001", implements=[])

    assert corpus.measure()["decided_adrs_without_spec"] == ["ADR-001"]


def test_a_proposed_adr_is_exempt(corpus):
    """A decision not yet taken cannot be owed an implementation."""
    corpus.adr("ADR-001", status="Proposed")

    assert corpus.measure()["decided_adrs_without_spec"] == []


def test_an_implemented_adr_nothing_implements_is_counted(corpus):
    """`Implemented` is the strictly stronger claim than `Accepted`: an ADR
    asserting the work is done, with no spec naming it, is a worse version of
    the same hole rather than an exempt one."""
    corpus.adr("ADR-001", status="Implemented")

    assert corpus.measure()["decided_adrs_without_spec"] == ["ADR-001"]


def test_one_implementing_spec_satisfies_the_adr(corpus):
    corpus.adr("ADR-001")
    corpus.spec("SPEC-001", implements=["ADR-001"])

    assert corpus.measure()["decided_adrs_without_spec"] == []


def test_the_reverse_index_is_built_from_the_specs_own_front_matter(corpus):
    """Scope item 5. Under `ADR-062026-9b30` date-based ids, two concurrent PRs
    can add specs implementing the same ADR without colliding — which only holds
    if the index is recomputed from content rather than read from a generated
    file somebody has to regenerate. Adding the spec is the whole fix here: no
    other artefact is touched, and the ADR stops being owed one immediately."""
    corpus.adr("ADR-062026-9b30")
    assert corpus.measure()["decided_adrs_without_spec"] == ["ADR-062026-9b30"]

    corpus.spec("SPEC-081523-aaaa", implements=["ADR-062026-9b30"])
    assert corpus.measure()["decided_adrs_without_spec"] == []


# --------------------------------------------------------------------------
# "A new spec with no criteria fails CI unless it declares itself
#  non-measurable, with a reason"
# --------------------------------------------------------------------------


def test_a_spec_with_no_criteria_is_counted(corpus):
    corpus.spec("SPEC-001", implements=["ADR-001"], criteria=0)

    assert corpus.measure()["specs_owing_criteria"] == ["SPEC-001"]


def test_a_spec_with_criteria_is_not_counted(corpus):
    corpus.spec("SPEC-001", implements=["ADR-001"], criteria=2)

    assert corpus.measure()["specs_owing_criteria"] == []


def test_a_waiver_retires_the_debt(corpus):
    corpus.spec(
        "SPEC-001",
        implements=["ADR-001"],
        criteria=0,
        non_measurable="A governance narrative with no runtime surface to assert on",
    )

    assert corpus.measure()["specs_owing_criteria"] == []


def test_a_waiver_retires_both_counters_at_once(corpus):
    """`specs_awaiting_retrofit` is the subset that wrote a heading and never
    gave the bullets ids. If a waiver left it standing, banking one waiver would
    be a fall in one counter and a stubborn number in the other — and the spec
    would still be described as mid-conversion when it has been resolved."""
    corpus.spec(
        "SPEC-001",
        implements=["ADR-001"],
        criteria=0,
        ac_heading=True,
        non_measurable="A governance narrative with no runtime surface to assert on",
    )
    measured = corpus.measure()

    assert measured["specs_owing_criteria"] == []
    assert measured["specs_awaiting_retrofit"] == []


def test_a_waived_spec_is_reported_with_its_reason(corpus):
    """The waiver is the one place the debt is retired by prose rather than by
    artefacts, so the prose has to be visible where the counters are read."""
    reason = "A governance narrative with no runtime surface to assert on"
    corpus.spec("SPEC-001", implements=["ADR-001"], criteria=0, non_measurable=reason)

    waived = corpus.measure()["specs_waiving_criteria"]
    assert [s["id"] for s in waived] == ["SPEC-001"]
    assert waived[0]["non_measurable"] == reason


def test_a_spec_with_no_ac_heading_at_all_is_still_counted(corpus):
    """The ambiguity `specs_awaiting_retrofit` absorbed: it only sees documents
    that wrote a heading, so seven specs with no heading at all were owed
    criteria and appeared in no counter."""
    corpus.spec("SPEC-001", implements=["ADR-001"], criteria=0, ac_heading=False)
    measured = corpus.measure()

    assert measured["specs_owing_criteria"] == ["SPEC-001"]
    assert measured["specs_awaiting_retrofit"] == []


# --------------------------------------------------------------------------
# "Pre-existing violations are enumerated" / "the counters appear in the same
#  report as the rest of the AC state"
# --------------------------------------------------------------------------


def test_all_three_counters_are_ratcheted(gate):
    """The enforcement is the ratchet, so a counter outside RATCHETED is
    measured and reported and stops nothing."""
    for name in ("specs_implementing_nothing", "decided_adrs_without_spec", "specs_owing_criteria"):
        assert name in gate.RATCHETED


def test_the_shipped_report_enumerates_and_not_only_counts(gate):
    """A ceiling of 76 says how much debt there is and nothing about which
    document to pick up next."""
    import json

    payload = json.loads((ROOT / "quality" / "ac-state.json").read_text(encoding="utf-8"))
    for name in ("specs_implementing_nothing", "decided_adrs_without_spec", "specs_owing_criteria"):
        assert len(payload[name]) == payload["totals"][name]
        assert all(isinstance(entry, str) for entry in payload[name])
