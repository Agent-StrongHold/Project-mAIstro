"""What an exported RSI patch may contain, and where its PR may go (#356).

The harvest step is where agent-authored work crosses from the sandbox into
the repository. `rsi-harvest.yml` runs with `contents: write` and
`pull-requests: write`, and the trust model (ADR-070126-6386 / ADR-093) rests
on one claim: no agent-authored code *runs* there, because the exports are
data.

The claim held for execution and not for content. The workflow refused an
export directory holding anything but `*.patch` and `manifest.json`, then
handed those patches to `git am` without asking what was in them — and a patch
is a program for the working tree.

It also let the *target tier* be a `workflow_dispatch` input defaulting to
`main`, so the documented way to run a harvest opened agent-authored PRs
straight at the release tier.
"""

from __future__ import annotations

import pytest

from maistro_rsi.export_policy import (
    CANONICAL_DEVELOPMENT_BRANCH,
    ExportPolicyError,
    patch_paths,
    resolve_export_path,
    resolve_pr_base,
    validate_patch,
)

ORDINARY = "packages/maistro-core/src/maistro/router/scorer.py"


def _patch(*, path: str = ORDINARY, extra: str = "") -> str:
    """A minimal but real `git format-patch` body."""
    return (
        "From 0123456789abcdef Mon Sep 17 00:00:00 2001\n"
        "From: maistro-rsi <rsi@maistro.local>\n"
        "Subject: [PATCH] tighten the scoring docstring\n"
        "---\n"
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,2 +1,2 @@\n"
        "-old line\n"
        "+new line\n" + extra
    )


class TestWhereAHarvestedPrMayGo:
    """ADR-095: topic branches → `develop` → `integration` → `main`, with
    `main` requiring an approving review. A harvest branch is a topic branch,
    so aiming one at a release tier skips both integration tiers *and* the
    approval."""

    def test_the_default_is_the_development_tier(self) -> None:
        """It used to be `main`, in both the CLI flag and the workflow input."""
        assert resolve_pr_base(None) == CANONICAL_DEVELOPMENT_BRANCH
        assert resolve_pr_base("") == CANONICAL_DEVELOPMENT_BRANCH
        assert resolve_pr_base("   ") == CANONICAL_DEVELOPMENT_BRANCH

    @pytest.mark.parametrize("tier", ["main", "integration", "master"])
    def test_a_release_tier_is_refused(self, tier: str) -> None:
        with pytest.raises(ExportPolicyError) as caught:
            resolve_pr_base(tier)

        assert tier in str(caught.value)

    @pytest.mark.parametrize("tier", ["main", "integration"])
    def test_a_release_tier_is_allowed_only_with_separate_authorization(self, tier: str) -> None:
        """The AC's "explicit separately authorized policy". It is a parameter
        of the caller — the workflow decides it from its own configuration —
        not something the export, the manifest, or a candidate can express."""
        assert resolve_pr_base(tier, release_tier_authorized=True) == tier

    def test_an_ordinary_branch_is_honoured(self) -> None:
        """Policy constrains the tier, not every target. A harvest onto a
        long-lived topic branch skips nothing."""
        assert resolve_pr_base("feat/rsi-experiment") == "feat/rsi-experiment"

    def test_surrounding_whitespace_does_not_smuggle_a_release_tier(self) -> None:
        """`" main "` is `main` to git. A check on the raw string would let it
        through and then push there anyway."""
        with pytest.raises(ExportPolicyError):
            resolve_pr_base("  main  ")


