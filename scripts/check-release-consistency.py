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
3. Every version heading is unique. A version is pending *or* released, never
   both — and release notes are cut from whichever section comes first, so a
   duplicate silently decides what gets published.
4. Every heading's date field is either `TBD` or a real ISO calendar date.
   Release state is read from that field and nothing else, so `TBA` or
   `2026-99-99` must not be counted as evidence that a version shipped.
5. `CHANGELOG.md` names exactly one **pending target** — a `## [X.Y.Z] - TBD`
   heading — because "which release are we writing notes for" must have one
   answer.
6. `VERSION <= target`. Shipping a version *above* the release you are still
   writing notes for means the notes are for a release that already happened
   under a different number.
7. Every **dated** heading is `<= VERSION`. You cannot have released a version
   higher than the one the packages carry.
8. The highest `vX.Y.Z` tag in the repository is `<= VERSION` and has a dated
   heading of its own. Tags are the only record of what was actually published;
   without reading them the other seven checks describe intent, not fact.
9. `README.md` carries a release-status block naming all three numbers as
   **labelled fields**, and each matches its source: `Released` the tags,
   `Version in the tree` the `VERSION` file, `Next release target` the pending
   heading. A status the reader can see is the point; one that can go stale
   silently is how the repo got here.

Why the README fields are labelled rather than merely present
-------------------------------------------------------------
The first version of this gate asked whether each number appeared *anywhere* in
the block. That is unsound exactly when it matters: promoting the target makes
`VERSION` and the target the same number, so a README still naming the old
current version passes on the strength of the target's occurrence — and the
target check passes on that same occurrence. Both halves are satisfied by the
stale state the gate exists to reject. Labels cannot alias each other.

The `Released` field is the one a publish leaves behind, so after a release the
next CI run fails until the README is updated. That is deliberate: the previous
design let the block claim "nothing has been released" forever, with nothing
able to notice. `--releasing vX.Y.Z` excludes the tag whose own release run is
asking, because at tag time the tag exists but the commit it points at
necessarily predates it.

Promotion follows from 4 and from `release_guard`: a `vX.Y.Z` tag needs a
`## [X.Y.Z]` heading *and* `VERSION == X.Y.Z`, so cutting the target release
means `scripts/bump_version.py <target>` first, which moves all 32 sites at
once. Until then the two numbers differ on purpose, and this says so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
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

#: What a heading says when its release has not happened. Everything else in
#: that field must be a real ISO date — see `classify_headings`.
PENDING_MARKER = "TBD"

#: A *final* release tag. `vX.Y.Z-rcN` is deliberately excluded: a candidate is
#: not a release, and `release_guard.py` already treats the two differently
#: (ADR-073126-c4e1 §6). Kept in the same shape as `release_guard.TAG_RE` so the
#: two agree on what a tag is.
_RELEASE_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")

#: What the README block must say, as labelled fields rather than loose prose.
#:
#: An earlier version checked `str(VERSION) in block`. That is unsound whenever
#: the two numbers coincide: promoting the target makes `VERSION` and the target
#: equal, so a README still claiming the *old* current version passes on the
#: strength of the target's occurrence, and the target check passes on the same
#: occurrence. Both halves of the gate are then satisfied by exactly the stale
#: state it exists to reject. Labelled fields cannot alias each other.
_README_FIELDS = {
    "released": re.compile(r"\*\*Released:\*\*\s*(?P<value>none|\d+\.\d+\.\d+)", re.I),
    "current": re.compile(r"\*\*Version in the tree:\*\*\s*(?P<value>\d+\.\d+\.\d+)"),
    "target": re.compile(r"\*\*Next release target:\*\*\s*(?P<value>\d+\.\d+\.\d+)"),
}

#: What the block says for `Released` when nothing has been.
NO_RELEASE = "none"

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


