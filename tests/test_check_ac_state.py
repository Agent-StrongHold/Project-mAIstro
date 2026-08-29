"""Tests for the acceptance-criterion state derivation.

The script's whole purpose is to stop a document asserting more than its
artefacts support, so the properties worth testing are the ones where it could
quietly assert too much itself: a criterion must not reach `reachable` without
both a passing test and a module the reachability graph can get to, and a
suite that never ran must report `unmeasured` rather than "not passing".
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


#: The measurement lives in `check_ac_state_impl`; `check-ac-state.py` is a thin
#: entry point over it that adds the merge guard. These tests are about the
#: measurement, and several of them monkeypatch what it reads -- `SPEC_DIR`,
#: `_passing_in_root`. Patching the entry point cannot work: it re-exports by
#: copying names into its own globals, and a re-exported function still closes
#: over the implementation's, so the patch rebinds something nothing reads.
#:
#: Making the entry point proxy those writes was tried and is worse: the same
#: file is loaded under four module names across this suite, and a shared
#: implementation turns one test's patch into every other load's problem. The
#: seam being tested is the implementation, so this names it.
IMPL = ROOT / "scripts" / "check_ac_state_impl.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_ac_state_impl_under_test", IMPL)
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

    def test_every_adr_state_in_which_the_decision_stands_is_owed(self, check):
        """ADR-097's taken ADR states are distinct from the SPEC lifecycle.

        `In Progress` and `Tests Passing` are SPEC states. Treating them as ADR
        states would make this governance metric accept vocabulary the
        kind-specific lifecycle linter rejects.
        """
        assert set(check.DECISION_TAKEN) == {
            "Accepted",
            "Fully Specced",
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


class TestUnprovenMarker:
    """The per-criterion escape hatch (#165).

    Same shape as the non-measurable marker and for the same reasons: the
    reason is mandatory, and the body cannot reach a closing delimiter — the
    earlier version of that pattern let a reasonless marker borrow a later
    comment's `-->`, which is exactly the bug this one is written to avoid
    repeating.
    """

    def test_a_marker_with_a_reason_exempts_that_criterion(self, check):
        assert check.declared_unproven(
            "<!-- ac-state: unproven AC-3 - blocked on the durable store (#132) -->"
        ) == {"AC-3"}

    def test_a_marker_with_no_reason_exempts_nothing(self, check):
        assert check.declared_unproven("<!-- ac-state: unproven AC-3 -->") == set()

    def test_a_reasonless_marker_cannot_borrow_a_later_comment(self, check):
        document = "<!-- ac-state: unproven AC-3 -->\n\nprose\n\n<!-- unrelated -->\n"
        assert check.declared_unproven(document) == set()

    def test_it_exempts_only_the_criterion_it_names(self, check):
        assert check.declared_unproven("<!-- ac-state: unproven AC-3 - why -->") == {"AC-3"}

    def test_several_markers_accumulate(self, check):
        document = "<!-- ac-state: unproven AC-1 - a -->\n<!-- ac-state: unproven AC-2 - b -->\n"
        assert check.declared_unproven(document) == {"AC-1", "AC-2"}


class TestTouchedSince:
    def test_a_new_criterion_is_touched(self, check):
        assert check.touched_since({}, {"S/AC-1": False}) == {"S/AC-1"}

    def test_ticking_an_existing_box_is_touching_it(self, check):
        """Ticking a box *is* the claim, so it is precisely the moment to
        demand the evidence — even when the criterion's text did not move."""
        assert check.touched_since({"S/AC-1": False}, {"S/AC-1": True}) == {"S/AC-1"}

    def test_an_unchanged_criterion_is_not_touched(self, check):
        assert check.touched_since({"S/AC-1": True}, {"S/AC-1": True}) == set()

    def test_untouched_legacy_debt_stays_out_of_the_mandate(self, check):
        """The whole point of the split: 68 unverifiable claims exist, and this
        gate must not demand they all be fixed by whoever next edits a spec."""
        base = {f"S/AC-{n}": False for n in range(50)}
        assert check.touched_since(base, base) == set()

    def test_removing_a_criterion_is_not_a_violation(self, check):
        """A deletion cannot be 'unproven'; it has nothing to prove."""
        assert check.touched_since({"S/AC-1": True}, {}) == set()


class TestMandateViolations:
    def _doc(self, rung, **extra):
        return {
            "id": "SPEC-1",
            "file": "docs/specs/SPEC-1.md",
            "criteria": [
                {
                    "id": "SPEC-1/AC-1",
                    "claimed": True,
                    "module": None,
                    "covered_by": [],
                    "rung": rung,
                }
            ],
            **extra,
        }

    def test_a_touched_criterion_short_of_reachable_fails(self, check):
        found = check.mandate_violations([self._doc("declared")], {"SPEC-1/AC-1"}, {})
        assert [v["id"] for v in found] == ["SPEC-1/AC-1"]

    def test_covered_is_not_enough(self, check):
        """`covered` means a test names it, not that the test passed."""
        found = check.mandate_violations([self._doc("covered")], {"SPEC-1/AC-1"}, {})
        assert len(found) == 1

    def test_reachable_passes(self, check):
        assert check.mandate_violations([self._doc("reachable")], {"SPEC-1/AC-1"}, {}) == []

    def test_an_untouched_criterion_is_ignored_however_weak(self, check):
        assert check.mandate_violations([self._doc("declared")], set(), {}) == []

    def test_a_declared_exemption_clears_it(self, check):
        found = check.mandate_violations(
            [self._doc("declared")], {"SPEC-1/AC-1"}, {"SPEC-1": {"AC-1"}}
        )
        assert found == []

    def test_an_exemption_for_another_criterion_does_not_clear_it(self, check):
        found = check.mandate_violations(
            [self._doc("declared")], {"SPEC-1/AC-1"}, {"SPEC-1": {"AC-2"}}
        )
        assert len(found) == 1


class TestMandateCannotBankItself:
    def test_the_mandate_is_not_a_ratcheted_counter(self, check):
        """A new criterion must never bank itself into the grandfathered
        population — that would make the escape hatch silent and the ratchet
        meaningless. It cannot, by construction: the mandate is a pass/fail over
        a computed set, not a number `--bank` writes down."""
        assert not any("mandate" in name or "touched" in name for name in check.RATCHETED)

    def test_an_unreadable_base_refuses_rather_than_failing_everything(self, check):
        """An unreadable base makes every criterion look new, which would demand
        the whole corpus be retrofitted in one PR — and a gate that fires on
        everything gets turned off."""
        assert check.snapshot_at("definitely-not-a-rev") is None


class TestAdrsAreFirstClassInTheMandate:
    """Three of the mandate's review findings were the same root cause: specs
    keep criteria under `criteria` and ADRs under `own_detail`, so every place
    that had to remember which was a place one could be forgotten."""

    def test_one_accessor_serves_both_shapes(self, check):
        assert check._criteria_of({"criteria": [{"id": "a"}]}) == [{"id": "a"}]
        assert check._criteria_of({"own_detail": [{"id": "b"}]}) == [{"id": "b"}]
        assert check._criteria_of({}) == []

    def test_an_adr_criterion_carries_its_claim_state(self, check):
        """Hard-coding this to False meant flipping an ADR criterion to `[x]`
        was invisible to `touched_since`, so the mandate passed without asking
        for evidence — on the documents that carry the most weight."""
        adrs = check.collect_adrs(specs=[], markers={}, unreachable=set(), passing=None)
        for adr in adrs:
            for criterion in adr["own_detail"]:
                assert "claimed" in criterion

    def test_an_adr_can_declare_a_criterion_unproven(self, check):
        """Without this the documented escape hatch did not exist for ADRs: an
        unproven criterion added to one blocked the PR with no way out."""
        adrs = check.collect_adrs(specs=[], markers={}, unreachable=set(), passing=None)
        assert all("declared_unproven" in a for a in adrs)


class TestSpecCorpusMatchesTheRegistry:
    def test_nested_specs_are_collected(self, check, tmp_path, monkeypatch):
        """`maistro_registry` walks `docs/specs/**/*.md`. A non-recursive glob
        accepted a nested spec at the registry gate while omitting every
        criterion in it here — the mandate would report success over a document
        it never opened."""
        nested = tmp_path / "subsystem"
        nested.mkdir()
        (nested / "SPEC-999-nested.md").write_text("---\nid: SPEC-999\nkind: spec\n---\n")
        (tmp_path / "SPEC-998-flat.md").write_text("---\nid: SPEC-998\nkind: spec\n---\n")
        monkeypatch.setattr(check, "SPEC_DIR", tmp_path)
        found = {p.name for p in check._spec_files()}
        assert found == {"SPEC-999-nested.md", "SPEC-998-flat.md"}

    def test_a_non_spec_markdown_file_is_not_collected(self, check, tmp_path, monkeypatch):
        """Filtering on `kind: spec` rather than the filename is what makes the
        two corpora the same set — a README under docs/specs is not a spec."""
        (tmp_path / "README.md").write_text("# not a spec\n")
        (tmp_path / "SPEC-1.md").write_text("---\nid: SPEC-1\nkind: spec\n---\n")
        monkeypatch.setattr(check, "SPEC_DIR", tmp_path)
        assert {p.name for p in check._spec_files()} == {"SPEC-1.md"}


def _adr(adr_id, status="Accepted", own=(), specs=()):
    """An ADR row in the shape `collect_adrs` emits."""
    return {
        "id": adr_id,
        "declared_status": status,
        "specs": list(specs),
        "own_detail": [{"id": f"{adr_id}/AC-{i}", "rung": r} for i, r in enumerate(own, 1)],
    }


def _spec(spec_id, rungs=()):
    """A spec row in the shape `collect_specs` emits."""
    return {
        "id": spec_id,
        "criteria": [{"id": f"{spec_id}/AC-{i}", "rung": r} for i, r in enumerate(rungs, 1)],
    }


class TestDesignCoverage:
    """The one number that has to go *up* (#166, ADR-082226-ff3c).

    Every other counter in the gate measures debt. These pin the four
    properties the ADR commits to, because each is a place where a metric of
    this kind normally goes wrong: a denominator that lets unwritten work
    vanish, a weighting that rewards verbosity, a bar set at `passing`, and a
    number that rises when you delete the evidence of your own debt.
    """

    @pytest.mark.ac("ADR-082226-ff3c/AC-1")
    def test_every_decision_weighs_the_same_however_verbosely_it_was_written(self, check):
        """One fully-proven criterion and forty fully-proven criteria are each
        one unit of design. Criterion-weighting would make the forty-criterion
        ADR worth forty times as much, so the metric would measure how much was
        typed rather than how much was decided."""
        small = _adr("ADR-A", own=["reachable"])
        large = _adr("ADR-B", own=["reachable"] * 40)
        pct, rows = check.design_coverage([], [small, large])
        assert pct == 100.0
        assert [r["fraction"] for r in rows] == [1, 1]

    @pytest.mark.ac("ADR-082226-ff3c/AC-1")
    def test_a_half_proven_decision_contributes_a_half(self, check):
        pct, _ = check.design_coverage([], [_adr("ADR-A", own=["reachable", "declared"])])
        assert pct == 50.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-2")
    def test_a_decision_declaring_no_criteria_scores_zero_rather_than_vanishing(self, check):
        """The property the whole shape turns on. Measured over criteria that
        *exist* the corpus reads 30.5%; measured over decisions *taken*, 4.0%.
        The gap is 76 taken ADRs with nothing written, and a denominator they
        drop out of is one that reads respectably while three-quarters of the
        design is unmeasured."""
        proven = _adr("ADR-A", own=["reachable"])
        silent = _adr("ADR-B", own=[])
        pct, rows = check.design_coverage([], [proven, silent])
        assert pct == 50.0, "the silent decision was excluded from the denominator"
        assert [r["criteria"] for r in rows] == [1, 0]

    @pytest.mark.ac("ADR-082226-ff3c/AC-3")
    def test_deleting_an_unproven_criterion_cannot_raise_the_number(self, check):
        """Gameable-in-the-wrong-direction is what disqualified the
        criterion-weighted formulation. Here the ADR falls from 1/2 to 0/0,
        which is 0 — deleting the record of debt destroys the credit with it."""
        before, _ = check.design_coverage([], [_adr("ADR-A", own=["reachable", "declared"])])
        after, _ = check.design_coverage([], [_adr("ADR-A", own=[])])
        assert before == 50.0
        assert after == 0.0
        assert after < before

    @pytest.mark.ac("ADR-082226-ff3c/AC-4")
    def test_proposed_decisions_are_excluded(self, check):
        """A decision not yet taken cannot be owed an implementation, and
        counting it would make writing an idea down look like incurring debt."""
        pct, rows = check.design_coverage(
            [], [_adr("ADR-A", own=["reachable"]), _adr("ADR-B", status="Proposed", own=[])]
        )
        assert [r["id"] for r in rows] == ["ADR-A"]
        assert pct == 100.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-4")
    def test_implemented_counts_as_taken_alongside_accepted(self, check):
        pct, rows = check.design_coverage(
            [], [_adr("ADR-A", status="Implemented", own=["declared"])]
        )
        assert [r["id"] for r in rows] == ["ADR-A"]
        assert pct == 0.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-5")
    def test_the_bar_is_reachable_and_not_passing(self, check):
        """A passing test whose module the import graph cannot reach proves the
        test runs, not that the system does."""
        pct, _ = check.design_coverage([], [_adr("ADR-A", own=["passing", "covered", "declared"])])
        assert pct == 0.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-6")
    def test_an_implementing_specs_criteria_count_toward_its_decision(self, check):
        """The fold the ADR specifies: own criteria *plus* every spec whose
        `implements:` names it. Most decisions carry no criteria of their own,
        so folding from specs is where nearly all the signal comes from."""
        spec = _spec("SPEC-1", rungs=["reachable", "declared"])
        pct, rows = check.design_coverage([spec], [_adr("ADR-A", own=[], specs=["SPEC-1"])])
        assert rows[0]["criteria"] == 2
        assert pct == 50.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-6")
    def test_own_and_spec_criteria_are_pooled_into_one_fraction(self, check):
        spec = _spec("SPEC-1", rungs=["reachable"])
        adr = _adr("ADR-A", own=["declared"], specs=["SPEC-1"])
        pct, rows = check.design_coverage([spec], [adr])
        assert (rows[0]["reachable"], rows[0]["criteria"]) == (1, 2)
        assert pct == 50.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-6")
    def test_a_spec_naming_its_decision_twice_is_not_counted_twice(self, check):
        """`collect_adrs` appends a child per resolved reference, so an
        `implements:` list naming one ADR twice puts the same spec in that
        ADR's children twice and would double-weight its criteria."""
        spec = _spec("SPEC-1", rungs=["reachable", "declared"])
        adr = _adr("ADR-A", own=[], specs=["SPEC-1", "SPEC-1"])
        _, rows = check.design_coverage([spec], [adr])
        assert rows[0]["criteria"] == 2

    def test_a_dangling_spec_reference_is_skipped_rather_than_raising(self, check):
        """The registry refuses unresolvable references, so this should not
        occur — but the gate must not be the thing that crashes if it does."""
        _, rows = check.design_coverage([], [_adr("ADR-A", own=["reachable"], specs=["SPEC-GONE"])])
        assert rows[0]["criteria"] == 1

    def test_no_taken_decisions_is_zero_rather_than_a_division_error(self, check):
        assert check.design_coverage([], []) == (0.0, [])
        assert check.design_coverage([], [_adr("ADR-A", status="Proposed")])[0] == 0.0

    @pytest.mark.ac("ADR-082226-ff3c/AC-7")
    def test_the_banked_precision_resolves_a_single_criterion(self, check):
        """The claim `COVERAGE_PRECISION` actually has to carry.

        The number is a float in a file of integers, so it is compared at a
        stated resolution rather than exactly. That resolution is only safe if
        it is finer than the smallest real move — proving one criterion of the
        largest decision, spread over the count of decisions. Here that is
        1/(99 * 46) of the mean; if rounding swallowed it, a PR could prove a
        criterion and the floor would read the result as no change.
        """
        decisions = 99
        biggest = 46
        adrs = [_adr(f"ADR-{i}", own=["declared"] * biggest) for i in range(decisions)]
        before, _ = check.design_coverage([], adrs)
        adrs[0]["own_detail"][0]["rung"] = "reachable"
        after, _ = check.design_coverage([], adrs)
        assert before == 0.0
        assert after > before, "one proven criterion rounded away to no change"
        assert round(after - before, check.COVERAGE_PRECISION) == pytest.approx(0.022, abs=0.001)

    def test_the_shipped_notes_agree_with_the_folded_floor(self, check):
        """The ADR banks 4.0% and says so in its own Consequences: a metric
        chosen to flatter would not be worth ratcheting.

        This used to pin the shipped ceiling to the shipped report. #585 retired
        both: the ceiling is folded from `quality/ac-state-notes/` and the report
        is generated rather than committed, so there is no committed pair left
        to drift apart. What survives here is the half that is still a property
        of the shipped files — every note is well-formed, and the fold over them
        is exactly the maximum any one of them claims, so no note can hold a
        floor the ledger does not actually support.

        The other half — that the floor equals what the tree *measures* — is now
        the gate's own assertion: `--ratchet` fails both a fall below the bound
        and an unbanked rise above it, so a hand-edited number cannot survive a
        run. It is checked by running the gate, not by reading a file.
        """
        notes_dir = ROOT / "quality" / "ac-state-notes"
        notes = [
            check.ac_state_notes.Note.parse(path.name, path.read_text())
            for path in sorted(notes_dir.glob("*.json"))
        ]
        assert notes, "the notes directory is the ledger; it may not be empty"

        folded = check.ac_state_notes.fold(notes)

        assert folded["design_coverage"] == max(
            note.counters["design_coverage"] for note in notes if "design_coverage" in note.counters
        )
        assert not (ROOT / "quality" / "ac-state-ceilings.json").exists()


class TestToolingReachesTheTopRung:
    """#249: a gate's own criteria can reach `reachable`.

    Before tooling entered the reachability graph this was unreachable by
    construction — `scripts/` was in no graph, so `_is_reachable` had nothing
    to consult and every gate ADR capped at `passing`. These pin both
    directions, because a ladder that says `reachable` for *any* tooling module
    would be worse than one that says it for none: it would grant the top rung
    to the nine mutation scripts that are dead behind a disabled workflow.
    """

    @pytest.mark.ac("ADR-082526-aef8/AC-6")
    def test_a_workflow_rooted_tooling_module_reaches_the_top_rung(self, check) -> None:
        criterion = check.Criterion(
            ac_id="ADR-X/AC-1",
            module="scripts/check-wiring-reads.py",
            covered_by=["tests/test_check_wiring_reads.py::test_x"],
            passing=True,
        )
        assert criterion.rung({"scripts/mutation_ratchet.py"}) == "reachable"

    @pytest.mark.ac("ADR-082526-aef8/AC-6")
    def test_an_unreachable_tooling_module_stays_at_passing(self, check) -> None:
        """The counterweight: a dead script's tests prove they run, not that it does."""
        criterion = check.Criterion(
            ac_id="ADR-X/AC-1",
            module="scripts/mutation_ratchet.py",
            covered_by=["tests/test_mutation.py::test_x"],
            passing=True,
        )
        assert criterion.rung({"scripts/mutation_ratchet.py"}) == "passing"

    @pytest.mark.ac("ADR-082526-aef8/AC-6")
    def test_the_real_ledger_agrees_with_both(self, check) -> None:
        """Against the committed baseline, not a hand-made set."""
        import json
        import pathlib as _pathlib

        root = _pathlib.Path(__file__).resolve().parents[1]
        unreachable = set(
            json.loads((root / "quality" / "reachability-baseline.json").read_text())["unreachable"]
        )
        live = check.Criterion(
            ac_id="ADR-X/AC-1",
            module="scripts/check-wiring-reads.py",
            covered_by=["t::x"],
            passing=True,
        )
        dead = check.Criterion(
            ac_id="ADR-X/AC-2",
            module="scripts/mutation_ratchet.py",
            covered_by=["t::x"],
            passing=True,
        )
        assert live.rung(unreachable) == "reachable"
        assert dead.rung(unreachable) == "passing"


class TestChainFacts:
    """The absence questions, answered from a document's text alone.

    Text-only is not a shortcut: the base side of the mandate is
    `git show <base>:<path>`, where there is no checkout to import from and no
    test that can be run. The head side calls the same function for the same
    reason — a fact derived two ways can differ two ways, and every difference
    would read as a violation the change introduced.
    """

    SPEC = (
        "---\nid: SPEC-900\nkind: spec\nstatus: Draft\n"
        "implements:\n  - maistro-engine#ADR-070\n---\n\n"
        "## Acceptance criteria\n\n- [ ] **AC-1** it holds\n"
    )

    def test_a_spec_names_its_kind_its_adrs_and_its_criteria(self, check):
        facts = check.chain_facts("docs/specs/SPEC-900.md", self.SPEC)
        assert facts.id == "SPEC-900"
        assert facts.kind == "spec"
        assert facts.implements == ("ADR-070",)
        assert facts.has_criteria and facts.has_ac_heading

    def test_an_inline_implements_list_still_names_its_adr(self, check):
        """`implements: [maistro-engine#ADR-073]` is valid front matter, and
        splitting the raw field on `#` yielded `ADR-073]` — the spec counted as
        mapped while its ADR still counted as uncovered, wrong in both
        directions at once."""
        text = self.SPEC.replace(
            "implements:\n  - maistro-engine#ADR-070", "implements: [maistro-engine#ADR-073]"
        )
        assert check.chain_facts("docs/specs/SPEC-900.md", text).implements == ("ADR-073",)

    def test_a_spec_implementing_only_another_spec_names_no_decision(self, check):
        """The schema accepts `SPEC-*` references too, and one of those maps to
        no decision at all — exactly the missing chain the counter reports."""
        text = self.SPEC.replace("maistro-engine#ADR-070", "maistro-engine#SPEC-101")
        assert check.chain_facts("docs/specs/SPEC-900.md", text).implements == ()

    def test_a_document_under_specs_without_kind_spec_is_not_in_the_corpus(self, check):
        """The same filter `_spec_files` applies. A document counted on one side
        of the comparison and not the other is a spurious violation waiting."""
        assert check.chain_facts("docs/specs/README.md", "---\nid: X\n---\n") is None

    def test_a_nested_adr_path_is_not_an_adr(self, check):
        """`collect_adrs` globs `docs/adr/ADR-*.md` and does not recurse."""
        text = "---\nid: ADR-1\nstatus: Accepted\n---\n"
        assert check.chain_facts("docs/adr/archive/ADR-1.md", text) is None
        assert check.chain_facts("docs/adr/ADR-1.md", text).kind == "adr"


class TestAbsentLinks:
    def _spec(self, check, doc_id, *, implements=(), criteria=True, heading=True, nm=False):
        return check.ChainFacts(
            id=doc_id,
            kind="spec",
            file=f"docs/specs/{doc_id}.md",
            status="Draft",
            implements=tuple(implements),
            has_criteria=criteria,
            has_ac_heading=heading,
            non_measurable=nm,
        )

    def _adr(self, check, doc_id, *, status="Accepted", criteria=False):
        return check.ChainFacts(
            id=doc_id,
            kind="adr",
            file=f"docs/adr/{doc_id}.md",
            status=status,
            implements=(),
            has_criteria=criteria,
            has_ac_heading=criteria,
            non_measurable=False,
        )

    def _links(self, check, *facts):
        return check.absent_links({f.id: f for f in facts})

    def test_a_spec_naming_no_adr_is_an_orphan(self, check):
        found = self._links(check, self._spec(check, "SPEC-1"))
        assert found["specs_implementing_nothing"] == {"SPEC-1"}

    def test_a_taken_adr_nothing_implements_is_uncovered(self, check):
        found = self._links(check, self._adr(check, "ADR-1"))
        assert found["adrs_without_implementing_spec"] == {"ADR-1"}

    def test_a_proposed_adr_is_owed_nothing(self, check):
        """A decision not yet made cannot be owed an implementation; counting it
        would make writing down an idea look like incurring debt."""
        found = self._links(check, self._adr(check, "ADR-1", status="Proposed"))
        assert found["adrs_without_implementing_spec"] == set()

    def test_an_adr_carrying_its_own_criteria_is_covered(self, check):
        """ADR-063..066 hold 147 scenarios written before the spec split, and
        calling those uncovered would report measured work as missing."""
        found = self._links(check, self._adr(check, "ADR-1", criteria=True))
        assert found["adrs_without_implementing_spec"] == set()

    def test_an_implementing_spec_covers_the_decision(self, check):
        found = self._links(
            check, self._adr(check, "ADR-1"), self._spec(check, "SPEC-1", implements=["ADR-1"])
        )
        assert found["adrs_without_implementing_spec"] == set()

    def test_coverage_is_a_property_of_the_corpus_not_of_the_adr(self, check):
        """Whether a decision is implemented depends on every spec's
        `implements:`, so deleting a reference in one file puts a *different*
        file's decision into the population."""
        with_spec = self._links(
            check, self._adr(check, "ADR-1"), self._spec(check, "SPEC-1", implements=["ADR-1"])
        )
        without = self._links(check, self._adr(check, "ADR-1"), self._spec(check, "SPEC-1"))
        assert with_spec["adrs_without_implementing_spec"] == set()
        assert without["adrs_without_implementing_spec"] == {"ADR-1"}

    def test_a_spec_with_no_criteria_and_no_heading_is_silent(self, check):
        found = self._links(
            check, self._spec(check, "SPEC-1", implements=["ADR-1"], criteria=False, heading=False)
        )
        assert found["specs_declaring_no_criteria"] == {"SPEC-1"}

    def test_a_heading_awaiting_ids_is_not_silence(self, check):
        """`specs_awaiting_retrofit` holds "criteria not written yet". Merging
        the two let "there are none" hide inside "there are none *yet*"."""
        found = self._links(
            check, self._spec(check, "SPEC-1", implements=["ADR-1"], criteria=False, heading=True)
        )
        assert found["specs_declaring_no_criteria"] == set()

    def test_a_declared_non_measurable_spec_is_exempt(self, check):
        found = self._links(
            check,
            self._spec(
                check, "SPEC-1", implements=["ADR-1"], criteria=False, heading=False, nm=True
            ),
        )
        assert found["specs_declaring_no_criteria"] == set()


class TestNewAbsentLinks:
    """#164 reopened on exactly this: the three counters were ratchets, and a
    ratchet compares totals."""

    def test_a_link_absent_at_the_base_is_not_this_change_s(self, check):
        base = {"specs_implementing_nothing": {"SPEC-1"}}
        head = {"specs_implementing_nothing": {"SPEC-1"}}
        found = check.new_absent_links(base | _others(), head | _others())
        assert found["specs_implementing_nothing"] == []

    @pytest.mark.ac("ADR-082526-ef55/AC-1")
    def test_a_link_this_change_introduced_is_reported(self, check):
        found = check.new_absent_links(
            {"specs_implementing_nothing": set()} | _others(),
            {"specs_implementing_nothing": {"SPEC-2"}} | _others(),
        )
        assert found["specs_implementing_nothing"] == ["SPEC-2"]

    @pytest.mark.ac("ADR-082526-ef55/AC-2")
    def test_a_new_violation_cannot_be_paid_for_by_fixing_a_legacy_one(self, check):
        """The audit's finding, stated as a test. The aggregate is unchanged —
        one in, one out — so the ceiling is satisfied while a new absent link
        entered the repository. Ids cannot net off against each other."""
        base = {"specs_implementing_nothing": {"SPEC-OLD"}} | _others()
        head = {"specs_implementing_nothing": {"SPEC-NEW"}} | _others()
        assert len(base["specs_implementing_nothing"]) == len(head["specs_implementing_nothing"])
        assert check.new_absent_links(base, head)["specs_implementing_nothing"] == ["SPEC-NEW"]

    @pytest.mark.ac("ADR-082526-ef55/AC-1")
    def test_closing_a_link_is_never_a_violation(self, check):
        found = check.new_absent_links(
            {"specs_implementing_nothing": {"SPEC-1"}} | _others(),
            {"specs_implementing_nothing": set()} | _others(),
        )
        assert found["specs_implementing_nothing"] == []

    @pytest.mark.ac("ADR-082526-ef55/AC-3")
    def test_every_absence_counter_is_carried(self, check):
        """Three counters, and a mandate covering two of them would be worse
        than none: the uncovered one reads as gated when it is not."""
        empty = {name: set() for name in check.ABSENCE_COUNTERS}
        assert set(check.new_absent_links(empty, empty)) == set(check.ABSENCE_COUNTERS)
        assert set(check.ABSENCE_COUNTERS) <= set(check.RATCHETED)


def _others():
    """The two counters a focused case is not exercising, empty on both sides."""
    return {"adrs_without_implementing_spec": set(), "specs_declaring_no_criteria": set()}


class TestChainMandateGate:
    def _facts(self, check, **kwargs):
        return check.ChainFacts(
            kind="spec",
            status="Draft",
            implements=(),
            has_criteria=True,
            has_ac_heading=True,
            non_measurable=False,
            **kwargs,
        )

    @pytest.mark.ac("ADR-082526-ef55/AC-4")
    def test_an_unchanged_corpus_passes(self, check):
        facts = {"SPEC-1": self._facts(check, id="SPEC-1", file="docs/specs/SPEC-1.md")}
        assert check.chain_mandate("base", facts, facts) == 0

    def test_a_newly_added_orphan_spec_fails(self, check, capsys):
        base: dict = {}
        head = {"SPEC-1": self._facts(check, id="SPEC-1", file="docs/specs/SPEC-1.md")}
        assert check.chain_mandate("base", base, head) == 1
        out = capsys.readouterr().out
        assert "SPEC-1" in out and "docs/specs/SPEC-1.md" in out

    def test_the_failure_says_how_to_close_the_link(self, check, capsys):
        """A gate that reports a violation and not its remedy gets worked around
        rather than satisfied."""
        head = {"SPEC-1": self._facts(check, id="SPEC-1", file="docs/specs/SPEC-1.md")}
        check.chain_mandate("base", {}, head)
        assert "implements:" in capsys.readouterr().out

    def test_a_pre_existing_orphan_alone_passes(self, check):
        """Legacy stays on the ceilings and falls over time. A gate that fires
        on all 76 of them at once gets turned off."""
        facts = {"SPEC-1": self._facts(check, id="SPEC-1", file="docs/specs/SPEC-1.md")}
        assert check.chain_mandate("base", facts, facts) == 0

    def test_head_and_base_select_the_same_corpus(self, check):
        """The two walks differ in *selection*, not in derivation: the base
        lists `git ls-tree` paths, the head rglobs the checkout. A document one
        side counts and the other does not is a spurious violation waiting, so
        on a clean tree the two must agree exactly.

        Unmarked deliberately. It can only run when `docs/` matches HEAD, and a
        criterion whose evidence is skippable would sit at `covered` and fail
        the mandate it belongs to — an acceptance criterion has to be bound to
        a test that always runs.
        """
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "docs/"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        if dirty.returncode != 0 or dirty.stdout.strip():
            pytest.skip("docs/ differs from HEAD; the checkout is not the revision")
        at_head = check.corpus_at("HEAD")
        assert at_head is not None
        assert at_head[1] == check.working_tree_facts()

    @pytest.mark.ac("ADR-082526-ef55/AC-5")
    def test_an_unreadable_base_refuses_rather_than_failing_everything(self, check):
        """Same refusal the criterion mandate makes, for the same reason: an
        unreadable base makes every absent link look introduced."""
        assert check.corpus_at("definitely-not-a-rev") is None


class TestPassingPerRoot:
    """One pytest session per root, and what each outcome is allowed to mean (#267).

    This used to be a single invocation over every root at once, which worked
    only because the roots it held did not collide. Adding
    `packages/hive-conductor/backend/tests` made them collide -- `tests/config/`
    under maistro-core claims the top-level name `config`, which Hive's flat
    layout also uses -- and the interrupted session reported *every* criterion
    in the repository as unmeasured. Measured: design coverage 17.24% -> 0.0%.

    So the distinction these tests defend is the one the script exists for. An
    empty set is "the suite ran and nothing passed"; None is "we do not know".
    A root that cannot run must produce the second, and must not let the roots
    that did run stand in for the whole answer.
    """

    def test_no_existing_root_is_unmeasured(self, check):
        assert check.passing_ac_ids([Path("/nonexistent-root")]) is None

    def test_outcomes_union_across_roots(self, check, monkeypatch, tmp_path):
        """Each root contributes its own passing ids; the answer is all of them."""
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        seen: list[Path] = []

        def fake(root: Path) -> set[str]:
            seen.append(root)
            return {"SPEC-1/AC-1"} if root == a else {"SPEC-2/AC-1"}

        monkeypatch.setattr(check, "_passing_in_root", fake)
        assert check.passing_ac_ids([a, b]) == {"SPEC-1/AC-1", "SPEC-2/AC-1"}
        assert seen == [a, b], "each root gets its own session"

    def test_one_unmeasured_root_takes_the_whole_answer_down(self, check, monkeypatch, tmp_path):
        """The property #267 turned on. Returning the roots that did run would
        report every criterion proven elsewhere as *not passing*, which is a
        fabrication rather than a gap -- and the ratchet would then fail on a
        floor nobody actually broke."""
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        monkeypatch.setattr(
            check, "_passing_in_root", lambda root: None if root == b else {"SPEC-1/AC-1"}
        )
        assert check.passing_ac_ids([a, b]) is None

    def test_a_root_with_no_markers_is_empty_not_unmeasured(self, check, monkeypatch, tmp_path):
        """pytest exits 5 when `-m ac` deselects everything, which per-root is
        ordinary: most roots carry no markers at all. Reading that as a failed
        measurement would make the common case indistinguishable from a broken
        one. It was unreachable while every root shared a session."""

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 5, "", "")

        monkeypatch.setattr(check.subprocess, "run", fake_run)
        assert check._passing_in_root(tmp_path) == set()

    def test_an_interrupted_session_is_unmeasured(self, check, monkeypatch, tmp_path):
        """Exit 2 is a collection error or an interrupt -- the session did not
        run to completion, so its outcome map is partial by definition."""

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, 2, "29 errors during collection", "")

        monkeypatch.setattr(check.subprocess, "run", fake_run)
        assert check._passing_in_root(tmp_path) is None

    def test_a_completed_session_reports_what_passed(self, check, monkeypatch, tmp_path):
        """The plugin writes its outcome map to the path the env var names, and
        exit 1 (some marked test failed) is still a completed measurement."""

        def fake_run(args, **kwargs):
            out = Path(kwargs["env"]["AC_OUTCOME_JSON"])
            out.write_text(json.dumps({"passing": ["SPEC-9/AC-2"]}), encoding="utf-8")
            return subprocess.CompletedProcess(args, 1, "", "")

        monkeypatch.setattr(check.subprocess, "run", fake_run)
        assert check._passing_in_root(tmp_path) == {"SPEC-9/AC-2"}

    def test_a_session_that_never_started_is_unmeasured(self, check, monkeypatch, tmp_path):
        """A timeout or a missing interpreter is not evidence about criteria."""

        def fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(args, 1800)

        monkeypatch.setattr(check.subprocess, "run", fake_run)
        assert check._passing_in_root(tmp_path) is None
