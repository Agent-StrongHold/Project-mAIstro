"""Harvest a session's promotions into a few PRs, grouped by file (ADR-070126-6386, stage 4).

A run promotes N commits onto the in-container ``rsi-baseline``; each commit
edits one target file. Rather than one sprawling branch or one PR per commit,
group the commits by the file they edit — one focused, reviewable PR per file
improved this session. This module is the pure logic (grouping, branch naming,
PR text, manifest projection); the git/gh orchestration is
``tools/harvest_rsi_prs.sh``.

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

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromotedPatch:
    """One promoted commit exported as a patch, tagged with the file it edits.

    ``gates``/``gate_evidence`` (#304/#820) carry the promotion's recorded
    gate results projected from the export manifest: ``gates`` is the plain
    name→boolean verdict map, ``gate_evidence`` adds each gate's state and
    execution provenance (tool version, exit status, output digest). Both
    default empty/None so pre-evidence manifests still project — a patch with
    no recorded evidence is rendered as UNVERIFIED, never as passed."""

    patch_file: str
    file: str
    subject: str = ""
    gates: dict[str, bool] = field(default_factory=dict)
    gate_evidence: dict[str, dict[str, object]] | None = None


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
    """Render the group's PR body from RECORDED gate results (#820).

    Only gates with a recorded result on one of the group's promotions are
    named, each with its outcome and — where recorded — its execution
    provenance. Every promotion without recorded evidence is stated as
    unverified — including in a mixed group, where another promotion's
    recorded rows must not vouch for a legacy patch with unknown outcomes.
    Nothing here claims a gate that did not run: the historical hard-coded
    "passed the full fitness scorecard (tests, coverage-not-dropped, ruff,
    mypy, bandit)" sentence was exactly the false-evidence defect #820
    closes, so it is gone; the body states evidence, never a wholesale pass.
    """
    lines = [
        f"Automated recursive-self-improvement changes to `{file}`.",
        "",
        "Gate evidence (only gates with a recorded result on these "
        "promotions are listed; no other gate ran and none is claimed):",
        "",
    ]
    evidence_lines = _gate_evidence_lines(patches)
    if evidence_lines:
        lines += evidence_lines
        lines += _unevidenced_lines(patches)
    else:
        lines.append(
            "- No recorded gate evidence on any promotion in this group — "
            "the gate outcomes are unknown and must not be treated as verified."
        )
    lines += ["", "Commits:"]
    lines += [f"- {p.subject}" for p in patches]
    return "\n".join(lines)


def manifest_records(data: list[dict[str, object]]) -> list[PromotedPatch]:
    """Project one already-read manifest into the typed harvest records.

    Callers read and parse ``manifest.json`` themselves so the parsed value can
    pass the Warden harvest boundary *before* it becomes harvest records; the
    production harvester deliberately projects the admitted value instead of
    re-reading the file here, which would reopen a scan/use TOCTOU gap.
    """
    return [
        PromotedPatch(
            patch_file=str(entry["patch_file"]),
            file=str(entry["file"]),
            subject=str(entry.get("subject", "")),
        )
        for entry in data
    ]
