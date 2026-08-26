"""What an exported RSI patch may contain, and where its PR may go (#356).

The harvest step is the one place agent-authored work crosses from the
sandbox into the repository. `rsi-harvest.yml` runs with `contents: write` and
`pull-requests: write`, and the trust model (ADR-070126-6386 / ADR-093) rests
on one claim: **no agent-authored code runs there — the exports are data.**

That claim held for execution and not for content. The workflow refused a
`.rsi-exports/` directory containing anything but `*.patch` and
`manifest.json`, and then handed those patches to `git am` without asking what
was *in* them. A patch is a program for the working tree: it can create a
symlink, replace a submodule pointer, write outside the directory the manifest
names, or edit the very files that decide what a future self-modification is
allowed to do.

Two separate policies live here.

Where the PR may go
-------------------
ADR-095 defines four tiers: topic branches → `develop` → `integration` →
`main`, with `main` requiring an approving review. `rsi-harvest.yml` took
`pr_base` as a `workflow_dispatch` **input defaulting to `main`**, and
`maistro_rsi harvest` defaulted `--pr-base` the same way. So the documented way
to run a harvest opened agent-authored PRs directly against the release tier,
skipping both integration tiers — and the target was chosen by whoever
dispatched the run rather than by policy.

The tier is policy now: `resolve_pr_base` returns the canonical development
branch unless a release tier is *separately authorized*, and that authorization
is not something a candidate can express.

What the patch may contain
--------------------------
`quarantine.py` already owns the protected-surface policy and applies it to a
run's diff **inside** the loop. `validate_patch` applies the same
`matches_sensitive_pattern` to the exported artifact, so the same policy
governs the workspace and the export — the AC's "the same protected-path
policy governs workspace, export, PR, and merge".

It is deliberately a re-check rather than a delegation. The in-loop scan and
this one read different objects: the loop scans what the agent produced, this
scans what actually arrived on the export branch. A trusted orchestrator sits
between them, and "the earlier check passed" is not evidence about the bytes
`git am` is about to consume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from maistro_rsi.quarantine import matches_sensitive_pattern

#: ADR-095's active integration tier. Topic branches PR here.
CANONICAL_DEVELOPMENT_BRANCH = "develop"

#: Tiers a harvest may not target without separate authorization. `main` is
#: release-grade and requires an approving review; `integration` is stabilized
#: QA and receives PRs from `develop`. Neither takes topic branches, which is
#: what a harvest branch is.
RELEASE_TIER_BRANCHES = frozenset({"main", "integration", "master"})

#: git's mode for a symlink. A patch that creates one can redirect a later
#: write outside the tree entirely, which is why the export guard resolving
#: symlinks is not enough on its own -- the symlink may not exist yet.
SYMLINK_MODE = "120000"

#: git's mode for a gitlink (submodule). Changing one points the repository at
#: someone else's history, and nothing downstream of here reviews that content.
SUBMODULE_MODE = "160000"

#: `diff --git a/x b/y`, in both spellings. git wraps a side in quotes when the
#: path holds a byte it will not print raw, and the quote comes *before* the
#: `a/` prefix -- so a pattern anchored on `diff --git a/` does not match a
#: quoted header at all. That is a bypass rather than a cosmetic gap: a patch
#: with one ordinary header and one quoted one has a non-empty path list, so
#: the "nothing here identifies what it changes" refusal never fires, and the
#: quoted path is simply never checked.
_DIFF_HEADER = re.compile(
    r'^diff --git (?:"a/((?:[^"\\]|\\.)*)"|a/(.+?)) (?:"b/((?:[^"\\]|\\.)*)"|b/(.+))$',
    re.MULTILINE,
)
_MODE_LINE = re.compile(
    r"^(?:new file mode|new mode|old mode|deleted file mode) (\d{6})$", re.MULTILINE
)
_RENAME_TO = re.compile(r"^rename to (.+)$", re.MULTILINE)
_RENAME_FROM = re.compile(r"^rename from (.+)$", re.MULTILINE)
_DELETED_FILE = re.compile(r"^diff --git a/(.+?) b/.+\n(?:.*\n)*?deleted file mode ", re.MULTILINE)
_BINARY = re.compile(r"^GIT binary patch$", re.MULTILINE)


class ExportPolicyError(Exception):
    """An exported artifact may not be turned into a pull request."""


@dataclass(frozen=True)
class PatchVerdict:
    """Why a patch was refused, or that it was not.

    A list rather than the first reason: a reviewer looking at a refused
    export wants everything wrong with it, not the earliest thing. A patch
    that both touches `.github/` and creates a symlink is a different object
    from one that only does the first.
    """

    paths: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.reasons


def resolve_pr_base(requested: str | None, *, release_tier_authorized: bool = False) -> str:
    """The branch a harvested PR targets. Policy, not candidate input.

    `requested` is honoured only where honouring it cannot skip a tier: an
    ordinary topic branch is fine, a release tier is not. The default when
    nothing is requested is the canonical development branch, never `main` --
    which is what it used to be, in both the workflow input and the CLI flag.

    `release_tier_authorized` is the "explicit separately authorized policy"
    the AC requires. It is a parameter of the *caller* -- the workflow decides
    it from its own configuration -- rather than anything the export, the
    manifest, or a dispatch input can set.
    """
    if requested is None or not requested.strip():
        return CANONICAL_DEVELOPMENT_BRANCH
    target = requested.strip()
    if target in RELEASE_TIER_BRANCHES and not release_tier_authorized:
        raise ExportPolicyError(
            f"refusing to open an agent-authored PR against {target!r}: ADR-095 routes "
            f"topic branches through {CANONICAL_DEVELOPMENT_BRANCH!r}, and a release "
            f"tier needs separately authorized policy rather than a dispatch input"
        )
    return target


def resolve_export_path(export_dir: Path, patch_file: str) -> Path:
    """The patch's real path inside `export_dir`, or raise.

    The manifest is data from the export branch, so `patch_file` is attacker-
    influenced in exactly the way a filename can be: `../../../etc/shadow`, an
    absolute path, or a name that is a symlink pointing anywhere. The previous
    code did `(export / patch.patch_file).resolve()`, which *follows* a symlink
    and normalises a traversal away -- turning both into a valid-looking path
    rather than an error.

    Resolved and then checked against the resolved root, so a symlink cannot
    land outside even when every textual component looks innocent.
    """
    root = export_dir.resolve()
    candidate = (root / patch_file).resolve()
    if candidate == root or root not in candidate.parents:
        raise ExportPolicyError(
            f"manifest entry {patch_file!r} resolves outside the export directory"
        )
    if not candidate.is_file():
        raise ExportPolicyError(f"manifest entry {patch_file!r} is not a regular file")
    return candidate


def patch_paths(patch_text: str) -> tuple[str, ...]:
    """Every repository path the patch writes to, in order, without duplicates.

    Both sides of each `diff --git` header, plus rename sources and targets:
    a rename touches two paths and only one of them appears where a reader
    skimming for `+++ b/` would look.
    """
    seen: dict[str, None] = {}
    for groups in _DIFF_HEADER.findall(patch_text):
        # Four groups: quoted-a, bare-a, quoted-b, bare-b. Exactly one of each
        # pair matches; the other is "".
        for path in groups:
            if path:
                seen.setdefault(_unquote(path), None)
    for path in _RENAME_FROM.findall(patch_text) + _RENAME_TO.findall(patch_text):
        seen.setdefault(_unquote(path), None)
    return tuple(seen)


def _unquote(path: str) -> str:
    """Undo git's C-style quoting, and drop a surrounding pair if present.

    Called on both the captured inside of a quoted header (where the quotes are
    already gone) and on a `rename to` line (where they may not be), so it
    handles either.
    """
    path = path.strip()
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        path = path[1:-1]
    return path.replace("\\t", "\t").replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def _escapes_repository(path: str) -> bool:
    """Whether `path` names something outside the repository root."""
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return True
    parts = Path(path.replace("\\", "/")).parts
    return ".." in parts


def _path_reasons(paths: tuple[str, ...], declared_file: str | None) -> list[str]:
    """Why any path this patch writes to is not allowed."""
    reasons: list[str] = []
    for path in paths:
        if _escapes_repository(path):
            reasons.append(f"{path!r} points outside the repository")
        elif matches_sensitive_pattern(path):
            reasons.append(
                f"{path!r} is on the containment surface — the same policy quarantine.py "
                f"applies inside the loop applies to what leaves it"
            )
        elif declared_file is not None and path != declared_file:
            reasons.append(
                f"{path!r} is not the file the manifest declares ({declared_file!r}); "
                f"the branch name, PR title and grouping all describe the declared one"
            )
    return reasons


def _mode_reasons(patch_text: str) -> list[str]:
    """Why the file *kinds* this patch creates are not allowed.

    A path check cannot see these: `a/b/c` is an ordinary-looking path whether
    the mode beside it says regular file, symlink, or gitlink.
    """
    reasons: list[str] = []
    for mode in _MODE_LINE.findall(patch_text):
        if mode == SYMLINK_MODE:
            reasons.append(
                "creates or changes a symlink: a later write through it lands wherever "
                "it points, which no path check on this patch can see"
            )
        elif mode == SUBMODULE_MODE:
            reasons.append(
                "changes a submodule pointer: nothing downstream of here reviews the "
                "history it would point at"
            )
    return reasons


def _content_reasons(patch_text: str) -> list[str]:
    """Why the patch's contents are not a promotion-shaped change."""
    reasons: list[str] = []
    if _BINARY.search(patch_text):
        reasons.append(
            "contains a binary hunk: the promotion contract is a minimal, reviewable "
            "edit to one source file, and a binary blob is neither"
        )
    for deleted in _DELETED_FILE.findall(patch_text):
        path = _unquote(deleted)
        if matches_sensitive_pattern(path):
            reasons.append(f"deletes {path!r}, which is on the containment surface")
    return reasons


