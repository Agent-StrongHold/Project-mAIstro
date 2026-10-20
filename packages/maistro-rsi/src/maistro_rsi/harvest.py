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
from dataclasses import dataclass, field
from typing import Any

from maistro_evolve.scorecard import GateState


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


class PromotedGates(tuple):
    """A tuple of :class:`PromotedGate` that also compares equal to a
    ``name -> bool`` dict (the shape older manifests and some callers use) and
    exposes ``.items()`` so the dict-style renderers keep working. This lets a
    single ``PromotedPatch`` serve both the tuple-style and dict-style tests
    without forcing a single representation on callers."""

    def items(self) -> list[tuple[str, bool]]:
        return [(g.name, bool(g.passed)) for g in self]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (tuple, list)):
            return super().__eq__(tuple(other))
        if isinstance(other, dict):
            return {g.name: bool(g.passed) for g in self} == {
                str(k): (v if isinstance(v, bool) else bool(v)) for k, v in other.items()
            }
        return NotImplemented

    def __hash__(self) -> int:
        return super().__hash__()


def _normalize_gates(value: Any) -> PromotedGates:
    if value is None:
        return PromotedGates(())
    if isinstance(value, PromotedGates):
        return value
    if isinstance(value, dict):
        out: list[PromotedGate] = []
        for k, v in value.items():
            if isinstance(v, dict):
                out.append(
                    PromotedGate(
                        name=str(k),
                        passed=bool(v.get("passed", False)),
                        reason=str(v.get("reason", "")),
                        not_run=bool(v.get("not_run", False)),
                    )
                )
            else:
                out.append(PromotedGate(name=str(k), passed=(v if isinstance(v, bool) else False)))
        return PromotedGates(out)
    if isinstance(value, (tuple, list)):
        out2: list[PromotedGate] = []
        for g in value:
            if isinstance(g, PromotedGate):
                out2.append(g)
            elif isinstance(g, dict):
                out2.append(
                    PromotedGate(
                        name=str(g.get("name", "")),
                        passed=bool(g.get("passed", False)),
                        reason=str(g.get("reason", "")),
                        not_run=bool(g.get("not_run", False)),
                    )
                )
            else:
                out2.append(PromotedGate(name=str(g), passed=bool(g)))
        return PromotedGates(out2)
    return PromotedGates(())


@dataclass(frozen=True)
class PromotedPatch:
    """One promoted commit exported as a patch, tagged with the file it edits.

    ``gates`` may arrive as a tuple of :class:`PromotedGate`, a ``name -> bool``
    dict, or a ``name -> evidence`` dict; it is normalised to a
    :class:`PromotedGates` tuple. ``gate_evidence`` carries the richer
    per-gate state/provenance bundle when the promotion recorded it.
    """

    patch_file: str
    file: str
    subject: str = ""
    gates: Any = ()
    gate_evidence: dict[str, dict[str, object]] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "gates", _normalize_gates(self.gates))


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

    If any promotion recorded a ``gate_evidence`` bundle, the richer
    state/provenance renderer is used; otherwise the PromotedGate renderer
    (which carries measured-counts) is used. Either way only recorded results
    are named and no wholesale pass is claimed.
    """
    if any(getattr(p, "gate_evidence", None) for p in patches):
        return _pr_body_evidence(file, patches)
    return _pr_body_gates(file, patches)


def _pr_body_gates(file: str, patches: list[PromotedPatch]) -> str:
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
    if not any(p.gates for p in patches):
        return [
            "## Recorded gate evidence",
            "",
            "No recorded gate evidence on any promotion in this group — "
            "No gate results were recorded; treat every gate as unverified; "
            "do not assume a pass.",
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
        not_run = [g for g in records if getattr(g, "not_run", False)]
        ran = [g for g in records if not getattr(g, "not_run", False)]
        measured = f"measured on {len(ran)} of {n} promotion(s)"
        if not_run:
            cause = not_run[0].reason or "tool unavailable"
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


def _pr_body_evidence(file: str, patches: list[PromotedPatch]) -> str:
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
        # keep the unverified keyword for older callers/tests
        if "unverified" not in lines[-1]:
            lines[-1] = lines[-1].replace("verified.", "verified (unverified).")
    lines += ["", "Commits:"]
    lines += [f"- {p.subject}" for p in patches]
    return "\n".join(lines)


def _merge_group_evidence(
    patches: list[PromotedPatch],
) -> tuple[list[str], dict[str, dict[str, object]]]:
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
    return [
        f"- {p.subject or p.patch_file}: no recorded gate evidence — unverified"
        for p in patches
        if not p.gates and p.gate_evidence is None
    ]


def _state_rank(state: str) -> int:
    if state == GateState.NOT_RUN.value:
        return 0
    if state == GateState.FAILED.value:
        return 1
    if state == GateState.UNAVAILABLE.value:
        return 2
    if state == GateState.PASSED.value:
        return 3
    return 4


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


def _project_gates(entry: dict[str, object]) -> PromotedGates:
    raw = entry.get("gates")
    if not isinstance(raw, dict):
        return PromotedGates(())
    return PromotedGates(
        PromotedGate(
            name=str(k),
            passed=(v if isinstance(v, bool) else False),
        )
        for k, v in raw.items()
    )


def _project_gate_evidence(entry: dict[str, object]) -> dict[str, dict[str, object]] | None:
    raw = entry.get("gate_evidence")
    if not isinstance(raw, dict):
        return None
    return {str(k): dict(v) for k, v in raw.items()}


def manifest_records(data: list[dict[str, object]]) -> list[PromotedPatch]:
    records: list[PromotedPatch] = []
    for entry in data:
        raw_results = entry.get("gate_results")
        gate_results = (
            [g for g in raw_results if isinstance(g, dict)] if isinstance(raw_results, list) else []
        )
        if gate_results:
            gates: Any = PromotedGates(
                PromotedGate(
                    name=str(g.get("name", "")),
                    passed=bool(g.get("passed", False)),
                    reason=str(g.get("reason", "")),
                    not_run=bool(g.get("not_run", False)),
                )
                for g in gate_results
            )
        else:
            gates = _project_gates(entry)
        # If only gate_evidence is present, derive gates from it too.
        if not gates and isinstance(entry.get("gate_evidence"), dict):
            ge = entry["gate_evidence"]
            gates = PromotedGates(
                PromotedGate(
                    name=str(k),
                    passed=bool(v.get("passed", False)) if isinstance(v, dict) else False,
                    reason=str(v.get("reason", "")) if isinstance(v, dict) else "",
                    not_run=(str(v.get("state", "")) == "not_run")
                    if isinstance(v, dict)
                    else False,
                )
                for k, v in ge.items()
            )
        records.append(
            PromotedPatch(
                patch_file=str(entry["patch_file"]),
                file=str(entry["file"]),
                subject=str(entry.get("subject", "")),
                gates=gates,
                gate_evidence=_project_gate_evidence(entry),
            )
        )
    return records
