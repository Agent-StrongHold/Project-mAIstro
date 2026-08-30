#!/usr/bin/env python3
"""Per-branch AC-state notes and the fold that replaces the shared ceiling (#585).

`quality/ac-state-ceilings.json` held eleven counters on one shared line and
`--ratchet` demanded exact equality on all of them, so every PR that moved any
counter had to rewrite that file — and the moment one merged, every other open
PR conflicted on it. Four PRs did exactly that in one pass through the queue,
each costing a full re-measurement that held only until the next merge.

This is #208's defect, and #208's fix: one small file per branch, and an
aggregate that is *folded* rather than stored.

Two properties make the fold safe as a ratchet:

* It is **monotone**. Debt counters fold by `min` and `design_coverage` by
  `max`, so accumulating notes can only tighten the bound, never loosen it.
* It is read **at the base revision** (ADR-082926-25a2, via `ratchet_provenance`).
  A candidate's own note is written locally and excluded from the fold it is
  judged against, so a note cannot relax its own bound — the self-approving
  oracle #534 closed.

A note therefore enters the bound only by merging, which is also what stops an
abandoned branch leaving a floor the trunk cannot meet (#508).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]

#: Loaded by path, not imported by name, for the same reason `check-wiring-reads`
#: does it: the tests load these scripts with `spec_from_file_location`, which
#: puts nothing on `sys.path` for a sibling to be found on.
_PROVENANCE_SOURCE = Path(__file__).resolve().parent / "ratchet_provenance.py"


def load_sibling(source: Path, name: str) -> ModuleType:
    """Import a sibling script by path, cached, dataclass-safe."""
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {source}")
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `@dataclass` resolves a field's type through
    # `sys.modules[cls.__module__]`, so a module executed while absent from that
    # table raises on its first dataclass.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def provenance() -> ModuleType:
    """`ratchet_provenance`, which resolves the base revision (#534)."""
    return load_sibling(_PROVENANCE_SOURCE, "_ratchet_provenance")


NOTES_DIR = ROOT / "quality" / "ac-state-notes"
BASELINE_NAME = "_baseline.json"

#: The file this scheme retires. A branch cut before the change has no notes
#: directory at its base, and a bound of "nothing" would let it regress freely —
#: so the retired ceiling is folded in as a single note when the directory is
#: absent. Deletable once no live branch predates ADR-082926-25a2; until then it
#: is the difference between a migration and an outage.
#: Held as a repo-relative path as well as an absolute one: `load_notes` takes a
#: `root`, and deriving the relative half with `RETIRED_CEILINGS.relative_to(ROOT)`
#: crashed as soon as a caller pointed `ROOT` somewhere else -- which every test
#: with a synthetic tree does.
RETIRED_CEILINGS_REL = Path("quality") / "ac-state-ceilings.json"
RETIRED_CEILINGS = ROOT / RETIRED_CEILINGS_REL

#: Counters that may only go down: each is a way a completion claim can outrun
#: its evidence. Kept here rather than imported from `check-ac-state.py`, which
#: is not an importable module name; that script imports these instead.
RATCHETED: tuple[str, ...] = (
    "completion_claims_contradicted",
    "completion_claims_unverifiable",
    "specs_awaiting_retrofit",
    "markers_without_criterion",
    "criteria_claimed_but_unproven",
    "scenarios_without_ac_tag",
    "gherkin_parse_errors",
    "specs_implementing_nothing",
    "adrs_without_implementing_spec",
    "specs_declaring_no_criteria",
)

#: Counters that may only go up. The direction is the whole reason this one
#: exists: a ratchet on debt says the repository did not get worse, and only a
#: floor under progress says it got better.
FLOORED: tuple[str, ...] = ("design_coverage",)

Direction = Literal["min", "max"]


class AcStateNoteError(RuntimeError):
    """A note could not be read, or says something the fold cannot use.

    Deliberately not survivable by skipping the note: a bound folded from an
    unknown subset of the evidence is not a bound.
    """


@dataclass(frozen=True)
class Note:
    """One branch's measured counters."""

    name: str
    branch: str | None
    measured_with_tests: bool
    counters: dict[str, Any]

    @classmethod
    def parse(cls, name: str, text: str) -> Note:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AcStateNoteError(f"{name} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise AcStateNoteError(f"{name} is not a JSON object")
        counters = raw.get("counters")
        if not isinstance(counters, dict) or not counters:
            raise AcStateNoteError(f"{name} records no counters")
        unknown = sorted(set(counters) - set(RATCHETED) - set(FLOORED))
        if unknown:
            raise AcStateNoteError(
                f"{name} records counters this build does not know: {', '.join(unknown)}"
            )
        for key, value in counters.items():
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise AcStateNoteError(f"{name} records a non-numeric {key}: {value!r}")
        if "measured_with_tests" not in raw:
            raise AcStateNoteError(f"{name} does not say whether it was measured with tests")
        return cls(
            name=name,
            branch=raw.get("branch"),
            measured_with_tests=bool(raw["measured_with_tests"]),
            counters=dict(counters),
        )

    def as_json(self) -> str:
        payload: dict[str, Any] = {
            "branch": self.branch,
            "measured_with_tests": self.measured_with_tests,
            "counters": self.counters,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class Bounds:
    """The folded bound, and enough provenance to say where it came from."""

    counters: dict[str, float]
    notes: tuple[str, ...]
    origin: Literal["base", "worktree", "empty"]
    base_sha: str | None
    #: note name -> the mode it was banked in. Carried so a caller can refuse a
    #: fold across measurement modes: the counters are incomparable, and only
    #: the *run* knows which mode it is in, so the check cannot live here.
    modes: dict[str, bool] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.counters

    def describe(self) -> str:
        if self.empty:
            return "no notes at the base revision, so nothing is bounded yet"
        where = f"{self.base_sha[:12]}" if self.base_sha else "the worktree"
        return f"folded from {len(self.notes)} note(s) at {where}: {', '.join(self.notes)}"


def direction_of(counter: str) -> Direction:
    """Which way this counter is allowed to move."""
    if counter in FLOORED:
        return "max"
    if counter in RATCHETED:
        return "min"
    raise AcStateNoteError(f"{counter} is not a ratcheted or floored counter")


def fold(notes: list[Note]) -> dict[str, float]:
    """The tightest bound the notes jointly support.

    `min` for debt and `max` for coverage, per counter and independently: a note
    that holds the best value of one counter says nothing about the others, and
    folding whole notes rather than counters would let a single strong note drag
    every other bound with it.
    """
    bounds: dict[str, float] = {}
    for note in notes:
        for counter, value in note.counters.items():
            if counter not in bounds:
                bounds[counter] = value
                continue
            bounds[counter] = (
                max(bounds[counter], value)
                if direction_of(counter) == "max"
                else min(bounds[counter], value)
            )
    return bounds


def load_notes(
    *, base: str | None = None, notes_dir: Path | None = None, root: Path | None = None
) -> tuple[list[Note], Literal["base", "worktree", "empty"], str | None]:
    """Every note as of the base revision, with where they were read from.

    `notes_dir` and `root` resolve at call time rather than in the signature, so
    a test that redirects `NOTES_DIR` at a synthetic tree actually redirects
    this — a default bound at def time would silently keep reading the real one.
    """
    notes_dir = NOTES_DIR if notes_dir is None else notes_dir
    root = ROOT if root is None else root
    prov = provenance()
    baselines = prov.resolve_baseline_dir(notes_dir, base=base, root=root)
    if baselines:
        notes = [Note.parse(item.path.name, item.text or "") for item in baselines]
        return notes, baselines[0].origin, baselines[0].base_sha

    retired = prov.resolve_baseline(root / RETIRED_CEILINGS_REL, base=base, root=root)
    if retired.absent_at_base:
        return [], "empty", None
    recorded = retired.loads({})
    if not isinstance(recorded, dict) or "ceilings" not in recorded:
        raise AcStateNoteError(
            f"{RETIRED_CEILINGS.name} at the base revision records no ceilings, so the "
            "migration bridge has nothing to fold"
        )
    bridge = Note(
        name=f"{RETIRED_CEILINGS.name} (migrating)",
        branch=None,
        measured_with_tests=bool(recorded.get("measured_with_tests")),
        counters=dict(recorded["ceilings"]),
    )
    return [bridge], retired.origin, retired.base_sha


def banked_bound(*, notes_dir: Path | None = None) -> Bounds:
    """The bound the notes *in this tree* jointly support.

    The answer to "did you bank what you measured?", and the reason it is a
    fold rather than one note: a stacked branch carries its parent's note as
    well as its own, and both are new relative to the base the comparison is
    read at. Asking which single note is "the candidate's" has no answer there,
    and the rule that used to answer `None` made every stacked PR read as an
    unbanked improvement -- the serialization #585 removed, reappearing one
    level up (#609).

    Folding the worktree is safe because folding only ever *tightens*: `max` for
    coverage, `min` for debt, so a note a candidate adds cannot loosen anything.
    What a candidate could do is delete or weaken a merged note, and that is
    caught by the other half of the comparison, which is folded at the base and
    which nothing in the worktree can reach.
    """
    notes = worktree_notes(notes_dir=notes_dir)
    if not notes:
        return Bounds(counters={}, notes=(), origin="empty", base_sha=None)
    return Bounds(
        counters=fold(notes),
        notes=tuple(note.name for note in notes),
        origin="worktree",
        base_sha=None,
        modes={note.name: note.measured_with_tests for note in notes},
    )


def worktree_notes(*, notes_dir: Path | None = None) -> list[Note]:
    """Every note file in this tree, unfolded.

    The fold answers "what do these notes jointly support"; some questions need
    the notes themselves. Whether a measurement was *banked* is one of them: it
    asks whether some note records this exact value, which a fold has already
    thrown away (#691).
    """
    notes_dir = NOTES_DIR if notes_dir is None else notes_dir
    if not notes_dir.is_dir():
        return []
    return [
        Note.parse(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(notes_dir.glob("*.json"))
    ]


def bounds(
    *, base: str | None = None, notes_dir: Path | None = None, root: Path | None = None
) -> Bounds:
    """The bound a candidate is judged against."""
    notes, origin, base_sha = load_notes(base=base, notes_dir=notes_dir, root=root)
    return Bounds(
        counters=fold(notes),
        notes=tuple(note.name for note in notes),
        origin=origin,
        base_sha=base_sha,
        modes={note.name: note.measured_with_tests for note in notes},
    )


def slug(branch: str) -> str:
    """A filename for a branch: same shape the suite-inventory notes use."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", branch).strip("-").lower()
    return cleaned or "detached"


def current_branch(root: Path | None = None) -> str:
    """The branch being banked, or `detached` outside one."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT if root is None else root,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "detached"
    name = proc.stdout.strip()
    return name if proc.returncode == 0 and name and name != "HEAD" else "detached"


def note_path(branch: str, *, notes_dir: Path | None = None) -> Path:
    return (NOTES_DIR if notes_dir is None else notes_dir) / f"{slug(branch)}.json"


def write_note(
    counters: dict[str, Any],
    *,
    branch: str | None = None,
    measured_with_tests: bool,
    notes_dir: Path | None = None,
    root: Path | None = None,
) -> Path:
    """Record this branch's measurement as its own note."""
    notes_dir = NOTES_DIR if notes_dir is None else notes_dir
    name = branch if branch is not None else current_branch(ROOT if root is None else root)
    path = note_path(name, notes_dir=notes_dir)
    notes_dir.mkdir(parents=True, exist_ok=True)
    note = Note(
        name=path.name,
        branch=name,
        measured_with_tests=measured_with_tests,
        counters={k: counters[k] for k in (*RATCHETED, *FLOORED) if k in counters},
    )
    path.write_text(note.as_json(), encoding="utf-8")
    return path


def stale(notes: list[Note]) -> list[Note]:
    """Notes that contribute nothing the rest do not already say.

    "Dominated by the fold of the others" is the definition, and it is
    deliberately per-note rather than per-counter: a note holding the strongest
    value of even one counter is still evidence, and removing it would loosen
    the bound.

    Computed against the fold of *all other* notes, one note at a time, so two
    notes that duplicate each other do not both read as stale and disappear
    together.
    """
    survivors = list(notes)
    dropped: list[Note] = []
    for note in notes:
        others = [item for item in survivors if item is not note]
        if not others:
            continue
        without = fold(others)
        if any(
            counter not in without
            or (direction_of(counter) == "max" and value > without[counter])
            or (direction_of(counter) == "min" and value < without[counter])
            for counter, value in note.counters.items()
        ):
            continue
        dropped.append(note)
        survivors = others
    return dropped
