#!/usr/bin/env python3
"""Measure each acceptance criterion's state and fold it up to spec and ADR.

A document status that a person types is a claim. A document status computed
from artefacts is a measurement. `Implemented` was wrong on six consecutive ADRs
for months (#357, #363) because one person could assert it about a whole
document and nothing checked. Nobody can falsely assert eighty-three criteria as
easily as one, and each of those is individually checkable — which is the whole
reason to push the unit of truth down to the criterion.

Each criterion climbs a ladder:

    declared   the spec states it, with an **AC-N** id
    covered    some test carries @pytest.mark.ac("<spec>/AC-N")
    passing    that test passes
    reachable  the module the criterion asserts about is reachable from a real
               entry point

The last rung is the one that matters and the one most easily left off. A green
test proves the code works; it does not prove anything runs it. `tick_decay`
(#344), `elevation_store` (#346) and the entire security pipeline (#350) were
all green, all tested, and all unreachable. A ladder stopping at `passing`
reproduces that lie one level down, having spent the effort to arrive back here.

Folding is by tier: a spec's tier is the highest rung *every* one of its criteria
has reached. That is deliberately strict — one lagging criterion holds the whole
spec down — so the report also carries the per-rung distribution, because a
label that only ever reads "declared" tells you nothing about whether one
criterion is missing or forty.

Report-only. Nothing here fails a build yet, and no front-matter status is
rewritten; the point of the first pass is to find out what is true.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gherkin.parser import Parser as GherkinParser
from gherkin.token_scanner import TokenScanner

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "docs" / "specs"
ADR_DIR = ROOT / "docs" / "adr"
REACHABILITY_BASELINE = ROOT / "quality" / "reachability-baseline.json"
DEFAULT_OUT = ROOT / "quality" / "ac-state.json"
PYPROJECT = ROOT / "pyproject.toml"

# Rungs, weakest first. A tier is the highest rung reached by *every* criterion.
RUNGS = ("declared", "covered", "passing", "reachable")

# Statuses that assert the work is done. A document carrying one of these
# while measuring below `reachable` is making a claim its own artefacts do
# not support — the #357/#363 failure, stated in the vocabulary that can
# now catch it.
COMPLETION_CLAIMS = {"Implemented", "Tests Passing"}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
# Case-insensitive on purpose: 126 specs write "## Acceptance criteria" and 39
# write "## Acceptance Criteria". A case-sensitive match sees a seventh of the
# corpus and reports the rest as having no criteria at all.
AC_HEADING_RE = re.compile(r"^##\s+acceptance\s+criteria.*$", re.IGNORECASE | re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)
AC_ID_RE = re.compile(r"\*\*AC-(\d+)\*\*")
AC_TAG_RE = re.compile(r"AC-\d+")
# `- [x] **AC-3** ...` — the box is the author's *claim*; the ladder below is
# the measurement. Where the two disagree the report says so, because a ticked
# box on an unproven criterion is the same falsehood ADR-level `Implemented`
# was on six documents at once.
CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*\*\*AC-(\d+)\*\*", re.MULTILINE)
GHERKIN_FENCE_RE = re.compile(r"```gherkin\n(.*?)```", re.DOTALL)
FEATURE_RE = re.compile(r"^\s*Feature:", re.MULTILINE)
ID_RE = re.compile(r"^id:\s*(\S+)", re.MULTILINE)
STATUS_RE = re.compile(r"^status:\s*(.+?)\s*$", re.MULTILINE)
LAYER_RE = re.compile(r"^layer:\s*(.+?)\s*$", re.MULTILINE)
IMPLEMENTS_RE = re.compile(r"^implements:\s*(.*)$((?:\n  - .*)*)", re.MULTILINE)
KIND_RE = re.compile(r"^kind:\s*spec\s*$", re.MULTILINE)

#: How a spec says "this document has no acceptance criteria, on purpose".
#:
#: A body marker rather than a front-matter field: the registry schema is
#: `extra = forbid`, so a new field is a schema change every consumer inherits,
#: and this needs to be visible in the diff far more than it needs to be
#: queryable. The reason is mandatory — an escape hatch that does not have to
#: justify itself is just a way to make the counter go down.
#: The whole `ac-state: non-measurable` comment, body captured but not parsed.
#:
#: The body is `(?:(?!-->).)*` so it physically cannot reach a closing
#: delimiter, and the delimiter between "non-measurable" and the reason is
#: matched in code rather than in the pattern. An earlier version put the
#: delimiter in a character class — which matched the first hyphen of the
#: marker's own `-->`, leaving `->` for a DOTALL body to run on from until the
#: *next* `-->` anywhere in the file. Any unrelated HTML comment further down
#: then donated a "reason", so the mandatory-reason rule was stated and not
#: enforced. The isolated reasonless test passed because its fixture had no
#: second comment: an assertion that proved less than it appeared to.
NON_MEASURABLE_RE = re.compile(
    r"<!--\s*ac-state:\s*non-measurable(?P<body>(?:(?!-->).)*)-->",
    re.IGNORECASE | re.DOTALL,
)

#: What may separate the marker from its reason. Both dashes and the colon,
#: because Markdown tooling and people produce different ones and the hatch
#: should not depend on which was typed.
_REASON_DELIMITERS = ("-", "\u2014", ":")


def declares_non_measurable(text: str) -> bool:
    """Whether `text` opts out of the criteria requirement, *with a reason*.

    An opt-out that does not have to justify itself is only a way to make a
    counter fall without doing anything, so a bare marker does not count.
    """
    match = NON_MEASURABLE_RE.search(text)
    if match is None:
        return False
    body = match.group("body").strip()
    if not body.startswith(_REASON_DELIMITERS):
        return False
    return bool(body[1:].strip())


#: An `implements:` entry that names an ADR.
#:
#: Two things the raw field is not. It may be an **inline** YAML list —
#: `implements: [maistro-engine#ADR-073]` is valid and `_list_field` hands back
#: the whole bracketed string, so splitting on `#` yielded `ADR-073]`: the spec
#: counted as mapped while its ADR still counted as uncovered, both wrong and in
#: opposite directions. And the schema accepts `SPEC-*` references as well as
#: `ADR-*`, so a spec implementing only another spec maps to no decision at all
#: — it would drop out of `specs_implementing_nothing` for exactly the missing
#: chain that counter exists to report.
_ADR_REF_RE = re.compile(r"\bADR-[0-9A-Za-z-]+")


def adr_refs(entries: list[str]) -> list[str]:
    """The ADR ids named by an `implements:` field, in any of its spellings."""
    return [ref for entry in entries for ref in _ADR_REF_RE.findall(entry)]


#: ADR statuses that mean the decision is taken, so implementation is owed.
#: `Proposed` is excluded by definition — a decision not yet made cannot be
#: owed an implementation, and counting it would make writing down an idea look
#: like incurring debt.
DECISION_TAKEN = ("Accepted", "Implemented")
AC_MODULES_RE = re.compile(r"^ac[-_]modules:\s*$((?:\n  \S+:\s*\S+)*)", re.MULTILINE)


def configured_test_roots() -> list[Path]:
    """The suites pytest is configured to run, from `[tool.pytest.ini_options]`.

    Deliberately not a hand-written list. `packages/` as a root additionally
    collects `maistro-canvas/frontend/server/**/tests`, which the repo does not
    run and which fails at import — 13 collection errors abort the session
    before a single test executes, and every criterion then reads `covered`
    forever with no signal that the run never happened.

    It also keeps one invariant that matters: markers are scanned in exactly the
    trees pytest will execute. A marker in a file pytest never collects could
    otherwise sit at `covered` permanently, looking like work in progress rather
    than a test that does not run.
    """
    with PYPROJECT.open("rb") as handle:
        paths = tomllib.load(handle)["tool"]["pytest"]["ini_options"]["testpaths"]
    return [ROOT / p for p in paths]


@dataclass
class Criterion:
    ac_id: str
    claimed: bool = False
    module: str | None = None
    covered_by: list[str] = field(default_factory=list)
    passing: bool | None = None
    form: str = "bullet"
    scenario: list[str] | None = None
    has_outcome: bool | None = None

    def rung(self, unreachable: set[str]) -> str:
        if not self.covered_by:
            return "declared"
        if not self.passing:
            return "covered"
        if self.module is None:
            # Unannotated: we can say the test passes, never that anything runs
            # it. Reporting this as reachable would be the exact failure the
            # last rung exists to catch.
            return "passing"
        return "reachable" if _is_reachable(self.module, unreachable) else "passing"


def _is_reachable(module: str, unreachable: set[str]) -> bool:
    """A module is reachable unless it, or an ancestor package, is baselined."""
    parts = module.split(".")
    return not any(".".join(parts[: i + 1]) in unreachable for i in range(len(parts)))


def parse_gherkin(block: str) -> tuple[list[dict[str, Any]], str | None]:
    """Scenarios and their tags from one ```gherkin fence, or a parse error.

    The corpus already carries 224 scenarios across 11 documents, written before
    anything read them — more structured acceptance criteria than the `**AC-N**`
    bullet form this script started with. They are parsed with the real Gherkin
    parser rather than a regex, because the point of choosing a standard grammar
    is that its own tooling decides what is well-formed. Four blocks do not
    parse today; an unenforced convention drifts, which is the argument for
    reporting the failures rather than tolerating them.

    A criterion's identity is a Gherkin *tag* — `@AC-3` above the scenario —
    not the scenario's name. Names get reworded; a reworded name would silently
    break the binding to the test claiming it and the criterion would drop back
    to `declared` with nothing saying why.
    """
    src = block if FEATURE_RE.search(block) else "Feature: (implicit)\n" + block
    try:
        doc = GherkinParser().parse(TokenScanner(src))
    except Exception as exc:
        return [], str(exc).splitlines()[0]

    scenarios: list[dict[str, Any]] = []
    for child in doc.get("feature", {}).get("children", []):
        scenario = child.get("scenario")
        if not scenario:
            continue
        steps = [s["keyword"].strip() for s in scenario.get("steps", [])]
        scenarios.append(
            {
                "name": scenario.get("name", ""),
                "tags": [tag["name"].lstrip("@") for tag in scenario.get("tags", [])],
                "keywords": steps,
                # A scenario with no Then states no observable outcome, so
                # nothing about it is falsifiable. That is a weaker defect than
                # a parse failure and a real one, so it is counted separately.
                "has_outcome": any(k in ("Then", "*") for k in steps),
            }
        )
    return scenarios, None


def gherkin_criteria(
    section: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """AC-tagged scenarios in an acceptance-criteria section.

    Returns the tagged scenarios keyed by AC id, the names of scenarios
    carrying no AC tag (declared but unaddressable), and any parse errors.
    """
    tagged: dict[str, list[dict[str, Any]]] = {}
    untagged: list[str] = []
    errors: list[str] = []
    for block in GHERKIN_FENCE_RE.findall(section):
        scenarios, error = parse_gherkin(block)
        if error:
            errors.append(error)
            continue
        for scenario in scenarios:
            ac_tags = [tag for tag in scenario["tags"] if AC_TAG_RE.fullmatch(tag)]
            if not ac_tags:
                untagged.append(scenario["name"])
                continue
            for tag in ac_tags:
                # A list, not an assignment: one criterion often needs several
                # scenarios (a table of divergence modes plus the non-mutation
                # case). Keying a single scenario per tag drops all but the last
                # and reports a smaller corpus than exists.
                tagged.setdefault(tag, []).append(scenario)
    return tagged, untagged, errors


def _frontmatter(text: str) -> str:
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def _ac_section(text: str) -> str:
    m = AC_HEADING_RE.search(text)
    if not m:
        return ""
    rest = text[m.end() :]
    nxt = NEXT_HEADING_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def _list_field(fm: str, pattern: re.Pattern[str]) -> list[str]:
    m = pattern.search(fm)
    if not m:
        return []
    inline = m.group(1).strip()
    if inline and inline != "[]":
        return [inline]
    return [ln.strip().lstrip("- ").strip() for ln in m.group(2).splitlines() if ln.strip()]


def _ac_modules(fm: str) -> dict[str, str]:
    m = AC_MODULES_RE.search(fm)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        out[key.strip()] = value.strip()
    return out


def _decorator_ac_ids(node: ast.AST) -> list[str]:
    """AC ids from `@pytest.mark.ac("...")` decorators on one def/class."""
    ids: list[str] = []
    for deco in getattr(node, "decorator_list", []):
        if not isinstance(deco, ast.Call):
            continue
        func = deco.func
        if not (isinstance(func, ast.Attribute) and func.attr == "ac"):
            continue
        owner = func.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "mark"):
            continue
        ids.extend(
            a.value for a in deco.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
        )
    return ids


def scan_markers(test_roots: list[Path]) -> dict[str, list[str]]:
    """Map AC id -> test files claiming it.

    Parsed, not grepped. A regex over the same files reports the `SPEC-x/AC-n`
    in `test_spec_tracker.py`'s own module docstring as a real claim on a spec
    that does not exist — a tool built to find false assertions must not open by
    making one. Only decorators on a `def` or `class` count.

    Only `test_*.py` is read. Widening to all of `packages/` additionally sweeps
    up the format strings in `maistro_rsi/local_loop.py`, which are prompt text.
    """
    found: dict[str, list[str]] = {}
    for root in test_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("test_*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    for ac_id in _decorator_ac_ids(node):
                        files = found.setdefault(ac_id, [])
                        # One entry per file, not per marker: three tests in
                        # one file is one piece of evidence about where the
                        # criterion is proven, not three.
                        if rel not in files:
                            files.append(rel)
    return found


def passing_ac_ids(test_roots: list[Path]) -> set[str] | None:
    """AC ids whose every claiming test passed, or None if the run never happened.

    None and `set()` mean different things and the caller must not conflate
    them: an empty set is "the suite ran and nothing passed", None is "we do not
    know". Reporting `passing` for an unrun suite is the failure this whole
    script exists to stop, one level up.
    """
    roots = [str(r) for r in test_roots if r.exists()]
    if not roots:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ac-outcomes.json"
        env = {**os.environ, "AC_OUTCOME_JSON": str(out), "PYTHONPATH": str(ROOT / "scripts")}
        args = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "ac_outcome_plugin",
            "-p",
            "no:randomly",
            "-q",
            "--no-header",
            # A marked test that fails still tells us the criterion is not
            # passing, so the run is worth finishing even once one is red.
            "-m",
            "ac",
            *roots,
        ]
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=1800, cwd=ROOT, env=env
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        # 0 = all passed, 1 = some failed, 5 = nothing collected. Anything else
        # (2 interrupted, 3 internal error, 4 usage error) means the session did
        # not run to completion, and a partial outcome map read as "these
        # criteria are not passing" would be a fabrication.
        if proc.returncode not in (0, 1) or not out.is_file():
            sys.stderr.write(
                f"pytest exited {proc.returncode}; the passing rung is unmeasured.\n"
                f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}\n"
            )
            return None
        return set(json.loads(out.read_text(encoding="utf-8"))["passing"])


def load_unreachable() -> set[str]:
    if not REACHABILITY_BASELINE.is_file():
        return set()
    payload = json.loads(REACHABILITY_BASELINE.read_text(encoding="utf-8"))
    return set(payload.get("unreachable", []))


def tier_of(rungs: list[str]) -> str:
    """Highest rung every criterion has reached."""
    if not rungs:
        return "none"
    return min(rungs, key=RUNGS.index)


def _spec_files() -> list[Path]:
    """Every spec document, matching the corpus the registry validates.

    `maistro_registry`'s walk is `docs/specs/**/*.md` — recursive, and not
    keyed on the filename. A non-recursive `glob("SPEC-*.md")` accepted a
    nested `docs/specs/subsystem/SPEC-*.md` as valid at the registry gate while
    omitting every criterion in it here, so the mandate would report success
    over a document it never opened. Filtering on `kind: spec` rather than the
    filename is what makes the two corpora the same set.
    """
    files = []
    for path in sorted(SPEC_DIR.rglob("*.md")):
        if KIND_RE.search(_frontmatter(path.read_text(encoding="utf-8"))):
            files.append(path)
    return files


def collect_specs(
    markers: dict[str, list[str]],
    unreachable: set[str],
    passing: set[str] | None,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in _spec_files():
        text = path.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        spec_id = (ID_RE.search(fm) or [None, path.stem])[1]
        section = _ac_section(text)
        modules = _ac_modules(fm)
        # Bullets stay section-scoped: a bare `**AC-1**` in prose elsewhere is
        # not a criterion. Gherkin fences do not need the scoping — a
        # `Scenario:` inside a ```gherkin block is a criterion by construction,
        # and requiring the heading loses SPEC-160 entirely, a document whose
        # whole body is 39 scenarios under topic headings with no
        # "## Acceptance criteria" anywhere in it.
        gherkin_scope = text
        boxes = {f"AC-{n}": state.lower() == "x" for state, n in CHECKBOX_RE.findall(section)}
        scenarios, untagged, gherkin_errors = gherkin_criteria(gherkin_scope)

        # Both forms count, and the mix is reported rather than quietly
        # normalised: the corpus is mid-convergence from prose bullets to
        # Gherkin, and hiding which form a spec uses would hide the progress.
        shorts = list(
            dict.fromkeys([f"AC-{n}" for n in AC_ID_RE.findall(section)] + list(scenarios))
        )

        criteria = []
        for short in shorts:
            ac_id = f"{spec_id}/{short}"
            scenario = scenarios.get(short)
            criteria.append(
                Criterion(
                    ac_id=ac_id,
                    claimed=boxes.get(short, False),
                    module=modules.get(short),
                    covered_by=markers.get(ac_id, []),
                    # None until a run settles it — never silently False, which
                    # would read as "the test failed".
                    passing=None if passing is None else ac_id in passing,
                    form="gherkin" if scenario else "bullet",
                    scenario=[s["name"] for s in scenario] if scenario else None,
                    has_outcome=all(s["has_outcome"] for s in scenario) if scenario else None,
                )
            )

        rungs = [c.rung(unreachable) for c in criteria]
        dist = {r: rungs.count(r) for r in RUNGS}
        specs.append(
            {
                "id": spec_id,
                "file": str(path.relative_to(ROOT)),
                "layer": (LAYER_RE.search(fm) or [None, "?"])[1],
                "declared_status": (STATUS_RE.search(fm) or [None, "?"])[1],
                "implements": _list_field(fm, IMPLEMENTS_RE),
                "declares_non_measurable": declares_non_measurable(text),
                "declared_unproven": sorted(declared_unproven(text)),
                "has_ac_heading": bool(AC_HEADING_RE.search(text)),
                "criteria_total": len(criteria),
                "annotated": sum(1 for c in criteria if c.module),
                "gherkin_criteria": sum(1 for c in criteria if c.form == "gherkin"),
                "gherkin_parse_errors": gherkin_errors,
                "scenarios_without_ac_tag": untagged,
                "distribution": dist,
                "tier": tier_of(rungs),
                "criteria": [
                    {
                        "id": c.ac_id,
                        "claimed": c.claimed,
                        "module": c.module,
                        "covered_by": c.covered_by,
                        "form": c.form,
                        "scenario": c.scenario,
                        "rung": c.rung(unreachable),
                    }
                    for c in criteria
                ],
            }
        )
    return specs


