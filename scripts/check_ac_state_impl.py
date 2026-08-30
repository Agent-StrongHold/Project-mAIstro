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
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from fractions import Fraction
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
#: like incurring debt. So are the states that decide *not* to (`Denied`,
#: `Will Not Implement`, `Deferred`) and the ones that retire a decision
#: (`Superseded`, `Deprecated`, whose successors carry the debt instead).
#:
#: ADR-097 gives ADRs one taken intermediate state between `Accepted` and
#: `Implemented`: `Fully Specced`. `In Progress` and `Tests Passing` are SPEC
#: states, not ADR states, so including them here would silently make this
#: governance metric accept lifecycle vocabulary the kind-specific linter rejects.
DECISION_TAKEN = (
    "Accepted",
    "Fully Specced",
    "Implemented",
)
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

    That invariant is why #267 was fixed by adding
    `packages/hive-conductor/backend/tests` to `testpaths` rather than by giving
    this function a hand-written list of its own. The Conductor suite really is
    executed -- ci.yml has a step for it -- so the honest repair was to make the
    configuration say so. See the comment beside `testpaths` in `pyproject.toml`
    for why the e2e tree stays out, and `passing_ac_ids` for why each root now
    runs as its own session.
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
    """A module is reachable unless it, or an ancestor package, is baselined.

    Membership in the *unreachable* set is the whole test, which is why an
    anchor naming nothing at all used to clear this rung: a typo, a bare name,
    a script filename and an invented string are all absent from that set, and
    absence reads as reachable. `unresolvable_anchors` closes that separately,
    because "this anchor is wrong" and "this module is unwired" are different
    findings and only the second belongs here (#631).
    """
    parts = module.split(".")
    return not any(".".join(parts[: i + 1]) in unreachable for i in range(len(parts)))


def load_module_universe() -> set[str]:
    """Every module identity the reachability graph knows, or empty if it cannot.

    Loaded from `check-reachability.py` rather than re-derived, so the names an
    anchor is checked against are the same names the rung is judged on. A
    second walk of the tree would be a second definition of "module", and the
    two would drift exactly where it mattered.
    """
    script = ROOT / "scripts" / "check-reachability.py"
    if not script.is_file():  # pragma: no cover - the tree always has it
        return set()
    spec = importlib.util.spec_from_file_location("_reachability_for_anchors", script)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return set()
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return set(module._collect_modules())


