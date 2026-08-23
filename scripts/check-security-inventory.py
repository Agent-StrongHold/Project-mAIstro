#!/usr/bin/env python3
"""Gate: the checkable claims in ``SECURITY.md`` must match the code (#157).

``check-convergence-matrix.py`` states the principle this repository runs on:

    A planning surface that drifts is worse than none — it launders stale
    assumptions as current architecture. So the matrix is checked, not trusted.

``BACKLOG.md``, ``CONVERGENCE-MATRIX.md`` and ``SUITE-INVENTORY.md`` each have a
gate. ``SECURITY.md`` had none — no script and no workflow referenced it at all
— while making the strongest claims in the repository about what the code does.
This closes that asymmetry for the subset that is mechanically decidable.

What it catches
---------------
1. **A cited path that does not resolve.** Renames and moves, cheaply.
2. **A cited constant that does not exist, or whose value has drifted.** Every
   row of the resource-limits inventory is a claim about a real constant; this
   compares each against the code, in both directions. (The row count is
   printed on success rather than written here — a docstring stating "eighteen
   rows" is the same unmeasured-number failure this gate exists to catch.)
3. **A line-number citation in the inventory.** ``detector.py:27`` rots the
   moment anything above line 27 changes, silently and invisibly — two rows had
   already drifted that way. The constant name is stable, greppable, and is
   what a gate must key on anyway, so the citation style is itself enforced.
4. **A control claimed absent from a file that imports it**, anywhere in the
   document. Known Limitation 1 named three files as having no SSRF guard; all
   three had one, and the concrete consequence was that a second SSRF
   implementation got written because the first was documented as not existing.
   The same falsehood also sat in the Stronghold gaps table, which the first
   version of this check could not see.
6. **An inventory row that compares nothing.** A row naming a file but no symbol
   used to pass silently and still count toward the success line. Five of
   sixteen rows were in that state — the scan window, both learning-store
   defaults and both rate-limiter windows.
5. **A tagged count that does not match the code.** A revision of that same
   limitation — the one whose stated purpose was that this document carried
   unmeasured numbers — said "three of eleven outbound surfaces". It was three
   of twenty-five. A sentence tagged with a ``_COUNTED_CLAIMS`` marker has its
   **bold** figures recomputed from the tree, and deleting the marker fails too,
   so the cheapest way out is not to make the number unchecked.

What it deliberately does **not** catch
---------------------------------------
**Prose.** "Warden scans at every trust boundary" is not decidable by a script,
and pretending otherwise would be exactly the laundering this gate exists to
stop. A green run means the paths resolve, the numbers match, and no seeded
absence-claim is contradicted by an import. It does not mean the document is
true. Anyone reading a passing build as "the security prose is correct" has
misread it, which is why this paragraph is here rather than in a commit message.

Checks 4 and 5 are also **heuristic and seeded**, not general. They know about
the control classes in ``_ABSENCE_CLAIMS`` and the queries in
``_COUNTED_CLAIMS``, and nothing else; adding an entry is a deliberate act,
because a fuzzy match between an English noun phrase and a query over the tree
would produce failures nobody can act on.

Check 4 additionally scopes a negation to the **sentence** holding the citation
(with a bullet's bold lede folded into the sentence after it, which is how the
original falsehood was worded), and exonerates any citation whose sentence names
the control. Scoping it to the whole bullet was the first version, and it failed
on exactly the kind of writing this gate should reward: a limitation saying
"these files *are* guarded, what is missing is enforcement" contains both the
control name and the word "no", so every file it named was reported as a
contradiction — a failure fixable only by making the document vaguer.

Usage
-----
    python3 scripts/check-security-inventory.py
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECURITY_MD = ROOT / "SECURITY.md"

#: Where a bare citation like ``security/warden/detector.py`` is resolved from,
#: in order. SECURITY.md cites module-relative paths far more often than
#: repo-relative ones, so the package root comes first.
_SEARCH_ROOTS = (
    ROOT / "packages" / "maistro-core" / "src" / "maistro",
    ROOT / "packages" / "maistro-core" / "src",
    ROOT / "packages" / "maistro-core" / "tests",
    # Package-relative citations like `tests/sandbox/backends/test_fake.py`.
    ROOT / "packages" / "maistro-core",
    ROOT,
)

#: Files named in the document that are illustrative rather than real — a
#: hypothetical in a threat-model sentence, say. Empty on purpose: every entry
#: here is a claim the gate stops checking, so adding one should feel costly.
_EXEMPT_PATHS: frozenset[str] = frozenset()

#: Control classes for check 4, keyed by the token that identifies the claim in
#: the document. ``symbols`` are the names whose presence in a cited file
#: falsifies "this file has no such control".
_ABSENCE_CLAIMS: dict[str, tuple[str, ...]] = {
    "SSRF": ("validate_outbound_url", "_block_ssrf", "SSRFBlockedError", "net_guard"),
}

#: The names whose import means a module can open an outbound HTTP connection.
#: `maistro.http` is the pooled-client helper, so importing it counts the same
#: way importing `httpx` does; `HTTPClient` is the injected-client protocol,
#: which is how the skill marketplace and import pipeline fetch without naming a
#: concrete library.
_HTTP_CLIENT_IMPORTS = frozenset({"httpx", "aiohttp", "requests"})
_HTTP_CLIENT_PROTOCOL = "HTTPClient"
_POOLED_CLIENT_MODULE = "maistro.http"

#: Functions that, when *called*, are an SSRF guard. Definitions do not count —
#: the number the document states is how many call sites are protected, and a
#: guard nobody calls protects nothing. A module that calls one is also, by
#: construction, a module that fetches.
_SSRF_GUARD_FUNCTIONS = frozenset({"_block_ssrf", "validate_outbound_url"})

#: Where the counted claims below are measured from.
_CORE_SRC = ROOT / "packages" / "maistro-core" / "src" / "maistro"


def _core_modules() -> list[tuple[Path, ast.Module]]:
    """Every parseable module under maistro-core, with its AST."""
    parsed: list[tuple[Path, ast.Module]] = []
    for path in sorted(_CORE_SRC.rglob("*.py")):
        try:
            parsed.append((path, ast.parse(path.read_text(encoding="utf-8"))))
        except (OSError, SyntaxError):
            continue
    return parsed


def _fetches_and_guards(tree: ast.Module) -> tuple[bool, int]:
    """Whether a module can fetch outbound, and how many guard calls it makes."""
    fetches = False
    guard_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in _HTTP_CLIENT_IMPORTS for a in node.names):
                fetches = True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in _HTTP_CLIENT_IMPORTS or module == _POOLED_CLIENT_MODULE:
                fetches = True
            if any(a.name == _HTTP_CLIENT_PROTOCOL for a in node.names):
                fetches = True
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in _SSRF_GUARD_FUNCTIONS:
                guard_calls += 1
                fetches = True
    return fetches, guard_calls


def _outbound_fetch_census() -> list[tuple[Path, int]]:
    """Modules that can open an outbound connection, with their guard-call count.

    One census, so the two numbers the document states describe the same set.
    The first version counted "modules importing an HTTP client" against
    "SSRF guard call sites" and those sets turned out to be **disjoint**: the
    skill marketplace and import pipeline take an injected `HTTPClient` and the
    browser tool drives a browser, so none of the three guarded modules imported
    a client library at all. "29 modules … only 3 call sites" was therefore a
    ratio between a numerator and a denominator with no member in common — a
    figure that looked like coverage and measured nothing.
    """
    census: list[tuple[Path, int]] = []
    for path, tree in _core_modules():
        fetches, guard_calls = _fetches_and_guards(tree)
        if fetches:
            census.append((path, guard_calls))
    return census


def _outbound_fetch_modules() -> int:
    """Modules in the outbound-fetch census."""
    return len(_outbound_fetch_census())


def _guarded_fetch_modules() -> int:
    """Census members that call an SSRF guard."""
    return sum(1 for _path, guard_calls in _outbound_fetch_census() if guard_calls)


def _ssrf_guard_call_sites() -> int:
    """Calls to an SSRF guard, counted as calls rather than as text.

    A grep for the name matches the two ``def`` lines and every mention in a
    docstring, which is how a document ends up claiming more coverage than
    exists. Only ``ast.Call`` counts.
    """
    return sum(guard_calls for _path, guard_calls in _outbound_fetch_census())


#: Prose claims whose numbers come from the code instead of from whoever was
#: typing. Keyed by the marker that tags the sentence making the claim; the
#: value returns the **bold** numbers that sentence must contain, in order.
#:
#: This exists because of a specific failure: a revision of Known Limitation #1
#: whose entire purpose was that this document carried unmeasured numbers said
#: "three of eleven outbound surfaces". It was three of twenty-five. A number
#: written into a security document without counting reads exactly like a
#: counted one, so the only fix is to count it here.
#:
#: Seeded, like ``_ABSENCE_CLAIMS`` — no script can decide in general which
#: English noun phrase maps to which query over the tree.
_COUNTED_CLAIMS: dict[str, tuple[str, ...]] = {
    "measured-outbound-http": ("_outbound_fetch_modules", "_guarded_fetch_modules"),
}

#: A number the document offers up for checking. Bold is the marking, so a
#: reader can see which figures are machine-verified and which are prose.
_BOLD_NUMBER = re.compile(r"\*\*(\d[\d,]*)\*\*")

#: Words that turn a mention of a control into a claim that it is missing.
#: "not" is deliberately absent: "not currently exploitable" is a statement
#: about reachability, not about whether the control exists.
_NEGATION = re.compile(r"\bno\b|\bnone\b|\bnothing\b|\bneither\b", re.I)

#: A ``.py`` path as it appears in running text. Scrubbed out before check 4
#: looks for control symbols, so that citing ``tools/net_guard.py`` does not
#: read as naming the guard — the exoneration has to come from the prose.
_PATH_TEXT = re.compile(r"[A-Za-z_][A-Za-z0-9_/.-]*\.py")

#: Clause boundaries within a sentence. Exoneration is per-clause, because a
#: sentence can make two claims at once: "`marketplace.py` has no SSRF guard,
#: while `client.py` calls `validate_outbound_url`" is half true, and a
#: sentence-wide skip let the accurate half clear the false half before either
#: path was inspected.
_CLAUSE = re.compile(r"[,;—]|\s+--\s+")


#: Value cells that are prose rather than a number, so no constant can back
#: them. Each entry is a row this gate does **not** check, listed here so that
#: fact is visible rather than inferred from an empty match. Anything not on
#: this list must cite a symbol.
_PROSE_VALUE_CELLS: frozenset[str] = frozenset(
    {
        "N=5 failures / W=60s window / T=30s cooldown",
    }
)


@dataclass
class Findings:
    """Accumulated failures, grouped so the output reads as a checklist."""

    unresolved_paths: list[str] = field(default_factory=list)
    missing_constants: list[str] = field(default_factory=list)
    drifted_values: list[str] = field(default_factory=list)
    line_citations: list[str] = field(default_factory=list)
    contradicted_absences: list[str] = field(default_factory=list)
    drifted_counts: list[str] = field(default_factory=list)
    unchecked_rows: list[str] = field(default_factory=list)

    def total(self) -> int:
        return sum(
            len(bucket)
            for bucket in (
                self.unresolved_paths,
                self.missing_constants,
                self.drifted_values,
                self.line_citations,
                self.contradicted_absences,
                self.drifted_counts,
                self.unchecked_rows,
            )
        )


# ---------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------

#: A backticked citation: a ``.py`` path, optionally suffixed with either a
#: line number (``:87``, ``:87-92``) or a symbol name (``::BLOCKED_HOST_PATHS``,
#: or the older single-colon ``:BLOCKED_HOST_PATHS``). Only the line-number form
#: is captured, because only it is a finding — the symbol form is the spelling
#: this gate exists to encourage.
#:
#: Every character class here was widened after a citation slipped through it.
#: The line-only pattern skipped ``skills/parser.py::security_scan`` entirely;
#: excluding ``-`` from the path skipped every
#: ``packages/hive-conductor/...`` citation and the gate's own filename;
#: requiring two colons skipped ``security/patterns.py:BLOCKED_HOST_PATHS``.
#: Four cited paths were unchecked in the first version — silently, which is
#: the failure mode of a gate that decides its own scope by pattern.
_CITATION = re.compile(
    r"`([A-Za-z_][A-Za-z0-9_/.-]*\.py)"
    r"(?:(:\d+(?:-\d+)?)|::?[A-Za-z_][A-Za-z0-9_.]*)?"
    r"`"
)

#: Sentence-ish boundaries for check 4. A negation has to sit in the same
#: sentence as the citation it is about, so the bullet has to be cut up first.
#: Sub-bullets are boundaries too: a limitation written as a list makes one
#: claim per line. The ``[*_`]*`` is load-bearing — every limitation opens with
#: a bold summary sentence, so the first full stop in the section is followed by
#: ``**`` rather than a space, and a pattern without it never splits there.
_SENTENCE = re.compile(r"(?<=[.;:])[*_`]*\s+|\n\s*[-*]\s+")

#: The name a row cites, in backticks. Four forms appear in the inventory and
#: all four are real citations of a real binding:
#:
#:   ``MAX_LEARNINGS``            a module constant
#:   ``window_size = 50 * 1024``  a local, cited with its expression
#:   ``max_results: int = 10``    a parameter default, cited with its annotation
#:   ``self._window``             an attribute assignment
#:
#: The first version matched only the first form, so five of sixteen rows
#: extracted no name at all — and a row that checks nothing still counted
#: toward the success line. The scan window, the two learning-store defaults and
#: both rate-limiter windows were the values not being checked, which is most of
#: what a resource-limits inventory is for.
_CONSTANT = re.compile(
    r"`(?:self\.)?([A-Za-z_][A-Za-z0-9_]*)(?:\s*:[^=`]+)?(?:\s*=[^`]*)?`",
)


def _inventory_rows(text: str) -> list[tuple[str, str]]:
    """``(value_cell, citation_cell)`` for each resource-limits table row.

    Returns the two cells this gate can check and ignores the rest. A row whose
    citation names no ``.py`` file — the circuit-breaker row cites ADR-038 —
    is left to the caller to skip, rather than dropped here, so the skip is
    visible at the point that decides it.
    """
    rows: list[tuple[str, str]] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("## Resource-limits inventory"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].startswith("---") or cells[0] == "Limit":
            continue
        rows.append((cells[1], cells[2]))
    return rows


def _resolve(path_text: str) -> Path | None:
    """First existing file for a cited path, searching the roots in order.

    A citation with no ``/`` is prose shorthand — the surrounding sentence
    supplies the directory, as in "Warden (`detector.py`, `heuristics.py`)" —
    so a bare name is searched for recursively rather than required to sit at a
    root. Ambiguity is tolerated and absence is not: the failure this check
    exists for is a file that was renamed or deleted while the document went on
    naming it, and one match is enough to rule that out. Demanding a unique
    match would instead fail on every `client.py` in the tree, which is a
    documentation-style opinion rather than a drift signal.
    """
    for root in _SEARCH_ROOTS:
        candidate = root / path_text
        if candidate.is_file():
            return candidate
    if "/" not in path_text:
        for root in _SEARCH_ROOTS:
            match = next(root.rglob(path_text), None)
            if match is not None:
                return match
    return None


# ---------------------------------------------------------------------------
# Reading the code
# ---------------------------------------------------------------------------


def _literal(node: ast.expr) -> float | int | None:
    """Evaluate a constant expression, or ``None`` if it is not one.

    ``50 * 1024`` has to work: the Warden scan-window row cites exactly that,
    and refusing to fold it would make the most arithmetic-heavy row the one
    the gate cannot check.
    """
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left, right = _literal(node.left), _literal(node.right)
            if left is not None and right is not None:
                return left * right
        return None
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _bound_names(node: ast.AST) -> list[tuple[str, ast.expr]]:
    """``(name, value)`` for every numeric binding one AST node introduces.

    Three binding forms, because the inventory cites all three: module and
    class assignments (``MAX_LEARNINGS = 10000``), annotated assignments, and
    **function parameter defaults** (``max_results: int = 10``). A gate that
    only looked at module constants would silently skip the two
    ``memory/learnings/store.py`` rows that cite defaults.
    """
    if isinstance(node, ast.Assign):
        pairs: list[tuple[str, ast.expr]] = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                pairs.append((target.id, node.value))
            elif isinstance(target, ast.Attribute):
                # `self._window = 60` — the rate-limiter rows cite these.
                pairs.append((target.attr, node.value))
        return pairs

    if isinstance(node, ast.AnnAssign):
        if node.value is None:
            return []
        if isinstance(node.target, ast.Name):
            return [(node.target.id, node.value)]
        if isinstance(node.target, ast.Attribute):
            return [(node.target.attr, node.value)]
        return []

    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        args = node.args
        positional = args.posonlyargs + args.args
        defaulted = positional[len(positional) - len(args.defaults) :]
        pairs = [(arg.arg, default) for arg, default in zip(defaulted, args.defaults, strict=True)]
        pairs += [
            (arg.arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
            if default is not None
        ]
        return pairs

    return []


def _assigned_values(source: Path) -> dict[str, float | int]:
    """Every name in ``source`` bound to a numeric literal."""
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}

    found: dict[str, float | int] = {}
    for node in ast.walk(tree):
        for name, value_node in _bound_names(node):
            value = _literal(value_node)
            if value is not None:
                found.setdefault(name, value)
    return found


#: A cell whose numbers are stated in binary units, so the code's byte count is
#: the documented figure times 1024.
_BINARY_UNIT = re.compile(r"\bKi?B\b")


def _documented_numbers(value_cell: str) -> set[float]:
    """Every number the Value cell states, in the units that cell uses.

    ``50,000 chars`` and ``50000`` are the same claim; so are ``50 KiB`` and
    ``51200``. Both spellings are admitted rather than picking one, because the
    document is written for people and the code is not.

    The scaled form is admitted **only for a cell that says KiB**. Offering it
    unconditionally made every row accept two values, and the second one was
    occasionally a real regression: a ``0.5 s`` timeout that drifted to ``512``
    would have passed, because 0.5 * 1024 is 512. A gate that accepts a
    thousandfold change in a security timeout is worse than no gate on that row.
    """
    scaled = bool(_BINARY_UNIT.search(value_cell))
    numbers: set[float] = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", value_cell):
        try:
            number = float(raw.replace(",", ""))
        except ValueError:
            continue
        numbers.add(number)
        if scaled:
            numbers.add(number * 1024)
    return numbers


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_paths(text: str, findings: Findings) -> None:
    """Every cited ``.py`` path resolves to a real file."""
    for match in _CITATION.finditer(text):
        path_text = match.group(1)
        if path_text in _EXEMPT_PATHS:
            continue
        if _resolve(path_text) is None:
            findings.unresolved_paths.append(path_text)


def _row_names(citation_cell: str, citations: list[tuple[str, str]]) -> list[str]:
    """The symbol names a citation cell claims, minus the paths themselves."""
    paths = {path for path, _ in citations}
    return [
        name
        for name in _CONSTANT.findall(citation_cell)
        if not name.endswith(".py") and name not in paths
    ]


def _check_row(
    value_cell: str,
    citation_cell: str,
    citations: list[tuple[str, str]],
    findings: Findings,
) -> None:
    """Compare one inventory row's names and values against the code."""
    names = _row_names(citation_cell, citations)
    documented = _documented_numbers(value_cell)

    for path_text, line_suffix in citations:
        if line_suffix:
            findings.line_citations.append(f"{path_text}{line_suffix}")
        source = _resolve(path_text)
        if source is None:
            continue  # already reported by check_paths
        if not names and value_cell not in _PROSE_VALUE_CELLS:
            # A row that names a file but no symbol compares nothing, and the
            # first version still counted it toward the success line. Failing is
            # the only honest option: the alternative is a gate reporting
            # "16 inventory rows match the code" about rows it never looked at.
            findings.unchecked_rows.append(f"{path_text}: {value_cell!r} cites no symbol")
            continue

        assigned = _assigned_values(source)
        for name in names:
            if name not in assigned:
                # Only a miss if no *other* cited file defines it — a row may
                # cite several files and one constant.
                if any(
                    name in _assigned_values(other)
                    for other_path, _ in citations
                    if (other := _resolve(other_path)) is not None and other != source
                ):
                    continue
                findings.missing_constants.append(f"{path_text}: {name}")
                continue
            if documented and assigned[name] not in documented:
                findings.drifted_values.append(
                    f"{path_text}: {name} = {assigned[name]!r}, document says {value_cell!r}"
                )