def collect_adrs(
    specs: list[dict[str, Any]],
    markers: dict[str, list[str]],
    unreachable: set[str],
    passing: set[str] | None,
) -> list[dict[str, Any]]:
    """Fold specs up to the ADRs they implement, via the spec's `implements:`."""
    by_adr: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        for ref in adr_refs(spec["implements"]):
            by_adr.setdefault(ref, []).append(spec)

    adrs = []
    for path in sorted(ADR_DIR.glob("ADR-*.md")):
        text = path.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        adr_id = (ID_RE.search(fm) or [None, path.stem])[1]
        children = by_adr.get(adr_id, [])
        tiers = [s["tier"] for s in children if s["criteria_total"]]

        # Four ADRs (063, 064, 065, 066) carry 147 scenarios of their own,
        # written before the spec split. Folding only from specs would report
        # them as `unmeasured` while their own acceptance criteria sit right
        # there in the document.
        own, own_untagged, own_errors = gherkin_criteria(text)
        # Bullet **AC-N** ids count as the ADR's own criteria as much as
        # scenarios do. Deriving `own_criteria` from Gherkin alone reported
        # ADR-062026-9b30 — three bullet criteria under its acceptance heading,
        # no implementing spec — as carrying none, so it landed in
        # `adrs_without_implementing_spec` against that counter's own stated
        # exemption, and banked a debt figure that was too high.
        own_section = _ac_section(text)
        own_bullets = [f"AC-{n}" for n in AC_ID_RE.findall(own_section)]
        own = list(dict.fromkeys(list(own) + own_bullets))
        # The tick is the claim, on an ADR exactly as on a spec. Hard-coding
        # this to False meant flipping an ADR criterion to [x] was invisible to
        # `touched_since`, so the mandate passed without ever asking for the
        # evidence — on the documents that carry the most weight.
        own_boxes = {
            f"AC-{n}": state.lower() == "x" for state, n in CHECKBOX_RE.findall(own_section)
        }
        # The ADR's own ac-modules map, same as a spec's. Without it every
        # ADR-owned criterion has module=None and silently caps at `passing` —
        # the ladder would tell an ADR its work can never be proven reachable,
        # which is false and would teach people to ignore the tier.
        own_modules = _ac_modules(fm)
        own_criteria = [
            Criterion(
                ac_id=f"{adr_id}/{short}",
                module=own_modules.get(short),
                covered_by=markers.get(f"{adr_id}/{short}", []),
                passing=None if passing is None else f"{adr_id}/{short}" in passing,
            )
            for short in own
        ]
        own_rungs = [c.rung(unreachable) for c in own_criteria]

        inputs = tiers + own_rungs
        adrs.append(
            {
                "id": adr_id,
                "file": str(path.relative_to(ROOT)),
                "declared_status": (STATUS_RE.search(fm) or [None, "?"])[1],
                "specs": [s["id"] for s in children],
                "measurable_specs": len(tiers),
                "own_criteria": len(own),
                "own_detail": [
                    {
                        "id": c.ac_id,
                        "claimed": own_boxes.get(c.ac_id.split("/")[-1], False),
                        "module": c.module,
                        "covered_by": c.covered_by,
                        "rung": c.rung(unreachable),
                    }
                    for c in own_criteria
                ],
                "scenarios_without_ac_tag": own_untagged,
                "gherkin_parse_errors": own_errors,
                "declared_unproven": sorted(declared_unproven(text)),
                "tier": tier_of(inputs) if inputs else "unmeasured",
            }
        )
    return adrs


