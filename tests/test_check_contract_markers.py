"""The contract-marker validator finds what ADR-032 promised it would (#345).

Built against a throwaway corpus rather than the repository's own, because the
claim under test is what the rules *do*, and a test that asserted over the real
327 documents would only restate today's ledger. Each case is one rule.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "scripts" / "check_contract_markers_impl.py"


@pytest.fixture(scope="module")
def impl():
    spec = importlib.util.spec_from_file_location("contract_markers_under_test", IMPL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _corpus(root: Path, *, doc: str, test: str = "") -> Path:
    """A tree shaped like the repository: one ADR, one test file."""
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "docs" / "adr" / "ADR-001-thing.md").write_text(doc, encoding="utf-8")
    if test:
        (root / "tests" / "test_thing.py").write_text(test, encoding="utf-8")
    return root


_MARKED = """
import pytest

@pytest.mark.contract("behavioral")
def test_it_behaves() -> None:
    assert True
"""

_SKIPPED = """
import pytest

@pytest.mark.skip(reason="not yet")
@pytest.mark.contract("behavioral")
def test_it_behaves() -> None:
    assert True
"""

_UNKNOWN_KIND = """
import pytest

@pytest.mark.contract("telepathic")
def test_it_behaves() -> None:
    assert True
"""


def _doc(*, kinds: str, tests: str) -> str:
    return f"---\nid: ADR-001\ncontracts: {kinds}\ntests: {tests}\n---\n# thing\n"


class TestTheCrossCheckADR032Describes:
    def test_a_declared_kind_with_a_marked_test_is_evidenced(self, impl, tmp_path) -> None:
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[behavioral]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )

        assert impl.collect(root) == []

    def test_a_declared_kind_with_no_marked_test_is_flagged(self, impl, tmp_path) -> None:
        """The case ADR-032 actually describes."""
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[boundary]", tests="[tests/test_thing.py]"),
            test=_MARKED,  # marked behavioral, not boundary
        )

        findings = impl.collect(root)

        assert [f.category for f in findings] == ["declared-kind-unproven"]
        assert "[boundary]" in findings[0].identity

    def test_a_document_with_no_tests_is_its_own_category(self, impl, tmp_path) -> None:
        """Vacuous rather than false, and counted separately so it reads that way."""
        root = _corpus(tmp_path, doc=_doc(kinds="[behavioral]", tests="[]"))

        assert [f.category for f in impl.collect(root)] == ["declares-contracts-without-tests"]

    def test_a_document_declaring_no_contracts_is_not_this_gate_s_business(
        self, impl, tmp_path
    ) -> None:
        root = _corpus(tmp_path, doc=_doc(kinds="[]", tests="[]"))

        assert impl.collect(root) == []


class TestEvidenceMustBeAbleToRun:
    def test_a_statically_skipped_test_does_not_count(self, impl, tmp_path) -> None:
        """A marker on a test that cannot run is a claim, not evidence."""
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[behavioral]", tests="[tests/test_thing.py]"),
            test=_SKIPPED,
        )

        assert [f.category for f in impl.collect(root)] == ["declared-kind-unproven"]


class TestTheMarkerVocabulary:
    def test_a_kind_adr_032_does_not_define_is_flagged(self, impl, tmp_path) -> None:
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[]", tests="[]"),
            test=_UNKNOWN_KIND,
        )

        findings = impl.collect(root)

        assert [f.category for f in findings] == ["undefined-marker-kind"]
        assert "telepathic" in findings[0].identity

    def test_every_defined_kind_is_accepted(self, impl, tmp_path) -> None:
        marks = "\n".join(
            f'@pytest.mark.contract("{kind}")\ndef test_{i}() -> None:\n    assert True\n'
            for i, kind in enumerate(impl.DEFINED_KINDS)
        )
        root = _corpus(tmp_path, doc=_doc(kinds="[]", tests="[]"), test=f"import pytest\n{marks}")

        assert impl.collect(root) == []


class TestTheLedger:
    def _finding(self, impl, category: str = "declared-kind-unproven", identity: str = "a"):
        return impl.Finding(category, identity)

    def test_a_new_finding_is_reported(self, impl) -> None:
        new, stale, unexplained = impl.compare([self._finding(impl)], {})

        assert [f.identity for f in new] == ["a"]
        assert (stale, unexplained) == ([], [])

    def test_a_recorded_finding_is_not(self, impl) -> None:
        baseline = {
            "declared-kind-unproven": {"disposition": "known", "entries": ["a"]},
        }

        new, stale, unexplained = impl.compare([self._finding(impl)], baseline)

        assert (new, stale, unexplained) == ([], [], [])

    def test_a_fixed_finding_must_shrink_the_ledger(self, impl) -> None:
        """A stale entry would silently absorb the next regression under its name."""
        baseline = {
            "declared-kind-unproven": {"disposition": "known", "entries": ["a", "gone"]},
        }

        _new, stale, _unexplained = impl.compare([self._finding(impl)], baseline)

        assert stale == ["declared-kind-unproven::gone"]

    def test_a_category_banked_without_a_reason_fails(self, impl) -> None:
        """Banked and explained have to be the same act."""
        baseline = {"declared-kind-unproven": {"disposition": "   ", "entries": ["a"]}}

        _new, _stale, unexplained = impl.compare([self._finding(impl)], baseline)

        assert unexplained == ["declared-kind-unproven"]


class TestRoundTrip:
    def test_writing_then_reading_a_baseline_reports_nothing_new(self, impl, tmp_path) -> None:
        findings = [impl.Finding("declared-kind-unproven", "docs/adr/ADR-001-thing.md [boundary]")]
        path = tmp_path / "baseline.json"

        impl.write_baseline(path, findings)
        new, stale, unexplained = impl.compare(findings, impl.load_baseline(path))

        assert (new, stale, unexplained) == ([], [], [])
        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert recorded["defined_kinds"] == list(impl.DEFINED_KINDS)

    def test_a_written_baseline_carries_each_category_s_reason(self, impl, tmp_path) -> None:
        path = tmp_path / "baseline.json"

        impl.write_baseline(path, [impl.Finding("undefined-marker-kind", "telepathic (x)")])

        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert recorded["categories"]["undefined-marker-kind"]["disposition"].strip()


ENTRY = ROOT / "scripts" / "check-contract-markers.py"


@pytest.fixture(scope="module")
def entry():
    """The script CI actually runs, loaded as a module so `main` is callable.

    Loaded separately from `impl` on purpose. The entry point is where the exit
    codes and the operator-facing output live, and neither is exercised by
    testing the measurement underneath it: a `main` that computed the right
    findings and then returned 0 for all of them would pass every test above.
    """
    spec = importlib.util.spec_from_file_location("contract_markers_entry_under_test", ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _aim(entry, impl, root: Path, baseline: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point both modules at a throwaway tree instead of the repository."""
    for module in (entry, impl):
        monkeypatch.setattr(module, "ROOT", root, raising=False)
        monkeypatch.setattr(module, "BASELINE", baseline, raising=False)


