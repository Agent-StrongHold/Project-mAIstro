"""Tests for the suite-inventory delta ledger (#208, ADR-082526-547c).

The gate's job — catching a suite that silently stops collecting — was never
in doubt. What #208 reopened over is *where the expected number is written*.
It used to be one row in `SUITE-INVENTORY.md`, which meant two branches that
both added tests both rewrote it, and adjacent table rows conflicted even
across unrelated suites.

So the property these tests exist to pin is the one the old shape failed:

    two changes recording deltas never write the same path, and their deltas
    sum to the truth without either being regenerated.

`TestNoSharedWrite` asserts exactly that, because it is the acceptance
criterion and nothing else in the repo checks it. The rest guard the ways a
derived number can go quietly wrong: an unparseable delta must raise rather
than read as zero, and a suite nothing collects must not carry an expected
count.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-suite-inventory.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_suite_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ledger(gate, tmp_path, monkeypatch):
    """A whole miniature repository: two suites, a baseline, notes, an inventory.

    All four have to agree, because the gate now requires it — the recipes, the
    baseline keys and the documented table are checked against each other, so a
    fixture that supplies only some of them is not a smaller version of the real
    thing, it is a broken one.
    """
    notes = tmp_path / "inventory-notes"
    notes.mkdir()
    (notes / "README.md").write_text("# notes\n", encoding="utf-8")
    baseline = tmp_path / "inventory" / "baseline.json"
    baseline.parent.mkdir()
    baseline.write_text(
        json.dumps({"counts": {"tests/": 100, "formal/": 50}, "folded": []}),
        encoding="utf-8",
    )
    inventory = tmp_path / "SUITE-INVENTORY.md"
    inventory.write_text(
        "see [notes](inventory-notes/)\n\n| `tests/` | `ci.yml` |\n| `formal/` | `ci.yml` |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "NOTES", notes)
    monkeypatch.setattr(gate, "BASELINE", baseline)
    monkeypatch.setattr(gate, "INVENTORY", inventory)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        gate, "RECIPES", {"tests/": gate.Recipe(args=[]), "formal/": gate.Recipe(args=[])}
    )
    return gate


def write_note(gate, name: str, body: str = "prose\n", **delta: int) -> Path:
    path = gate.NOTES / f"{name}.md"
    front = "\n".join(gate.render_delta_block({k.replace("_", "/"): v for k, v in delta.items()}))
    path.write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")
    return path


class TestNoSharedWrite:
    """#208 AC-1: two test-changing PRs must not conflict."""

    @pytest.mark.ac("ADR-082526-547c/AC-1")
    def test_two_changes_write_different_paths(self, ledger, tmp_path):
        a = write_note(ledger, "branch-a", tests_=+7)
        b = write_note(ledger, "branch-b", tests_=+3)
        assert a != b, "two changes must not write the same file"

    @pytest.mark.ac("ADR-082526-547c/AC-1")
    def test_deltas_from_two_changes_sum(self, ledger):
        """The whole mechanism: independent deltas add up to the truth."""
        write_note(ledger, "branch-a", tests_=+7)
        write_note(ledger, "branch-b", tests_=+3)
        expected, deltas = ledger.expected_counts()
        assert expected["tests/"] == 110
        assert set(deltas) == {"branch-a", "branch-b"}

    @pytest.mark.ac("ADR-082526-547c/AC-2")
    def test_a_base_move_does_not_invalidate_a_recorded_delta(self, ledger):
        """The saving the conflict framing hides.

        Branch B recorded +3 before A merged. After A merges, B's own file is
        untouched and still correct — no re-collection, no regeneration. Under
        the old absolute this was the expensive part: a branch that changed no
        test still had to collect thirteen suites.
        """
        write_note(ledger, "branch-b", tests_=+3)
        before, _ = ledger.expected_counts()
        assert before["tests/"] == 103

        write_note(ledger, "branch-a", tests_=+7)  # A merges
        after, _ = ledger.expected_counts()
        assert after["tests/"] == 110

        b = (ledger.NOTES / "branch-b.md").read_text(encoding="utf-8")
        assert "tests/: +3" in b, "B's recorded delta must not have been rewritten"

    @pytest.mark.ac("ADR-082526-547c/AC-1")
    def test_opposing_deltas_cancel(self, ledger):
        """A removal and an addition net out rather than fighting."""
        write_note(ledger, "adds", tests_=+12)
        write_note(ledger, "removes", tests_=-12)
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 100