def _completion_claims(
    specs: list[dict[str, Any]], adrs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Documents their own artefacts refute, and those that cannot yet say.

    Two different things, and merging them would be the same error this script
    exists to catch. A document at tier `none`/`unmeasured` has no criteria to
    measure yet -- its `Implemented` is unverified, not refuted. One that *has*
    measurable criteria and still falls short of `reachable` is contradicted.
    """

    def row(d: dict[str, Any], kind: str) -> dict[str, Any]:
        return {
            "id": d["id"],
            "kind": kind,
            "declared_status": d["declared_status"],
            "measured_tier": d["tier"],
            "file": d.get("file"),
        }

    claiming = [d for d in specs if d["declared_status"] in COMPLETION_CLAIMS]
    claiming += [d for d in adrs if d["declared_status"] in COMPLETION_CLAIMS]
    kinds = {id(d): "spec" for d in specs}
    kinds.update({id(d): "adr" for d in adrs})
    return (
        [row(d, kinds[id(d)]) for d in claiming if d["tier"] in RUNGS[:-1]],
        [row(d, kinds[id(d)]) for d in claiming if d["tier"] in ("none", "unmeasured")],
    )


def _report_unresolvable_anchors(specs: list[dict[str, Any]], adrs: list[dict[str, Any]]) -> bool:
    """Print every anchor that resolves to nothing. True when the gate must fail.

    Both document kinds, and `adrs` has no default on purpose. #631 built this
    gate and walked specs alone, which left 49 of 279 ADR anchors unchecked --
    graded on the same ladder, folded into the same floor, and read by nothing.
    A parameter that can be omitted is a parameter the next caller omits, which
    is the shape of the defect this closes (#653).
    """
    universe = load_module_universe()
    unresolvable = [("spec", *row) for row in unresolvable_anchors(specs, universe)]
    unresolvable += [("adr", *row) for row in unresolvable_anchors(adrs, universe)]
    if not unresolvable:
        return False
    print("FAIL: ac-modules anchors that name no module the reachability graph knows\n")
    for kind, file, ac_id, module in unresolvable:
        print(f"  {kind} {file}\n      {ac_id}: {module!r}")
    print(
        "\nAn anchor is a claim that something runs this criterion's code. A name the "
        "graph\nhas never heard of cannot support that claim, and used to clear the top "
        "rung anyway.\nUse the identity `scripts/check-reachability.py` reports -- dotted "
        "for packages\n(`maistro_rsi.local_loop`), scoped for apps and tooling "
        "(`@flat/hive-conductor/routes.settings`,\n`@tool/ac_state_notes`)."
    )
    return True


def unresolvable_anchors(
    documents: list[dict[str, Any]], universe: set[str]
) -> list[tuple[str, str, str]]:
    """Every `ac-modules` anchor that names no module the graph knows.

    Takes documents of either kind. Specs hold their criteria under `criteria`
    and ADRs under `own_detail`, so the walk goes through `_criteria_of` rather
    than naming one key -- the same divergence that cost the mandate three
    review findings, and here it cost the gate half its corpus (#653).

    An empty universe means the graph could not be loaded; reporting every
    anchor as unresolvable then would be a gate failing for its own reason
    rather than the corpus's, so it reports nothing instead.
    """
    if not universe:
        return []
    found: list[tuple[str, str, str]] = []
    for document in documents:
        for criterion in _criteria_of(document):
            module = criterion.get("module")
            # `None` is *unannotated*, which the rung already handles by
            # stopping at `passing`. An empty string is not that: it is an
            # anchor someone wrote and left blank, and the rung scores it
            # `reachable` like any other name absent from the unreachable set.
            # Testing truthiness instead of `is None` would let exactly that
            # one through -- the narrowest version of this whole defect.
            if module is None:
                continue
            if module not in universe:
                found.append((document["file"], criterion["id"], module))
    return found


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
    """`ac-modules` as AC id -> module identity, read the way YAML would read it.

    The quotes are stripped because they are syntax, not part of the name. A
    scoped identity has to carry them -- `@` cannot start a bare YAML scalar,
    so `AC-1: @tool/check-ac-state` does not parse at all -- and keeping them
    made the anchor `"'@tool/...'"`, which matches no module and is not what
    the document says.
    """
    m = AC_MODULES_RE.search(fm)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.strip().partition(":")
        out[key.strip()] = _unquote(value.strip())
    return out


def _unquote(value: str) -> str:
    """Drop one matched pair of surrounding quotes, as a YAML scalar would."""
    for quote in ("'", '"'):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1]
    return value


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
    """AC ids whose every claiming test passed, or None if a run never happened.

    None and `set()` mean different things and the caller must not conflate
    them: an empty set is "the suite ran and nothing passed", None is "we do not
    know". Reporting `passing` for an unrun suite is the failure this whole
    script exists to stop, one level up.

    **One session per root, not one session for all of them.** This used to be a
    single pytest invocation over every root at once, which worked only because
    the roots it happened to hold did not collide. They do now: `tests/` under
    `maistro-core` has no `__init__.py` while `tests/config/` does, so importlib
    mode puts `packages/maistro-core/tests` on `sys.path` and the top-level name
    `config` binds to that test package -- after which hive-conductor's
    `settings_defaults.py` does `from config import get_settings` and gets
    somebody else's module. 29 collection errors, the session interrupted, and
    every criterion in the repository reported unmeasured (#267).

    The rest of this repository already learned this. `ci.yml` gives every
    package its own pytest step, and `quality.yml` says why in as many words:
    an earlier single combined invocation "broke an unrelated maistro-rsi test
    (structlog's `capture_logs()` picks up stale global config when another
    package's tests configure structlog first)". This gate was the last place
    still assuming one session could hold them all.

    Isolation also makes the failure mode local. A root that cannot run poisons
    only its own outcome -- and, because a partial map read as "these criteria
    are not passing" would be a fabrication, it still takes the whole
    measurement down to None rather than reporting the rest as fact.
    """
    roots = [r for r in test_roots if r.exists()]
    if not roots:
        return None
    passing: set[str] = set()
    for root in roots:
        outcome = _passing_in_root(root)
        if outcome is None:
            return None
        passing |= outcome
    return passing


def _passing_in_root(root: Path) -> set[str] | None:
    """One root's passing AC ids, or None if that session did not complete."""
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
            str(root),
        ]
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=1800, cwd=ROOT, env=env
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        # 5 = nothing collected, which per-root is ordinary rather than
        # suspicious: most roots carry no `ac` markers at all, and deselecting
        # every test in one is not a failed measurement. It was unreachable
        # while this ran as a single session over every root at once.
        if proc.returncode == 5:
            return set()
        # 0 = all passed, 1 = some failed. Anything else (2 interrupted,
        # 3 internal error, 4 usage error) means the session did not run to
        # completion, and a partial outcome map read as "these criteria are not
        # passing" would be a fabrication.
        if proc.returncode not in (0, 1) or not out.is_file():
            sys.stderr.write(
                f"pytest exited {proc.returncode} for {root}; the passing rung is unmeasured.\n"
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


# ─── design coverage: how much of the decided design is proven (#166) ─────────
#
# Every other counter in this file measures debt — things that are wrong,
# recorded so they cannot increase. None of them measures *distance*: how much
# of the design the ADRs describe is implemented and proven. Without that,
# "every green PR moves us closer to the designed future state" is an
# aspiration CI cannot check, because there is no number that would have to go
# up. Traceability plus non-regression is necessary and is not progress — a PR
# that changes nothing satisfies both.
#
# ADR-082226-ff3c decides the shape, and the choice that matters is the
# denominator. Measured over the criteria that *exist*, the corpus reads 30.5%;
# measured over the decisions that have been *taken*, 3.96%. The gap is 76 of 99
# taken ADRs that declare no acceptance criteria anywhere. The first number lets
# a decision with nothing written vanish from its own denominator, and is
# gameable in the wrong direction — deleting an unproven criterion raises it.

#: Decimal places kept on the banked percentage.
#:
#: This is a float in a file of integers, so it needs a stated resolution rather
#: than exact equality on a binary fraction. The bound to clear is the smallest
#: move one criterion can make: proving a single criterion of the *largest*
#: decision, spread over the count of decisions, i.e. 100/(decisions * criteria
#: in the biggest one). Measured on today's corpus that is 100/(99 * 46) =
#: 0.0220 percentage points. Four places resolves 0.0001 — 200x finer — and
#: stays finer until the product of those two counts passes a million, so no
#: real change to a single criterion can round away into a no-op.
COVERAGE_PRECISION = 4


def design_coverage(
    specs: list[dict[str, Any]], adrs: list[dict[str, Any]]
) -> tuple[float, list[dict[str, Any]]]:
    """Mean, over taken decisions, of the fraction of their criteria at ``reachable``.

    Decision-weighted per ADR-082226-ff3c: one ADR is one unit of design however
    verbosely it was written, and one that declares no criteria contributes 0
    rather than dropping out of the denominator. ``Proposed`` is excluded — a
    decision not yet taken cannot be owed an implementation, and counting it
    would make writing an idea down look like incurring debt.

    ``reachable`` and not ``passing`` is the bar: a passing test whose module the
    import graph cannot reach proves the test runs, not that the system does.

    The sum is over ``Fraction`` and rounds once at the end, so the value is a
    property of the corpus rather than of summation order. To be clear about
    what that buys: measured against naive float accumulation the difference is
    about 4e-16, twelve orders of magnitude below the 1e-4 the floor compares,
    and no divergence appears at that precision over 200k randomised corpora.
    It is insurance against a later precision increase, not a bug being fixed
    here — worth the two lines it costs, and not worth claiming more for.
    """
    by_spec = {s["id"]: s for s in specs}
    rows: list[dict[str, Any]] = []
    for adr in adrs:
        if adr["declared_status"] not in DECISION_TAKEN:
            continue
        rungs = [c["rung"] for c in adr["own_detail"]]
        # dict.fromkeys, not the raw list: a spec whose `implements:` names one
        # ADR twice appears twice among that ADR's children, and would weight
        # its own criteria double inside the fraction.
        for spec_id in dict.fromkeys(adr["specs"]):
            spec = by_spec.get(spec_id)
            if spec is not None:
                rungs.extend(c["rung"] for c in spec["criteria"])
        proven = sum(1 for rung in rungs if rung == "reachable")
        rows.append(
            {
                "id": adr["id"],
                "declared_status": adr["declared_status"],
                "criteria": len(rungs),
                "reachable": proven,
                "fraction": Fraction(proven, len(rungs)) if rungs else Fraction(0),
            }
        )
    if not rows:
        return 0.0, rows
    mean = sum((row["fraction"] for row in rows), Fraction(0)) / len(rows)
    return round(float(mean) * 100, COVERAGE_PRECISION), rows


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


# ─── the chain in the *absent* direction, as one definition (#164) ────────────
#
# The three absence counters were computed inline in `main` and nowhere else,
# which made them a report. Turning them into a per-change mandate needs the
# same question asked of a *past* revision, where nothing can be imported and no
# test can be run — so the populations move here, behind one text-only
# derivation that both sides call.
#
# One derivation, not two, is the load-bearing part. A fact derived one way for
# head and another way for base can differ for reasons that have nothing to do
# with the change, and every such difference would read as a violation this PR
# introduced. So `main` gives up its inline copies and asks the same function.


@dataclass(frozen=True)
class ChainFacts:
    """One document's answers to the three absence questions.

    Text-only, for the same reason `_criteria_in` is: this runs against
    `git show <base>:<path>`, where there is no working tree to import from.
    """

    id: str
    kind: str
    file: str
    status: str
    implements: tuple[str, ...]
    has_criteria: bool
    has_ac_heading: bool
    non_measurable: bool


def chain_facts(path: str, text: str) -> ChainFacts | None:
    """`text` as a chain participant, or None when it is not one.

    The corpus filter is the same one `_spec_files` and `collect_adrs` apply —
    `kind: spec` anywhere under `docs/specs`, and a top-level `docs/adr/ADR-*.md`
    — because a document counted on one side of the comparison and not the other
    is a spurious violation waiting to happen.
    """
    fm = _frontmatter(text)
    parts = Path(path).parts
    if parts[:2] == ("docs", "specs") and KIND_RE.search(fm):
        kind = "spec"
    elif len(parts) == 3 and parts[:2] == ("docs", "adr") and parts[2].startswith("ADR-"):
        kind = "adr"
    else:
        return None
    doc_id = (ID_RE.search(fm) or [None, Path(path).stem])[1]
    return ChainFacts(
        id=doc_id,
        kind=kind,
        file=path,
        status=(STATUS_RE.search(fm) or [None, "?"])[1],
        implements=tuple(adr_refs(_list_field(fm, IMPLEMENTS_RE))),
        # `_criteria_in` is section-scoped bullets plus tagged scenarios, which
        # is exactly what `collect_specs` counts as a spec's criteria and what
        # `collect_adrs` counts as an ADR's own — one rule, both kinds.
        has_criteria=bool(_criteria_in(text, doc_id)),
        has_ac_heading=bool(AC_HEADING_RE.search(text)),
        non_measurable=declares_non_measurable(text),
    )


#: The counters that answer "is the link absent?", as opposed to "is it broken?".
ABSENCE_COUNTERS = (
    "specs_implementing_nothing",
    "adrs_without_implementing_spec",
    "specs_declaring_no_criteria",
)


def absent_links(facts: dict[str, ChainFacts]) -> dict[str, set[str]]:
    """The three absent-link populations over a whole corpus, keyed by counter.

    A whole corpus rather than a document at a time, because one of the three is
    not a property of any single document: whether an ADR is implemented depends
    on every spec's `implements`, so deleting a reference in one file can put a
    different file's decision into the population.
    """
    implemented = {ref for f in facts.values() if f.kind == "spec" for ref in f.implements}
    specs = {i: f for i, f in facts.items() if f.kind == "spec"}
    return {
        # `implements: []` is valid front matter, so a spec naming no ADR was
        # clean. That made "specs map to ADRs" mean "specs do not *mis*-map".
        "specs_implementing_nothing": {i for i, f in specs.items() if not f.implements},
        # Owed once the decision is taken. Carrying its own criteria counts:
        # ADR-063..066 hold 147 scenarios written before the spec split, and
        # calling those uncovered would report measured work as missing.
        "adrs_without_implementing_spec": {
            i
            for i, f in facts.items()
            if f.kind == "adr"
            and f.status in DECISION_TAKEN
            and i not in implemented
            and not f.has_criteria
        },
        # Split from `specs_awaiting_retrofit` deliberately. That counter holds
        # documents with an acceptance heading and no ids yet — "criteria not
        # written". These have neither, which is a different statement, and
        # merging them let "there are none" hide inside "there are none *yet*".
        "specs_declaring_no_criteria": {
            i
            for i, f in specs.items()
            if not f.has_criteria and not f.has_ac_heading and not f.non_measurable
        },
    }


def new_absent_links(base: dict[str, set[str]], head: dict[str, set[str]]) -> dict[str, list[str]]:
    """Per counter, the documents this change put into the population.

    Set difference on document ids, not on counts, and that is the entire point
    of #164's reopening. The aggregate ceiling is blind to a PR that adds one
    orphan spec while a legacy one is fixed: the count is unchanged, so the
    ratchet is satisfied while a new absent link entered the repository. Ids
    cannot net off against each other.
    """
    return {name: sorted(head[name] - base[name]) for name in ABSENCE_COUNTERS}


def absence_rows(
    populations: dict[str, set[str]],
    facts: dict[str, ChainFacts],
    counter: str,
    *,
    with_status: bool = False,
) -> list[dict[str, Any]]:
    """One absent-link population as report rows, ordered by file.

    By file rather than by id so the report keeps the order it had when each
    population was a comprehension over a sorted directory walk — a reordered
    artefact is a diff a reviewer has to read past to find the real change.
    """
    rows = []
    for doc_id in sorted(populations[counter], key=lambda i: facts[i].file):
        row: dict[str, Any] = {"id": doc_id, "file": facts[doc_id].file}
        if with_status:
            row["declared_status"] = facts[doc_id].status
        rows.append(row)
    return rows


def working_tree_facts() -> dict[str, ChainFacts]:
    """The same chain facts, read from the checkout rather than from a revision.

    Same `chain_facts` as the base side, deliberately, rather than adapting the
    richer structures `collect_specs`/`collect_adrs` build. Those carry the
    ladder and the module graph, neither of which a past revision can be asked
    about; deriving head from them and base from text would make the two sides
    answerable to different code.
    """
    facts: dict[str, ChainFacts] = {}
    for directory in (SPEC_DIR, ADR_DIR):
        for path in sorted(directory.rglob("*.md")):
            rel = str(path.relative_to(ROOT))
            found = chain_facts(rel, path.read_text(encoding="utf-8"))
            if found is not None:
                facts[found.id] = found
    return facts


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


def corpus_at(rev: str) -> tuple[dict[str, bool], dict[str, ChainFacts]] | None:
    """The whole corpus as of `rev`: every criterion, and every chain fact.

    One walk for both. The mandate asks two questions of the same revision and
    each answer costs a `git show` per document, so splitting them would double
    ~200 subprocesses to re-read files that were already open.

    None rather than an empty result, and the caller refuses rather than
    proceeding: an unreadable base makes *every* criterion look new and *every*
    absent link look introduced, which would turn the mandate from a gate on
    this PR into a demand that the whole corpus be retrofitted at once. A gate
    that fires on everything gets turned off, which is worse than one that stops
    and says why.
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

    criteria: dict[str, bool] = {}
    facts: dict[str, ChainFacts] = {}
    for path in listing.stdout.split():
        if not path.endswith(".md"):
            continue
        text = _file_at(rev, path)
        if text is None:
            continue
        fm = _frontmatter(text)
        doc_id = (ID_RE.search(fm) or [None, Path(path).stem])[1]
        criteria.update(_criteria_in(text, doc_id))
        found = chain_facts(path, text)
        if found is not None:
            facts[found.id] = found
    return criteria, facts


def snapshot_at(rev: str) -> dict[str, bool] | None:
    """Every criterion in the corpus as of `rev`. None when `rev` is unreadable."""
    corpus = corpus_at(rev)
    return None if corpus is None else corpus[0]


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


#: Same by-path load as `check-wiring-reads`, and for the same reason: the tests
#: load this script with `spec_from_file_location`, which puts nothing on
#: `sys.path` for a sibling to be found on.
_NOTES_SOURCE = Path(__file__).resolve().parent / "ac_state_notes.py"


def _load_notes_module() -> Any:
    spec = importlib.util.spec_from_file_location("_ac_state_notes", _NOTES_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_NOTES_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


ac_state_notes = _load_notes_module()
RatchetProvenanceError = ac_state_notes.provenance().RatchetProvenanceError

# The bound is folded from per-branch notes now, not read off one shared line
# (#585, ADR-082926-25a2). `quality/ac-state-ceilings.json` is retired; its
# final content lives on as `quality/ac-state-notes/_baseline.json`.
#
# The counter names and their directions are unchanged and live in
# `ac_state_notes`, which is what folds them. Re-exported here because this
# script's own help text and comparison read them.
RATCHETED = ac_state_notes.RATCHETED
FLOORED = ac_state_notes.FLOORED


def _report_movement(regressions: list[str], improvements: list[str], bound: Any) -> None:
    """Print what moved, and what to do about it.

    Split out of `ratchet` for the same reason as `_exact_target`: the function's
    job is to decide, and two multi-paragraph remedies inline made the decision
    hard to read — and pushed it past the complexity ceiling once the fold
    gained its own refusals.
    """
    if regressions:
        print("FAIL: the repository moved away from its recorded state\n")
        for line in regressions:
            print(f"  - {line}")
        print(
            "\nA ceiling exceeded: either prove the claim (add an **AC-N** id and a "
            "@pytest.mark.ac test) or correct the document's status. The ceiling does not "
            "move up.\nA floor undercut: design coverage fell, so a decision that was "
            "proven no longer is — restore the evidence, or bank the fall with --bank and "
            "justify it in the diff (retiring an ADR and accepting a new one both do this "
            "legitimately; see ADR-082226-ff3c)."
        )
        print(f"\nThe bound was {bound.describe()}.")
    if improvements:
        print(
            "FAIL: unbanked improvement — the recorded bound holds slack a regression could spend\n"
        )
        for line in improvements:
            print(f"  - {line}")
        print(
            f"\nThe bound was {bound.describe()}.\n"
            "Bank it: python scripts/check-ac-state.py --run-tests --ratchet --bank\n"
            "That writes only quality/ac-state-notes/<your-branch>.json, so it "
            "cannot conflict with another branch doing the same (#585)."
        )


def _report_stale_grants(stale: list[str]) -> None:
    if not stale:
        return
    print("\nFAIL: authorized floor(s) the notes have overtaken\n")
    for line in stale:
        print(f"  - {line}")
    print(
        "\nA grant that lowers nothing is not harmless. It sits in "
        "quality/ratchet-authorizations.json\nunder someone's name and reason, ready to "
        "absorb the next real fall as though that had\nbeen the one reviewed."
    )


def _report_superseded_grants(superseded: dict[str, list[str]]) -> None:
    if not superseded:
        return
    print("\nFAIL: authorized floor(s) independent landings have superseded\n")
    for counter, names in sorted(superseded.items()):
        print(f"  - {counter}: {len(names)} note(s) already clear it on their own:")
        for name in names:
            print(f"      {name}")
    print(
        "\nNone of these needed the grant, and none of them are the note it "
        "corrects -- each\nlanded through its own review, independently of "
        "this one and of each other.\nA correction this durably overtaken is "
        "no longer what holds the floor up; prune it\nfrom "
        "quality/ratchet-authorizations.json."
    )


def _report_removed_grants(removed: list[str]) -> None:
    if not removed:
        return
    print("\nFAIL: authorized floor(s) spent by this change and deleted by it\n")
    for line in removed:
        print(f"  - {line}")
    print(
        "\nThe grant is the record. Permission is read at the base, so removing "
        "it here\nstill lets the fall land -- and leaves the next run looking at a "
        "number nobody\ncan account for. Prune a grant once the notes have "
        "overtaken it, not before."
    )


def _exact_target(
    bound: Any, measured: bool, floors: dict[str, float]
) -> tuple[dict[str, float], str | None]:
    """The counters the exact comparison is read against, or why it cannot be.

    Extracted from `ratchet` rather than inlined: the fold has two ways to
    refuse, and putting them beside the comparison pushed `ratchet` past the
    complexity ceiling — which is the gate noticing that "compare" had quietly
    become "compare, and also decide whether comparing is allowed".

    A branch with no notes at all falls back to the base fold, which is the old
    exact-equality behaviour, along with the message telling it to bank.
    """
    try:
        banked = _banked()
    except (ac_state_notes.AcStateNoteError, RatchetProvenanceError) as exc:
        # `bounds()` reads the notes as of the base and already succeeded, so a
        # failure here is a note in *this tree* that will not parse — including
        # `_baseline.json`, which the old one-note rule skipped and the fold
        # does not. Read outside a handler it exited with a traceback instead of
        # the gate's own diagnostic (Codex, #609).
        return {}, f"FAIL: the banked AC-state fold could not be read: {exc}"
    mismatch = _worktree_mode_mismatch(banked, measured)
    if mismatch is not None:
        return {}, mismatch
    # The worktree fold as the grants correct it, then raised by the notes this
    # change writes. The `min` alone was the cap (#691): the fold carries the
    # merged notes a grant exists to disown, so it re-asserts the number the
    # grant just declared wrong and the `min` pulls the target back there
    # however the candidate banks. Raising by the fresh notes is what lets
    # banking move it again.
    #
    # The fold stays in, rather than being replaced by the base bound, because
    # it is the only thing that sees an inherited note this change *weakened*
    # (Codex, #692). Rewriting the bound-holding note from 20 to 15 while still
    # measuring 20 leaves the base comparison happy -- it reads the measurement,
    # not the notes -- and would silently lower the floor for everyone after the
    # merge. Against the fold the target drops to 15 and the run says so.
    #
    # With no grant `_lowered` is the identity and the fresh notes are a subset
    # of the fold, so this is exactly develop's behaviour.
    target = _lowered(banked.counters if banked.counters else bound.counters, floors)
    for counter, value in _fresh_note_bound().items():
        target[counter] = (
            value
            if counter not in target
            else max(target[counter], value)
            if ac_state_notes.direction_of(counter) == "max"
            else min(target[counter], value)
        )
    return target, None


def _worktree_mode_mismatch(banked: Any, run_tests: bool) -> str | None:
    """The same refusal, for the notes the *worktree* fold reads.

    `_mode_mismatch` validates the notes `load_notes()` returns from the merge
    base. The fold folds every note in the candidate tree, and a stacked branch
    carries notes the base has never seen — so a note banked without
    `--run-tests` could be folded into a `--run-tests` target, mixing two
    measurement modes this gate treats as incomparable everywhere else, in the
    direction that can only loosen the bound (Codex, #609).

    Checked here rather than inside `banked_bound` because the mode is the
    *run's* property, not the notes': the same notes are correct for one
    invocation and wrong for the other.
    """
    mismatched = [name for name, mode in banked.modes.items() if mode != run_tests]
    if not mismatched:
        return None
    want = "with" if not run_tests else "without"
    return (
        f"FAIL: {len(mismatched)} note(s) in this tree were banked {want} --run-tests: "
        f"{', '.join(sorted(mismatched))}. Re-run in that mode. The passing rung is "
        "unreachable without it, so the counters are not comparable and folding "
        "across both would be a bound nobody measured."
    )


def _slack_this_run_enforces(improvements: list[str]) -> list[str]:
    """The unbanked-improvement findings this run is entitled to fail on.

    The slack rule asks the *author* to record the improvement they made. In a
    merge group the thing measured is the merged result, and the extra coverage
    came from whichever PR merged first -- which banked it in its own note.
    Demanding it here asks the candidate to have banked a number that did not
    exist when it banked, so every PR behind the first in a batch was dequeued
    for a reason nobody could have prevented (#620).

    The regression half is untouched and still runs here: it is judged against
    the base-resolved fold, which nothing in the worktree can reach, and it is
    the half the queue exists to enforce.

    Extracted rather than inlined because a branch here pushed `ratchet` past
    the complexity ceiling -- the linter noticing that "compare" had acquired a
    second question, "and is this run allowed to fail on that?".
    """
    if not improvements or not in_merge_group():
        return improvements
    print(
        "merge group: not enforcing the unbanked-improvement half. The tree "
        "measured above its own notes because the base moved, not because this "
        "change failed to bank (#620). Still enforced here: every counter "
        "against the base-resolved fold, which nothing in the worktree can "
        "reach.\n  " + "\n  ".join(improvements)
    )
    return []


def in_merge_group() -> bool:
    """Whether this run is judging a merge group rather than a pull request.

    Read from the event name, not the ref: `gh-readonly-queue/...` is a
    convention GitHub could change, while `merge_group` is the fact the workflow
    was triggered by. A local run and an ordinary pull-request run both answer
    False, so nothing about review changes.
    """
    return os.environ.get("GITHUB_EVENT_NAME") == "merge_group"


def _mode_mismatch(run_tests: bool) -> str | None:
    """The refusal message for a wrong-mode ratchet, checked before measuring.

    This runs first because the report is written to disk before the ratchet
    would otherwise reach its own mode check — so a wrong-mode invocation used to
    overwrite the report with an unmeasured payload and *then* complain. Failing
    before any measurement leaves the artefact untouched.

    Every note has to agree with the run's mode, not just one: without
    `--run-tests` no criterion reaches the `passing` rung, so counters banked in
    the two modes are not comparable and a fold across both would be a bound
    nobody measured.
    """
    try:
        notes, _origin, _sha = ac_state_notes.load_notes()
    except (ac_state_notes.AcStateNoteError, RatchetProvenanceError) as exc:
        return f"FAIL: the AC-state notes could not be read: {exc}"
    mismatched = [note.name for note in notes if note.measured_with_tests != run_tests]
    if not mismatched:
        return None
    want = "with" if not run_tests else "without"
    return (
        f"FAIL: {len(mismatched)} note(s) were banked {want} --run-tests: "
        f"{', '.join(mismatched)}. Re-run in that mode. The passing rung is "
        "unreachable without it, so the counters are not comparable. Nothing was "
        "measured or written."
    )


def _bank(totals: dict[str, Any], measured: bool) -> int:
    """Write this branch's own note. No shared line, so no conflict (#585)."""
    path = ac_state_notes.write_note(totals, measured_with_tests=measured)
    try:
        shown = path.relative_to(ROOT)
    except ValueError:  # a test may point the notes directory outside the repo
        shown = path
    print(f"banked {shown}; review the diff before committing")
    print(
        "This file is yours alone — another branch banking its own note will not conflict with it."
    )
    return 0


#: Grants live under this key in quality/ratchet-authorizations.json, one per
#: floored counter, spelled `<counter>@<value>` — `design_coverage@26.4762`.
AUTHORIZATION_RATCHET = "ac-state"


def authorized_floors(base: str | None) -> tuple[dict[str, float], dict[str, str]]:
    """Floors a landed, reviewed grant has lowered, and the reasons given.

    The fold takes `max` across notes, and notes outlive the branches that
    wrote them, so a merged branch's note holds a floor no later change can
    lower (#662). That is right for a regression and wrong for a *correction*:
    when a measurement is found to have been over-counting, the recorded
    number was never true, and `--bank` cannot say so because it writes only
    this branch's own note.

    A grant says it. `load_authorizations` reads grants **at the base**, so the
    same commit cannot both lower the floor and permit itself to — the property
    the whole mechanism exists for — and the value is in the key, so a grant
    licenses one specific fall rather than an open season.
    """
    prov = ac_state_notes.provenance()
    # The same tree and the same revision the notes were folded from.
    # `load_authorizations` defaults both to the helper's own ROOT, which is
    # the real repository -- so a caller working against another tree would
    # resolve the base in one repo and the grants in another, and the tests
    # that stand the ratchet up on a synthetic history would ask the real one
    # for a SHA it has never seen.
    root = ac_state_notes.ROOT
    path = root / "quality" / "ratchet-authorizations.json"
    # The helper reads `(loaded.get(ratchet) or {})`, so a section that is a
    # list comes back as "no grants" rather than as a refusal -- silently
    # ignoring a file somebody wrote and expects to be enforced. The shape is
    # checked here, at the base revision the permission is read from.
    _require_grant_section(prov.resolve_baseline(path, base=base, root=root).loads(default={}))
    try:
        granted = prov.load_authorizations(
            AUTHORIZATION_RATCHET,
            path=path,
            base=base,
            root=root,
        )
    except (AttributeError, TypeError) as exc:
        # `"ac-state": []`, or an entry whose record is a scalar, reaches the
        # helper's `.items()` / `.get()` as an AttributeError. Translated here
        # rather than fixed there: the helper is shared with the wiring ratchet,
        # and tightening it would change that gate's behaviour in a change that
        # is not about it. A malformed grant must refuse, and a traceback is not
        # a refusal -- it is a crash, and the two read differently in a log.
        raise RatchetProvenanceError(
            "ratchet-authorizations.json: the "
            f"{AUTHORIZATION_RATCHET!r} section is malformed -- it must be an "
            "object mapping `<counter>@<value>` to a record with an owner, an "
            f"issue and a reason ({type(exc).__name__}: {exc})"
        ) from exc
    return _grant_floors(granted)


def _grant_floors(granted: dict[str, str]) -> tuple[dict[str, float], dict[str, str]]:
    """The floor each validated entry names, and why.

    Shared by both revisions (#685). The candidate side used to read the same
    file with a different, looser rule -- keys only, and a `ValueError`
    suppressed -- so the two could reach opposite conclusions about one file:
    the candidate passed and the base, reading it next run, refused.
    """
    floors: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for entry, reason in granted.items():
        counter, _, raw = entry.partition("@")
        if counter not in FLOORED:
            raise RatchetProvenanceError(
                f"ratchet-authorizations.json: {AUTHORIZATION_RATCHET}:{entry} names "
                f"{counter!r}, which is not a floored counter. Only a floor can be "
                "lowered by a grant; a debt ceiling is raised by banking it."
            )
        try:
            floors[counter] = float(raw)
        except ValueError as exc:
            raise RatchetProvenanceError(
                f"ratchet-authorizations.json: {AUTHORIZATION_RATCHET}:{entry} does not "
                "name the value it lowers the floor to. Spell it "
                "`<counter>@<value>`, so the grant permits one fall and not the next."
            ) from exc
        reasons[counter] = reason
    return floors, reasons


def _validated_grant_records(section: object) -> dict[str, str]:
    """Every record in a grants section, checked the way the base checks them.

    `load_authorizations` does this for a *revision*; the candidate's file is
    already in hand, and there is no revision to resolve it from. The rule has
    to be the same rule, though, which is why the message is the same one: a
    record the candidate accepts and the base refuses is a file that passes its
    own run and breaks every run after it (#685).
    """
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise RatchetProvenanceError(
            f"ratchet-authorizations.json: the {AUTHORIZATION_RATCHET!r} section in the "
            f"working tree is a {type(section).__name__}, not an object of grants"
        )
    granted: dict[str, str] = {}
    for entry, record in section.items():
        if not isinstance(record, dict):
            raise RatchetProvenanceError(
                f"ratchet-authorizations.json: authorization for "
                f"{AUTHORIZATION_RATCHET}:{entry} is a {type(record).__name__}, not a "
                "record with an owner, an issue and a reason. Keeping the key while "
                "emptying the record is not keeping the grant."
            )
        missing = [k for k in ("owner", "issue", "reason") if not str(record.get(k, "")).strip()]
        if missing:
            raise RatchetProvenanceError(
                f"ratchet-authorizations.json: authorization for "
                f"{AUTHORIZATION_RATCHET}:{entry} is missing {', '.join(missing)}. "
                "An unexplained floor-raise is not an authorization."
            )
        granted[str(entry)] = f"{record['issue']} -- {record['owner']}: {record['reason']}"
    return granted


def _require_grant_section(payload: object) -> None:
    """Refuse a grants file whose own section is the wrong shape.

    Absent is "no grants" and passes. Present but not an object is a malformed
    file, and the two must not answer the same -- a file somebody wrote and
    expects to be enforced should not be read as an empty one.
    """
    if payload is None:
        return
    if not isinstance(payload, dict):
        raise RatchetProvenanceError(
            f"ratchet-authorizations.json is malformed -- it must be a JSON object, "
            f"not {type(payload).__name__}"
        )
    section = payload.get(AUTHORIZATION_RATCHET)
    if section is None or isinstance(section, dict):
        return
    raise RatchetProvenanceError(
        f"ratchet-authorizations.json: the {AUTHORIZATION_RATCHET!r} section is "
        f"malformed -- it must be an object mapping `<counter>@<value>` to a "
        f"record, not {type(section).__name__}"
    )


def candidate_grants() -> dict[str, float]:
    """The floors this change's *own* authorization file names, if any.

    Permission is a base question and stays one: `authorized_floors` answers
    "may this fall land". This answers a different one -- "does the file in
    front of me still say so" -- and the two must not be read from the same
    revision (#662 review).

    Reading stale-ness from the base made pruning impossible: once the notes
    folded to a grant's value, every later run failed on a spent grant that the
    base still carried, including the run whose only change was to remove it.
    Reading permission from the candidate would reopen self-approval. Each
    question gets the revision it is actually about.
    """
    path = ac_state_notes.ROOT / "quality" / "ratchet-authorizations.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        section = payload.get(AUTHORIZATION_RATCHET) if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        raise RatchetProvenanceError(
            f"ratchet-authorizations.json: the {AUTHORIZATION_RATCHET!r} section in "
            f"the working tree could not be read ({type(exc).__name__}: {exc})"
        ) from exc
    # One shape check for both revisions, so the candidate and the base cannot
    # come to different conclusions about the same file.
    _require_grant_section(payload)

    # The same per-entry rule the base applies, not a looser one (#685). Reading
    # keys and suppressing the `ValueError` let a change keep a binding key,
    # replace its record with `{}` or a scalar, and pass: `_removed_binding_grants`
    # saw the key, the value parsed, and nothing looked inside. After the merge
    # the base *does* look, so every later run failed on a file only another
    # grant could repair. A malformed key was dropped in silence by the same
    # loop -- written, expected to be enforced, ignored without a word.
    floors, _reasons = _grant_floors(_validated_grant_records(section))
    return floors


def _removed_binding_grants(
    counters: dict[str, float],
    floors: dict[str, float],
    present: dict[str, float],
    superseded: dict[str, list[str]],
) -> list[str]:
    """Grants this change is spending that it also deletes (#662 review).

    Permission comes from the base, so a candidate could consume a landed grant
    and remove it in the same commit: the fall lands, and the owner, issue and
    reason that justified it are gone from the file afterwards. The next run
    then sees the old folded floor with nothing authorizing it and fails, with
    no record of why the number moved.

    A grant that is *binding* -- one actually lowering the comparison -- has to
    survive the change that uses it. A spent one may go; that is the pruning
    `_stale_grants` asks for.

    `superseded` is the other pruning `_superseded_grants` asks for, and this
    refusal must not undo it (SPEC-083026-fcc9): a grant several independent
    already-landed notes have grown past is exactly the case where nobody
    downstream needs the record "why the number moved" to point at this
    file any more -- those notes are that record, and they will keep
    existing, in git history, whether or not the grant does.
    """
    return [
        f"{counter}@{floor}: this change spends that authorization and removes it. "
        "A grant that is still lowering the floor has to stay, or the fall lands "
        "with no record of who permitted it"
        for counter, floor in sorted(floors.items())
        if counter in counters
        and counters[counter] > floor
        and present.get(counter) != floor
        and counter not in superseded
    ]


def _lowered(counters: dict[str, float], floors: dict[str, float]) -> dict[str, float]:
    """The folded bound with each authorized floor applied.

    `min`, not replacement: a grant may only *lower*. One that names a value
    the fold is already below has been overtaken and raises nothing — it is
    stale rather than binding, and `_stale_grants` says so.
    """
    lowered = dict(counters)
    for counter, floor in floors.items():
        if counter in lowered:
            lowered[counter] = min(lowered[counter], floor)
    return lowered


def _fresh_note_bound() -> dict[str, float]:
    """The bound the notes this change *adds or rewrites* jointly support.

    The worktree fold cannot be used whole (#691). It carries the merged notes
    a grant exists to disown, so it re-asserts the very number the grant just
    declared wrong, and `max` then pins the exact target there however the
    candidate banks. Splitting the fold puts each half under the rule that
    belongs to it: the inherited notes are what a grant corrects, and the notes
    this change writes are what "did you bank it?" asks about.

    A note counts as fresh when the base has none by that name, or has one
    saying something different. That keeps #609's stacking rule intact -- a
    parent's note is new relative to the base too, so a stacked branch is still
    judged against it and cannot regress below what its parent banked.
    """
    inherited, _, _ = ac_state_notes.load_notes()
    at_base = {note.name: note.counters for note in inherited}
    fresh = [
        note for note in ac_state_notes.worktree_notes() if at_base.get(note.name) != note.counters
    ]
    # Annotated because `ac_state_notes` is loaded by path at runtime, so every
    # attribute of it is `Any` and the declared return would be unchecked.
    folded: dict[str, float] = ac_state_notes.fold(fresh)
    return folded


def _stale_grants(counters: dict[str, float], floors: dict[str, float]) -> list[str]:
    """Grants the fold has overtaken, which must be pruned.

    The same rule every ledger here carries: a row that no longer does
    anything is slack the next regression would spend under someone else's
    reason. A grant is spent once the notes themselves fold to its value or
    below.
    """
    return [
        f"{counter}@{floor}: the folded floor is already {counters[counter]}, so this "
        "grant lowers nothing — prune it"
        for counter, floor in sorted(floors.items())
        if counter in counters and counters[counter] <= floor
    ]


#: How many notes must, each on its own, already clear a grant's floor before
#: the grant counts as superseded rather than merely exceeded (SPEC-083026-fcc9).
#: One note above the floor is the ordinary "unbanked improvement" every PR
#: hits and clears with `--bank` -- it says nothing about the grant's own
#: correction. A single contributor can never manufacture more than one note
#: at a time, so three *independently landed* ones agreeing the floor is
#: behind the repository is the same trust a merge already represents,
#: taken three times over -- deliberately higher than a bare majority, since
#: a threshold this ratchet gets wrong in either direction is expensive:
#: too low lets a short run of related PRs retire a correction that still
#: matters, too high leaves a genuinely dead grant blocking merges longer
#: than it has to.
MIN_SUPERSEDING_NOTES = 3


def _superseded_grants(notes: list[Any], floors: dict[str, float]) -> dict[str, list[str]]:
    """Grants that independent, already-landed work has grown past and stayed
    past, mapped to the note names that did it.

    `_stale_grants` is `SPEC-082926-6f49`'s answer to one direction: the fold
    fell back to the grant, so lowering it does nothing. It has no answer for
    the other direction, and that spec says so in its own consequences --
    "a grant... is permanent for as long as those notes are... which is
    honest, because the record it corrects is still there." That was written
    against a grant tied to one specific corrected note; it did not anticipate
    a floored counter that only ever grows, corrected via a rare fall and then
    climbing again on entirely unrelated work that keeps landing above the
    grant forever. `_removed_binding_grants` refuses to let such a grant go
    (`counters[counter] > floor` is true of every future base once this
    happens, regardless of what the removing change touches), so
    `_stale_grants` never fires and no PR, however constructed, can prune it
    under the original design. Verified against develop on 2026-08-30: a
    grant at 27.8791 from #631/#662, a base fold of 31.7134, and nineteen
    already-merged notes independently above the grant -- none of them the
    note the grant corrects, none of them written to spend or influence this
    check, each landed through the same review this repository already
    trusts.

    The count is deliberately per-note, not "the fold exceeds the floor":
    `max`-folding already means one high note is enough to raise the fold, and
    that one note could be wrong, or unrelated to what the grant corrects, or
    -- worst case -- written specifically to game this check. Multiple
    independent notes, each clearing the floor without any help from the
    others or from a grant, is a claim collusion cannot manufacture as
    cheaply: it costs as many separately-reviewed merges as the threshold
    names.
    """
    supersede_by: dict[str, list[str]] = {counter: [] for counter in floors}
    for note in notes:
        for counter, floor in floors.items():
            value = note.counters.get(counter)
            if value is not None and value > floor:
                supersede_by[counter].append(note.name)
    return {
        counter: sorted(names)
        for counter, names in supersede_by.items()
        if len(names) >= MIN_SUPERSEDING_NOTES
    }


def _compare(ceilings: dict[str, Any], totals: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Split the counters into "worse than recorded" and "better than recorded".

    Both lists fail the gate; they differ in what the reviewer has to do about
    it. The two loops are the same shape with the inequality reversed, kept
    apart rather than folded behind a sign because reading `actual > allowed`
    and having to remember which counters that means is exactly how a
    higher-is-better counter gets silently ratcheted the wrong way.
    """
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
    for name in FLOORED:
        required = ceilings.get(name)
        actual = totals[name]
        if required is None:
            regressions.append(f"{name}: no floor recorded (measured {actual})")
        elif actual < required:
            regressions.append(f"{name}: {actual} falls below the floor of {required}")
        elif actual > required:
            improvements.append(f"{name}: {actual}, floor still says {required}")
    return regressions, improvements


def _banked() -> Any:
    """What the notes in this tree jointly claim, for the "did you bank it?" half.

    A fold rather than one note: a stacked branch carries its parent's note as
    well as its own and both are new relative to the base, so "which one is the
    candidate's" has no answer there — see `ac_state_notes.banked_bound` (#609).
    """
    return ac_state_notes.banked_bound()


def _show_bounds() -> int:
    """Print the folded bound. The single line it replaces was readable at a
    glance, and a fold is not — so it gets a command instead of a file."""
    try:
        bound = ac_state_notes.bounds()
    except (ac_state_notes.AcStateNoteError, RatchetProvenanceError) as exc:
        print(f"FAIL: the AC-state bound could not be established: {exc}")
        return 1
    if bound.empty:
        print(bound.describe())
        return 1
    print(bound.describe())
    for name in (*RATCHETED, *FLOORED):
        if name in bound.counters:
            arrow = "floor" if name in FLOORED else "ceiling"
            print(f"  {name:<34} {arrow:>7} {bound.counters[name]}")
    return 0


def _compact() -> int:
    """Fold the notes into the baseline and drop the ones that say nothing new.

    Maintenance, run by a person, never by the gate: a gate that prunes its own
    evidence is a gate that can lose it. Reads the worktree rather than the base
    — this rewrites files, so it must see the ones it is about to rewrite.
    """
    notes_dir = ac_state_notes.NOTES_DIR
    if not notes_dir.is_dir():
        print(f"nothing to compact: {notes_dir} does not exist")
        return 0
    paths = sorted(notes_dir.glob("*.json"))
    try:
        notes = [
            ac_state_notes.Note.parse(path.name, path.read_text(encoding="utf-8")) for path in paths
        ]
    except ac_state_notes.AcStateNoteError as exc:
        print(f"FAIL: {exc}")
        return 1
    if not notes:
        print(f"nothing to compact: no notes in {notes_dir}")
        return 0

    before = ac_state_notes.fold(notes)
    stale = {note.name for note in ac_state_notes.stale(notes)}
    baseline = notes_dir / ac_state_notes.BASELINE_NAME
    merged = ac_state_notes.Note(
        name=ac_state_notes.BASELINE_NAME,
        branch=None,
        measured_with_tests=all(note.measured_with_tests for note in notes),
        counters=before,
    )
    baseline.write_text(merged.as_json(), encoding="utf-8")
    for path in paths:
        if path.name in stale and path.name != ac_state_notes.BASELINE_NAME:
            path.unlink()

    after = ac_state_notes.fold(
        [
            ac_state_notes.Note.parse(path.name, path.read_text(encoding="utf-8"))
            for path in sorted(notes_dir.glob("*.json"))
        ]
    )
    if after != before:  # pragma: no cover - the fold is idempotent by construction
        print("FAIL: compaction changed the bound; nothing should have been dropped")
        return 1
    print(
        f"compacted {len(paths)} note(s) into {ac_state_notes.BASELINE_NAME}; "
        f"removed {len(stale - {ac_state_notes.BASELINE_NAME})} that contributed nothing"
    )
    return 0


def ratchet(totals: dict[str, Any], measured: bool, bank: bool) -> int:
    """Compare the measured state against its reviewed bounds, in both directions.

    Both directions fail. For the ten debt counters a rise is a regression: a
    document started claiming more than its artefacts support. A fall that has
    not been banked is slack — the same weakness a count ceiling always has,
    where one genuine improvement silently pays for a later regression. Banking
    is a reviewed edit to a small JSON file, so there is no reason to leave the
    margin sitting there.

    `design_coverage` runs the same mechanism with the inequality reversed: it
    is the one counter where higher is better, so its recorded number is a floor
    and a *fall* is what fails. The symmetry is deliberate — unbanked slack
    above the floor is the same weakness as unbanked slack below a ceiling.

    The comparison is refused across measurement modes. Without ``--run-tests``
    no criterion can reach the ``passing`` rung, so every claim above it reads as
    contradicted and the counters are not comparable with ones banked from a real
    run. Comparing them anyway would produce a gate that fails or passes
    according to how it was invoked.
    """
    if bank:
        return _bank(totals, measured)
    # The mode guard again, here and not only in `_mode_mismatch`. That one runs
    # before measuring so a wrong-mode invocation cannot overwrite the report;
    # this one is the comparison's own precondition, and `ratchet()` is called
    # directly by tests and by any future caller that skips `main`.
    mismatch = _mode_mismatch(measured)
    if mismatch is not None:
        print(mismatch)
        return 1
    try:
        bound = ac_state_notes.bounds()
    except (ac_state_notes.AcStateNoteError, RatchetProvenanceError) as exc:
        print(f"FAIL: the AC-state bound could not be established: {exc}")
        return 1
    if bound.empty:
        print(
            "FAIL: no AC-state notes at the base revision, so there is nothing to "
            "compare against.\nBank one: python scripts/check-ac-state.py "
            "--run-tests --ratchet --bank"
        )
        return 1

    # Two comparisons, because the two halves of this gate answer to different
    # oracles (#585).
    #
    # A **regression** is judged against the base-resolved fold, which the
    # candidate cannot write. That is #534's property: the thing being judged
    # does not supply the judge.
    #
    # **Slack** is judged against what this tree's notes jointly claim, because a
    # candidate that improves is *supposed* to be above the base fold — that is
    # what improving means — and comparing the improvement against the base
    # would make every genuine gain unpassable. What must not happen is banking
    # less than you measured, and that is `measured == the banked fold`.
    #
    # The banked fold rather than one note (#609): a stacked branch carries its
    # parent's note as well as its own, both new relative to the base, and the
    # rule that asked for exactly one made every stacked PR read as an unbanked
    # improvement. Folding the worktree cannot loosen anything — `max` for
    # coverage, `min` for debt — and the deletion this does not catch is caught
    # by `regressions`, which is folded at the base.
    #
    # A branch with no notes at all falls back to the base fold, which is the
    # old exact-equality behaviour, along with the message telling it to bank.
    #
    # A landed grant may lower a floor the fold cannot (#662). Read at the
    # base, like the fold itself, so the change being judged did not write its
    # own permission.
    # Two revisions, two questions. `floors` is permission and comes from the
    # base; `present` is bookkeeping about the file this change actually ships.
    # Reading stale-ness from the base made pruning impossible -- once the notes
    # folded to a grant's value, the run whose only change removed that grant
    # failed on the base's copy of it (#662 review). Both refuse the same way,
    # so both sit inside the same guard: a malformed file is a failed gate, not
    # a traceback, whichever revision it is malformed in.
    try:
        floors, reasons = authorized_floors(bound.base_sha)
        present = candidate_grants()
    except RatchetProvenanceError as exc:
        print(f"FAIL: {exc}")
        return 1
    stale = _stale_grants(bound.counters, present)
    # The notes at the same base `floors` and `bound` were already read from,
    # so a grant's supersession is judged against the same reviewed history
    # everything else here is (SPEC-083026-fcc9). Computed twice against two
    # sources for the same reason `stale`/`removed` split base from candidate:
    # `by_floor` answers the base question `_removed_binding_grants` asks
    # ("is the grant this change spends actually still needed"), `by_present`
    # answers the candidate one `_report_superseded_grants` asks ("is the
    # grant still sitting in this tree's own file after independent work has
    # already overtaken it"). They agree except in the one run that prunes --
    # where `by_present` is correctly empty, because there is nothing left in
    # the file to report on.
    notes, _origin, _base_sha = ac_state_notes.load_notes(base=bound.base_sha)
    superseded_by_floor = _superseded_grants(notes, floors)
    superseded_by_present = _superseded_grants(notes, present)
    removed = _removed_binding_grants(bound.counters, floors, present, superseded_by_floor)

    # A superseded grant is excluded from every comparison, not only from the
    # removal refusal (SPEC-083026-fcc9). `superseded_by_floor` is computed purely
    # from the base's own notes -- the same self-approval-proof source
    # `floors` itself comes from -- so honouring it here is not the candidate
    # loosening its own bound; it is recognising that the base's own history
    # has already, collectively, made the grant's original permission moot.
    # Without this, the one PR that prunes the grant would still measure
    # against the un-pruned floor for want of a fresh note of its own, and
    # every PR after it would need to re-litigate the same "unbanked
    # improvement" this whole mechanism exists to stop asking.
    effective_floors = {c: v for c, v in floors.items() if c not in superseded_by_floor}

    # The grants have to be in hand before the exact target can be composed:
    # the target *is* the inherited bound as they correct it (#691).
    target, refusal = _exact_target(bound, measured, effective_floors)
    if refusal is not None:
        print(refusal)
        return 1

    # Both comparisons, because both fold with `max`. The worktree fold carries
    # every note in the candidate tree -- including the merged branch's note
    # that holds the floor -- so a branch cannot *record* a lower value either:
    # its own note at 26.4762 beside a `_baseline.json` at 27.2395 folds to
    # 27.2395. Lowering only the regression floor would leave the exact
    # comparison demanding a number the correction has just disproved.
    #
    # The grant is therefore the record, not a step toward one, which is why it
    # carries the owner, the issue and the reason. What the exact comparison
    # still enforces is that the measurement *is* the authorized value: below it
    # is a regression the grant does not cover, above it is slack to bank.
    regressions, _ = _compare(_lowered(bound.counters, effective_floors), totals)
    # `target` already carries the grants and this tree's banked values (#691),
    # so it is compared as it stands. Lowering it again here is what turned a
    # grant into a cap: the exact target was pulled back to the granted value
    # every run, and banking -- the remedy the gate printed -- could not move it.
    exact_regressions, improvements = _compare(target, totals)
    regressions = list(dict.fromkeys([*regressions, *exact_regressions]))
    improvements = _slack_this_run_enforces(improvements)
    if regressions or improvements or stale or removed or superseded_by_present:
        _report_movement(regressions, improvements, bound)
        _report_stale_grants(stale)
        _report_superseded_grants(superseded_by_present)
        _report_removed_grants(removed)
        return 1
    for counter, floor in sorted(floors.items()):
        print(f"authorized floor: {counter} may fall to {floor} — {reasons[counter]}")
    print(
        f"OK: {len(RATCHETED)} debt counters sit exactly on their ceilings and "
        f"{len(FLOORED)} progress counter sits exactly on its floor "
        f"({bound.describe()})"
    )
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--ratchet",
        action="store_true",
        help="fail when any debt counter differs from the bound folded from quality/ac-state-notes/",
    )
    ap.add_argument(
        "--bank",
        action="store_true",
        help="write this branch's own note from this measurement (review the diff)",
    )
    ap.add_argument(
        "--show-bounds",
        action="store_true",
        help="print the folded bound and where it came from, then exit",
    )
    ap.add_argument(
        "--compact",
        action="store_true",
        help=(
            "fold quality/ac-state-notes/ into _baseline.json and drop the notes that "
            "contribute nothing (maintenance; never part of the gate)"
        ),
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

    if args.show_bounds:
        return _show_bounds()
    if args.compact:
        return _compact()

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

    # Before any counting: an anchor that names nothing cannot be judged, and
    # the old rung read it as `reachable` because it checked membership in the
    # *unreachable* set. Failing here rather than scoring it keeps the number
    # the ratchet floors on made of criteria something actually resolves (#631).
    if _report_unresolvable_anchors(specs, adrs):
        return 1

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
    contradicted, unverifiable = _completion_claims(specs, adrs)

    # ---- the chain checked in the *absent* direction (#164) --------------
    #
    # The registry refuses a reference that does not resolve, so every link that
    # exists is real. Nothing asked whether the link exists at all: `implements:
    # []` is valid front matter, so a spec could name no ADR and an ADR could be
    # implemented by nothing, and both were clean. That makes "specs map to
    # ADRs" mean "specs do not *mis*-map to ADRs" — a much weaker claim than the
    # one a green build is read as supporting.
    #
    # Computed by `absent_links` rather than here, so the report and the
    # per-change mandate cannot drift apart. The rows keep the shape they had.
    working = working_tree_facts()
    populations = absent_links(working)
    orphan_specs = absence_rows(populations, working, "specs_implementing_nothing")
    uncovered_adrs = absence_rows(
        populations, working, "adrs_without_implementing_spec", with_status=True
    )
    silent_specs = absence_rows(populations, working, "specs_declaring_no_criteria")

    # ---- distance rather than debt (#166) --------------------------------
    coverage, coverage_rows = design_coverage(specs, adrs)

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
            # The one counter here that is a percentage and the one that may
            # only rise. It is 0.0 without --run-tests, because `reachable`
            # sits above `passing` and nothing can reach it in an unmeasured
            # run; the ratchet refuses to compare across modes for that reason.
            "design_coverage": coverage,
        },
        "markers_without_criterion": orphans,
        "criteria_claimed_but_unproven": false_claims,
        "completion_claims_contradicted": contradicted,
        "completion_claims_unverifiable": unverifiable,
        "specs_implementing_nothing": orphan_specs,
        "adrs_without_implementing_spec": uncovered_adrs,
        "specs_declaring_no_criteria": silent_specs,
        "design_coverage": {
            "definition": (
                "mean over Accepted|Fully Specced|Implemented ADRs of the fraction of their criteria "
                "(own, plus every implementing spec's) at the `reachable` rung; an ADR "
                "declaring no criteria contributes 0 (ADR-082226-ff3c)"
            ),
            "percent": coverage,
            "decisions": len(coverage_rows),
            "decisions_scoring_zero": sum(1 for r in coverage_rows if not r["reachable"]),
            "decisions_declaring_no_criteria": sum(1 for r in coverage_rows if not r["criteria"]),
            "per_decision": [
                {
                    "id": r["id"],
                    "declared_status": r["declared_status"],
                    "criteria": r["criteria"],
                    "reachable": r["reachable"],
                    "percent": round(float(r["fraction"]) * 100, COVERAGE_PRECISION),
                }
                for r in coverage_rows
            ],
        },
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
    zero = sum(1 for r in coverage_rows if not r["reachable"])
    print(
        f"  design coverage              : {t['design_coverage']}% "
        f"over {len(coverage_rows)} taken decisions ({zero} at zero)"
    )
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
        exit_code = run_mandate(args.mandate, specs, adrs, working) or exit_code
    return exit_code


def run_mandate(
    base_rev: str,
    specs: list[dict[str, Any]],
    adrs: list[dict[str, Any]],
    working: dict[str, ChainFacts],
) -> int:
    """Zero tolerance on what this change created, in both mandates.

    One base read serves both. Both run even when the first fails: a PR should
    see everything it has to fix in one go, not discover the second gate after
    pushing a fix for the first.
    """
    corpus = corpus_at(base_rev)
    if corpus is None:
        print(
            f"FAIL: could not read the criteria corpus at {base_rev!r}.\n\n"
            "  On a shallow clone, fetch the base first (`fetch-depth: 0`).\n"
            "  Refusing rather than proceeding: an unreadable base makes every\n"
            "  criterion look new, which would demand the whole corpus be\n"
            "  retrofitted in one PR — a gate that fires on everything gets\n"
            "  turned off."
        )
        return 1
    base, base_facts = corpus
    criterion_code = _criterion_mandate(base_rev, base, specs, adrs)
    print()
    chain_code = chain_mandate(base_rev, base_facts, working)
    return criterion_code or chain_code


def _criterion_mandate(
    base_rev: str,
    base: dict[str, bool],
    specs: list[dict[str, Any]],
    adrs: list[dict[str, Any]],
) -> int:
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
        "  Legacy criteria are grandfathered on the folded quality/ac-state-notes/ bound;\n"
        "  these are not legacy — this change created them, or ticked their box.\n"
        "  Reaching `reachable` needs an AC-N id, a module annotation the\n"
        "  reachability graph can get to, and a passing @pytest.mark.ac test.\n\n"
        "  To declare one deliberately unproven, put the reason in the document\n"
        "  where a reviewer will see it:\n\n"
        "      <!-- ac-state: unproven AC-3 - blocked on the durable store (#132) -->\n"
    )
    return 1


#: What each absent link costs the reader, and what closing it takes. Keyed by
#: counter so the message a PR gets is about the link it actually broke rather
#: than a paragraph covering all three.
_ABSENCE_HELP = {
    "specs_implementing_nothing": (
        "a spec that names no ADR",
        "Name the decision it implements in `implements:`. If the spec predates\n"
        "  any ADR, the decision has to be written down before the spec can be\n"
        "  said to implement one — do not guess which ADR it belongs to.",
    ),
    "adrs_without_implementing_spec": (
        "a taken decision nothing implements",
        "Either write a spec whose `implements:` names it, give the ADR its own\n"
        "  **AC-N** criteria, or leave the ADR `Proposed` until it is owed an\n"
        "  implementation. Accepting a decision is the moment the debt starts.",
    ),
    "specs_declaring_no_criteria": (
        "a spec that states nothing checkable",
        "Add an `## Acceptance criteria` heading with **AC-N** ids, or declare\n"
        "  the document non-measurable *with a reason* where a reviewer sees it:\n\n"
        "      <!-- ac-state: non-measurable - a glossary, nothing to assert -->",
    ),
}


def chain_mandate(
    base_rev: str,
    base_facts: dict[str, ChainFacts],
    working: dict[str, ChainFacts],
) -> int:
    """Zero tolerance on absent links this change introduced (#164).

    The three counters above this are ratchets, and #164's acceptance asks for
    something a ratchet cannot give. A ceiling compares *totals*, so a change
    that adds one orphan spec while a legacy orphan is fixed leaves the count
    where it was and passes — the new absent link is paid for by an unrelated
    old one. Comparing the populations by document id instead means nothing nets
    off: a document that was not in the population at the base and is in it at
    the head is this change's, whatever else moved.
    """
    introduced = new_absent_links(absent_links(base_facts), absent_links(working))
    total = sum(len(v) for v in introduced.values())

    print(f"chain mandate (absent links introduced since {base_rev}):")
    for name in ABSENCE_COUNTERS:
        print(f"  {name:<32}: {len(introduced[name])}")
    if not total:
        print("\nOK: this change adds no spec, decision or criterion-less document to the chain.")
        return 0

    print()
    for name in ABSENCE_COUNTERS:
        for doc_id in introduced[name]:
            print(f"  {doc_id}  {working[doc_id].file}  ({_ABSENCE_HELP[name][0]})")
    print("\nFAIL: this change introduces an absent link in the ADR → spec → AC chain.\n")
    for name in ABSENCE_COUNTERS:
        if introduced[name]:
            print(f"  {name} — {_ABSENCE_HELP[name][0]}\n  {_ABSENCE_HELP[name][1]}\n")
    print(
        "  Pre-existing violations stay on the folded quality/ac-state-notes/ bound and fall\n"
        "  over time. These are not pre-existing: this change put them there, and\n"
        "  a ceiling comparing totals would have let an unrelated fix pay for them."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
