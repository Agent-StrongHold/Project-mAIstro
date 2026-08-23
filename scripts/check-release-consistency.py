#!/usr/bin/env python3
"""The version sites agree; this checks that the *release story* does too (#83).

`scripts/bump_version.py --check` already proves all 32 version sites carry the
same number, and `scripts/release_guard.py` refuses to publish a tag whose base
version disagrees with `VERSION`. Neither says anything about the relationship
between the version the repo *ships* and the release it is *working toward* —
and that relationship is where this repo was inconsistent:

    VERSION            0.9.0
    CHANGELOG          ## [1.0.0] - TBD
    git tags           (none)
    README             says nothing about either

Read together those are coherent — 0.9.0 developing toward a 1.0.0 that has not
been tagged, which is exactly what ADR-073126-c4e1 records. Read separately,
each one invites a different wrong conclusion, and nothing failed if one of them
drifted. A reader who finds `## [1.0.0]` and a `Complete` column in README has
been told the project released v1; it never has.

So this makes the relationship a checked fact rather than three documents that
happen to agree today:

1. `VERSION` is a plain `X.Y.Z`. The rc suffix lives only in tags (ADR §2), so
   it must not appear here.
2. `CHANGELOG.md` keeps an `## [Unreleased]` section.
3. `CHANGELOG.md` names exactly one **pending target** — a `## [X.Y.Z] - TBD`
   heading — because "which release are we writing notes for" must have one
   answer.
4. `VERSION <= target`. Shipping a version *above* the release you are still
   writing notes for means the notes are for a release that already happened
   under a different number.
5. Every **dated** heading is `<= VERSION`. You cannot have released a version
   higher than the one the packages carry.
6. `README.md` carries a release-status block naming both numbers, and both
   match the files. A status the reader can see is the point; one that can go
   stale silently is how the repo got here.

Promotion follows from 4 and from `release_guard`: a `vX.Y.Z` tag needs a
`## [X.Y.Z]` heading *and* `VERSION == X.Y.Z`, so cutting the target release
means `scripts/bump_version.py <target>` first, which moves all 32 sites at
once. Until then the two numbers differ on purpose, and this says so.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"

#: Plain `X.Y.Z`. No rc suffix: ADR-073126-c4e1 §2 puts candidate-ness in the
#: tag alone, so a suffix here would mean two places disagree about what a
#: release candidate is.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: `## [X.Y.Z] - <date-or-TBD>`. The link-reference form Keep a Changelog uses.
_HEADING_RE = re.compile(r"^##\s*\[(?P<version>\d+\.\d+\.\d+)\]\s*-\s*(?P<when>.+?)\s*$")

_UNRELEASED_RE = re.compile(r"^##\s*\[Unreleased\]\s*$", re.M)

#: What a heading says when its release has not happened.
PENDING_MARKER = "TBD"

#: The README block this checks. Fenced by markers rather than matched loosely,
#: so moving the prose cannot silently take the numbers out of scope.
README_BEGIN = "<!-- release-status:begin -->"
README_END = "<!-- release-status:end -->"


def _fail(message: str) -> None:
    print(f"::error::{message}")


def parse_version(raw: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(raw.strip())
    if match is None:
        return None
    return (int(match[1]), int(match[2]), int(match[3]))


def changelog_headings(text: str) -> list[tuple[str, str]]:
    """Every `## [X.Y.Z] - when` heading, in file order."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match is not None:
            out.append((match["version"], match["when"]))
    return out


def readme_block(text: str) -> str | None:
    """The fenced release-status block, or None when it is missing."""
    start = text.find(README_BEGIN)
    end = text.find(README_END)
    if start == -1 or end == -1 or end < start:
        return None
    return text[start + len(README_BEGIN) : end]


def check() -> list[str]:
    """Every inconsistency found. Empty means the release story holds."""
    problems: list[str] = []

    raw_version = VERSION_FILE.read_text().strip()
    version = parse_version(raw_version)
    if version is None:
        problems.append(
            f"VERSION is {raw_version!r}, which is not a plain X.Y.Z. Release candidates "
            "carry their suffix in the tag only (ADR-073126-c4e1 §2)."
        )
        return problems

    changelog = CHANGELOG.read_text()
    if _UNRELEASED_RE.search(changelog) is None:
        problems.append(
            "CHANGELOG.md has no '## [Unreleased]' section — there is nowhere to write "
            "the change you are making now."
        )

    headings = changelog_headings(changelog)
    pending = [(v, w) for v, w in headings if w.strip().upper() == PENDING_MARKER]
    dated = [(v, w) for v, w in headings if w.strip().upper() != PENDING_MARKER]

    if len(pending) != 1:
        found = ", ".join(f"[{v}] - {w}" for v, w in pending) or "none"
        problems.append(
            f"CHANGELOG.md must name exactly one pending release "
            f"('## [X.Y.Z] - {PENDING_MARKER}'); found {len(pending)}: {found}. "
            "'Which release are these notes for' needs one answer."
        )
        return problems

    target_raw = pending[0][0]
    target = parse_version(target_raw)
    if target is None:  # pragma: no cover - the heading regex already shaped it
        problems.append(f"CHANGELOG.md pending heading {target_raw!r} is not X.Y.Z")
        return problems

    if version > target:
        problems.append(
            f"VERSION ({raw_version}) is above the pending CHANGELOG release "
            f"({target_raw}). The notes describe a release the packages have already "
            "passed; bump the pending heading or correct VERSION."
        )

    for released, when in dated:
        released_version = parse_version(released)
        if released_version is not None and released_version > version:
            problems.append(
                f"CHANGELOG.md records [{released}] as released ({when}), which is above "
                f"VERSION ({raw_version}). A released version cannot exceed the one the "
                "packages carry."
            )

    problems.extend(_readme_problems(raw_version, target_raw))
    return problems


def _readme_problems(raw_version: str, target_raw: str) -> list[str]:
    """What the README's release-status block fails to say."""
    block = readme_block(README.read_text())
    if block is None:
        return [
            f"README.md has no release-status block. Add one between {README_BEGIN} and "
            f"{README_END} naming the current version and the release target, so a reader "
            "is not left to infer either from a feature table."
        ]
    problems: list[str] = []
    if raw_version not in block:
        problems.append(f"README.md's release-status block does not name VERSION ({raw_version}).")
    if target_raw not in block:
        problems.append(
            f"README.md's release-status block does not name the release target ({target_raw})."
        )
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        _fail(problem)
    if problems:
        print(
            f"\nFAIL: {len(problems)} release-consistency problem(s). "
            "VERSION, CHANGELOG.md and README.md have to tell one story."
        )
        return 1
    version = VERSION_FILE.read_text().strip()
    target = changelog_headings(CHANGELOG.read_text())
    pending = next(v for v, w in target if w.strip().upper() == PENDING_MARKER)
    if version == pending:
        print(f"ok: shipping {version}, and CHANGELOG's pending release is the same — taggable")
    else:
        print(f"ok: shipping {version}, working toward {pending} (not yet tagged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
