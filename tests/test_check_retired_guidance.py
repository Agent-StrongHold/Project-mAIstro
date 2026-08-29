"""The retired-guidance gate (#386).

`packages/maistro-core/CLAUDE.md` directed against accepted architecture for as
long as it did because nothing compared instruction files to the decisions that
govern them. The distinction this gate turns on — *directing* against a retired
statement versus *recording* that it was retired — is the whole design, so most
of what follows is about that boundary rather than about pattern matching.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-retired-guidance.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("_check_retired_guidance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def entries(check):
    return check.load_entries()


def _scan(check, entries, text: str):
    return check.scan_text(text, entries, path="fake.md")


class TestWhatIsADefect:
    def test_a_live_directive_is_reported(self, check, entries) -> None:
        found = _scan(
            check, entries, "- **No `org_id` in core.** Multi-tenant isolation is Stronghold-only."
        )
        assert len(found) == 1
        assert found[0].entry.retired_by == "ADR-068"

    def test_the_acceptance_criterion_phrasing_is_reported(self, check, entries) -> None:
        """The other half of #386: the shorthand had already propagated out of
        the instruction file and into a spec's acceptance criteria."""
        assert _scan(check, entries, "No `org_id` anywhere (ADR-019 CI grep).")

    def test_it_reports_the_replacement_not_just_the_violation(self, check, entries) -> None:
        """A gate that says only "this is wrong" makes the reader go find the
        decision. The registry carries the replacement so the message can."""
        found = _scan(check, entries, "No org_id in core.")
        assert "soft scope axes" in found[0].entry.replacement


class TestRecordingIsNotDirecting:
    """Each of these says the retired words on purpose. Flagging them would make
    the only way to pass be deleting the history of the change."""

    def test_the_root_decision_s_own_supersedes_clause_passes(self, check, entries) -> None:
        line = '(Supersedes the older "no org_id in core" shorthand, which conflated scope with tenancy.)'
        assert not _scan(check, entries, line)

    def test_the_adr_s_own_correction_passes(self, check, entries) -> None:
        line = 'The "no `org_id` in core" shorthand conflated **scope** with **tenancy**. Corrected: core'
        assert not _scan(check, entries, line)

    def test_a_note_that_the_phrasing_is_stale_passes(self, check, entries) -> None:
        line = 'package-level `maistro-core/CLAUDE.md` "no org_id in core" phrasing is stale relative to'
        assert not _scan(check, entries, line)

    def test_naming_the_superseding_adr_is_enough(self, check, entries) -> None:
        assert not _scan(check, entries, 'the "no org_id in core" rule, per ADR-068')

    def test_the_marker_must_be_on_the_same_line(self, check, entries) -> None:
        """Line-scoped deliberately. A citation three paragraphs away does not
        stop the directive from reading as a directive to someone skimming."""
        assert _scan(check, entries, "ADR-068 is the hierarchy.\n\nNo `org_id` in core.")


class TestTheRegistryIsTheContract:
    def test_an_entry_declares_what_replaced_the_statement(self, entries) -> None:
        """An entry without a replacement makes the gate unactionable."""
        for entry in entries:
            assert entry.retired_by
            assert entry.replacement

    def test_every_entry_has_citation_markers(self, entries) -> None:
        """Without them there is no way to record the retirement without
        failing the gate, and the only passing edit is deletion."""
        for entry in entries:
            assert entry.citation_markers

    def test_the_superseding_decision_is_a_citation_marker_for_its_own_entry(self, entries) -> None:
        """Otherwise the canonical way to cite a replacement — naming it — does
        not satisfy the check that demands it."""
        for entry in entries:
            markers = [m.lower() for m in entry.citation_markers]
            assert entry.retired_by.lower() in markers

    def test_the_registry_file_itself_is_not_scanned(self, check, entries) -> None:
        """It states every retired pattern by definition, and cannot cite its
        way out of doing so."""
        findings = check.scan(entries)
        assert not [f for f in findings if "retired-guidance" in f.path]


class TestAgainstTheRealTree:
    def test_the_governed_set_reaches_the_package_instruction_files(self, check) -> None:
        """The file #386 is about. A gate whose glob misses it is worth nothing,
        and the root CLAUDE.md alone would have looked correct throughout."""
        governed = {p.relative_to(ROOT).as_posix() for p in check.governed_files()}
        assert "packages/maistro-core/CLAUDE.md" in governed
        assert "CLAUDE.md" in governed

    def test_the_governed_set_reaches_specs_and_adrs(self, check) -> None:
        """Acceptance criteria are drawn from these, which is how the shorthand
        reached SPEC-183."""
        governed = {p.relative_to(ROOT).as_posix() for p in check.governed_files()}
        assert any(p.startswith("docs/specs/") for p in governed)
        assert any(p.startswith("docs/adr/") for p in governed)

    def test_the_current_tree_is_clean(self, check, entries) -> None:
        assert check.scan(entries) == []

    def test_the_real_registry_parses(self) -> None:
        payload = json.loads(
            (ROOT / "quality" / "retired-guidance.json").read_text(encoding="utf-8")
        )
        assert payload["entries"]


class TestTheCommandLine:
    def test_a_clean_tree_exits_zero(self, check) -> None:
        assert check.main([]) == 0

    def test_a_violation_exits_nonzero(self, check, tmp_path, monkeypatch) -> None:
        registry = tmp_path / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "id": "always",
                            "pattern": "Development Commands",
                            "retired_by": "ADR-000",
                            "replacement": "nothing",
                            "citation_markers": ["ADR-000"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        # A phrase the root CLAUDE.md really carries, so this exercises the
        # failing path against the real tree rather than a fixture of one.
        assert check.main(["--registry", str(registry)]) == 1

    def test_the_clean_message_says_how_much_it_looked_at(self, check, capsys) -> None:
        """ "ok" with no denominator cannot be told from "ok, I scanned nothing"
        — the same vacuous-pass shape the diff-coverage gate reports."""
        check.main([])
        out = capsys.readouterr().out
        assert "governed file(s)" in out
        assert "retired statement(s) checked" in out