class TestTripwireIntact:
    """#208 AC-2: a suite silently ceasing to collect must still fail."""

    def test_a_suite_dropping_to_zero_is_drift(self, ledger):
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 100
        assert expected["tests/"] != 0, "0 collected must not match a recorded 100"

    def test_baseline_without_counts_is_an_error(self, ledger):
        ledger.BASELINE.write_text(json.dumps({"counts": {}}), encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="non-empty `counts`"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_recorded_suite_with_no_recipe_is_an_error(self, ledger):
        """An expected count nothing collects reads as gating that is not happening."""
        ledger.BASELINE.write_text(
            json.dumps({"counts": {"tests/": 100, "packages/ghost/tests": 5}, "folded": []}),
            encoding="utf-8",
        )
        with pytest.raises(ledger.LedgerError, match="no collection recipe"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_delta_naming_an_unknown_suite_is_an_error(self, ledger):
        write_note(ledger, "typo", **{"packages/ghost/tests": 4})
        with pytest.raises(ledger.LedgerError, match="no collection recipe"):
            ledger.expected_counts()


class TestUnreadableDeltaRaises:
    """A delta that cannot be parsed must not quietly become zero."""

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_malformed_delta_line_raises(self, ledger):
        (ledger.NOTES / "bad.md").write_text(
            "---\ninventory-delta:\n  tests/: lots\n---\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="cannot read"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_unclosed_front_matter_raises(self, ledger):
        (ledger.NOTES / "bad.md").write_text(
            "---\ninventory-delta:\n  tests/: +1\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="never closed"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_duplicate_suite_in_one_note_raises(self, ledger):
        (ledger.NOTES / "dupe.md").write_text(
            "---\ninventory-delta:\n  tests/: +1\n  tests/: +2\n---\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="appears twice"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_inline_value_instead_of_block_raises(self, ledger):
        (ledger.NOTES / "inline.md").write_text(
            "---\ninventory-delta: 7\n---\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="indented"):
            ledger.expected_counts()


class TestNotesWithoutDeltas:
    """Every note written before this ADR has no front matter and must be fine."""

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_a_note_with_no_front_matter_contributes_nothing(self, ledger):
        (ledger.NOTES / "historical.md").write_text("# old note\n\nprose\n", encoding="utf-8")
        expected, deltas = ledger.expected_counts()
        assert expected["tests/"] == 100
        assert deltas == {}

    def test_front_matter_without_the_key_contributes_nothing(self, ledger):
        (ledger.NOTES / "other.md").write_text(
            "---\ntitle: something\n---\n\nprose\n", encoding="utf-8"
        )
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 100

    def test_readme_is_not_a_note(self, ledger):
        (ledger.NOTES / "README.md").write_text(
            "---\ninventory-delta:\n  tests/: +999\n---\n", encoding="utf-8"
        )
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 100, "the directory's own README must not count as a change"


class TestWritingADelta:
    """`--update` must edit one change's own file and preserve its prose."""

    def test_prose_survives_a_rewrite(self, ledger):
        path = write_note(ledger, "mine", body="# why\n\nthe real explanation\n", tests_=+1)
        ledger.write_note_delta(path, {"tests/": 5})
        text = path.read_text(encoding="utf-8")
        assert "the real explanation" in text
        assert "tests/: +5" in text
        assert "tests/: +1" not in text

    def test_other_front_matter_keys_survive(self, ledger):
        path = ledger.NOTES / "mine.md"
        path.write_text(
            "---\ntitle: keep me\ninventory-delta:\n  tests/: +1\n---\n\nprose\n", encoding="utf-8"
        )
        ledger.write_note_delta(path, {"tests/": 2})
        text = path.read_text(encoding="utf-8")
        assert "title: keep me" in text
        assert "tests/: +2" in text

    def test_a_new_note_is_created_with_a_prose_prompt(self, ledger):
        path = ledger.NOTES / "fresh.md"
        ledger.write_note_delta(path, {"tests/": 3})
        text = path.read_text(encoding="utf-8")
        assert "tests/: +3" in text
        assert "why" in text.lower(), "a new note should prompt for the explanation"

    def test_an_emptied_delta_removes_the_block(self, ledger):
        path = write_note(ledger, "mine", tests_=+4)
        ledger.write_note_delta(path, {})
        text = path.read_text(encoding="utf-8")
        assert "inventory-delta" not in text
        assert "prose" in text

    def test_a_written_delta_reads_back_identically(self, ledger):
        """Round-trip: what `--update` writes is what the checker parses."""
        path = ledger.NOTES / "rt.md"
        ledger.write_note_delta(path, {"tests/": -6, "formal/": 2})
        assert ledger.parse_delta(path.read_text(encoding="utf-8"), "rt") == {
            "tests/": -6,
            "formal/": 2,
        }


class TestCompaction:
    """Folding deltas into the baseline must not change any expected count."""

    @pytest.mark.ac("ADR-082526-547c/AC-5")
    def test_compaction_preserves_expected_counts(self, ledger):
        write_note(ledger, "a", tests_=+7)
        write_note(ledger, "b", formal_=-2)
        before, deltas = ledger.expected_counts()

        assert ledger.compact(before, deltas) == 2
        after, remaining = ledger.expected_counts()

        assert after == before, "compaction must be arithmetically invisible"
        assert remaining == {}, "folded notes must stop contributing"

    @pytest.mark.ac("ADR-082526-547c/AC-5")
    def test_folded_notes_are_not_edited(self, ledger):
        path = write_note(ledger, "a", tests_=+7)
        original = path.read_text(encoding="utf-8")
        expected, deltas = ledger.expected_counts()
        ledger.compact(expected, deltas)
        assert path.read_text(encoding="utf-8") == original, (
            "inventory-notes/ is a record of what was written, not a document kept current"
        )

    @pytest.mark.ac("ADR-082526-547c/AC-5")
    def test_a_delta_added_after_compaction_still_counts(self, ledger):
        write_note(ledger, "a", tests_=+7)
        expected, deltas = ledger.expected_counts()
        ledger.compact(expected, deltas)

        write_note(ledger, "later", tests_=+5)
        after, _ = ledger.expected_counts()
        assert after["tests/"] == 112


@pytest.fixture
def two_suites(ledger):
    """Kept as a name: `ledger` now already restricts RECIPES to its two suites."""
    return ledger


def fake_collect(counts: dict[str, int], broken: set[str] = frozenset()):
    """A ``collect`` stand-in returning fixed counts, or raising for ``broken``."""

    def _collect(suite, recipe):
        if suite in broken:
            raise RuntimeError(f"collection failed for `{suite}`")
        return counts[suite], f"pytest {suite}"

    return _collect


class TestCollectParsing:
    """`collect` reads pytest's own summary line, and must not guess."""

    def test_reads_the_last_collected_count(self, gate, monkeypatch):
        """pytest can print more than one summary; the final one is the answer."""
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type(
                "P",
                (),
                {
                    "stdout": "12 tests collected\n41 tests collected\n",
                    "stderr": "",
                    "returncode": 0,
                },
            )(),
        )
        count, cmd = gate.collect("tests/", gate.Recipe(args=[]))
        assert count == 41
        assert "tests/" in cmd

    def test_a_nonzero_exit_raises_rather_than_returning_a_count(self, gate, monkeypatch):
        """A broken suite must never be read as a number, however plausible."""
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type(
                "P", (), {"stdout": "0 tests collected\n2 errors\n", "stderr": "", "returncode": 2}
            )(),
        )
        with pytest.raises(RuntimeError, match="2 errors during collection"):
            gate.collect("tests/", gate.Recipe(args=[]))

    def test_no_summary_line_raises(self, gate, monkeypatch):
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type("P", (), {"stdout": "", "stderr": "", "returncode": 0})(),
        )
        with pytest.raises(RuntimeError, match="exit 0"):
            gate.collect("tests/", gate.Recipe(args=[]))

    def test_pythonpath_is_prepended_not_replaced(self, gate, monkeypatch):
        """formal/ needs evolve + rsi; clobbering an existing PYTHONPATH breaks callers."""
        seen = {}

        def _run(argv, cwd, env, capture_output, text):
            seen.update(env)
            return type("P", (), {"stdout": "3 tests collected", "stderr": "", "returncode": 0})()

        monkeypatch.setenv("PYTHONPATH", "/pre-existing")
        monkeypatch.setattr(gate.subprocess, "run", _run)
        gate.collect("formal/", gate.Recipe(args=[], pythonpath=["a/src", "b/src"]))
        assert seen["PYTHONPATH"] == "a/src:b/src:/pre-existing"

    def test_bare_python_suites_do_not_shell_out_to_uv(self, gate, monkeypatch):
        """Trap 1: hive-conductor's conftest needs bare python, never `uv run`."""
        seen = {}

        def _run(argv, **kwargs):
            seen["argv"] = argv
            return type("P", (), {"stdout": "5 tests collected", "stderr": "", "returncode": 0})()

        monkeypatch.setattr(gate.subprocess, "run", _run)
        gate.collect("x/tests", gate.Recipe(args=[], bare_python=True))
        assert seen["argv"][0] != "uv"
        assert seen["argv"][1:3] == ["-m", "pytest"]


class TestRunChecks:
    """Drift and collection failure are different things and must stay apart."""

    def test_matching_counts_produce_no_drift(self, two_suites, monkeypatch):
        monkeypatch.setattr(two_suites, "collect", fake_collect({"tests/": 100, "formal/": 50}))
        drift, failures = two_suites.run_checks(
            ["tests/", "formal/"], {"tests/": 100, "formal/": 50}
        )
        assert drift == [] and failures == []

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_moved_count_is_drift(self, two_suites, monkeypatch):
        monkeypatch.setattr(two_suites, "collect", fake_collect({"tests/": 107, "formal/": 50}))
        drift, failures = two_suites.run_checks(
            ["tests/", "formal/"], {"tests/": 100, "formal/": 50}
        )
        assert drift == [("tests/", 100, 107)]
        assert failures == []

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_broken_suite_is_a_failure_not_drift(self, two_suites, monkeypatch):
        """The distinction that matters: you must not record a delta for a suite
        that did not run. That would bank the breakage as the new truth."""
        monkeypatch.setattr(two_suites, "collect", fake_collect({"formal/": 50}, broken={"tests/"}))
        drift, failures = two_suites.run_checks(
            ["tests/", "formal/"], {"tests/": 100, "formal/": 50}
        )
        assert drift == []
        assert len(failures) == 1 and "tests/" in failures[0]


class TestRecordDelta:
    def test_it_writes_only_the_named_note(self, ledger):
        assert ledger.record_delta("mine", [("tests/", 100, 106)], {}, []) == 0
        assert (ledger.NOTES / "mine.md").is_file()
        assert ledger.parse_delta((ledger.NOTES / "mine.md").read_text(), "x") == {"tests/": 6}

    def test_further_drift_accumulates_onto_a_delta_already_recorded(self, ledger):
        """A second batch of tests adds to this note's delta rather than replacing it.

        Worth stating why this is not double-counting. `drift` is measured
        against `expected`, which already contains this note's own delta. So a
        reported gap is always *new* movement on top of what is recorded, and
        adding it is right. If nothing new were added there would be no drift
        at all — that is `test_a_base_move_does_not_invalidate_a_recorded_delta`
        — and `--update` returns at "ok" without touching the file, which is
        what makes re-running it safe.
        """
        ledger.record_delta("mine", [("tests/", 100, 106)], {}, [])
        deltas = {"mine": {"tests/": 6}}
        # Six more tests land: expected is 106, the suite now collects 112.
        ledger.record_delta("mine", [("tests/", 106, 112)], deltas, [])
        assert ledger.parse_delta((ledger.NOTES / "mine.md").read_text(), "x") == {"tests/": 12}

    @pytest.mark.ac("ADR-082526-547c/AC-2")
    def test_no_drift_leaves_the_note_untouched(self, two_suites, monkeypatch):
        """Re-running --update when nothing moved must not rewrite anything."""
        path = write_note(two_suites, "mine", body="hand-written prose\n", tests_=+6)
        original = path.read_text(encoding="utf-8")
        monkeypatch.setattr(two_suites.sys, "argv", ["x", "--update", "--note", "mine"])
        monkeypatch.setattr(two_suites, "collect", fake_collect({"tests/": 106, "formal/": 50}))
        assert two_suites.main() == 0
        assert path.read_text(encoding="utf-8") == original

    def test_no_derivable_name_is_an_error_not_a_guess(self, ledger, monkeypatch):
        monkeypatch.setattr(ledger, "default_note_slug", lambda: None)
        assert ledger.record_delta(None, [("tests/", 100, 106)], {}, []) == 2

    def test_a_branch_name_becomes_the_note_name(self, ledger, monkeypatch):
        monkeypatch.setattr(ledger, "default_note_slug", lambda: "claude-issue-208")
        ledger.record_delta(None, [("tests/", 100, 101)], {}, [])
        assert (ledger.NOTES / "claude-issue-208.md").is_file()


class TestDefaultNoteSlug:
    def test_a_branch_name_is_slugified(self, gate, monkeypatch):
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type("P", (), {"stdout": "claude/Issue_208-Fix\n", "returncode": 0})(),
        )
        assert gate.default_note_slug().startswith("claude-issue-208-fix-")

    @pytest.mark.ac("ADR-082526-547c/AC-1")
    def test_branches_that_sanitize_alike_still_get_distinct_names(self, gate, monkeypatch):
        """Sanitising alone would put three distinct branches on one path.

        `feature/foo`, `feature-foo` and `Feature_Foo` all fold to the same
        readable slug. If the note name stopped there, two of them would write
        the same file and recreate the exact conflict this ledger removes.
        """

        def slug_for(branch):
            monkeypatch.setattr(
                gate.subprocess,
                "run",
                lambda *a, **k: type("P", (), {"stdout": f"{branch}\n", "returncode": 0})(),
            )
            return gate.default_note_slug()

        names = {slug_for(b) for b in ("feature/foo", "feature-foo", "Feature_Foo")}
        assert len(names) == 3, f"branches collided onto {names}"

    def test_the_same_branch_always_gets_the_same_name(self, gate, monkeypatch):
        """Otherwise re-running --update would strand the earlier delta."""
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type("P", (), {"stdout": "claude/x\n", "returncode": 0})(),
        )
        assert gate.default_note_slug() == gate.default_note_slug()

    def test_detached_head_yields_nothing(self, gate, monkeypatch):
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type("P", (), {"stdout": "HEAD\n", "returncode": 0})(),
        )
        assert gate.default_note_slug() is None

    def test_git_failure_yields_nothing(self, gate, monkeypatch):
        monkeypatch.setattr(
            gate.subprocess,
            "run",
            lambda *a, **k: type("P", (), {"stdout": "", "returncode": 128})(),
        )
        assert gate.default_note_slug() is None

    def test_no_git_at_all_yields_nothing(self, gate, monkeypatch):
        def _boom(*a, **k):
            raise OSError("no git")

        monkeypatch.setattr(gate.subprocess, "run", _boom)
        assert gate.default_note_slug() is None


