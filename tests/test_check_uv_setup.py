"""Tests for the uv-setup gate (#213, ADR-082526-3011).

The property worth pinning is narrow and easy to get wrong: **a range looks
like a pin and protects nothing**.

That is not hypothetical. `quality.yml` carried `version: "0.5.x"` for months.
It reads as the fix for #213's flake, and it is not: `setup-uv` resolves a
range by fetching the same manifest an unpinned job fetches, so those three
jobs took the identical network dependency while appearing not to — and they
silently ran uv 0.5.31 while every other job ran 0.12.5.

So a gate that only counted direct `astral-sh/setup-uv` usages would have
called that state compliant. `TestVersionMustBeExact` is the half that would
not have.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-uv-setup.py"

WRAPPER = """\
name: Set up uv
runs:
  using: composite
  steps:
    - uses: astral-sh/setup-uv@v7
      with:
        version: "{version}"
"""


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_uv_setup", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(gate, tmp_path, monkeypatch):
    """A miniature repo: one wrapper pinned exactly, one routed workflow."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    wrapper = tmp_path / ".github" / "actions" / "setup-uv" / "action.yml"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(WRAPPER.format(version="0.12.5"), encoding="utf-8")
    (workflows / "ci.yml").write_text(
        "jobs:\n  a:\n    steps:\n      - uses: ./.github/actions/setup-uv\n", encoding="utf-8"
    )
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "WORKFLOWS", workflows)
    monkeypatch.setattr(gate, "WRAPPER", wrapper)
    return gate


class TestVersionMustBeExact:
    """The half a "no direct usages" gate would have missed."""

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    @pytest.mark.parametrize(
        "version", ["0.5.x", "latest", ">=0.8", "^1.2.3", "0.5", "latest-known"]
    )
    def test_a_non_exact_version_is_refused(self, repo, version):
        """Each of these resolves over the network, so each is the bug (#213).

        `latest-known` is in the list deliberately. It does skip the fetch, but
        it installs whatever the action's own release knows about — a version
        nobody here chose — so this gate does not accept it either.
        """
        repo.WRAPPER.write_text(WRAPPER.format(version=version), encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "exact" in problems[0]

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    @pytest.mark.parametrize("version", ["0.12.5", "0.5.31", "1.0.0"])
    def test_an_exact_version_is_accepted(self, repo, version):
        repo.WRAPPER.write_text(WRAPPER.format(version=version), encoding="utf-8")
        assert repo.wrapper_problems() == []

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_a_wrapper_pinning_nothing_is_refused(self, repo):
        """No version at all means the action falls back to `latest`."""
        repo.WRAPPER.write_text(
            "runs:\n  using: composite\n  steps:\n    - uses: astral-sh/setup-uv@v7\n",
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "pins no version" in problems[0]

    def test_a_commented_version_does_not_count_as_a_pin(self, repo):
        """The real wrapper's comment block mentions versions; only a key counts."""
        repo.WRAPPER.write_text(
            "runs:\n  using: composite\n  steps:\n"
            '    # version: "0.5.x" was the old value\n'
            "    - uses: astral-sh/setup-uv@v7\n",
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "pins no version" in problems[0]

    def test_a_wrapper_that_stopped_wrapping_setup_uv_is_refused(self, repo):
        repo.WRAPPER.write_text("runs:\n  using: composite\n  steps: []\n", encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "no longer wraps" in problems[0]

    def test_a_missing_wrapper_is_refused(self, repo):
        repo.WRAPPER.unlink()
        problems = repo.wrapper_problems()
        assert problems and "missing" in problems[0]


class TestNoDirectUsages:
    """#213: a mix means the flake gets rarer and harder to attribute."""

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_direct_usage_is_found(self, repo):
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv@v7\n", encoding="utf-8"
        )
        found = repo.direct_usages()
        assert len(found) == 1 and "rogue.yml:4" in found[0]

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_direct_usage_without_a_ref_is_found(self, repo):
        """`uses: astral-sh/setup-uv` unversioned must not slip past."""
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv\n", encoding="utf-8"
        )
        assert repo.direct_usages()

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_the_name_then_uses_form_is_found(self, repo):
        """The form that hid three stale `version:` inputs while being rewritten."""
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n"
            "      - name: Install uv\n        uses: astral-sh/setup-uv@v7\n",
            encoding="utf-8",
        )
        assert repo.direct_usages()

    def test_the_wrapper_itself_is_not_a_direct_usage(self, repo):
        """It is the one file that must call setup-uv; it is not a workflow."""
        assert repo.direct_usages() == []

    def test_a_routed_usage_is_counted(self, repo):
        assert repo.routed_usages() == 1


class TestDriver:
    def test_a_clean_repo_exits_zero(self, repo, capsys):
        assert repo.main() == 0
        assert "0.12.5" in capsys.readouterr().out

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_direct_usage_exits_one(self, repo):
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv@v7\n", encoding="utf-8"
        )
        assert repo.main() == 1

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_a_range_in_the_wrapper_exits_one(self, repo):
        """The state the repository was actually in, now a build failure."""
        repo.WRAPPER.write_text(WRAPPER.format(version="0.5.x"), encoding="utf-8")
        assert repo.main() == 1

    def test_both_problems_are_reported_together(self, repo, capsys):
        """One run should name everything wrong, not the first thing wrong."""
        repo.WRAPPER.write_text(WRAPPER.format(version="latest"), encoding="utf-8")
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv@v7\n", encoding="utf-8"
        )
        assert repo.main() == 1
        err = capsys.readouterr().err
        assert "exact" in err and "rogue.yml" in err


class TestAgainstTheRealTree:
    """The gate's own subject: this repository, as committed."""

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_no_workflow_calls_setup_uv_directly(self, gate):
        assert gate.direct_usages() == []

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_the_committed_wrapper_pins_an_exact_version(self, gate):
        assert gate.wrapper_problems() == []
        version = gate.wrapper_version(gate.WRAPPER.read_text(encoding="utf-8"))
        assert gate.EXACT_RE.match(version), f"{version} is not exact"

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_every_workflow_that_uses_uv_goes_through_the_wrapper(self, gate):
        """Guards the rewrite itself: 20 usages were routed, none dropped."""
        assert gate.routed_usages() >= 20