class TestTheEntryPoint:
    """Exit codes and output, which the measurement tests cannot reach."""

    def test_a_clean_corpus_exits_zero(
        self, entry, impl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[behavioral]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )
        baseline = tmp_path / "baseline.json"
        baseline.write_text("{}", encoding="utf-8")
        _aim(entry, impl, root, baseline, monkeypatch)

        assert entry.main([]) == 0
        assert "every contract claim is either evidenced" in capsys.readouterr().out

    def test_an_unevidenced_claim_exits_one_and_names_it(
        self, entry, impl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The exit code is the whole point: CI reads it, not the prose."""
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[boundary]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )
        baseline = tmp_path / "baseline.json"
        baseline.write_text("{}", encoding="utf-8")
        _aim(entry, impl, root, baseline, monkeypatch)

        assert entry.main([]) == 1
        out = capsys.readouterr().out
        assert "ADR-001-thing.md" in out
        assert "--update" in out

    def test_update_writes_the_baseline_and_exits_zero(
        self, entry, impl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[boundary]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )
        baseline = tmp_path / "quality" / "baseline.json"
        baseline.parent.mkdir(parents=True)
        _aim(entry, impl, root, baseline, monkeypatch)

        assert entry.main(["--update"]) == 0
        assert json.loads(baseline.read_text(encoding="utf-8"))

    def test_banking_then_rechecking_passes(
        self, entry, impl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A banked finding is explained, so the next run is green.

        The two halves have to agree, and only the entry point runs both.
        """
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[boundary]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )
        baseline = tmp_path / "quality" / "baseline.json"
        baseline.parent.mkdir(parents=True)
        _aim(entry, impl, root, baseline, monkeypatch)

        assert entry.main(["--update"]) == 0
        assert entry.main([]) == 0

    def test_a_category_banked_without_a_disposition_fails(
        self, entry, impl, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Banking a finding and explaining it have to be the same act.

        A baseline entry with an empty disposition records that something was
        seen without recording why it was accepted, which is the shape a later
        regression can hide inside. So it fails even though every finding in it
        is recorded.
        """
        root = _corpus(
            tmp_path,
            doc=_doc(kinds="[boundary]", tests="[tests/test_thing.py]"),
            test=_MARKED,
        )
        baseline = tmp_path / "quality" / "baseline.json"
        baseline.parent.mkdir(parents=True)
        _aim(entry, impl, root, baseline, monkeypatch)

        assert entry.main(["--update"]) == 0
        banked = json.loads(baseline.read_text(encoding="utf-8"))
        banked["categories"]["declared-kind-unproven"]["disposition"] = "   "
        baseline.write_text(json.dumps(banked), encoding="utf-8")

        assert entry.main([]) == 1
        assert "have to be the same act" in capsys.readouterr().out

    def test_report_truncates_and_says_how_much_it_withheld(self, entry, capsys) -> None:
        """A gate that prints 200 lines is a gate nobody reads to the end."""
        entry._report("things", [f"line {n}" for n in range(25)])

        out = capsys.readouterr().out
        assert "25 things:" in out
        assert "line 19" in out
        assert "line 20" not in out
        assert "... and 5 more" in out

    def test_report_prints_nothing_for_an_empty_class(self, entry, capsys) -> None:
        entry._report("things", [])

        assert capsys.readouterr().out == ""
