"""Tests for diff-scoped mutation sessions (#330).

The scope decision has two failure directions: over-scoping wastes runner
minutes, under-scoping silently weakens the gate. These tests pin the parsing
(what counts as a changed line), the skip rule (only mutants wholly outside
the changed set), and the two explicit failures — an empty changed-line set
and zero in-scope mutants — that must never masquerade as a pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_diff_scope.py"

pytest.importorskip("cosmic_ray")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("mutation_diff_scope", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DIFF = """\
diff --git a/pkg/mod.py b/pkg/mod.py
index 111..222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,6 +1,7 @@
 def kept(a):
-    return a
+    return a + 1
+
+def added(b):
+    return b
 
 def untouched():
     return 0
"""


class TestChangedLineParsing:
    def test_only_plus_lines_on_the_new_side_count(self, mod):
        scope = mod.DiffScope.from_unified_diff(DIFF)
        # Line 1 is context; 2 is the replaced return; 3-4 are the added
        # function; 5 blank inside the hunk; 6 is the trailing context line.
        assert scope.lines == {2, 3, 4, 5}

    def test_deleted_lines_have_no_new_side_position(self, mod):
        diff = "@@ -1,2 +1,2 @@\n-old one\n+new one\n context\n"
        assert mod.DiffScope.from_unified_diff(diff).lines == {1}

    def test_a_hunk_far_into_the_file_offsets_correctly(self, mod):
        diff = "@@ -10,3 +98,3 @@\n context\n+inserted\n context\n"
        assert mod.DiffScope.from_unified_diff(diff).lines == {99}

    def test_an_empty_diff_yields_an_empty_scope(self, mod):
        assert mod.DiffScope.from_unified_diff("").lines == set()

    def test_a_garbled_hunk_header_is_rejected(self, mod):
        with pytest.raises(ValueError, match="hunk header"):
            mod.DiffScope.from_unified_diff("@@ -x,y +z,w @@\n+added\n")


class _Mutation:
    def __init__(self, module_path, row):
        self.module_path = module_path
        self.start_pos = (row, 0)
        self.end_pos = (row, 10)


class _Item:
    def __init__(self, job_id, mutations):
        self.job_id = job_id
        self.mutations = mutations


class _WorkDB:
    def __init__(self, items):
        self.pending_work_items = items
        self.results = {}

    def set_result(self, job_id, result):
        self.results[job_id] = result


class TestTheSkipRule:
    def _db(self):
        return _WorkDB(
            [
                _Item("on-changed", [_Mutation("pkg/mod.py", 2)]),
                _Item("on-context", [_Mutation("pkg/mod.py", 1)]),
                _Item("straddling", [_Mutation("pkg/mod.py", 1), _Mutation("pkg/mod.py", 2)]),
            ]
        )

    def test_only_mutants_wholly_outside_the_change_are_skipped(self, mod):
        db = self._db()
        scope = mod.DiffScope.from_unified_diff(DIFF)
        kept, skipped = mod.apply_diff_scope(db, "pkg/mod.py", scope)
        assert (kept, skipped) == (2, 1)
        assert set(db.results) == {"on-context"}
        assert db.results["on-context"].worker_outcome.name == "SKIPPED"

    def test_a_mutant_touching_a_changed_line_stays(self, mod):
        db = _WorkDB([_Item("edge", [_Mutation("pkg/mod.py", 2), _Mutation("pkg/mod.py", 9)])])
        kept, _ = mod.apply_diff_scope(db, "pkg/mod.py", mod.DiffScope.from_unified_diff(DIFF))
        assert kept == 1
        assert db.results == {}

    def test_multi_module_items_are_refused_not_guessed(self, mod):
        db = _WorkDB([_Item("mixed", [_Mutation("pkg/mod.py", 2), _Mutation("pkg/other.py", 5)])])
        with pytest.raises(ValueError, match="several modules"):
            mod.apply_diff_scope(db, "pkg/mod.py", mod.DiffScope.from_unified_diff(DIFF))


class TestExplicitFailures:
    def test_main_fails_when_the_diff_has_no_changed_lines(self, mod, tmp_path):
        diff = tmp_path / "empty.diff"
        diff.write_text("", encoding="utf-8")
        assert (
            mod.main([str(tmp_path / "unused.sqlite"), "--source", "x", "--diff", str(diff)]) == 1
        )

    def test_main_fails_when_no_mutant_intersects(self, mod, tmp_path):
        from cosmic_ray.work_db import MutationSpec, WorkDB, WorkItem, use_db

        session = tmp_path / "session.sqlite"
        with use_db(session, mode=WorkDB.Mode.create) as db:
            db.add_work_items(
                [
                    WorkItem(
                        "job-1",
                        [MutationSpec("pkg/mod.py", "core/Number", 0, (1, 0), (1, 5))],
                    )
                ]
            )
        diff = tmp_path / "real.diff"
        diff.write_text(DIFF, encoding="utf-8")
        exit_code = mod.main(
            [
                str(session),
                "--source",
                "pkg/mod.py",
                "--diff",
                str(diff),
                "--require-intersection",
                "--report",
            ]
        )
        assert exit_code == 1

    def test_main_marks_off_scope_mutants_in_a_real_session(self, mod, tmp_path):
        from cosmic_ray.work_db import MutationSpec, WorkDB, WorkerOutcome, WorkItem, use_db

        session = tmp_path / "session.sqlite"
        with use_db(session, mode=WorkDB.Mode.create) as db:
            db.add_work_items(
                [
                    WorkItem(
                        "in-scope",
                        [MutationSpec("pkg/mod.py", "core/Number", 0, (2, 4), (2, 12))],
                    ),
                    WorkItem(
                        "out-of-scope",
                        [MutationSpec("pkg/mod.py", "core/Number", 1, (7, 4), (7, 12))],
                    ),
                ]
            )
        diff = tmp_path / "real.diff"
        diff.write_text(DIFF, encoding="utf-8")
        assert (
            mod.main([str(session), "--source", "pkg/mod.py", "--diff", str(diff), "--report"]) == 0
        )
        with use_db(session, mode=WorkDB.Mode.open) as db:
            results = dict(db.results)
        assert "in-scope" not in results
        assert results["out-of-scope"].worker_outcome == WorkerOutcome.SKIPPED
