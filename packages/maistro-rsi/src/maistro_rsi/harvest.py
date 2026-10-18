"""Harvest a session's promotions into a few PRs, grouped by file (ADR-070126-6386, stage 4).

A run promotes N commits onto the in-container ``rsi-baseline``; each commit
edits one target file. Rather than one sprawling branch or one PR per commit,
group the commits by the file they edit — one focused, reviewable PR per file
improved this session. This module is the pure logic (grouping, branch naming,
PR text, manifest projection); the git/gh orchestration is
``tools/harvest_rsi_prs.sh``.

The run exports, into a host-mounted dir, one ``git format-patch`` file per
promotion plus a ``manifest.json`` mapping each patch to the source file it
edits and to the gate results recorded for its promotion; the harvester reads
that, groups, and opens the PRs. PR bodies are rendered FROM those recorded
gate results (#304, #820): only gates with a recorded result are named, with
their recorded state, and a promotion with no recorded evidence is stated as
unverified — the body never asserts a full pass it cannot show.

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
class PromotedGate:
    """One gate's recorded result for a promotion (#304/#820).

    ``not_run`` marks a gate whose tool never executed (missing/unavailable) —
    recorded as the blocking failure evidence; since every gate in the
    Scorecard is a veto, a not-run required gate cannot sit on a promoted
    commit, but the rendered record must still be able to state it.
    """

    name: str
    passed: bool
    reason: str = ""
    not_run: bool = False


@dataclass(frozen=True)
class PromotedPatch:
    """One promoted commit exported as a patch, tagged with the file it edits."""

    patch_file: str
    file: str
    subject: str = ""
    # Recorded per-gate results (from the promotion's trace note, via the
    # manifest). Empty means no gate evidence was recorded — rendered as
    # "unverified", never as success.
    gates: tuple[PromotedGate, ...] = ()


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
        "Each was produced in an isolated container and competed head-to-head "
        "before promotion. The gate results below are the ones recorded at "
        "promotion time; no gate without a recorded result is claimed.",
        "",
        *_gate_section(patches),
        "",
        "Commits:",
    ]
    lines += [f"- {p.subject}" for p in patches]
    return "\n".join(lines)


def _gate_section(patches: list[PromotedPatch]) -> list[str]:
    """Render the recorded gate evidence for a PR's promotions (#820, from
    #304). Only gates with a recorded result are listed, with their recorded
    state — measured pass, failure, or NOT RUN (tool unavailable). A promotion
    with no recorded evidence is stated as unverified, never summed up as a
    pass: the body a reviewer reads must be reconstructible from the
    promotion records alone."""
    if not any(p.gates for p in patches):
        return [
            "## Recorded gate evidence",
            "",
            "No gate results were recorded for these promotions — treat every "
            "gate as unverified; do not assume they passed.",
        ]
    n = len(patches)
    names: list[str] = []
    for p in patches:
        for g in p.gates:
            if g.name not in names:
                names.append(g.name)
    lines = [
        "## Recorded gate evidence",
        "",
        f"Rendered from the promotions' recorded gate results ({n} promotion(s) "
        "in this PR); only gates with a recorded result appear.",
        "",
    ]
    for name in names:
        records = [g for p in patches for g in p.gates if g.name == name]
        not_run = [g for g in records if g.not_run]
        ran = [g for g in records if not g.not_run]
        measured = f"measured on {len(ran)} of {n} promotion(s)"
        if not_run:
            cause = not_run[0].reason or "tool unavailable"
            # The recorded reason for a not-run gate already names the state
            # ("NOT RUN: bandit unavailable (…)") — don't render it twice.
            if cause.startswith("NOT RUN: "):
                cause = cause[len("NOT RUN: ") :]
            lines.append(f"- {name}: NOT RUN — {cause} ({measured})")
        elif all(g.passed for g in ran):
            lines.append(f"- {name}: passed ({measured})")
        else:
            failed = next((g for g in ran if not g.passed), None)
            reason = failed.reason if failed and failed.reason else "gate failed"
            lines.append(f"- {name}: FAILED — {reason} ({measured})")
    return lines


def manifest_records(data: list[dict[str, object]]) -> list[PromotedPatch]:
    """Project one already-read manifest into the typed harvest records.

    Callers read and parse ``manifest.json`` themselves so the parsed value can
    pass the Warden harvest boundary *before* it becomes harvest records; the
    production harvester deliberately projects the admitted value instead of
    re-reading the file here, which would reopen a scan/use TOCTOU gap.

    Each entry's recorded gate evidence is projected too (#304/#820):
    ``gate_results`` (name/passed/not_run/reason records) when present, else
    the coarser ``gates`` bool-map written for promotions whose note predates
    per-gate records. An entry with neither projects NO gates — rendered as
    "no recorded evidence", never as a pass.
    """
    records: list[PromotedPatch] = []
    for entry in data:
        raw_results = entry.get("gate_results")
        gate_results = (
            [g for g in raw_results if isinstance(g, dict)] if isinstance(raw_results, list) else []
        )
        if gate_results:
            gates = tuple(
                PromotedGate(
                    name=str(g.get("name", "")),
                    passed=bool(g.get("passed", False)),
                    reason=str(g.get("reason", "")),
                    not_run=bool(g.get("not_run", False)),
                )
                for g in gate_results
            )
        else:
            raw_bools = entry.get("gates")
            bools = raw_bools if isinstance(raw_bools, dict) else {}
            gates = tuple(
                PromotedGate(name=str(name), passed=bool(passed)) for name, passed in bools.items()
            )
        records.append(
            PromotedPatch(
                patch_file=str(entry["patch_file"]),
                file=str(entry["file"]),
                subject=str(entry.get("subject", "")),
                gates=gates,
            )
        )
    return records
