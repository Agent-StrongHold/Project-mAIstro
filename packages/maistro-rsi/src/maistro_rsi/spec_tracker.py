"""Spec completion as an *objective* fitness sensor (ADR-070126-6386 v3).

The repo's own discipline provides the measurement: specs in ``docs/specs/``
enumerate acceptance criteria (``- [ ] **AC-N**`` checkboxes), and tests claim
them with ``@pytest.mark.ac("SPEC-xxx/AC-n")``. A spec is measurably complete
when every AC has a marked, passing test — no LLM judge required. This module
answers three questions for the loop:

- :func:`spec_gaps` — which contracted promises are still unproven? (the scout's
  highest-reward targets, and — when empty everywhere — the tier-5 trigger
  sensor for autonomous exploration)
- :func:`new_ac_coverage` — which AC ids did *this candidate* newly prove?
  (drives the presence-gated ``spec_completion`` signal; only markers net-new
  vs. the baseline count, so re-tagging existing ACs earns nothing)
- :func:`proposed_specs` — did this candidate *contract new work* by drafting a
  well-formed spec? (drives ``spec_proposed`` — the disciplined alternative to
  shipping an unspecced feature)

Everything here is regex/AST-free text scanning over files + ``git show`` —
cheap enough to run per cycle, honest enough to score against (SPEC-202).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

# @pytest.mark.ac("SPEC-176/AC-1") — single or double quotes, tolerant of spaces.
_AC_MARKER = re.compile(r"pytest\.mark\.ac\(\s*[\"']([^\"']+)[\"']")
# - [ ] **AC-7** ...   (unchecked = unimplemented promise; checked boxes and the
# ac-marker id join below both normalise to the same "SPEC-id/AC-n" key)
_AC_HEADING = re.compile(r"^\s*-\s*\[( |x|X)\]\s*\*\*(AC-\d+)\*\*", re.MULTILINE)
_SPEC_ID = re.compile(r"^id:\s*(SPEC-[\w-]+)\s*$", re.MULTILINE)


def ac_markers_in(source: str) -> set[str]:
    """All ``SPEC-xxx/AC-n`` ids claimed by ``pytest.mark.ac`` in test source."""
    return set(_AC_MARKER.findall(source))


def _spec_acs(spec_text: str) -> tuple[str | None, list[str]]:
    """Parse one spec doc → (spec_id, [AC ids]); (None, []) if malformed."""
    id_match = _SPEC_ID.search(spec_text)
    if not id_match:
        return None, []
    return id_match.group(1), [m[1] for m in _AC_HEADING.findall(spec_text)]


def _iter_test_files(repo_dir: Path) -> Iterable[Path]:
    yield from repo_dir.glob("packages/*/tests/**/*.py")
    yield from repo_dir.glob("tests/**/*.py")


def spec_gaps(repo_dir: str | Path) -> dict[str, list[str]]:
    """Contracted-but-unproven promises: ``{spec_id: [unclaimed AC ids]}``.

    Every AC enumerated in ``docs/specs/*.md`` minus the ids claimed by
    ``pytest.mark.ac`` markers anywhere in the test suites. A spec with no
    parseable id or no AC checkboxes contributes nothing (it predates the AC
    discipline — not a gap, just not measurable).
    """
    root = Path(repo_dir)
    claimed: set[str] = set()
    for test_file in _iter_test_files(root):
        try:
            claimed |= ac_markers_in(test_file.read_text(encoding="utf-8"))
        except OSError:
            continue
    gaps: dict[str, list[str]] = {}
    for spec_file in sorted(root.glob("docs/specs/SPEC-*.md")):
        try:
            spec_id, acs = _spec_acs(spec_file.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not spec_id:
            continue
        missing = [ac for ac in acs if f"{spec_id}/{ac}" not in claimed]
        if missing:
            gaps[spec_id] = missing
    return gaps


def format_gaps(gaps: dict[str, list[str]], *, limit: int = 12) -> str:
    """Render gaps for the scout's prompt — real ids it can name, never invent."""
    lines = []
    for spec_id, acs in gaps.items():
        for ac in acs:
            lines.append(f"- {spec_id}/{ac}")
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines)


def new_ac_coverage(
    repo_dir: str | Path, baseline_ref: str, changed_test_files: list[str]
) -> list[str]:
    """AC ids marked in the candidate's changed tests but absent on baseline.

    Net-new across each file vs. ``git show baseline_ref:file`` (a file absent
    on baseline contributes all its markers). Moving an existing marker between
    files could double-count only if the removal lands in a different commit —
    the whole-suite dedupe in :func:`spec_gaps` still bounds the reward to ACs
    that were genuinely unclaimed.
    """
    cwd = Path(repo_dir)
    new: set[str] = set()
    for rel in changed_test_files:
        try:
            candidate = (cwd / rel).read_text(encoding="utf-8")
        except OSError:
            candidate = ""
        base = subprocess.run(
            ["git", "show", f"{baseline_ref}:{rel}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        baseline_src = base.stdout if base.returncode == 0 else ""
        new |= ac_markers_in(candidate) - ac_markers_in(baseline_src)
    return sorted(new)


# A proposed spec must look like a real contract before it earns anything: id
# frontmatter plus at least this many enumerated acceptance criteria. Bounds
# marker-farming; the human harvest gate reviews the substance.
_MIN_PROPOSED_ACS = 2


def proposed_specs(repo_dir: str | Path, changed_files: list[str]) -> list[str]:
    """Spec ids of well-formed, NEW spec docs among ``changed_files``.

    A BACKLOG candidate earns ``spec_proposed`` only for a doc under
    ``docs/specs/`` that parses (id frontmatter) and enumerates at least
    ``_MIN_PROPOSED_ACS`` acceptance criteria — an idea formalised into
    testable, contracted work, not a stray markdown file.
    """
    cwd = Path(repo_dir)
    ids: list[str] = []
    for rel in changed_files:
        norm = rel.replace("\\", "/")
        if not (norm.startswith("docs/specs/") and norm.endswith(".md")):
            continue
        try:
            text = (cwd / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        spec_id, acs = _spec_acs(text)
        if spec_id and len(acs) >= _MIN_PROPOSED_ACS:
            ids.append(spec_id)
    return sorted(ids)