class TestReadingThePatchTheManifestNames:
    """`patch_file` comes off the export branch, so it is attacker-influenced
    in exactly the way a filename can be. The previous code did
    `(export / patch.patch_file).resolve()`, which *follows* a symlink and
    normalises a traversal away — turning both into a valid-looking path."""

    def test_a_normal_entry_resolves(self, tmp_path) -> None:
        (tmp_path / "0001.patch").write_text(_patch(), encoding="utf-8")

        assert resolve_export_path(tmp_path, "0001.patch").name == "0001.patch"

    @pytest.mark.parametrize(
        "entry", ["../outside.patch", "../../etc/shadow", "a/../../outside.patch"]
    )
    def test_a_traversal_is_refused(self, tmp_path, entry: str) -> None:
        outside = tmp_path.parent / "outside.patch"
        outside.write_text(_patch(), encoding="utf-8")
        export = tmp_path / "exports"
        export.mkdir()

        with pytest.raises(ExportPolicyError):
            resolve_export_path(export, entry)

    def test_an_absolute_path_is_refused(self, tmp_path) -> None:
        target = tmp_path / "elsewhere.patch"
        target.write_text(_patch(), encoding="utf-8")
        export = tmp_path / "exports"
        export.mkdir()

        with pytest.raises(ExportPolicyError):
            resolve_export_path(export, str(target))

    def test_a_symlink_pointing_out_of_the_export_is_refused(self, tmp_path) -> None:
        """Every textual component is innocent here — the escape only exists
        after the link is followed, which is why the check has to be on the
        *resolved* path against the *resolved* root."""
        outside = tmp_path / "outside.patch"
        outside.write_text(_patch(), encoding="utf-8")
        export = tmp_path / "exports"
        export.mkdir()
        (export / "0001.patch").symlink_to(outside)

        with pytest.raises(ExportPolicyError):
            resolve_export_path(export, "0001.patch")

    def test_a_symlink_staying_inside_the_export_is_allowed(self, tmp_path) -> None:
        """Refusing every symlink would be simpler and would refuse a legitimate
        export layout. The property is where it lands, not that it is a link."""
        export = tmp_path / "exports"
        export.mkdir()
        real = export / "real.patch"
        real.write_text(_patch(), encoding="utf-8")
        (export / "0001.patch").symlink_to(real)

        assert resolve_export_path(export, "0001.patch") == real.resolve()

    def test_a_directory_is_refused(self, tmp_path) -> None:
        (tmp_path / "0001.patch").mkdir()

        with pytest.raises(ExportPolicyError):
            resolve_export_path(tmp_path, "0001.patch")

    def test_a_missing_entry_is_refused(self, tmp_path) -> None:
        with pytest.raises(ExportPolicyError):
            resolve_export_path(tmp_path, "nope.patch")


class TestWhichPathsAPatchTouches:
    def test_both_sides_of_the_header_are_read(self) -> None:
        assert patch_paths(_patch()) == (ORDINARY,)

    def test_a_rename_contributes_both_ends(self) -> None:
        """A rename touches two paths, and only one of them appears where a
        reader skimming for `+++ b/` would look."""
        text = (
            "diff --git a/old/name.py b/new/name.py\n"
            "similarity index 95%\n"
            "rename from old/name.py\n"
            "rename to new/name.py\n"
        )
        assert set(patch_paths(text)) == {"old/name.py", "new/name.py"}

    def test_a_quoted_path_is_unwrapped(self) -> None:
        """git quotes a path containing unusual bytes. Without unwrapping,
        a path could be hidden from the policy by containing one."""
        text = 'diff --git "a/maistro/security/warden.py" "b/maistro/security/warden.py"\n'
        assert "maistro/security/warden.py" in patch_paths(text)

    def test_a_quoted_rename_target_is_unwrapped(self) -> None:
        """git quotes a rename line the same way it quotes a header, and the
        rename lines are the only place the quotes reach `_unquote` still
        attached — the header pattern captures the inside of them. So this is
        the one path on which stripping a surrounding pair matters at all."""
        text = (
            "diff --git a/old.py b/new.py\n"
            "similarity index 95%\n"
            'rename from "packages/maistro-core/src/maistro/security/warden.py"\n'
            'rename to "packages/maistro-core/src/maistro/security/warden2.py"\n'
        )
        paths = patch_paths(text)

        assert "packages/maistro-core/src/maistro/security/warden.py" in paths
        assert not any(path.startswith('"') for path in paths)

    def test_a_quoted_rename_onto_the_containment_surface_is_refused(self) -> None:
        """The consequence, rather than the parsing. A quoted rename that left
        its quotes attached would compare against a name no pattern matches."""
        text = (
            "diff --git a/docs/a.py b/docs/b.py\n"
            "similarity index 95%\n"
            'rename from "docs/a.py"\n'
            'rename to "packages/maistro-rsi/src/maistro_rsi/quarantine.py"\n'
        )
        assert not validate_patch(text).ok

    def test_a_patch_touching_nothing_is_reported(self) -> None:
        """A body with no `diff --git` identifies nothing about what it
        changes, which is not a thing to apply and open a PR for."""
        verdict = validate_patch("Subject: [PATCH] nothing at all\n")

        assert not verdict.ok