def check_inventory(text: str, findings: Findings) -> None:
    """Inventory rows cite real constants, by name, with matching values."""
    for value_cell, citation_cell in _inventory_rows(text):
        citations = _CITATION.findall(citation_cell)
        if not citations:
            # A row citing an ADR rather than a file. Not a failure — the
            # circuit-breaker defaults live in a decision record — but it is
            # also not checked, and saying so beats implying coverage.
            continue
        _check_row(value_cell, citation_cell, citations, findings)


def _claim_sentences(item: str) -> list[str]:
    """Sentences of one limitation, with its bold lede folded into the first.

    A bullet opens with a bold title, and a title is not a sentence — it is the
    subject the sentence after it elaborates. The falsehood this gate exists for
    was worded exactly that way:

        **No SSRF blocklist for outbound HTTP.** Skills, connectors and the
        browser tool all make outbound HTTP calls (`a.py`, `b.py`, `c.py`).

    The negation is in the title and every citation is in the sentence after it,
    so treating the two as separate sentences misses the one case that has
    actually happened.
    """
    sentences = _SENTENCE.split(item)
    if len(sentences) > 1 and sentences[0].lstrip().startswith("**"):
        return [f"{sentences[0]} {sentences[1]}", *sentences[2:]]
    return sentences


def check_absence_claims(text: str, findings: Findings) -> None:
    """A control claimed absent from a file that imports it is a failure.

    Three scoping rules keep this from punishing precise writing, and all three
    were learned by getting it wrong:

    **The negation must share a sentence with the citation** (see
    ``_claim_sentences`` for what counts as one). Scoping it to a whole bullet
    was the first version: a limitation saying "these files *are* guarded, what
    is missing is enforcement" contains both the control name and the word "no",
    so every file it named came back as a contradiction — a failure that could
    only be fixed by making the document vaguer.

    **Naming the control next to the file exonerates it, per clause.**
    "the import pipeline calls ``marketplace.py::_block_ssrf``" is not a claim
    that the guard is absent. But the exoneration is clause-local: a
    sentence-wide skip meant "``marketplace.py`` has no SSRF guard, while
    ``client.py`` calls ``validate_outbound_url``" passed entirely, the accurate
    half clearing the false half. Path text is scrubbed before this match, so
    citing ``tools/net_guard.py`` is not mistaken for naming the guard.

    **The whole document is scanned, not one section.** The first version read
    only ``## Known Limitations`` — and the same commit that corrected the
    limitation left the identical falsehood standing in the Stronghold gaps
    table, where the gate could not see it. A gate that chooses its own scope by
    section heading is one heading away from being decorative.
    """
    for sentence in _document_sentences(text):
        for token, symbols in _ABSENCE_CLAIMS.items():
            if token not in sentence or not _NEGATION.search(sentence):
                continue
            for clause in _CLAUSE.split(sentence):
                prose = _PATH_TEXT.sub("", clause)
                if any(symbol in prose for symbol in symbols):
                    continue
                for path_text, _ in _CITATION.findall(clause):
                    source = _resolve(path_text)
                    if source is None:
                        continue
                    content = source.read_text(encoding="utf-8")
                    present = [symbol for symbol in symbols if symbol in content]
                    if present:
                        findings.contradicted_absences.append(
                            f"{path_text} is named as having no {token} control, "
                            f"but references {', '.join(sorted(present))}"
                        )


