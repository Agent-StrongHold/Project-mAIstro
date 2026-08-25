"""Tests for the uv-setup gate (#213, ADR-082526-3011).

Two different things are pinned here and they fix two different problems. The
tests are organised so that distinction cannot quietly collapse, because it
already collapsed once — in #213's own framing, and then in the first version
of this PR.

**The manifest fetch is unconditional.** Measured on PR #264: `v7` with an
exact version fetches, `v7` with `latest-known` fetches and then fails, and
`v10.0.1` with an exact version fetches. No `version` value avoids the request.
What `v10.0.1` changes is that a transient failure of it is no longer fatal —
that release ships as "Tolerate transient manifest timeouts".

So `TestActionReleaseIsPinned` guards the actual #213 fix, and
`TestVersionMustBeExact` guards something real but different: `quality.yml`
carried `version: "0.5.x"`, which resolved to uv 0.5.31 while every other job
resolved `latest` to 0.12.5. Two uv versions, seven minor releases apart,
neither chosen. That is a determinism defect, and a gate that only counted
direct `astral-sh/setup-uv` usages would have called it compliant.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-uv-setup.py"

PINNED = "astral-sh/setup-uv@v10.0.1"

WRAPPER = """\
name: Set up uv
runs:
  using: composite
  steps:
    - uses: {action}
      with:
        version: "{version}"
