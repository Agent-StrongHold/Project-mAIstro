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
from dataclasses import dataclass, field

from maistro_evolve.scorecard import GateState


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


def _merge_group_evidence(
    patches: list[PromotedPatch],
) -> tuple[list[str], dict[str, dict[str, object]]]:
    """Merge every recorded gate result in the group by gate name.

    A per-file PR groups promotions of one file, so every promotion was
    scored against the same gate set; the worst recorded state wins — a gate
    that is not_run/failed on ANY promotion is reported at that state, since
    the group PR ships every patch. Evidence rows are kept in first-seen
    order so the rendered body is stable."""
    order: list[str] = []
    merged: dict[str, dict[str, object]] = {}
    for patch in patches:
        for name, evidence in (patch.gate_evidence or {}).items():
            if name not in merged:
                order.append(name)
                merged[name] = dict(evidence)
            elif _state_rank(str(evidence.get("state", ""))) < _state_rank(
                str(merged[name].get("state", ""))
            ):
                # The group PR ships every patch, so the worst recorded state
                # for a gate is the group's state (#820): not_run/failed
                # outrank a pass from another promotion in the same group.
                merged[name] = dict(evidence)
        for name, passed in patch.gates.items():
            if name not in merged:
                order.append(name)
                merged[name] = {
                    "state": "passed" if passed else "failed",
                    "passed": passed,
                }
    return order, merged


def _gate_evidence_lines(patches: list[PromotedPatch]) -> list[str]:
    """One line per recorded gate result across the group's promotions.

    Only gates with a recorded result are named. Provenance (tool version,
    exit status, output digest) rides along when a promotion recorded it, so
    a reviewer can tell a measured pass from an unavailable tool."""
    if not any(p.gates or p.gate_evidence for p in patches):
        return []
    order, merged = _merge_group_evidence(patches)
    lines: list[str] = []
    for name in order:
        ev = merged[name]
        state = str(ev.get("state", "failed"))
        if state == GateState.PASSED.value:
            suffix = _provenance_suffix(ev)
            lines.append(f"- {name}: passed{suffix}")
        elif state == GateState.NOT_RUN.value:
            reason = str(ev.get("reason", "required gate never executed"))
            lines.append(f"- {name}: NOT RUN — blocking ({reason})")
        elif state == GateState.UNAVAILABLE.value:
            reason = str(ev.get("reason", "no result recorded"))
            lines.append(f"- {name}: unavailable — not executed ({reason})")
        else:
            suffix = _provenance_suffix(ev)
            lines.append(f"- {name}: FAILED{suffix}")
    return lines


def _unevidenced_lines(patches: list[PromotedPatch]) -> list[str]:
    """One line per promotion with no recorded gate result, naming it
    unverified. Evidence is judged per patch: in a group that mixes an
    evidenced promotion with a legacy row (neither ``gates`` nor
    ``gate_evidence``), the recorded rows must not read as evidence for the
    unevidenced patch, whose gate outcomes are unknown (#820)."""
    return [
        f"- {p.subject or p.patch_file}: no recorded gate evidence — unverified"
        for p in patches
        if not p.gates and p.gate_evidence is None
    ]


def _state_rank(state: str) -> int:
    """Reporting precedence when promotions disagree: not_run (0) and failed
    (1) outrank passed (2) — a group PR must surface the worst recorded
    evidence, and an absent state ranks lowest (gets replaced)."""
    if state == GateState.NOT_RUN.value:
        return 0
    if state == GateState.FAILED.value:
        return 1
    if state == GateState.PASSED.value:
        return 2
    return 3


def _provenance_suffix(ev: dict[str, object]) -> str:
    prov = ev.get("provenance")
    if not isinstance(prov, dict):
        return ""
    parts: list[str] = []
    version = prov.get("tool_version")
    if version:
        parts.append(f"tool {version}")
    exit_status = prov.get("exit_status")
    if exit_status is not None:
        parts.append(f"exit {exit_status}")
    digest = prov.get("output_digest")
    if isinstance(digest, str) and digest:
        parts.append(f"output {digest[:19]}")
    return f" ({', '.join(parts)})" if parts else ""


def _project_gates(entry: dict[str, object]) -> dict[str, bool]:
    """The row's recorded name→boolean verdict map, defaulting empty when the
    manifest row predates gate recording."""
    raw = entry.get("gates")
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def _project_gate_evidence(entry: dict[str, object]) -> dict[str, dict[str, object]] | None:
    """The row's recorded per-gate evidence bundle, or None when the manifest
    row predates evidence (#304) — rendered downstream as UNVERIFIED, never
    as a pass."""
    raw = entry.get("gate_evidence")
    if not isinstance(raw, dict):
        return None
    return {str(k): dict(v) for k, v in raw.items()}


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
            gates=_project_gates(entry),
            gate_evidence=_project_gate_evidence(entry),
        )
        for entry in data
    ]
