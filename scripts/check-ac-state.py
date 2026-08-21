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


def collect_specs(
    markers: dict[str, list[str]],
    unreachable: set[str],
    passing: set[str] | None,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(SPEC_DIR.glob("SPEC-*.md")):
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
        for ref in spec["implements"]:
            by_adr.setdefault(ref.split("#")[-1], []).append(spec)

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
                        "module": c.module,
                        "covered_by": c.covered_by,
                        "rung": c.rung(unreachable),
                    }
                    for c in own_criteria
                ],
                "scenarios_without_ac_tag": own_untagged,
                "gherkin_parse_errors": own_errors,
                "tier": tier_of(inputs) if inputs else "unmeasured",
            }
        )
    return adrs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--run-tests",
        action="store_true",
        help="run the ac-marked tests to settle the passing rung (slow; off by default)",
    )
    args = ap.parse_args(argv)

    roots = configured_test_roots()
    markers = scan_markers(roots)
    unreachable = load_unreachable()
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
        },
        "markers_without_criterion": orphans,
        "criteria_claimed_but_unproven": false_claims,
        "completion_claims_contradicted": contradicted,
        "completion_claims_unverifiable": unverifiable,
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
    for rung in RUNGS:
        n = sum(1 for s in specs if s["criteria_total"] and s["tier"] == rung)
        print(f"  specs at tier {rung:<10}: {n}")
    print(f"\nwrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
