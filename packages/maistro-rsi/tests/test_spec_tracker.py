"""spec_tracker: AC markers, contracted gaps, net-new AC claims, proposed specs.

Fixtures are tiny synthetic repos on disk (plus git where baselines matter) —
no LLM, no network, mirroring the repo's real conventions:
``- [ ] **AC-n**`` checkboxes in docs/specs/ and ``@pytest.mark.ac("SPEC-x/AC-n")``
markers in tests.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro_rsi.spec_tracker import (
    ac_markers_in,
    format_gaps,
    new_ac_coverage,
    proposed_specs,
    spec_gaps,
)

_SPEC = """---
id: SPEC-900-demo
title: "demo"
---
# Demo

- [ ] **AC-1** first promise
- [ ] **AC-2** second promise
- [x] **AC-3** already-checked promise (still needs a marked test)
"""

_TEST_WITH_MARKERS = """import pytest

@pytest.mark.ac("SPEC-900-demo/AC-1")
def test_first():
    assert True

@pytest.mark.ac('SPEC-900-demo/AC-3')
def test_third():
    assert True
"""


def test_ac_markers_in_handles_both_quote_styles() -> None:
    assert ac_markers_in(_TEST_WITH_MARKERS) == {
        "SPEC-900-demo/AC-1",
        "SPEC-900-demo/AC-3",
    }
    assert ac_markers_in("def test_x(): pass") == set()


def _make_repo(root: Path, *, spec: str = _SPEC, test_src: str = "") -> Path:
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "docs" / "specs" / "SPEC-900-demo.md").write_text(spec, encoding="utf-8")
    tests_dir = root / "packages" / "demo" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_demo.py").write_text(test_src, encoding="utf-8")
    return root


def test_spec_gaps_are_the_unclaimed_acs(tmp_path: Path) -> None:
    _make_repo(tmp_path, test_src=_TEST_WITH_MARKERS)
    gaps = spec_gaps(tmp_path)
    # AC-1 and AC-3 are claimed by markers; AC-2 is the contracted gap. The
    # checkbox state in the doc is aspiration — only a marked test claims an AC.
    assert gaps == {"SPEC-900-demo": ["AC-2"]}


def test_spec_gaps_empty_when_every_ac_claimed(tmp_path: Path) -> None:
    all_marked = _TEST_WITH_MARKERS + (
        '\n@pytest.mark.ac("SPEC-900-demo/AC-2")\ndef test_second():\n    assert True\n'
    )
    _make_repo(tmp_path, test_src=all_marked)
    assert spec_gaps(tmp_path) == {}  # the tier-5 trigger state


def test_malformed_spec_contributes_nothing(tmp_path: Path) -> None:
    _make_repo(tmp_path, spec="# no frontmatter, no id\n- [ ] **AC-1** orphan\n")
    assert spec_gaps(tmp_path) == {}


def test_format_gaps_renders_real_ids() -> None:
    text = format_gaps({"SPEC-900-demo": ["AC-2", "AC-5"]})
    assert "SPEC-900-demo/AC-2" in text and "SPEC-900-demo/AC-5" in text


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.ac("SPEC-070126-9d37/AC-16")
def test_new_ac_coverage_counts_only_net_new_markers(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, test_src=_TEST_WITH_MARKERS)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    test_file = "packages/demo/tests/test_demo.py"
    # Candidate adds AC-2 (new) while AC-1/AC-3 already existed on baseline.
    (repo / test_file).write_text(
        _TEST_WITH_MARKERS
        + '\n@pytest.mark.ac("SPEC-900-demo/AC-2")\ndef test_second():\n    assert True\n',
        encoding="utf-8",
    )
    assert new_ac_coverage(repo, "HEAD", [test_file]) == ["SPEC-900-demo/AC-2"]
    # Unchanged content ⇒ nothing net-new: re-tagging existing ACs earns zero.
    (repo / test_file).write_text(_TEST_WITH_MARKERS, encoding="utf-8")
    assert new_ac_coverage(repo, "HEAD", [test_file]) == []


@pytest.mark.ac("SPEC-070126-9d37/AC-16")
def test_proposed_specs_requires_wellformed_contract(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs" / "specs").mkdir(parents=True)
    good = "---\nid: SPEC-901-idea\n---\n- [ ] **AC-1** a\n- [ ] **AC-2** b\n"
    thin = "---\nid: SPEC-902-thin\n---\n- [ ] **AC-1** only one\n"
    no_id = "# just markdown\n- [ ] **AC-1** a\n- [ ] **AC-2** b\n"
    (root / "docs" / "specs" / "SPEC-901-idea.md").write_text(good, encoding="utf-8")
    (root / "docs" / "specs" / "SPEC-902-thin.md").write_text(thin, encoding="utf-8")
    (root / "docs" / "specs" / "SPEC-903-noid.md").write_text(no_id, encoding="utf-8")
    changed = [
        "docs/specs/SPEC-901-idea.md",
        "docs/specs/SPEC-902-thin.md",
        "docs/specs/SPEC-903-noid.md",
        "packages/demo/src/other.py",
    ]
    # Only the well-formed contract (id + >=2 ACs) earns spec_proposed.
    assert proposed_specs(root, changed) == ["SPEC-901-idea"]