# ─── the mandate: a PR must prove the criteria it declares (#165) ─────────────
#
# Everything above this line is a *ratchet*. A ratchet says "the repository did
# not get worse"; it never says "this change proved what it claimed". The
# difference is not academic: a PR could add a spec, tick a criterion
# `Implemented`, add no marker, and pass — because the counter it lands in is a
# counter that already permits 68 of them. The ceiling absorbs the new debt, and
# the absorption is silent.
#
# So two populations, two rules. Legacy criteria stay on the ceiling and fall
# over time. Criteria a PR *creates or touches* get zero tolerance. That split
# is what turns "adherence to acceptance criteria" from a trend into a gate.


#: How a spec says "this criterion is declared but deliberately not yet proven".
#:
#: Per-criterion, reason mandatory, and in the body so it shows up in the diff —
#: an escape hatch nobody can see while reviewing is an unstated one. Same shape
#: as the non-measurable marker, for the same reasons.
UNPROVEN_RE = re.compile(
    r"<!--\s*ac-state:\s*unproven\s+(?P<ac>AC-\d+)(?P<body>(?:(?!-->).)*)-->",
    re.IGNORECASE | re.DOTALL,
)


def declared_unproven(text: str) -> set[str]:
    """The `AC-N` ids this document declares unproven, *with a reason*."""
    found = set()
    for match in UNPROVEN_RE.finditer(text):
        body = match.group("body").strip()
        if body.startswith(_REASON_DELIMITERS) and body[1:].strip():
            found.add(match.group("ac").upper())
    return found


