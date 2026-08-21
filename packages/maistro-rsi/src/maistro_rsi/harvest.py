"""Harvest a session's promotions into a few PRs, grouped by file (ADR-070126-6386, stage 4).

A run promotes N commits onto the in-container ``rsi-baseline``; each commit
edits one target file. Rather than one sprawling branch or one PR per commit,
group the commits by the file they edit — one focused, reviewable PR per file
improved this session. This module is the pure logic (grouping, branch naming,
PR text, manifest I/O); the git/gh orchestration is ``tools/harvest_rsi_prs.sh``.

The run exports, into a host-mounted dir, one ``git format-patch`` file per
promotion plus a ``manifest.json`` mapping each patch to the source file it
edits; the harvester reads that, groups, and opens the PRs.

Assumption / limitation: each promotion is treated as a *self-contained* change
to one file and is applied onto the base independently. This holds for the
targeted single-file tournament (each cycle improves one named file with a
minimal, behaviour-preserving edit). It does NOT hold if a later promotion in
one file depends on an earlier promotion in another — the per-file PR branch
would apply cleanly but fail tests, because it drops the prerequisite. For
interdependent runs, either harvest a single combined branch or retest each
branch before pushing (the rsi-harvest workflow runs on trusted infra where a
retest step can be added). Tracked in ADR-070126-6386.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromotedPatch:
    """One promoted commit exported as a patch, tagged with the file it edits."""

    patch_file: str
    file: str
    subject: str = ""


def group_by_file(patches: list[PromotedPatch]) -> dict[str, list[PromotedPatch]]:
    """Group promotions by edited file — one PR per file. Insertion order of
    files and the patch order within each file are preserved."""
    groups: dict[str, list[PromotedPatch]] = {}
    for patch in patches:
        groups.setdefault(patch.file, []).append(patch)
    return groups


def branch_slug(file: str, session: str) -> str:
    """A collision-safe, ref-legal branch name for a file's PR.

    Encodes the whole path (not just the basename) so two same-named files in
    different packages get distinct branches: ``rsi/<session>/<path-slug>``.
    """
    stem = file[:-3] if file.endswith(".py") else file
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()
    return f"rsi/{session}/{slug}"


def pr_title(file: str, patches: list[PromotedPatch]) -> str:
    n = len(patches)
    plural = "improvement" if n == 1 else "improvements"
    return f"RSI: {n} {plural} to {file}"


def pr_body(file: str, patches: list[PromotedPatch]) -> str:
    lines = [
        f"Automated recursive-self-improvement changes to `{file}`.",
        "",
        "Each was produced in an isolated container, competed head-to-head, and "
        "passed the full fitness scorecard (tests, coverage-not-dropped, ruff, "
        "mypy, bandit) before promotion.",
        "",
        "Commits:",
    ]
    lines += [f"- {p.subject}" for p in patches]
    return "\n".join(lines)


def load_manifest(path: str | Path) -> list[PromotedPatch]:
    """Read the export manifest.json into PromotedPatch records."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        PromotedPatch(
            patch_file=entry["patch_file"],
            file=entry["file"],
            subject=entry.get("subject", ""),
        )
        for entry in data
    ]