class TestRenderTable:
    def test_every_recorded_suite_and_a_total(self, two_suites):
        out = two_suites.render_table({"tests/": 100, "formal/": 50})
        assert "tests/" in out and "formal/" in out
        assert "150" in out, "the total is what a reader sanity-checks against"


class TestBaselineErrors:
    def test_a_missing_baseline_is_an_error(self, ledger):
        ledger.BASELINE.unlink()
        with pytest.raises(ledger.LedgerError, match="is missing"):
            ledger.load_baseline()

    def test_invalid_json_is_an_error(self, ledger):
        ledger.BASELINE.write_text("{not json", encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="not valid JSON"):
            ledger.load_baseline()

    def test_a_non_integer_count_is_an_error(self, ledger):
        ledger.BASELINE.write_text('{"counts": {"tests/": "100"}}', encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="not an integer"):
            ledger.load_baseline()

    def test_a_boolean_count_is_an_error(self, ledger):
        """`True` is an int in Python; a count of `true` is a corrupt file."""
        ledger.BASELINE.write_text('{"counts": {"tests/": true}}', encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="not an integer"):
            ledger.load_baseline()

    def test_a_malformed_folded_list_is_an_error(self, ledger):
        ledger.BASELINE.write_text('{"counts": {"tests/": 1}, "folded": [7]}', encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="list of strings"):
            ledger.load_baseline()