def _document_sentences(text: str) -> list[str]:
    """Every sentence in the document, with each limitation's lede folded in.

    Limitations are numbered bullets whose bold opening is a title rather than a
    sentence, so they are split with ``_claim_sentences``. Everything else —
    table rows, prose paragraphs — splits plainly: a table row is one line and
    makes its claim there.
    """
    sentences: list[str] = []
    limitations = text.split("## Known Limitations")
    body = limitations[1].split("\n## ")[0] if len(limitations) > 1 else ""
    for item in re.split(r"\n\d+\. ", body):
        sentences.extend(_claim_sentences(item))
    rest = text.replace(body, "") if body else text
    sentences.extend(_SENTENCE.split(rest))
    return sentences


def check_counted_claims(text: str, findings: Findings) -> None:
    """Every tagged count in the prose equals what the code actually has.

    A marker that appears nowhere in the document is itself a failure. Without
    that, deleting the marker would be the cheapest way to make a wrong number
    pass, which is the opposite of what a ratchet is for.
    """
    computed = {
        "_outbound_fetch_modules": _outbound_fetch_modules,
        "_guarded_fetch_modules": _guarded_fetch_modules,
        "_ssrf_guard_call_sites": _ssrf_guard_call_sites,
    }

    for marker, sources in _COUNTED_CLAIMS.items():
        tag = f"`{marker}`"
        if tag not in text:
            findings.drifted_counts.append(
                f"{marker}: the marker is gone from SECURITY.md, so the claim it tagged "
                f"is no longer checked — restore it or remove it from _COUNTED_CLAIMS"
            )
            continue

        expected = tuple(computed[name]() for name in sources)
        for sentence in _SENTENCE.split(text):
            if tag not in sentence:
                continue
            stated = tuple(int(n.replace(",", "")) for n in _BOLD_NUMBER.findall(sentence))
            if stated != expected:
                findings.drifted_counts.append(
                    f"{marker}: document states {stated or '()'}, code has {expected} "
                    f"({', '.join(sources)})"
                )


