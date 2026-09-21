#!/usr/bin/env python3
"""Body status language may not contradict front matter (#387).

Front matter is canonical (#379): the lifecycle machine, the AC ladder and the
citation gate all read it. But a reader opening the document reads the *body*,
and ADR-046 spent three weeks saying two opposite things — front matter
`status: Superseded`, banner "Superseded by ADR-082126-f69c", and a body
paragraph arguing "The status therefore stays `Accepted`; it is deliberately
not moved to `Deferred` or `Superseded`." Different readers received different
authority answers, and no check could see it because nothing read the body's
status claims at all.

This gate reads the structured status markers a body can carry and requires
each to agree with the front matter:

1. `**Status:** X` lines — **retired entirely** (ADR-092126-a28a). Any such
   line in a body is a finding, in either the bare or the list-item spelling,
   whatever value it carries. This category used to check *agreement* with
   front matter; the 83 documents that carried a line are now cleared, and a
   line that agrees today is one that drifts tomorrow, so absence is what is
   enforced. The fix is always the same: delete the line.
2. `**Superseded by [ID](...)`` banners — when present on a Superseded
   document, every ID it names must be in the front matter's `superseded-by`
   (and the canonical spelling is the one to fix, because front matter feeds
   every tool).
3. Status-asserting prose on a Superseded document — "the status therefore
   stays/remains X", "status is deliberately not moved to X", "keep this ADR
   as the target ... status stays". Historical rationale is allowed (and
   preserved — that is #387's own requirement), but it must be framed as
   history: the marker patterns above match *unqualified* assertions. The
   pattern is anchored to the deciding verbs ("stays", "remains", "not moved
   to") rather than to any status word, so it catches the shape of the
   ADR-046 defect without guessing at vocabulary.

Run:  python scripts/check-adr-status-language.py
Bank: python scripts/check-adr-status-language.py --update

The baseline is per-identity for the legacy `**Status:**` lines written before
front matter was canonical: a new one fails, and a fixed one must shrink the
ledger in the same change. Category-2 and category-3 contradictions are *not*
baselined — they were zero at filing, so any occurrence is new.

**The ledger is empty and category 1 keeps it that way.** #387 banked 28
legacy lines it could see; the 19 list-form spec lines it could not see were
corrected when the category learned that spelling, the 28 were corrected
after, and ADR-092126-a28a then removed the remaining 83 lines outright. The
ratchet has nothing left to tolerate, and any finding this gate reports is
new by construction. Refilling the ledger is an expansion, which the
provenance adapter requires a landed grant for (#534) — delete the line
instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "maistro-registry" / "src"))

from maistro_registry.validator import validate_file  # noqa: E402

DOC_ROOTS = (ROOT / "docs" / "adr", ROOT / "docs" / "specs")
LEDGER = ROOT / "quality" / "adr-status-language-baseline.json"

#: A body status line, bare or as a Markdown list item (`- **Status:** X`).
#: Both spellings are retired (ADR-092126-a28a), so the *value* is never
#: parsed — only quoted back in the diagnostic. That is the simplification
#: retirement buys: while this category compared body against front matter it
#: needed the status vocabulary, multi-word values (`AC Defined` read as `AC`)
#: and case folding, and each of those was a defect in turn.
_BODY_STATUS_RE = re.compile(r"^(?:[-*+]\s+)?\*\*Status:\*\*.*$", re.M)

#: `**Superseded by [ADR-xxx](...)`` — the banner naming the replacement.
#: `^`-anchored per line, tolerating the blockquote and emphasis markup the
#: corpus actually wraps banners in (`> **Superseded by ...`). One capture
#: group: the superseding document's id.
_BANNER_RE = re.compile(r"^[>#\s]*\*{0,2}Superseded by \[([A-Za-z0-9-]+)\]", re.M)

#: An *unqualified* assertion that the status is staying put or was
#: deliberately not advanced. These are the ADR-046 defect's shape: prose that
#: overrides the front matter without saying on whose authority. Whitespace-
#: tolerant because the phrase wraps across lines in flowing prose. A *dated*
#: past statement ("the status was `Accepted` at that time") is history, not an
#: assertion of continuing status, and does not match — which is the line this
#: gate draws between preserved rationale and normative contradiction.
_STAYS_RE = re.compile(
    r"status\s+(?:therefore\s+|is\s+|was\s+)?(?:stays|stayed|remains|remained)"
    r"|deliberately\s+not\s+moved\s+to",
    re.I | re.M,
)

#: The `maistro-engine#` prefix the registry adds to cross-references; body
#: banners use the bare id.
_REF_PREFIX = "maistro-engine#"


@dataclass(frozen=True)
class StatusProblem:
    path: Path
    kind: str
    detail: str

    @property
    def identity(self) -> str:
        return f"{_display(self.path)} :: {self.kind}"

    def render(self) -> str:
        return f"{_display(self.path)}: {self.kind} — {self.detail}"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def audit(*, roots: tuple[Path, ...] | None = None) -> list[StatusProblem]:
    """Every structured status marker that contradicts its front matter."""
    problems: list[StatusProblem] = []
    for root in roots or DOC_ROOTS:
        for path in sorted(root.glob("*.md")):
            if path.name == "ADR-INDEX.md":
                continue
            problems.extend(_audit_file(path))
    return problems


def _audit_file(path: Path) -> list[StatusProblem]:
    result = validate_file(path)
    front_matter = result.front_matter
    if front_matter is None:
        return []  # missing front matter is the registry lint's failure, not ours
    body = _body_without_front_matter(path)
    problems: list[StatusProblem] = []

    for match in _BODY_STATUS_RE.finditer(body):
        problems.append(
            StatusProblem(
                path,
                "body-status-line",
                f"body carries {match[0].strip()!r}; body status lines are retired "
                f"(ADR-092126-a28a) — front matter ({front_matter.status.value}) is the "
                f"only status. Delete the line.",
            )
        )

    superseded_by = {ref.removeprefix(_REF_PREFIX) for ref in front_matter.superseded_by}
    for match in _BANNER_RE.finditer(body):
        if not superseded_by:
            problems.append(
                StatusProblem(
                    path,
                    "banner-without-superseded-by",
                    f"body banner names {match[1]!r} but front matter has no superseded-by",
                )
            )
        elif match[1] not in superseded_by:
            problems.append(
                StatusProblem(
                    path,
                    "banner-names-other-replacement",
                    f"body banner names {match[1]!r}, front matter superseded-by names "
                    f"{sorted(superseded_by)}",
                )
            )

    if front_matter.status.value == "Superseded" and _STAYS_RE.search(body):
        problems.append(
            StatusProblem(
                path,
                "body-asserts-status-stays",
                "a Superseded document may keep its historical rationale but must not assert "
                "an unqualified continuing status; frame the old decision as history instead",
            )
        )
    return problems


def _body_without_front_matter(path: Path) -> str:
    text = path.read_text()
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4 :] if end != -1 else text


def _load_baseline() -> frozenset[str]:
    if not LEDGER.exists():
        return frozenset()
    payload = json.loads(LEDGER.read_text())
    return frozenset(payload.get("known", []))


def _write_baseline(problems: list[StatusProblem]) -> None:
    payload = {
        "_comment": (
            "Legacy body '**Status:**' lines written before front matter was canonical (#379). "
            "Body status language is checked per-identity (#387): a new contradiction fails, "
            "and a fixed one must shrink this ledger in the same change. Banner and "
            "status-assertion contradictions are never baselined. This ledger is empty: the "
            "whole corpus now agrees with its front matter, so an entry here would be a "
            "tolerance nothing currently needs — fix the document instead."
        ),
        "known": sorted({p.identity for p in problems}),
        "details": {p.identity: p.detail for p in sorted(problems, key=lambda p: p.identity)},
    }
    LEDGER.write_text(json.dumps(payload, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="bank the current state")
    args = parser.parse_args(argv)

    problems = audit()

    if args.update:
        _write_baseline(problems)
        print(
            f"wrote {LEDGER.relative_to(ROOT) if LEDGER.is_relative_to(ROOT) else LEDGER} "
            f"with {len({p.identity for p in problems})} known contradiction(s)"
        )
        return 0

    known = _load_baseline()
    found = {p.identity for p in problems}
    new = sorted(found - known)
    stale = sorted(known - found)

    if new:
        print(f"FAIL: {len(new)} new body/front-matter status contradiction(s)\n")
        for identity in new:
            problem = next(p for p in problems if p.identity == identity)
            print(f"  {problem.render()}")
        print(
            "\nFront matter is canonical (#379). Make the body agree with it, or bank a "
            "reviewed legacy exception with --update if this predates that rule."
        )
        return 1

    if stale:
        print(f"FAIL: {len(stale)} baseline entr(y/ies) no longer found — prune them\n")
        for entry in stale:
            print(f"  {entry}")
        print(
            "\nA fixed contradiction must shrink the ledger in the same change; a stale entry "
            "silently absorbs the next regression at the same site."
        )
        return 1

    print(f"ok: {len(found)} baselined body-status contradiction(s), no new ones, none stale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