"""


def wrapper_text(version: str = "0.12.5", action: str = PINNED) -> str:
    return WRAPPER.format(version=version, action=action)


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
    wrapper.write_text(wrapper_text(), encoding="utf-8")
    (workflows / "ci.yml").write_text(
        "jobs:\n  a:\n    steps:\n      - uses: ./.github/actions/setup-uv\n", encoding="utf-8"
    )
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "WORKFLOWS", workflows)
    monkeypatch.setattr(gate, "WRAPPER", wrapper)
    return gate


class TestActionReleaseIsPinned:
    """The actual #213 fix: only this release tolerates a manifest outage."""

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_an_older_action_release_is_refused(self, repo):
        """v7 is what the repo was on, and what has no tolerance."""
        repo.WRAPPER.write_text(wrapper_text(action="astral-sh/setup-uv@v7"), encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "v10.0.1" in problems[0]

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_a_floating_major_is_refused(self, repo):
        """There is no floating major above v7 to track — measured with
        `git ls-remote --tags`, and `@v10` fails to resolve at job start."""
        repo.WRAPPER.write_text(wrapper_text(action="astral-sh/setup-uv@v10"), encoding="utf-8")
        assert repo.wrapper_problems()

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_the_pinned_release_is_accepted(self, repo):
        assert repo.wrapper_problems() == []

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_the_committed_wrapper_uses_the_pinned_release(self, gate):
        assert f"uses: {gate.PINNED_ACTION}" in gate.WRAPPER.read_text(encoding="utf-8")


class TestVersionMustBeExact:
    """Real, but a determinism defect — not the flake fix."""

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    @pytest.mark.parametrize(
        "version", ["0.5.x", "latest", ">=0.8", "^1.2.3", "0.5", "latest-known"]
    )
    def test_a_non_exact_version_is_refused(self, repo, version):
        """Each leaves the installed uv to whatever the manifest offers that day.

        `latest-known` is in the list deliberately, and for a reason that has
        nothing to do with the fetch — it installs whatever the action release
        happens to know about, which is still not a version anyone here chose.
        (Measured: it does not skip the fetch either, and on v7 it is not even
        a valid selector.)
        """
        repo.WRAPPER.write_text(wrapper_text(version), encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "exact" in problems[0]

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    @pytest.mark.parametrize("version", ["0.12.5", "0.5.31", "1.0.0"])
    def test_an_exact_version_is_accepted(self, repo, version):
        repo.WRAPPER.write_text(wrapper_text(version), encoding="utf-8")
        assert repo.wrapper_problems() == []

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_a_wrapper_pinning_nothing_is_refused(self, repo):
        """No version at all means the action falls back to `latest`."""
        repo.WRAPPER.write_text(
            f"runs:\n  using: composite\n  steps:\n    - uses: {PINNED}\n",
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "pins no uv version" in problems[0]

    def test_a_commented_version_does_not_count_as_a_pin(self, repo):
        """The real wrapper's comment block mentions versions; only a key counts."""
        repo.WRAPPER.write_text(
            "runs:\n  using: composite\n  steps:\n"
            '    # version: "0.5.x" was the old value\n'
            f"    - uses: {PINNED}\n",
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "pins no uv version" in problems[0]

    def test_a_wrapper_that_stopped_wrapping_setup_uv_is_refused(self, repo):
        repo.WRAPPER.write_text("runs:\n  using: composite\n  steps: []\n", encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "no `runs.steps` entry" in problems[0]

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
        repo.WRAPPER.write_text(wrapper_text("0.5.x"), encoding="utf-8")
        assert repo.main() == 1

    def test_both_problems_are_reported_together(self, repo, capsys):
        """One run should name everything wrong, not the first thing wrong."""
        repo.WRAPPER.write_text(wrapper_text("latest"), encoding="utf-8")
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


class TestReviewFindings:
    """Regressions for the three findings Codex raised on PR #264.

    All three were the same shape as the ones on #263, and the same shape as
    the bug this whole gate exists to prevent: a check that reports success
    while checking nothing. Two of them defeated the gate by *quoting* or by
    *renaming a file extension*, which is not a high bar to clear.
    """

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_yaml_extension_workflow_is_scanned(self, repo):
        """GitHub runs `.yaml` too; the glob only had `.yml`."""
        (repo.WORKFLOWS / "build.yaml").write_text(
            f"jobs:\n  a:\n    steps:\n      - uses: {PINNED}\n", encoding="utf-8"
        )
        found = repo.direct_usages()
        assert found and "build.yaml" in found[0]

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_trailing_comment_does_not_hide_a_direct_usage(self, repo):
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - uses: astral-sh/setup-uv@v7 # install uv\n",
            encoding="utf-8",
        )
        assert repo.direct_usages()

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_quoted_scalar_does_not_hide_a_direct_usage(self, repo):
        (repo.WORKFLOWS / "rogue.yml").write_text(
            'jobs:\n  a:\n    steps:\n      - uses: "astral-sh/setup-uv@v7"\n',
            encoding="utf-8",
        )
        assert repo.direct_usages()

    @pytest.mark.ac("ADR-082526-3011/AC-2")
    def test_a_job_level_uses_is_found(self, repo):
        """Reusable-workflow `uses:` sits at job level, not under steps."""
        (repo.WORKFLOWS / "rogue.yml").write_text(
            "jobs:\n  a:\n    uses: astral-sh/setup-uv@v7\n", encoding="utf-8"
        )
        assert repo.direct_usages()

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_comments_naming_the_action_do_not_satisfy_the_check(self, repo):
        """The real wrapper's comment block names the action many times.

        A substring check over the file text was therefore satisfied by the
        prose explaining the pin rather than by the pin itself — so a swap to
        a different action, with the comments left in place, passed.
        """
        repo.WRAPPER.write_text(
            f"# this wrapper exists to pin {PINNED}\n"
            "runs:\n  using: composite\n  steps:\n"
            "    - uses: some-other/action@v1\n"
            '      with:\n        version: "0.12.5"\n',
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "no `runs.steps` entry" in problems[0]

    @pytest.mark.ac("ADR-082526-3011/AC-1")
    def test_a_version_in_a_comment_is_not_the_pinned_version(self, repo):
        """Only the parsed step's `with.version` counts."""
        repo.WRAPPER.write_text(
            '# version: "0.12.5" used to live here\n'
            "runs:\n  using: composite\n  steps:\n"
            f"    - uses: {PINNED}\n",
            encoding="utf-8",
        )
        problems = repo.wrapper_problems()
        assert problems and "pins no uv version" in problems[0]

    def test_a_malformed_wrapper_is_reported_not_ignored(self, repo):
        repo.WRAPPER.write_text("runs: [unclosed\n", encoding="utf-8")
        problems = repo.wrapper_problems()
        assert problems and "not valid YAML" in problems[0]

    def test_a_malformed_workflow_is_skipped_deliberately(self, repo):
        """Documented, not accidental: actionlint owns malformed workflows.

        The cost is real and worth stating — a direct usage inside a workflow
        that does not parse is not reported here. `workflow-lint` runs actionlint
        in the same job, and it fails on such a file first, so the hole cannot
        be reached in CI without that job already being red.
        """
        (repo.WORKFLOWS / "broken.yml").write_text(
            "jobs: [unclosed\n      - uses: astral-sh/setup-uv@v7\n", encoding="utf-8"
        )
        assert repo.direct_usages() == []

    def test_a_wrapper_step_without_a_with_block_pins_no_version(self, repo):
        repo.WRAPPER.write_text(
            f"runs:\n  using: composite\n  steps:\n    - uses: {PINNED}\n", encoding="utf-8"
        )
        assert repo.wrapper_version(repo.WRAPPER.read_text(encoding="utf-8")) is None

    def test_a_wrapper_with_no_steps_at_all_pins_no_version(self, repo):
        repo.WRAPPER.write_text("runs:\n  using: composite\n", encoding="utf-8")
        assert repo.wrapper_version(repo.WRAPPER.read_text(encoding="utf-8")) is None