def _file_at(rev: str, path: str) -> str | None:
    """`path` as of `rev`, or None when it did not exist there."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{rev}:{path}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _criteria_in(text: str, doc_id: str) -> dict[str, bool]:
    """Every criterion the document declares, mapped to whether it claims done.

    Text-only on purpose: this is run against a *past* revision, where the tests
    cannot be executed and the module graph does not apply. Ids and tick marks
    are all the comparison needs.
    """
    section = _ac_section(text)
    scenarios, _untagged, _errors = gherkin_criteria(text)
    boxes = {f"AC-{n}": state.lower() == "x" for state, n in CHECKBOX_RE.findall(section)}
    shorts = dict.fromkeys([f"AC-{n}" for n in AC_ID_RE.findall(section)] + list(scenarios))
    return {f"{doc_id}/{short}": boxes.get(short, False) for short in shorts}


def snapshot_at(rev: str) -> dict[str, bool] | None:
    """Every criterion in the corpus as of `rev`. None when `rev` is unreadable.

    None rather than an empty dict, and the caller refuses rather than
    proceeding: an unreadable base makes *every* criterion look new, which would
    turn the mandate from a gate on this PR into a demand that the whole
    corpus be retrofitted at once. A gate that fires on everything gets turned
    off, which is worse than one that stops and says why.
    """
    try:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", rev, "--", "docs/specs", "docs/adr"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listing.returncode != 0:
        return None

    snapshot: dict[str, bool] = {}
    for path in listing.stdout.split():
        if not path.endswith(".md"):
            continue
        text = _file_at(rev, path)
        if text is None:
            continue
        fm = _frontmatter(text)
        doc_id = (ID_RE.search(fm) or [None, Path(path).stem])[1]
        snapshot.update(_criteria_in(text, doc_id))
    return snapshot


def touched_since(base: dict[str, bool], head: dict[str, bool]) -> set[str]:
    """Criteria this change created, or newly claimed as done.

    Ticking a box is the claim, so flipping one to `[x]` counts as touching the
    criterion even when its text did not move — that is precisely the moment to
    demand the evidence.
    """
    added = set(head) - set(base)
    newly_claimed = {ac for ac, claimed in head.items() if claimed and not base.get(ac, False)}
    return added | newly_claimed


def _criteria_of(document: dict[str, Any]) -> list[dict[str, Any]]:
    """A spec's `criteria` or an ADR's `own_detail`, under one name.

    The two shapes are the reason three of the mandate's four review findings
    existed: every place that had to remember which key a document uses was a
    place one of them could be forgotten.
    """
    return document.get("criteria") or document.get("own_detail") or []


def mandate_violations(
    documents: list[dict[str, Any]],
    touched: set[str],
    exempt: dict[str, set[str]],
) -> list[dict[str, str]]:
    """Touched criteria that are not proven and not declared unproven."""
    violations = []
    for doc in documents:
        allowed = exempt.get(doc["id"], set())
        for criterion in _criteria_of(doc):
            ac_id = criterion["id"]
            if ac_id not in touched or ac_id.split("/")[-1].upper() in allowed:
                continue
            if criterion["rung"] == "reachable":
                continue
            violations.append(
                {
                    "id": ac_id,
                    "file": doc.get("file", ""),
                    "rung": criterion["rung"],
                    "module": criterion.get("module") or "-",
                    "covered_by": ", ".join(criterion.get("covered_by") or []) or "-",
                }
            )
    return violations


CEILINGS = ROOT / "quality" / "ac-state-ceilings.json"

#: Counters that may only go down. Each is a way a completion claim can outrun
#: its evidence, so a rise is a new contradiction entering the repository.
RATCHETED = (
    "completion_claims_contradicted",
    "completion_claims_unverifiable",
    "specs_awaiting_retrofit",
    "markers_without_criterion",
    "criteria_claimed_but_unproven",
    "scenarios_without_ac_tag",
    "gherkin_parse_errors",
    # The chain checked for absence rather than breakage (#164).
    "specs_implementing_nothing",
    "adrs_without_implementing_spec",
    "specs_declaring_no_criteria",
)


def _mode_mismatch(run_tests: bool) -> str | None:
    """The refusal message for a wrong-mode ratchet, checked before measuring.

    This runs first because the report is written to disk before the ratchet
    would otherwise reach its own mode check — so a wrong-mode invocation used to
    overwrite the committed `ac-state.json` with an unmeasured payload and *then*
    complain. Failing before any measurement leaves the artefact untouched.
    """
    if not CEILINGS.is_file():
        return None
    recorded = json.loads(CEILINGS.read_text(encoding="utf-8"))
    if recorded.get("measured_with_tests") == run_tests:
        return None
    want = "with" if recorded.get("measured_with_tests") else "without"
    return (
        f"FAIL: ceilings were banked {want} --run-tests; re-run in that mode. The passing "
        "rung is unreachable without it, so the counters are not comparable. Nothing was "
        "measured or written."
    )


def _bank(recorded: dict[str, Any], totals: dict[str, Any], measured: bool) -> int:
    recorded["measured_with_tests"] = measured
    recorded["ceilings"] = {name: totals[name] for name in RATCHETED}
    CEILINGS.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    try:
        shown = CEILINGS.relative_to(ROOT)
    except ValueError:  # a test may point CEILINGS outside the repo
        shown = CEILINGS
    print(f"banked {shown}; review the diff before committing")
    return 0


def _compare(ceilings: dict[str, Any], totals: dict[str, Any]) -> tuple[list[str], list[str]]:
    regressions: list[str] = []
    improvements: list[str] = []
    for name in RATCHETED:
        allowed = ceilings.get(name)
        actual = totals[name]
        if allowed is None:
            regressions.append(f"{name}: no ceiling recorded (measured {actual})")
        elif actual > allowed:
            regressions.append(f"{name}: {actual} exceeds the ceiling of {allowed}")
        elif actual < allowed:
            improvements.append(f"{name}: {actual}, ceiling still says {allowed}")
    return regressions, improvements


def ratchet(totals: dict[str, Any], measured: bool, bank: bool) -> int:
    """Compare the measured debt against its reviewed ceilings.

    Both directions fail. A rise is a regression: a document started claiming
    more than its artefacts support. A fall that has not been banked is slack —
    the same weakness a count ceiling always has, where one genuine improvement
    silently pays for a later regression. Banking is a reviewed edit to a small
    JSON file, so there is no reason to leave the margin sitting there.

    The comparison is refused across measurement modes. Without ``--run-tests``
    no criterion can reach the ``passing`` rung, so every claim above it reads as
    contradicted and the counters are not comparable with ones banked from a real
    run. Comparing them anyway would produce a gate that fails or passes
    according to how it was invoked.
    """
    if not CEILINGS.is_file():
        print(f"FAIL: {CEILINGS} is missing; run with --ratchet --bank to create it")
        return 1
    recorded = json.loads(CEILINGS.read_text(encoding="utf-8"))
    if bank:
        return _bank(recorded, totals, measured)
    if recorded.get("measured_with_tests") != measured:
        want = "with" if recorded.get("measured_with_tests") else "without"
        print(
            f"FAIL: ceilings were banked {want} --run-tests; re-run in that mode. "
            "The passing rung is unreachable without it, so the counters are not comparable."
        )
        return 1

    regressions, improvements = _compare(recorded["ceilings"], totals)
    if regressions:
        print("FAIL: a completion claim now outruns its evidence\n")
        for line in regressions:
            print(f"  - {line}")
        print(
            "\nEither prove the claim (add an **AC-N** id and a @pytest.mark.ac test) or "
            "correct the document's status. The ceiling does not move up."
        )
    if improvements:
        print("FAIL: unbanked improvement — the ceiling holds slack a regression could spend\n")
        for line in improvements:
            print(f"  - {line}")
        print("\nBank it: python scripts/check-ac-state.py --run-tests --ratchet --bank")
    if regressions or improvements:
        return 1
    print(f"OK: every acceptance-state debt counter sits exactly on its ceiling ({len(RATCHETED)})")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--ratchet",
        action="store_true",
        help="fail when any debt counter differs from quality/ac-state-ceilings.json",
    )
    ap.add_argument(
        "--bank",
        action="store_true",
        help="rewrite the ceilings from this measurement (review the diff)",
    )
    ap.add_argument(
        "--run-tests",
        action="store_true",
        help="run the ac-marked tests to settle the passing rung (slow; off by default)",
    )
    ap.add_argument(
        "--mandate",
        metavar="BASE_REV",
        help=(
            "fail when a criterion this change adds or newly claims is not proven "
            "(requires --run-tests; legacy criteria stay on the ceilings)"
        ),
    )
    args = ap.parse_args(argv)

    if args.mandate and not args.run_tests:
        # Without a measured run nothing reaches `reachable`, so every touched
        # criterion would look unproven. Refusing beats failing a PR for a
        # question that was never asked.
        print("FAIL: --mandate needs --run-tests; the passing rung is what it checks against")
        return 1

    roots = configured_test_roots()
    markers = scan_markers(roots)
    unreachable = load_unreachable()
    if args.ratchet and not args.bank and (early := _mode_mismatch(args.run_tests)) is not None:
        print(early)
        return 1
    passing = passing_ac_ids(roots) if args.run_tests else None

    specs = collect_specs(markers, unreachable, passing)
    adrs = collect_adrs(specs, markers, unreachable, passing)

    # Criteria live in specs AND in the ADRs that carry their own scenarios;
    # counting only spec ids here would report every ADR-bound marker as
    # naming no criterion — an orphan list poisoned by exactly the bindings
    # the ADR pass adds.
    declared_ids = {c["id"] for s in specs for c in s["criteria"]}
    declared_ids |= {c["id"] for a in adrs for c in a["own_detail"]}
    orphans = sorted(set(markers) - declared_ids)
    # A ticked box on a criterion the ladder cannot get to `reachable` is a
    # claim the artefacts do not support. With --run-tests off, everything sits
    # at or below `covered`, so this is only meaningful on a measured run.
    false_claims = [
        c["id"] for s in specs for c in s["criteria"] if c["claimed"] and c["rung"] != "reachable"
    ]

    # Two different things, and merging them would be the same error this
    # script exists to catch. A document at tier `none`/`unmeasured` has no
    # criteria to measure yet — its `Implemented` is unverified, not refuted.
    # A document that *has* measurable criteria and still falls short of
    # `reachable` is contradicted by its own artefacts.
    claiming = [d for d in specs if d["declared_status"] in COMPLETION_CLAIMS]
    claiming += [d for d in adrs if d["declared_status"] in COMPLETION_CLAIMS]

    def _row(d: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "id": d["id"],
            "kind": kind,
            "declared_status": d["declared_status"],
            "measured_tier": d["tier"],
            "file": d.get("file"),
        }

    kinds = {id(d): "spec" for d in specs}
    kinds.update({id(d): "adr" for d in adrs})
    contradicted = [_row(d, kinds[id(d)]) for d in claiming if d["tier"] in RUNGS[:-1]]
    unverifiable = [_row(d, kinds[id(d)]) for d in claiming if d["tier"] in ("none", "unmeasured")]

    # ---- the chain checked in the *absent* direction (#164) --------------
    #
    # The registry refuses a reference that does not resolve, so every link that
    # exists is real. Nothing asked whether the link exists at all: `implements:
    # []` is valid front matter, so a spec could name no ADR and an ADR could be
    # implemented by nothing, and both were clean. That makes "specs map to
    # ADRs" mean "specs do not *mis*-map to ADRs" — a much weaker claim than the
    # one a green build is read as supporting.
    orphan_specs = [
        {"id": s["id"], "file": s["file"]} for s in specs if not adr_refs(s["implements"])
    ]

    # An ADR is owed an implementation once the decision is taken. Carrying its
    # own criteria counts: ADR-063..066 hold 147 scenarios written before the
    # spec split, and calling those uncovered would report measured work as
    # missing.
    implemented_adrs = {ref for s in specs for ref in adr_refs(s["implements"])}
    uncovered_adrs = [
        {"id": a["id"], "file": a["file"], "declared_status": a["declared_status"]}
        for a in adrs
        if a["declared_status"] in DECISION_TAKEN
        and a["id"] not in implemented_adrs
        and not a["own_criteria"]
    ]

    # Split out of `specs_awaiting_retrofit` deliberately. That counter holds
    # documents with an acceptance heading and no ids yet — "criteria not
    # written". These have no heading and no criteria at all, which is a
    # different statement, and merging the two let "there are none" hide inside
    # "there are none *yet*".
    silent_specs = [
        {"id": s["id"], "file": s["file"]}
        for s in specs
        if not s["criteria_total"] and not s["has_ac_heading"] and not s["declares_non_measurable"]
    ]

    payload = {
        "generated_by": "scripts/check-ac-state.py",
        "measured": passing is not None,
        "rungs": list(RUNGS),
        "fold": "a tier is the highest rung every criterion of the document has reached",
        "totals": {
            "specs": len(specs),
            "specs_with_ac_heading": sum(1 for s in specs if s["has_ac_heading"]),
            "specs_with_ac_ids": sum(1 for s in specs if s["criteria_total"]),
            "specs_awaiting_retrofit": sum(
                1 for s in specs if s["has_ac_heading"] and not s["criteria_total"]
            ),
            "criteria_declared": len(declared_ids),
            "criteria_annotated": sum(s["annotated"] for s in specs),
            "markers_found": len(markers),
            "markers_without_criterion": len(orphans),
            "criteria_claimed_but_unproven": len(false_claims),
            "gherkin_criteria": sum(s["gherkin_criteria"] for s in specs),
            "scenarios_without_ac_tag": sum(
                len(d["scenarios_without_ac_tag"]) for d in (*specs, *adrs)
            ),
            "gherkin_parse_errors": sum(len(d["gherkin_parse_errors"]) for d in (*specs, *adrs)),
            "completion_claims_contradicted": len(contradicted),
            "completion_claims_unverifiable": len(unverifiable),
            "specs_implementing_nothing": len(orphan_specs),
            "adrs_without_implementing_spec": len(uncovered_adrs),
            "specs_declaring_no_criteria": len(silent_specs),
        },
        "markers_without_criterion": orphans,
        "criteria_claimed_but_unproven": false_claims,
        "completion_claims_contradicted": contradicted,
        "completion_claims_unverifiable": unverifiable,
        "specs_implementing_nothing": orphan_specs,
        "adrs_without_implementing_spec": uncovered_adrs,
        "specs_declaring_no_criteria": silent_specs,
        "specs": specs,
        "adrs": adrs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    t = payload["totals"]
    print("acceptance-criterion state (report only):")
    print(
        f"  passing rung measured        : {'yes' if passing is not None else 'no (--run-tests)'}"
    )
    print(f"  specs                        : {t['specs']}")
    print(f"  ...with an AC heading        : {t['specs_with_ac_heading']}")
    print(f"  ...carrying **AC-N** ids     : {t['specs_with_ac_ids']}")
    print(f"  ...prose only, awaiting ids  : {t['specs_awaiting_retrofit']}")
    print(f"  criteria declared            : {t['criteria_declared']}")
    print(f"  ...with a module annotation  : {t['criteria_annotated']}")
    print(f"  test markers found           : {t['markers_found']}")
    print(f"  markers naming no criterion  : {t['markers_without_criterion']}")
    print(f"  ticked but unproven          : {t['criteria_claimed_but_unproven']}")
    print(f"  criteria written as Gherkin  : {t['gherkin_criteria']}")
    print(f"  scenarios carrying no @AC tag: {t['scenarios_without_ac_tag']}")
    print(f"  gherkin blocks that fail parse: {t['gherkin_parse_errors']}")
    print(f"  'Implemented', contradicted  : {t['completion_claims_contradicted']}")
    print(f"  'Implemented', unverifiable  : {t['completion_claims_unverifiable']}")
    print(f"  specs implementing no ADR    : {t['specs_implementing_nothing']}")
    print(f"  taken ADRs with no spec      : {t['adrs_without_implementing_spec']}")
    print(f"  specs with no criteria at all: {t['specs_declaring_no_criteria']}")
    for rung in RUNGS:
        n = sum(1 for s in specs if s["criteria_total"] and s["tier"] == rung)
        print(f"  specs at tier {rung:<10}: {n}")
    try:
        written = args.out.relative_to(ROOT)
    except ValueError:  # --out may legitimately point outside the repo
        written = args.out
    print(f"\nwrote {written}")
    exit_code = 0
    if args.ratchet:
        print()
        exit_code = ratchet(t, measured=passing is not None, bank=args.bank)

    if args.mandate:
        print()
        exit_code = run_mandate(args.mandate, specs, adrs) or exit_code
    return exit_code


def run_mandate(base_rev: str, specs: list[dict[str, Any]], adrs: list[dict[str, Any]]) -> int:
    """Zero tolerance on the criteria this change created or newly claimed."""
    base = snapshot_at(base_rev)
    if base is None:
        print(
            f"FAIL: could not read the criteria corpus at {base_rev!r}.\n\n"
            "  On a shallow clone, fetch the base first (`fetch-depth: 0`).\n"
            "  Refusing rather than proceeding: an unreadable base makes every\n"
            "  criterion look new, which would demand the whole corpus be\n"
            "  retrofitted in one PR — a gate that fires on everything gets\n"
            "  turned off."
        )
        return 1

    head = {c["id"]: c["claimed"] for d in (*specs, *adrs) for c in _criteria_of(d)}
    touched = touched_since(base, head)

    exempt = {d["id"]: set(d.get("declared_unproven") or []) for d in (*specs, *adrs)}
    violations = mandate_violations([*specs, *adrs], touched, exempt)

    print(f"acceptance mandate (criteria touched since {base_rev}):")
    print(f"  criteria added or newly claimed: {len(touched)}")
    print(f"  unproven and not declared so   : {len(violations)}")
    if not violations:
        print("\nOK: every criterion this change declares is proven.")
        return 0

    print()
    for violation in violations:
        print(
            f"  {violation['id']}  rung={violation['rung']}  "
            f"module={violation['module']}  tests={violation['covered_by']}"
        )
    print(
        "\nFAIL: a criterion this change declares is not proven by it.\n\n"
        "  Legacy criteria are grandfathered on quality/ac-state-ceilings.json;\n"
        "  these are not legacy — this change created them, or ticked their box.\n"
        "  Reaching `reachable` needs an AC-N id, a module annotation the\n"
        "  reachability graph can get to, and a passing @pytest.mark.ac test.\n\n"
        "  To declare one deliberately unproven, put the reason in the document\n"
        "  where a reviewer will see it:\n\n"
        "      <!-- ac-state: unproven AC-3 - blocked on the durable store (#132) -->\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