class TestDriver:
    """`main` end to end, with collection stubbed."""

    def run(self, gate, monkeypatch, argv, counts, broken=frozenset()):
        monkeypatch.setattr(gate.sys, "argv", ["check-suite-inventory.py", *argv])
        monkeypatch.setattr(gate, "collect", fake_collect(counts, broken))
        return gate.main()

    def test_matching_counts_exit_zero(self, two_suites, monkeypatch):
        assert self.run(two_suites, monkeypatch, [], {"tests/": 100, "formal/": 50}) == 0

    def test_drift_exits_one(self, two_suites, monkeypatch):
        assert self.run(two_suites, monkeypatch, [], {"tests/": 101, "formal/": 50}) == 1

    def test_drift_with_update_exits_zero_and_records(self, two_suites, monkeypatch):
        code = self.run(
            two_suites, monkeypatch, ["--update", "--note", "n"], {"tests/": 101, "formal/": 50}
        )
        assert code == 0
        assert two_suites.parse_delta((two_suites.NOTES / "n.md").read_text(), "x") == {"tests/": 1}

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_broken_suite_exits_one_even_with_update(self, two_suites, monkeypatch):
        """--update must not paper over a suite that failed to collect."""
        code = self.run(
            two_suites,
            monkeypatch,
            ["--update", "--note", "n"],
            {"formal/": 50},
            broken={"tests/"},
        )
        assert code == 1
        assert not (two_suites.NOTES / "n.md").exists()

    def test_show_exits_zero_without_collecting(self, two_suites, monkeypatch):
        monkeypatch.setattr(two_suites.sys, "argv", ["x", "--show"])
        monkeypatch.setattr(
            two_suites, "collect", lambda *a: pytest.fail("--show must not collect")
        )
        assert two_suites.main() == 0

    def test_compact_exits_zero_without_collecting(self, two_suites, monkeypatch):
        write_note(two_suites, "a", tests_=+7)
        monkeypatch.setattr(two_suites.sys, "argv", ["x", "--compact"])
        monkeypatch.setattr(
            two_suites, "collect", lambda *a: pytest.fail("--compact must not collect")
        )
        assert two_suites.main() == 0
        assert two_suites.load_baseline()[1] == ["a"]

    def test_an_unknown_suite_argument_is_an_error(self, two_suites, monkeypatch):
        assert self.run(two_suites, monkeypatch, ["--suite", "packages/ghost"], {}) == 2

    def test_a_single_suite_narrows_the_check(self, two_suites, monkeypatch):
        """--suite formal/ must not fail on tests/ drifting."""
        code = self.run(
            two_suites, monkeypatch, ["--suite", "formal/"], {"tests/": 999, "formal/": 50}
        )
        assert code == 0

    def test_a_missing_notes_directory_is_an_error(self, two_suites, monkeypatch):
        (two_suites.NOTES / "README.md").unlink()
        two_suites.NOTES.rmdir()
        monkeypatch.setattr(two_suites.sys, "argv", ["x", "--show"])
        assert two_suites.main() == 2

    def test_a_bad_ledger_is_an_error_before_any_collection(self, two_suites, monkeypatch):
        two_suites.BASELINE.write_text("{oops", encoding="utf-8")
        monkeypatch.setattr(two_suites.sys, "argv", ["x"])
        monkeypatch.setattr(
            two_suites, "collect", lambda *a: pytest.fail("must not collect on a bad ledger")
        )
        assert two_suites.main() == 2


