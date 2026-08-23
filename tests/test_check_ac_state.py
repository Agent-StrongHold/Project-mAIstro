"""Tests for the acceptance-criterion state derivation.

The script's whole purpose is to stop a document asserting more than its
artefacts support, so the properties worth testing are the ones where it could
quietly assert too much itself: a criterion must not reach `reachable` without
both a passing test and a module the reachability graph can get to, and a
suite that never ran must report `unmeasured` rather than "not passing".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_ac_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _criterion(check, **kwargs):
    return check.Criterion(ac_id="SPEC-000/AC-1", **kwargs)


class TestLadder:
    def test_no_test_is_only_declared(self, check):
        assert _criterion(check).rung(set()) == "declared"

    def test_a_test_that_did_not_pass_stops_at_covered(self, check):
        c = _criterion(check, covered_by=["t.py"], module="maistro.ok", passing=False)
        assert c.rung(set()) == "covered"

    def test_an_unmeasured_run_stops_at_covered(self, check):
        """`passing=None` is "we did not look", and must not read as proven."""
        c = _criterion(check, covered_by=["t.py"], module="maistro.ok", passing=None)
        assert c.rung(set()) == "covered"

    def test_passing_without_a_module_never_reaches_reachable(self, check):
        """A green test proves the code works, not that anything runs it.

        tick_decay, elevation_store and the security pipeline were all green and
        all unreachable. Reporting an unannotated criterion as reachable would
        reproduce exactly that, having built the rung that exists to catch it.
        """
        c = _criterion(check, covered_by=["t.py"], module=None, passing=True)
        assert c.rung(set()) == "passing"

    def test_passing_but_unreachable_module_stops_at_passing(self, check):
        c = _criterion(check, covered_by=["t.py"], module="maistro.dead", passing=True)
        assert c.rung({"maistro.dead"}) == "passing"

    def test_a_baselined_ancestor_package_sinks_the_module(self, check):
        """Nothing imports `maistro.dead`, so `maistro.dead.leaf` is dead too."""
        c = _criterion(check, covered_by=["t.py"], module="maistro.dead.leaf", passing=True)
        assert c.rung({"maistro.dead"}) == "passing"

    def test_passing_and_reachable_is_the_top_rung(self, check):
        c = _criterion(check, covered_by=["t.py"], module="maistro.live", passing=True)
        assert c.rung({"maistro.dead"}) == "reachable"


class TestTierFold:
    def test_the_tier_is_the_weakest_criterion(self, check):
        """One lagging criterion holds the whole document down, on purpose."""
        assert check.tier_of(["reachable", "reachable", "declared"]) == "declared"

    def test_all_reachable_folds_to_reachable(self, check):
        assert check.tier_of(["reachable", "reachable"]) == "reachable"

    def test_no_criteria_is_none_not_a_rung(self, check):
        """A document with nothing to measure is unmeasured, never complete."""
        assert check.tier_of([]) == "none"


class TestMarkerScan:
    def test_a_marker_in_a_docstring_is_not_a_claim(self, check, tmp_path):
        """Parsed, not grepped.

        `test_spec_tracker.py` documents the marker format in its own module
        docstring. A regex reports that prose as a claim on `SPEC-x`, a spec
        that does not exist — a tool built to find false assertions opening by
        making one.
        """
        (tmp_path / "test_sample.py").write_text(
            '"""Docs say @pytest.mark.ac("SPEC-x/AC-n") is the format."""\n'
            "import pytest\n\n"
            '@pytest.mark.ac("SPEC-001/AC-1")\n'
            "def test_real() -> None:\n    pass\n",
            encoding="utf-8",
        )
        found = check.scan_markers([tmp_path])
        assert set(found) == {"SPEC-001/AC-1"}

    def test_one_file_is_listed_once_however_many_tests_claim_it(self, check, tmp_path):
        (tmp_path / "test_sample.py").write_text(
            "import pytest\n\n"
            '@pytest.mark.ac("SPEC-001/AC-1")\n'
            "def test_a() -> None:\n    pass\n\n"
            '@pytest.mark.ac("SPEC-001/AC-1")\n'
            "def test_b() -> None:\n    pass\n",
            encoding="utf-8",
        )
        assert check.scan_markers([tmp_path])["SPEC-001/AC-1"] == [str(tmp_path / "test_sample.py")]

    def test_a_file_that_does_not_parse_is_skipped_not_fatal(self, check, tmp_path):
        (tmp_path / "test_broken.py").write_text("def (\n", encoding="utf-8")
        assert check.scan_markers([tmp_path]) == {}


class TestConfiguredRoots:
    def test_roots_come_from_pyproject_not_a_hand_written_list(self, check):
        """A hand-written `packages/` root collects the canvas frontend suites,
        which abort the session at import — and every criterion then reads
        `covered` with nothing saying the run never happened."""
        roots = check.configured_test_roots()
        assert roots, "testpaths resolved to nothing"
        assert all(r.is_absolute() for r in roots)
        assert not any(r == check.ROOT / "packages" for r in roots)


GHERKIN_SPEC = """
```gherkin
Feature: Example

  @AC-1
  Scenario: A tagged scenario with an outcome
    Given a precondition
    When something happens
    Then something observable is true

  @AC-2 @slow
  Scenario: Extra tags do not confuse the id
    Given a precondition
    Then it holds

  @AC-1
  Scenario: A second scenario for the same criterion
    Given another precondition
    Then it also holds

  Scenario: An untagged scenario is not addressable
    Given a precondition
    Then it holds

  @AC-3
  Scenario: No Then, so nothing falsifiable
    Given a precondition
    When something happens
```
"""


class TestGherkin:
    def test_tags_are_the_identity_not_scenario_names(self, check):
        """Names get reworded; a reworded name would silently break the binding
        to the test claiming it, dropping the criterion to `declared` with
        nothing saying why."""
        tagged, _, errors = check.gherkin_criteria(GHERKIN_SPEC)
        assert not errors
        assert set(tagged) == {"AC-1", "AC-2", "AC-3"}

    def test_one_criterion_may_have_several_scenarios(self, check):
        """A table of cases plus an edge case is still one criterion. Keying a
        single scenario per tag drops all but the last and reports a smaller
        corpus than exists."""
        tagged, _, _ = check.gherkin_criteria(GHERKIN_SPEC)
        assert len(tagged["AC-1"]) == 2

    def test_an_untagged_scenario_is_reported_not_silently_dropped(self, check):
        _, untagged, _ = check.gherkin_criteria(GHERKIN_SPEC)
        assert untagged == ["An untagged scenario is not addressable"]

    def test_a_scenario_with_no_then_states_no_observable_outcome(self, check):
        tagged, _, _ = check.gherkin_criteria(GHERKIN_SPEC)
        assert tagged["AC-3"][0]["has_outcome"] is False
        assert tagged["AC-1"][0]["has_outcome"] is True

    def test_a_block_without_a_feature_line_still_parses(self, check):
        """Most of the corpus writes bare `Scenario:` blocks with no Feature."""
        tagged, _, errors = check.gherkin_criteria(
            "```gherkin\n@AC-9\nScenario: Bare\n  Given x\n  Then y\n```"
        )
        assert not errors
        assert set(tagged) == {"AC-9"}

    def test_a_malformed_block_is_an_error_not_an_exception(self, check):
        """An unenforced convention drifts; the gate must survive the drift it
        exists to report."""
        _, _, errors = check.gherkin_criteria(
            "```gherkin\nScenario: Broken\n  Given x\n    bare indented prose\n```"
        )
        assert len(errors) == 1

    def test_the_committed_corpus_has_no_new_parse_failures(self, check):
        """A floor, deliberately: the four known-bad blocks are fixed in this
        change, so the corpus parses clean and any regression is visible."""
        specs = check.collect_specs(check.scan_markers([]), set(), None)
        adrs = check.collect_adrs(specs, {}, set(), None)
        bad = [d["id"] for d in (*specs, *adrs) if d["gherkin_parse_errors"]]
        assert bad == []


class TestNonMeasurableMarker:
    """The escape hatch for a spec that legitimately has no criteria (#164).

    An opt-out that costs nothing is a way to make a counter fall without doing
    anything, so the marker is only honoured when it carries a reason.
    """

    def test_a_marker_with_a_reason_is_recognised(self, check):
        assert check.declares_non_measurable(
            "<!-- ac-state: non-measurable - a glossary, nothing to assert -->"
        )

    def test_an_em_dash_reads_the_same_as_a_hyphen(self, check):
        """Markdown tooling and humans both produce the em dash; rejecting it
        would make the hatch depend on which one somebody typed."""
        assert check.declares_non_measurable("<!-- ac-state: non-measurable — because -->")

    def test_the_marker_is_case_insensitive(self, check):
        assert check.declares_non_measurable("<!-- AC-State: Non-Measurable: because -->")

    def test_a_marker_with_no_reason_does_not_count(self, check):
        """The whole point of the hatch is that it justifies itself."""
        assert not check.declares_non_measurable("<!-- ac-state: non-measurable -->")
        assert not check.declares_non_measurable("<!-- ac-state: non-measurable -  -->")

    def test_a_reasonless_marker_cannot_borrow_a_later_comment(self, check):
        """The bug this test exists for, found in review.

        The delimiter class matches the first hyphen of the marker's own `-->`,
        and under DOTALL the body then ran on to the *next* `-->` anywhere in
        the file — so any unrelated HTML comment further down donated a
        "reason". The isolated reasonless test above passed only because its
        fixture had no second comment, which is exactly the shape of an
        assertion that proves less than it appears to.
        """
        document = (
            "<!-- ac-state: non-measurable -->\n"
            "\n"
            "prose that is not a reason\n"
            "\n"
            "<!-- an unrelated comment -->\n"
        )
        assert not check.declares_non_measurable(document)

    def test_a_real_reason_still_counts_with_later_comments_present(self, check):
        """Fixing the bypass must not break the legitimate case."""
        document = (
            "<!-- ac-state: non-measurable - a glossary; nothing to assert -->\n"
            "\n<!-- an unrelated comment -->\n"
        )
        assert check.declares_non_measurable(document)


class TestAdrRefs:
    """`implements:` has more spellings than one, and two of them broke the
    counters in opposite directions (found in review)."""

    def test_a_block_list_entry_yields_its_adr(self, check):
        assert check.adr_refs(["- maistro-engine#ADR-073"]) == ["ADR-073"]

    def test_an_inline_yaml_list_is_parsed(self, check):
        """`implements: [maistro-engine#ADR-073]` is valid YAML, and
        `_list_field` hands back the whole bracketed string. Splitting on `#`
        gave `ADR-073]`, so the spec counted as mapped while its ADR still
        counted as uncovered — both wrong, and in opposite directions."""
        assert check.adr_refs(["[maistro-engine#ADR-073]"]) == ["ADR-073"]

    def test_an_inline_list_of_several_keeps_every_mapping(self, check):
        assert check.adr_refs(["[maistro-engine#ADR-073, maistro-engine#ADR-072]"]) == [
            "ADR-073",
            "ADR-072",
        ]

    def test_a_spec_reference_is_not_an_adr_reference(self, check):
        """The schema accepts `SPEC-*` in `implements` too. A spec implementing
        only another spec maps to no *decision*, so it must stay counted — the
        alternative is the check going green for precisely the missing chain it
        reports."""
        assert check.adr_refs(["maistro-engine#SPEC-160"]) == []

    def test_a_mixed_list_keeps_only_the_decisions(self, check):
        assert check.adr_refs(["maistro-engine#SPEC-160", "- maistro-engine#ADR-073"]) == [
            "ADR-073"
        ]

    def test_a_date_based_id_survives_intact(self, check):
        """ADR-062026-9b30's scheme has two hyphenated groups; a lazier pattern
        would truncate it and silently orphan every spec implementing it."""
        assert check.adr_refs(["maistro-engine#ADR-062026-9b30"]) == ["ADR-062026-9b30"]


class TestAdrOwnCriteria:
    def test_bullet_criteria_count_as_the_adrs_own(self, check):
        """An ADR carrying `**AC-N**` bullets rather than Gherkin scenarios is
        measured, not uncovered. Counting only scenarios put ADR-062026-9b30 —
        three bullets, no implementing spec — into
        `adrs_without_implementing_spec` against that counter's own stated
        exemption, and banked a debt figure one too high.
        """
        adrs = check.collect_adrs(specs=[], markers={}, unreachable=set(), passing=None)
        by_id = {a["id"]: a for a in adrs}
        assert by_id["ADR-062026-9b30"]["own_criteria"] == 3

    def test_prose_mentioning_the_words_does_not_count(self, check):
        assert not check.declares_non_measurable("This spec is non-measurable, sadly.")


class TestDecisionTaken:
    def test_proposed_is_not_owed_an_implementation(self, check):
        """Counting `Proposed` would make writing an idea down look like
        incurring debt, which would teach people not to write ideas down."""
        assert "Proposed" not in check.DECISION_TAKEN

    def test_every_state_in_which_the_decision_stands_is_owed(self, check):
        """`Fully Specced` *means* every child spec has acceptance criteria, so
        an ADR carrying it with no child spec at all is precisely the absent
        link this counter exists to report. `In Progress` and `Tests Passing`
        sit on the same ladder between Accepted and Implemented. None of the
        three is on any ADR today, which is why leaving them out was invisible."""
        assert set(check.DECISION_TAKEN) == {
            "Accepted",
            "Fully Specced",
            "In Progress",
            "Tests Passing",
            "Implemented",
        }

    def test_a_decision_not_to_do_is_not_owed_an_implementation(self, check):
        """A spec implementing a denied or superseded ADR would contradict the
        decision, so counting these would push work in the wrong direction."""
        for declined in ("Denied", "Will Not Implement", "Deferred"):
            assert declined not in check.DECISION_TAKEN
        for retired in ("Superseded", "Deprecated"):
            assert retired not in check.DECISION_TAKEN


class TestAbsenceCountersAreRatcheted:
    def test_all_three_may_only_fall(self, check):
        """A counter that is measured but not ratcheted is a dashboard, not a
        gate — it would report the chain breaking and let the PR through."""
        for name in (
            "specs_implementing_nothing",
            "adrs_without_implementing_spec",
            "specs_declaring_no_criteria",
        ):
            assert name in check.RATCHETED

    def test_the_reverse_index_is_derived_from_spec_front_matter(self, check):
        """Not from a checked-in file.

        A recorded ADR->spec index is a file somebody has to regenerate, and the
        one nobody regenerates is exactly how a stale entry absorbs a later
        regression. Deriving it from `implements:` at run time also means two
        concurrent PRs adding specs under one ADR cannot collide.
        """
        import inspect

        source = inspect.getsource(check.collect_adrs)
        assert 'spec["implements"]' in source