def main() -> int:
    if not SECURITY_MD.is_file():
        print(f"FAIL: {SECURITY_MD} does not exist", file=sys.stderr)
        return 1

    text = SECURITY_MD.read_text(encoding="utf-8")
    findings = Findings()
    check_paths(text, findings)
    check_inventory(text, findings)
    check_absence_claims(text, findings)
    check_counted_claims(text, findings)

    if findings.total() == 0:
        rows = len(_inventory_rows(text))
        cited = len({m.group(1) for m in _CITATION.finditer(text)})
        print(
            f"OK: {cited} cited paths resolve, {rows} inventory rows match the code, "
            f"{len(_COUNTED_CLAIMS)} counted claims recomputed. "
            "The rest of the prose is not checked — see this script's docstring."
        )
        return 0

    print("FAIL: SECURITY.md does not match the code it describes\n", file=sys.stderr)
    for title, bucket, remedy in (
        ("Cited paths that do not resolve", findings.unresolved_paths, "fix the path"),
        ("Cited constants that do not exist", findings.missing_constants, "fix the name"),
        ("Values that have drifted", findings.drifted_values, "fix the document or the code"),
        (
            "Line-number citations in the inventory",
            findings.line_citations,
            "cite the constant name instead — a line number rots silently",
        ),
        (
            "Controls claimed absent from a file that has them",
            findings.contradicted_absences,
            "correct the limitation",
        ),
        (
            "Counted claims that do not match the code",
            findings.drifted_counts,
            "restate the measured number",
        ),
        (
            "Inventory rows that check nothing",
            findings.unchecked_rows,
            "cite a named constant, or add the cell to _PROSE_VALUE_CELLS with a reason",
        ),
    ):
        if not bucket:
            continue
        print(f"  {title} ({remedy}):", file=sys.stderr)
        for entry in bucket:
            print(f"    - {entry}", file=sys.stderr)
        print(file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
