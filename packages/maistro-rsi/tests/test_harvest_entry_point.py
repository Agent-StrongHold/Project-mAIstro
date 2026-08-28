"""The export policy is reached through the command the workflow runs (#356).

`test_export_policy.py` proves the policy. This proves it is *wired*: the
harvest subcommand is the only way `rsi-harvest.yml` reaches any of this, and a
correct policy nothing calls is the shape #257 was filed about.

Everything here stops before git does any work. The pre-flight validation pass
runs before the clone and before the first `checkout -B`, which is the point of
it — a refused export must leave no branch behind, not clean one up.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from maistro_rsi.__main__ import _build_parser, main
from maistro_rsi.export_policy import CANONICAL_DEVELOPMENT_BRANCH

ORDINARY = "packages/maistro-core/src/maistro/router/scorer.py"


def _patch_text(path: str = ORDINARY) -> str:
    return (
        "From 0123456789abcdef Mon Sep 17 00:00:00 2001\n"
        "Subject: [PATCH] improve\n"
        "---\n"
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """An export directory shaped exactly like the one the workflow fetches."""
    directory = tmp_path / ".rsi-exports"
    directory.mkdir()
    (directory / "0001.patch").write_text(_patch_text(), encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps([{"patch_file": "0001.patch", "file": ORDINARY, "subject": "improve"}]),
        encoding="utf-8",
    )
    return directory


def _argv(export: Path, *extra: str) -> list[str]:
    return [
        "harvest",
        "--export-dir",
        str(export),
        "--repo-dir",
        str(export),  # never reached on the paths under test
        *extra,
    ]


class TestTheTierIsPolicyAtTheEntryPoint:
    def test_the_flag_no_longer_defaults_to_the_release_tier(self) -> None:
        """`--pr-base` used to default to the string "main", which is what made
        the release tier the *documented* target of a harvest."""
        args = _build_parser().parse_args(["harvest", "--export-dir", "x"])

        assert args.pr_base is None
        assert args.allow_release_tier is False

    def test_a_release_tier_is_refused_before_any_git_work(self, export: Path, capsys) -> None:
        assert main(_argv(export, "--pr-base", "main")) == 2
        assert "main" in capsys.readouterr().err

    def test_the_authorization_flag_exists_and_is_separate(self, export: Path) -> None:
        """The AC's "explicit separately authorized policy": reaching a release
        tier takes a second, deliberate flag rather than a different value in
        the first one."""
        args = _build_parser().parse_args(
            ["harvest", "--export-dir", "x", "--pr-base", "main", "--allow-release-tier"]
        )

        assert args.allow_release_tier is True

    def test_nothing_in_the_manifest_can_choose_the_tier(self, export: Path) -> None:
        """The manifest is data off the export branch. If a field there could
        move the target, the tier would be candidate-controlled by another
        name."""
        (export / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "patch_file": "0001.patch",
                        "file": ORDINARY,
                        "pr_base": "main",
                        "base": "main",
                        "allow_release_tier": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        args = _build_parser().parse_args(_argv(export))

        assert args.pr_base is None
        assert args.allow_release_tier is False


class TestARefusedExportOpensNothing:
    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/ci.yml",
            "packages/maistro-rsi/src/maistro_rsi/quarantine.py",
            "packages/maistro-core/src/maistro/security/warden/detector.py",
        ],
    )
    def test_a_patch_on_the_containment_surface_fails_the_harvest(
        self, export: Path, capsys, path: str
    ) -> None:
        (export / "0001.patch").write_text(_patch_text(path), encoding="utf-8")
        (export / "manifest.json").write_text(
            json.dumps([{"patch_file": "0001.patch", "file": path}]), encoding="utf-8"
        )

        assert main(_argv(export)) == 3
        assert "containment surface" in capsys.readouterr().err

    def test_a_manifest_pointing_outside_the_export_fails_the_harvest(
        self, export: Path, capsys
    ) -> None:
        outside = export.parent / "elsewhere.patch"
        outside.write_text(_patch_text(), encoding="utf-8")
        (export / "manifest.json").write_text(
            json.dumps([{"patch_file": "../elsewhere.patch", "file": ORDINARY}]), encoding="utf-8"
        )

        assert main(_argv(export)) == 3
        assert "outside the export directory" in capsys.readouterr().err

    def test_a_symlinked_manifest_entry_fails_the_harvest(self, export: Path) -> None:
        outside = export.parent / "elsewhere.patch"
        outside.write_text(_patch_text(), encoding="utf-8")
        (export / "0001.patch").unlink()
        (export / "0001.patch").symlink_to(outside)

        assert main(_argv(export)) == 3

    def test_one_bad_patch_fails_the_whole_export(self, export: Path) -> None:
        """Not a per-patch skip. A stale patch is an accident and the rest of
        the run is still good; a patch reaching for the containment surface is
        a statement about this export, and opening the other PRs from it would
        treat one artifact as trustworthy and untrustworthy at once."""
        (export / "0002.patch").write_text(
            _patch_text(".github/workflows/ci.yml"), encoding="utf-8"
        )
        (export / "manifest.json").write_text(
            json.dumps(
                [
                    {"patch_file": "0001.patch", "file": ORDINARY},
                    {"patch_file": "0002.patch", "file": ".github/workflows/ci.yml"},
                ]
            ),
            encoding="utf-8",
        )

        assert main(_argv(export)) == 3

    def test_the_refusal_names_every_reason(self, export: Path, capsys) -> None:
        """An operator reading a refused harvest wants the whole list, not the
        first line of it."""
        (export / "0001.patch").write_text(
            _patch_text(".github/workflows/ci.yml")
            + "diff --git a/docs/link b/docs/link\nnew file mode 120000\n",
            encoding="utf-8",
        )
        (export / "manifest.json").write_text(
            json.dumps([{"patch_file": "0001.patch", "file": ".github/workflows/ci.yml"}]),
            encoding="utf-8",
        )
        main(_argv(export))
        err = capsys.readouterr().err

        assert "containment surface" in err
        assert "symlink" in err

    def test_an_ordinary_export_passes_validation(self, export: Path) -> None:
        """The counterweight: the policy must not stop a legitimate harvest.

        Reaching git at all is the assertion. The pre-flight runs before any
        git work, so a refusal returns 3 without ever invoking it — getting as
        far as `rev-parse` failing on a directory that is not a repository is
        precisely "the policy did not refuse this"."""
        with pytest.raises(subprocess.CalledProcessError) as caught:
            main(_argv(export))

        assert "rev-parse" in " ".join(caught.value.cmd)


class TestTheWorkflowMatchesThePolicy:
    """The workflow is the only caller in the repository, so a policy the CLI
    enforces and the workflow works around is not enforced."""

    WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/rsi-harvest.yml"

    def test_it_no_longer_takes_a_free_text_target(self) -> None:
        """Asserted on the parsed inputs, not on the file text: the comment
        explaining why `pr_base` was removed necessarily mentions it, and a
        substring check would either fail on the explanation or force the
        explanation out."""
        import yaml

        spec = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))
        inputs = spec[True]["workflow_dispatch"]["inputs"]

        assert "pr_base" not in inputs

    def test_it_does_not_pass_the_retired_flag_either(self) -> None:
        """An input removed from the form but still passed on the command line
        would be the same defect with a constant instead of a variable."""
        body = self.WORKFLOW.read_text(encoding="utf-8")
        commands = [
            line
            for line in body.splitlines()
            if "maistro_rsi harvest" in line or line.strip().startswith("--")
        ]

        assert not [line for line in commands if "--pr-base" in line]

    def test_it_does_not_pass_a_base_at_all(self) -> None:
        """Passing one would re-introduce the same input by another name; the
        harvester defaults both to the canonical development branch."""
        body = self.WORKFLOW.read_text(encoding="utf-8")

        assert "--base " not in body

    def test_its_authorization_input_defaults_to_off(self) -> None:
        import yaml

        spec = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))
        # `on:` parses as the boolean True in YAML 1.1, which is why this reads
        # the key rather than the attribute.
        inputs = spec[True]["workflow_dispatch"]["inputs"]

        assert inputs["allow_release_tier"]["default"] is False

    def test_the_harvest_still_runs_with_least_privilege(self) -> None:
        """Unchanged by this PR, and worth a test because the trust model rests
        on it: open PRs, never merge them."""
        import yaml

        spec = yaml.safe_load(self.WORKFLOW.read_text(encoding="utf-8"))

        assert spec["permissions"] == {"contents": "write", "pull-requests": "write"}


def test_the_canonical_branch_matches_the_repositorys_default() -> None:
    """ADR-095 names `develop` as the active integration tier and the base every
    topic branch targets. If that ever moves, this constant has to move with it
    rather than silently keep aiming at the old one.

    Matched against two places rather than one sentence. #162 rewrote this ADR
    and reworded "branch off" to "branch from", which failed the single exact
    phrase this used to pin even though the decision it encodes had not moved
    at all -- the constant still matched the ADR. Naming the branch in the flow
    diagram *and* in the prose keeps a genuine change to the canonical branch
    failing while a rewrite that leaves it alone does not.
    """
    adr = Path(__file__).resolve().parents[3] / "docs/adr/ADR-095-four-tier-branch-model.md"
    body = adr.read_text(encoding="utf-8")

    assert f"topic branches -> {CANONICAL_DEVELOPMENT_BRANCH} -> main" in body
    assert f"branch from `{CANONICAL_DEVELOPMENT_BRANCH}`" in body
