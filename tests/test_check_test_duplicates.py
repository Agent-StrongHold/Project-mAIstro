"""Tests for the duplicate-test-file gate (#396).

#396's base state: eleven test files existed byte-identical under a package
tree and the root ``tests/`` tree, both roots in ``testpaths``, so suite
totals and AC-outcome counts double-credited each one. The gate now in
``scripts/check-test-duplicates.py`` exists to keep the next such copy from
being checked in silently.

The property worth pinning is not "hashing works" — it is the contract
semantics: a duplicate is only ever excused by an entry that names **every**
file in the group. A contract covering a strict subset must approve nothing,
because the remaining pair is precisely the unexplained copy the gate exists
for. The tests below fail against a gate that approves partial coverage,
ignores non-test files it should ignore, or errors unhelpfully on a
malformed contract.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-test-duplicates.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_test_duplicates", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(gate, tmp_path, monkeypatch):
    """A miniature gated tree: two suite roots, no contracts.

    Pointing the module's ``REPO_ROOT`` at the tmp tree keeps the real
    repository's files out of every scan below, so assertions are about the
    fixture content only.
    """
    (tmp_path / "docs" / "testing").mkdir(parents=True)
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / "root" / "tests").mkdir(parents=True)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "CONTRACTS", tmp_path / "docs" / "testing" / "contracts.json")
    monkeypatch.setattr(gate, "_suite_roots", lambda: ["pkg/tests", "root/tests"])
    # main() parses sys.argv; under pytest that is pytest's own argv.
    monkeypatch.setattr(sys, "argv", ["check-test-duplicates.py"])
    return tmp_path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


TEST_BODY = "def test_x():\n    assert True\n"


def test_identical_test_files_fail(gate, repo):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    assert gate.main() == 1


def test_distinct_content_passes(gate, repo, capsys):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", "def test_y():\n    assert True\n")
    assert gate.main() == 0
    assert "no byte-identical test files" in capsys.readouterr().out


def test_identical_non_test_files_are_not_duplicates(gate, repo):
    """The gate's universe is test files; identical conftest/helpers elsewhere
    are ordinary (and common) and must not fail it."""
    _write(repo / "pkg/tests/conftest.py", "import pytest\n")
    _write(repo / "root/tests/conftest.py", "import pytest\n")
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", "def test_other():\n    assert 1\n")
    assert gate.main() == 0


def test_identical_files_within_one_tree_also_fail(gate, repo):
    """The failure mode is byte-identical test content, wherever it sits —
    two copies under the same root double-collect just the same."""
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "pkg/tests/test_a_copy.py", TEST_BODY)
    assert gate.main() == 1


def test_contract_naming_every_file_approves(gate, repo, capsys):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    gate.CONTRACTS.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "id": "gen-suite",
                        "generator": "tools/gen_tests.py",
                        "files": ["pkg/tests/test_a.py", "root/tests/test_a.py"],
                        "justification": "generator emits one suite per install layout",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert gate.main() == 0
    assert "approved by generated-test contract: 1 group(s)" in capsys.readouterr().out


def test_contract_naming_a_subset_approves_nothing(gate, repo, capsys):
    """The regression the contract logic must not have: a contract listing
    one file of a pair leaving the other half unexplained — and approved."""
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_b.py", TEST_BODY)
    gate.CONTRACTS.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "id": "gen-suite",
                        "generator": "tools/gen_tests.py",
                        "files": ["pkg/tests/test_a.py", "root/tests/test_a.py"],
                        "justification": "covers the first pair only",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert gate.main() == 1
    err = capsys.readouterr().err
    assert "1 byte-identical test-file group(s) with no generated-test contract" in err
    assert "root/tests/test_b.py" in err
    assert "pkg/tests/test_b.py" not in err  # the approved pair is not re-listed


def test_contract_overlapping_but_not_matching_is_a_hint_not_an_approval(gate, repo, capsys):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    gate.CONTRACTS.write_text(
        json.dumps(
            {
                "contracts": [
                    {
                        "id": "gen-suite",
                        "generator": "tools/gen_tests.py",
                        "files": ["pkg/tests/test_a.py", "root/tests/some_other.py"],
                        "justification": "names a file that no longer exists",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert gate.main() == 1
    assert "overlaps contract gen-suite" in capsys.readouterr().err


@pytest.mark.parametrize(
    "doc",
    [
        '{"contracts": [{"id": "", "justification": "x", "files": ["a", "b"]}]}',
        '{"contracts": [{"id": "g", "justification": "", "files": ["a", "b"]}]}',
        '{"contracts": [{"id": "g", "generator": "", "justification": "x", "files": ["a", "b"]}]}',
        '{"contracts": [{"id": "g", "justification": "x", "files": ["a", "b"]}]}',
        '{"contracts": [{"id": "g", "justification": "x", "files": ["a"]}]}',
        '{"contracts": [{"id": "g", "justification": "x", "files": "a b"}]}',
        '{"contracts": "all of them"}',
    ],
)
def test_malformed_contract_fails_loudly(gate, repo, doc, capsys):
    """A contract the gate cannot validate must stop the run with exit 2 —
    an unreadable exemption silently approving everything is worse than none."""
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    gate.CONTRACTS.write_text(doc, encoding="utf-8")
    assert gate.main() == 2
    assert "error:" in capsys.readouterr().err


def test_missing_contracts_file_means_no_exemptions(gate, repo):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    assert not gate.load_contracts()
    assert gate.main() == 1


def test_list_mode_reports_without_failing(gate, repo, capsys, monkeypatch):
    _write(repo / "pkg/tests/test_a.py", TEST_BODY)
    _write(repo / "root/tests/test_a.py", TEST_BODY)
    monkeypatch.setattr(sys, "argv", ["check-test-duplicates.py", "--list"])
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "byte-identical groups: 1 (redundant files: 1" in out


def test_metrics_count_redundant_files_and_bytes(gate, repo):
    body = TEST_BODY * 10
    _write(repo / "pkg/tests/test_a.py", body)
    _write(repo / "root/tests/test_a.py", body)
    _write(repo / "pkg/tests/test_unique.py", "def test_z():\n    assert 1\n")
    files = gate.test_files(gate._suite_roots())
    groups = gate.duplicate_groups(files)
    assert len(groups) == 1
    report = gate.metrics(files, groups)
    assert "test files scanned: 3" in report
    assert "unique content: 2" in report
    assert "byte-identical groups: 1 (redundant files: 1" in report


def test_missing_suite_root_is_an_error_not_a_pass(gate, repo, monkeypatch):
    """A tree that moved must fail loudly (exit 2); a gate that scanned
    nothing and said ok would be the C1 failure mode all over again."""
    monkeypatch.setattr(gate, "_suite_roots", lambda: ["pkg/tests", "gone/tests"])
    assert gate.main() == 2


def test_real_tree_has_no_unapproved_duplicates(gate):
    """Integration: the actual repository — the state #396 leaves behind —
    must pass the same predicate CI will run. If this fails, a byte-identical
    test file was re-introduced without a contract."""
    files = gate.test_files(gate._suite_roots())
    groups = gate.duplicate_groups(files)
    approved, _hints = gate.approved_groups(groups, gate.load_contracts())
    assert not [d for d in groups if d not in approved], (
        f"unapproved duplicate test files: { {d[:12]: [str(p) for p in ps] for d, ps in groups.items() if d not in approved} }"
    )