class TestNotesDirectoryGuard:
    """The pointer and the directory must agree, or the split silently rots."""

    def test_a_missing_readme_is_reported(self, ledger):
        (ledger.NOTES / "README.md").unlink()
        assert any("README.md is missing" in p for p in ledger.notes_problems())

    def test_an_inventory_that_stopped_linking_the_directory_is_reported(
        self, ledger, tmp_path, monkeypatch
    ):
        inventory = tmp_path / "SUITE-INVENTORY.md"
        inventory.write_text("# no link here\n", encoding="utf-8")
        monkeypatch.setattr(ledger, "INVENTORY", inventory)
        assert any("no longer links to" in p for p in ledger.notes_problems())

    def test_a_linking_inventory_is_clean(self, ledger, tmp_path, monkeypatch):
        inventory = tmp_path / "SUITE-INVENTORY.md"
        inventory.write_text("see [notes](inventory-notes/)\n", encoding="utf-8")
        monkeypatch.setattr(ledger, "INVENTORY", inventory)
        assert ledger.notes_problems() == []


class TestFrontMatterTolerance:
    """Front matter a person wrote by hand must not trip the parser."""

    def test_blank_lines_and_comments_inside_the_block_are_ignored(self, ledger):
        (ledger.NOTES / "spaced.md").write_text(
            "---\n# a comment\ninventory-delta:\n\n  tests/: +4\n---\n\nprose\n",
            encoding="utf-8",
        )
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 104

    def test_an_indented_line_before_the_key_is_ignored(self, ledger):
        """Another key's nested values must not be read as deltas."""
        (ledger.NOTES / "nested.md").write_text(
            "---\nrelated:\n  - something\ninventory-delta:\n  tests/: +2\n---\n\nprose\n",
            encoding="utf-8",
        )
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 102