class TestTheContainmentSurfaceIsTheSameOnTheWayOut:
    """`quarantine.py` applies `matches_sensitive_pattern` to a run's diff
    *inside* the loop. The AC asks for the same policy on the export, the PR
    and the merge — this is the export half."""

    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/ci.yml",
            "quality/vulture-baseline.json",
            "packages/maistro-core/src/maistro/security/warden/detector.py",
            "packages/maistro-rsi/src/maistro_rsi/quarantine.py",
            "packages/maistro-rsi/src/maistro_rsi/sandbox/local.py",
            "packages/maistro-core/src/maistro/policy/budget.py",
        ],
    )
    def test_a_patch_reaching_for_the_containment_surface_is_refused(self, path: str) -> None:
        verdict = validate_patch(_patch(path=path))

        assert not verdict.ok
        assert any("containment surface" in reason for reason in verdict.reasons)

    def test_the_gate_config_is_covered_because_it_gates_everything_else(self) -> None:
        """`.github/` is on the surface for a reason worth restating: a
        self-improvement loop that can edit its own CI can retire the checks
        that would have caught its next change."""
        assert not validate_patch(_patch(path=".github/workflows/quality.yml")).ok

    def test_deleting_a_protected_file_is_refused_too(self) -> None:
        """Removal is the cheapest way to disable a check, and a deletion diff
        has no `+++ b/` side to notice."""
        text = (
            "diff --git a/packages/maistro-rsi/src/maistro_rsi/quarantine.py "
            "b/packages/maistro-rsi/src/maistro_rsi/quarantine.py\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
        )
        assert not validate_patch(text).ok

    def test_deleting_an_ordinary_file_is_allowed(self) -> None:
        """The counterweight to the protected-deletion check. A promotion that
        removes a dead ordinary module is a legitimate improvement, and a
        policy that refused every deletion would block it for nothing."""
        text = (
            "diff --git a/packages/maistro-core/src/maistro/dead.py "
            "b/packages/maistro-core/src/maistro/dead.py\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
        )
        assert validate_patch(text).ok

    def test_ordinary_application_code_is_not_refused(self) -> None:
        """The counterweight. A policy that refused everything would stop the
        loop rather than contain it."""
        assert validate_patch(_patch(), declared_file=ORDINARY).ok


class TestFileKindsAPathCheckCannotSee:
    """`a/b/c` is an ordinary-looking path whether the mode beside it says
    regular file, symlink, or gitlink."""

    def test_a_symlink_is_refused(self) -> None:
        """A later write through it lands wherever it points — and the link
        need not exist yet, so resolving symlinks in the export directory does
        not cover this."""
        extra = (
            "diff --git a/docs/link b/docs/link\n"
            "new file mode 120000\n"
            "--- /dev/null\n"
            "+++ b/docs/link\n"
            "@@ -0,0 +1 @@\n"
            "+/etc/passwd\n"
        )
        verdict = validate_patch(_patch(extra=extra))

        assert not verdict.ok
        assert any("symlink" in reason for reason in verdict.reasons)

    def test_a_mode_change_to_a_symlink_is_refused(self) -> None:
        """Turning an existing regular file into a link is the same capability
        without a `new file mode` line."""
        extra = "diff --git a/docs/thing b/docs/thing\nold mode 100644\nnew mode 120000\n"
        assert not validate_patch(_patch(extra=extra)).ok

    def test_a_submodule_pointer_is_refused(self) -> None:
        """Nothing downstream of the harvest reviews the history it would
        point at."""
        extra = (
            "diff --git a/vendor/thing b/vendor/thing\n"
            "new file mode 160000\n"
            "--- /dev/null\n"
            "+++ b/vendor/thing\n"
        )
        verdict = validate_patch(_patch(extra=extra))

        assert not verdict.ok
        assert any("submodule" in reason for reason in verdict.reasons)

    def test_a_binary_hunk_is_refused(self) -> None:
        """The promotion contract is a minimal, reviewable edit to one source
        file. A blob is neither, and no reviewer of the PR can read it."""
        extra = (
            "diff --git a/assets/blob.bin b/assets/blob.bin\n"
            "new file mode 100644\n"
            "GIT binary patch\n"
            "literal 8\n"
            "zcmZQzU|\n"
        )
        assert not validate_patch(_patch(extra=extra)).ok