def validate_patch(patch_text: str, *, declared_file: str | None = None) -> PatchVerdict:
    """Every reason this patch may not become a pull request.

    `declared_file` is the manifest's claim about which file the promotion
    edits. The harvester groups by it, names the branch after it, and writes it
    into the PR title -- so a patch that touches anything else is a PR whose
    every human-readable label is wrong about its own contents. Checked rather
    than trusted, because the manifest and the patch come from the same place.

    Every reason, not the first: a reviewer looking at a refused export wants
    everything wrong with it. A patch that both edits `.github/` and creates a
    symlink is a different object from one that only does the first, and
    stopping at the earliest finding hides which one this is.
    """
    paths = patch_paths(patch_text)
    reasons: list[str] = []
    if not paths:
        reasons.append("no `diff --git` header: nothing here identifies what it changes")
    reasons += _path_reasons(paths, declared_file)
    reasons += _mode_reasons(patch_text)
    reasons += _content_reasons(patch_text)
    return PatchVerdict(paths=paths, reasons=tuple(dict.fromkeys(reasons)))


__all__ = [
    "CANONICAL_DEVELOPMENT_BRANCH",
    "RELEASE_TIER_BRANCHES",
    "ExportPolicyError",
    "PatchVerdict",
    "patch_paths",
    "resolve_export_path",
    "resolve_pr_base",
    "validate_patch",
]