class TestShowReportsOutstandingDeltas:
    def test_show_names_the_unfolded_notes(self, two_suites, monkeypatch, capsys):
        """A reader needs to know the number is a sum, and of what."""
        write_note(two_suites, "branch-a", tests_=+7)
        monkeypatch.setattr(two_suites.sys, "argv", ["x", "--show"])
        assert two_suites.main() == 0
        assert "branch-a" in capsys.readouterr().out


class TestReviewFindings:
    """Regressions for the seven findings Codex raised on PR #263.

    Each one is a way the ledger could report success while gating nothing, so
    each gets a test rather than only a fix.
    """

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_recipe_with_no_baseline_count_is_an_error(self, ledger):
        """The direction that fails OPEN.

        A recorded suite with no recipe was already caught. The reverse — a
        recipe with no recorded count — left the suite out of `expected`, so the
        check loop skipped it and reported success, and `--suite <that-one>`
        reported success having collected nothing.
        """
        ledger.BASELINE.write_text(
            json.dumps({"counts": {"tests/": 100}, "folded": []}), encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="no baseline count"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_suite_missing_a_count_cannot_pass_as_a_narrowed_check(self, ledger, monkeypatch):
        ledger.BASELINE.write_text(
            json.dumps({"counts": {"tests/": 100}, "folded": []}), encoding="utf-8"
        )
        monkeypatch.setattr(ledger.sys, "argv", ["x", "--suite", "formal/"])
        monkeypatch.setattr(
            ledger, "collect", lambda *a: pytest.fail("must not report success silently")
        )
        assert ledger.main() == 2

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_documented_suite_with_no_recipe_is_an_error(self, ledger):
        """The document says every row is collected; that claim is now checked."""
        ledger.INVENTORY.write_text(
            "see [notes](inventory-notes/)\n\n| `tests/` | `ci.yml` |\n"
            "| `formal/` | `ci.yml` |\n| `packages/ghost/tests` | `ci.yml` |\n",
            encoding="utf-8",
        )
        assert any("no collection recipe" in p for p in ledger.table_problems())

    @pytest.mark.ac("ADR-082526-547c/AC-3")
    def test_a_collected_suite_absent_from_the_table_is_an_error(self, ledger):
        ledger.INVENTORY.write_text(
            "see [notes](inventory-notes/)\n\n| `tests/` | `ci.yml` |\n", encoding="utf-8"
        )
        assert any("absent from" in p for p in ledger.table_problems())

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_an_empty_delta_block_raises(self, ledger):
        """`inventory-delta:` with nothing under it used to read as no delta."""
        (ledger.NOTES / "empty.md").write_text(
            "---\ninventory-delta:\n---\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="records nothing"):
            ledger.expected_counts()

    @pytest.mark.ac("ADR-082526-547c/AC-4")
    def test_a_dedented_delta_entry_raises(self, ledger):
        """A suite path at top level silently ended the block and lost the delta."""
        (ledger.NOTES / "dedent.md").write_text(
            "---\ninventory-delta:\ntests/: +2\n---\n\nprose\n", encoding="utf-8"
        )
        with pytest.raises(ledger.LedgerError, match="top level"):
            ledger.expected_counts()

    def test_a_note_slug_with_a_path_separator_is_refused(self, ledger):
        """`--note feature/foo` wrote a nested file the checker never reads."""
        assert ledger.record_delta("feature/foo", [("tests/", 100, 101)], {}, []) == 2
        assert not (ledger.NOTES / "feature").exists()

    def test_a_note_slug_escaping_the_directory_is_refused(self, ledger):
        for bad in ("..", "../escape", "/etc/passwd"):
            assert ledger.record_delta(bad, [("tests/", 100, 101)], {}, []) == 2

    def test_updating_a_folded_slug_is_refused(self, ledger):
        """Its delta is already in the baseline, so a new one would never count.

        Left alone this is a trap with no exit: `--update` reports success, the
        ledger does not move, and the next check fails again identically.
        """
        assert ledger.record_delta("done", [("tests/", 100, 105)], {}, ["done"]) == 2
        assert not (ledger.NOTES / "done.md").exists()

    @pytest.mark.ac("ADR-082526-547c/AC-2")
    def test_a_non_additive_interaction_is_detected_not_silently_wrong(self, ledger, monkeypatch):
        """Where base-move invariance genuinely does not hold.

        Node-ID counts are not additive in every case: two branches can each add
        one value to a different parametrize list and the merged product grows
        multiplicatively, so the recorded deltas under-count. The design does not
        claim otherwise — it claims the failure is LOUD. Two `+1` deltas over a
        baseline of 1 expect 3; the merged tree collects 4, and that must be
        drift, not a silently accepted sum.
        """
        ledger.BASELINE.write_text(
            json.dumps({"counts": {"tests/": 1, "formal/": 50}, "folded": []}), encoding="utf-8"
        )
        write_note(ledger, "branch-a", tests_=+1)
        write_note(ledger, "branch-b", tests_=+1)
        expected, _ = ledger.expected_counts()
        assert expected["tests/"] == 3

        monkeypatch.setattr(ledger, "collect", fake_collect({"tests/": 4}))
        drift, failures = ledger.run_checks(["tests/"], expected)
        assert failures == []
        assert drift == [("tests/", 3, 4)], "the interaction must surface as drift"