class TestTheManifestsClaimIsCheckedNotTrusted:
    """The harvester groups by the manifest's `file`, names the branch after
    it, and puts it in the PR title. A patch touching anything else produces a
    PR whose every human-readable label is wrong about its own contents — and
    the manifest and the patch come from the same place."""

    def test_a_patch_touching_an_undeclared_file_is_refused(self) -> None:
        verdict = validate_patch(
            _patch(path="packages/maistro-core/src/maistro/other.py"), declared_file=ORDINARY
        )

        assert not verdict.ok
        assert any("manifest declares" in reason for reason in verdict.reasons)

    def test_a_second_file_smuggled_alongside_the_declared_one_is_refused(self) -> None:
        """The realistic shape: the declared edit is genuine and something else
        rides along in the same patch."""
        extra = (
            "diff --git a/packages/maistro-core/src/maistro/quiet.py "
            "b/packages/maistro-core/src/maistro/quiet.py\n"
            "index 3333333..4444444 100644\n"
            "--- a/packages/maistro-core/src/maistro/quiet.py\n"
            "+++ b/packages/maistro-core/src/maistro/quiet.py\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
        )
        assert not validate_patch(_patch(extra=extra), declared_file=ORDINARY).ok

    def test_without_a_declared_file_the_other_checks_still_run(self) -> None:
        """`declared_file` is optional, and its absence must not switch off the
        protected-path policy."""
        assert not validate_patch(_patch(path=".github/workflows/ci.yml")).ok


class TestPathsThatLeaveTheRepository:
    @pytest.mark.parametrize(
        "path", ["../outside.py", "a/../../outside.py", "/etc/passwd", "..\\\\windows\\\\thing"]
    )
    def test_a_path_outside_the_repository_is_refused(self, path: str) -> None:
        verdict = validate_patch(_patch(path=path))

        assert not verdict.ok
        assert any("outside the repository" in reason for reason in verdict.reasons)

    def test_a_dotdot_inside_a_filename_is_not_a_traversal(self) -> None:
        """`..` as a path *segment* escapes; `..` inside a name does not.
        Refusing `weird..name.py` would be a false positive of the kind that
        teaches people to work around the gate."""
        assert validate_patch(
            _patch(path="docs/weird..name.py"), declared_file="docs/weird..name.py"
        ).ok


class TestARefusalSaysEverythingThatIsWrong:
    """A reviewer looking at a refused export wants all of it, not the earliest
    finding: a patch that both edits `.github/` and creates a symlink is a
    different object from one that only does the first."""

    def test_multiple_problems_are_all_reported(self) -> None:
        extra = (
            "diff --git a/docs/link b/docs/link\n"
            "new file mode 120000\n"
            "--- /dev/null\n"
            "+++ b/docs/link\n"
        )
        verdict = validate_patch(_patch(path=".github/workflows/ci.yml", extra=extra))

        assert len(verdict.reasons) >= 2
        assert any("containment surface" in reason for reason in verdict.reasons)
        assert any("symlink" in reason for reason in verdict.reasons)

    def test_reasons_are_deduplicated(self) -> None:
        """Two symlinks are one thing to fix, not two lines of the same
        sentence."""
        extra = (
            "diff --git a/docs/l1 b/docs/l1\nnew file mode 120000\n"
            "diff --git a/docs/l2 b/docs/l2\nnew file mode 120000\n"
        )
        verdict = validate_patch(_patch(extra=extra))
        symlink_reasons = [r for r in verdict.reasons if "symlink" in r]

        assert len(symlink_reasons) == 1

    def test_the_paths_it_saw_are_reported_alongside(self) -> None:
        """So an operator can tell "the policy refused this path" from "the
        policy never saw this path" — the two need different fixes."""
        verdict = validate_patch(_patch(path=".github/workflows/ci.yml"))

        assert verdict.paths == (".github/workflows/ci.yml",)

    def test_a_quoted_header_beside_an_ordinary_one_is_still_checked(self) -> None:
        """The bypass the quoting gap actually bought. A patch whose *only*
        header is quoted fails closed — the path list is empty, so the "nothing
        here identifies what it changes" refusal fires. One ordinary header
        alongside it makes the list non-empty, that refusal never fires, and
        the quoted path goes unexamined."""
        extra = (
            'diff --git "a/packages/maistro-core/src/maistro/security/warden/detector.py" '
            '"b/packages/maistro-core/src/maistro/security/warden/detector.py"\n'
            "index 5555555..6666666 100644\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
        )
        verdict = validate_patch(_patch(extra=extra), declared_file=ORDINARY)

        assert not verdict.ok
        assert any("containment surface" in reason for reason in verdict.reasons)

    def test_an_escaped_quote_inside_a_path_survives_unquoting(self) -> None:
        r"""git writes a literal `"` in a path as `\"`. Unwrapping has to undo
        the escape, or the policy compares against a name that never existed."""
        text = 'diff --git "a/docs/od\\"d.py" "b/docs/od\\"d.py"\n'

        assert patch_paths(text) == ('docs/od"d.py',)