def classify_headings(
    headings: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Split headings into pending and dated, reporting malformed `when` fields.

    The `when` field is the *only* evidence this gate has for whether a version
    was released, so it cannot be "TBD, or else assume a date". `## [1.0.0] -
    TBA` and `## [1.0.0] - 2026-99-99` would both otherwise count as proof that
    1.0.0 shipped. Anything that is not `TBD` must parse as a real ISO calendar
    date or it is a problem, not a release.
    """
    pending: list[tuple[str, str]] = []
    dated: list[tuple[str, str]] = []
    problems: list[str] = []
    for version, when in headings:
        value = when.strip()
        if value.upper() == PENDING_MARKER:
            pending.append((version, value))
            continue
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            problems.append(
                f"CHANGELOG.md heading '## [{version}] - {value}' has neither "
                f"'{PENDING_MARKER}' nor an ISO date (YYYY-MM-DD). Release state is read "
                "from this field, so an unparseable one would be counted as released."
            )
            continue
        dated.append((version, value))
    return pending, dated, problems


def duplicate_versions(headings: list[tuple[str, str]]) -> list[str]:
    """Versions that appear in more than one heading.

    Uniqueness has to hold across *all* headings, not only among the pending
    ones. `## [1.0.0] - TBD` beside `## [1.0.0] - 2026-08-23` leaves exactly one
    pending heading and one dated heading equal to VERSION, so every other check
    here passes while the same release is simultaneously pending and shipped —
    and `release_notes.py` publishes whichever section it reaches first.
    """
    seen: dict[str, int] = {}
    for version, _ in headings:
        seen[version] = seen.get(version, 0) + 1
    return sorted(v for v, count in seen.items() if count > 1)


def list_release_tags() -> list[str]:
    """Every final `vX.Y.Z` tag in this repository, newest-sorting last.

    A module-level function so tests can replace it; `check()` calls it through
    the module namespace rather than holding a reference.

    Both workflows that run this gate check out with `fetch-depth: 0`, which
    fetches tags. On a checkout without them this returns nothing and the
    README's `Released:` field is then required to say `none` — which fails
    loudly on a repo that has published, rather than passing while the README
    understates. That is the safe direction to be wrong in.
    """
    try:
        completed = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def latest_release(tags: list[str], *, releasing: str | None = None) -> str | None:
    """The highest final release among `tags`, or None.

    `releasing` names the tag whose own workflow run is asking. It is excluded
    because at tag time the tag exists but the release has not been published,
    and the README cannot have been committed already claiming otherwise — the
    commit necessarily precedes the tag that points at it.
    """
    versions: list[tuple[int, int, int]] = []
    for tag in tags:
        if releasing is not None and tag == releasing:
            continue
        match = _RELEASE_TAG_RE.match(tag)
        if match is None:
            continue
        parsed = parse_version(match["version"])
        if parsed is not None:
            versions.append(parsed)
    if not versions:
        return None
    return ".".join(str(part) for part in max(versions))


def readme_block(text: str) -> str | None:
    """The fenced release-status block, or None when it is missing."""
    start = text.find(README_BEGIN)
    end = text.find(README_END)
    if start == -1 or end == -1 or end < start:
        return None
    return text[start + len(README_BEGIN) : end]


def check(*, releasing: str | None = None) -> list[str]:
    """Every inconsistency found. Empty means the release story holds."""
    raw_version = VERSION_FILE.read_text().strip()
    version = parse_version(raw_version)
    if version is None:
        return [
            f"VERSION is {raw_version!r}, which is not a plain X.Y.Z. Release candidates "
            "carry their suffix in the tag only (ADR-073126-c4e1 §2)."
        ]

    problems, resolved = _changelog_problems(CHANGELOG.read_text(), raw_version, version)
    if resolved is None:
        return problems
    target_raw, dated = resolved

    released = latest_release(list_release_tags(), releasing=releasing)
    problems.extend(_tag_problems(raw_version, version, dated, released))
    problems.extend(_readme_problems(raw_version, target_raw, released))
    return problems


def _changelog_problems(
    changelog: str,
    raw_version: str,
    version: tuple[int, int, int],
) -> tuple[list[str], tuple[str, list[tuple[str, str]]] | None]:
    """Problems in `CHANGELOG.md`, plus the target and dated headings it settles.

    The second element is None when the file is too broken to say what the
    pending target *is* — every later check is a statement about that target, so
    reporting them against a guess would bury the real problem under noise.
    """
    problems: list[str] = []
    if _UNRELEASED_RE.search(changelog) is None:
        problems.append(
            "CHANGELOG.md has no '## [Unreleased]' section — there is nowhere to write "
            "the change you are making now."
        )

    headings = changelog_headings(changelog)
    duplicates = duplicate_versions(headings)
    if duplicates:
        problems.append(
            f"CHANGELOG.md gives {', '.join(duplicates)} more than one heading. A version "
            "is pending or released, never both, and release notes are cut from whichever "
            "section comes first — which makes the duplicate silently decide the payload."
        )
    pending, dated, malformed = classify_headings(headings)
    problems.extend(malformed)
    if duplicates or malformed:
        return problems, None

    if len(pending) != 1:
        found = ", ".join(f"[{v}] - {w}" for v, w in pending) or "none"
        problems.append(
            f"CHANGELOG.md must name exactly one pending release "
            f"('## [X.Y.Z] - {PENDING_MARKER}'); found {len(pending)}: {found}. "
            "'Which release are these notes for' needs one answer."
        )
        return problems, None

    target_raw = pending[0][0]
    target = parse_version(target_raw)
    if target is None:  # pragma: no cover - the heading regex already shaped it
        problems.append(f"CHANGELOG.md pending heading {target_raw!r} is not X.Y.Z")
        return problems, None

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

    return problems, (target_raw, dated)


def _tag_problems(
    raw_version: str,
    version: tuple[int, int, int],
    dated: list[tuple[str, str]],
    released: str | None,
) -> list[str]:
    """What the repository's tags contradict.

    Tags are the only record of what was actually *published*; the checks above
    describe intent. Without this, `## [1.0.0] - TBD` and a pushed `v1.0.0` are
    indistinguishable from the files alone.
    """
    if released is None:
        return []
    problems: list[str] = []
    released_version = parse_version(released)
    if released_version is not None and released_version > version:
        problems.append(
            f"tag v{released} exists but VERSION is {raw_version}. A published release "
            "cannot be above the version the packages carry."
        )
    if released not in {v for v, _ in dated}:
        problems.append(
            f"tag v{released} exists but CHANGELOG.md has no dated '## [{released}]' "
            "heading. A published release has to have notes, and they have to be dated."
        )
    return problems


def _readme_problems(raw_version: str, target_raw: str, released: str | None) -> list[str]:
    """What the README's release-status block fails to say.

    Each field is matched by its own label. Containment would let one number
    satisfy two checks — see `_README_FIELDS`.
    """
    block = readme_block(README.read_text())
    if block is None:
        return [
            f"README.md has no release-status block. Add one between {README_BEGIN} and "
            f"{README_END} naming the released version, the version in the tree and the "
            "release target, so a reader is not left to infer any of them from a feature "
            "table."
        ]
    problems: list[str] = []
    found: dict[str, str] = {}
    for name, pattern in _README_FIELDS.items():
        match = pattern.search(block)
        if match is None:
            problems.append(
                f"README.md's release-status block has no '{name}' field. Every number in "
                "it carries its own label so one cannot stand in for another."
            )
            continue
        found[name] = match["value"]
    if problems:
        return problems

    if found["current"] != raw_version:
        problems.append(
            f"README.md says the version in the tree is {found['current']}, but VERSION "
            f"says {raw_version}."
        )
    if found["target"] != target_raw:
        problems.append(
            f"README.md says the next release target is {found['target']}, but CHANGELOG.md's "
            f"pending heading says {target_raw}."
        )

    expected = released if released is not None else NO_RELEASE
    if found["released"].lower() != expected.lower():
        problems.append(
            f"README.md says the released version is {found['released']}, but the repository's "
            f"tags say {expected}. Update the 'Released:' field in the release-status block "
            "(this is the edit a publish leaves behind); if this is a shallow checkout, fetch "
            "tags first."
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--releasing",
        default=None,
        metavar="TAG",
        help=(
            "The tag whose release run is calling, e.g. v1.0.0. Excluded from the "
            "released-version comparison: at tag time the tag exists but the README "
            "commit it points at necessarily predates it."
        ),
    )
    args = parser.parse_args(argv)

    problems = check(releasing=args.releasing)
    for problem in problems:
        _fail(problem)
    if problems:
        print(
            f"\nFAIL: {len(problems)} release-consistency problem(s). "
            "VERSION, CHANGELOG.md, README.md and the repository's tags have to tell "
            "one story."
        )
        return 1
    version = VERSION_FILE.read_text().strip()
    pending, _, _ = classify_headings(changelog_headings(CHANGELOG.read_text()))
    target = pending[0][0]
    released = latest_release(list_release_tags(), releasing=args.releasing) or NO_RELEASE
    if version == target:
        print(
            f"ok: released {released}, shipping {version}, and CHANGELOG's pending "
            "release is the same — taggable"
        )
    else:
        print(f"ok: released {released}, shipping {version}, working toward {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
