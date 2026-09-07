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

Why Unreleased *content* is checked, not just the heading (#385)
----------------------------------------------------------------
A heading is not an entry. This gate used to accept an `## [Unreleased]`
section that was empty or held only placeholders while extensive
user-visible work landed, because "the heading exists" was the whole test.
The policy this gate now enforces, stated where PR authors write entries:

- A change a user, operator or security reviewer can observe from outside
  the code — API surface or behaviour, CLI, configuration, database schema,
  dependencies, security posture, anything an operator must do differently —
  requires a categorized `## [Unreleased]` entry in the same PR.
- Generated churn (formatting, lockfile regeneration, baseline re-basing) and
  purely internal refactors with no observable effect are excluded by
  policy: they need no entry. Dependency updates get an entry under
  `Dependencies` linking their PR, so an operator-visible upgrade can never
  hide as "noise".
- Every entry sits under a recognized category and links the issue or PR it
  belongs to (`(#1234)`); a change with no tracked issue carries the explicit
  exclusion `(no linked issue: <reason>)` instead.
- Placeholders (TODO/TBD/none/...) are *worse* than an empty section: they
  defeat a presence check while committing nothing. Placeholder-only
  content fails; a genuinely empty section passes an ordinary run — a tree
  may simply not have accumulated user-visible changes yet.
- Release readiness is the one place emptiness cannot stand: at tag time
  (`--releasing vX.Y.Z`) the section being published must contain meaningful
  content, because `release_notes.py` publishes exactly that section and
  never substitutes generated output for the curated one (E3, #296).
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

#: The categories an `## [Unreleased]` entry may sit under. Keep a Changelog
#: 1.1's set, plus `Dependencies` — this repo's explicit home for the one class
#: of generated churn that is still operator-visible (an upgrade changes what
#: ships). Without a recognized home a dependency bump either landed under a
#: wrong category or nowhere, and "nowhere" passed because only the heading's
#: presence was checked (#385).
UNRELEASED_CATEGORIES: frozenset[str] = frozenset(
    {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security", "Dependencies"}
)

#: A linked issue or PR, Keep a Changelog style: `(#1234)`. The leading `(`
#: matters — bare `#1234` in prose ("see #1234") is a mention, not a link, and
#: a mention is exactly what an entry that ought to name its own issue would
#: hide behind.
_ISSUE_LINK_RE = re.compile(r"\(#\d+")

#: The explicit exclusion for an entry with no tracked issue. An annotation,
#: not a pattern: the reason is part of the text.
_NO_ISSUE_RE = re.compile(r"\(no linked issue: ", re.I)

#: Words that read as content to a presence check and mean nothing. An
#: Unreleased section made only of these is *worse* than an empty one: it
#: satisfies "the heading has something under it" while committing no
#: information at all (#385).
_PLACEHOLDER_RE = re.compile(
    r"(?i)\b(tbd|todo|placeholder|forthcoming|n/?a|nothing here|lorem ipsum)\b"
)

#: One entry bullet, CommonMark list form. Continuation lines belong to the
#: bullet above them and carry no claim of their own.
_ENTRY_RE = re.compile(r"^(?:\*|\+|-) ")


def _entry_text(entry_line: str) -> str:
    """An entry bullet's own text: the marker stripped, whitespace trimmed.

    Placeholder matching is `fullmatch` on purpose — a *line-shaped* token,
    not a mention — and `- TODO` must therefore be compared as `TODO`, not
    fail the match because of the list marker every real entry carries.
    """
    return _ENTRY_RE.sub("", entry_line, count=1).strip()


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


def section_body(text: str, heading_re: re.Pattern[str]) -> str | None:
    """The body under the first `heading_re` heading, to the next `## ` one.

    None when the heading is absent. Curated sections may open with prose
    before their first `###` category (the 1.0.0 section does), so the body is
    returned verbatim and callers decide what counts as an entry.
    """
    match = heading_re.search(text)
    if match is None:
        return None
    rest = text[match.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _entries(body: str) -> list[tuple[int, str, str]]:
    """`(line_no, category, entry_text)` for every entry bullet in a section.

    `category` is the `### ` heading the bullet sits under, or "" for bullets
    before any category heading — which the Unreleased shape rules reject, so
    the position is kept rather than silently dropped. Continuation lines
    (indented prose of the same bullet) are folded into `entry_text`: a Keep a
    Changelog entry carries its issue link anywhere in the bullet, and only
    reading the first line would reject the well-formed entries that happen to
    wrap onto a second line — like every entry this file already carries.
    """
    out: list[tuple[int, str, str]] = []
    category = ""
    current: tuple[int, str, list[str]] | None = None
    for index, line in enumerate(body.splitlines()):
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading is not None:
            category = heading[1]
            current = None
            continue
        if _ENTRY_RE.match(line):
            if current is not None:
                out.append((current[0], current[1], " ".join(current[2])))
            current = (index, category, [line])
            continue
        if current is not None and line[:1].isspace():
            current[2].append(line)
        elif line.strip() and current is not None:
            out.append((current[0], current[1], " ".join(current[2])))
            current = None
    if current is not None:
        out.append((current[0], current[1], " ".join(current[2])))
    return out


def _placeholder_only(body: str) -> bool:
    """Whether every content line of a section body is a placeholder token.

    `TODO` under `### Added` is the canonical way to defeat a presence check:
    the heading exists, the category exists, and the entry says nothing.
    Category headings are structure, not content, so they are ignored — a
    body of headings plus TODO is placeholder-only in every way that matters.
    """
    lines = [
        line.strip() for line in body.splitlines() if line.strip() and not re.match(r"^###\s", line)
    ]
    lines = [
        _ENTRY_RE.sub("", line, count=1).strip() if _ENTRY_RE.match(line) else line
        for line in lines
    ]
    return bool(lines) and all(_PLACEHOLDER_RE.fullmatch(line) is not None for line in lines)


def unreleased_problems(changelog: str) -> list[str]:
    """Shape problems in the `## [Unreleased]` section (#385).

    A heading is not an entry. When the section carries any content at all,
    every entry must be categorized, and every entry must link the issue or PR
    it belongs to or carry the explicit no-issue exclusion — otherwise the
    section can look populated while nothing in it is traceable. A genuinely
    empty section is not a problem here: a tree may not have accumulated
    user-visible changes, and release readiness — where emptiness *is* a
    problem — is `_release_readiness_problems`'s job.
    """
    body = section_body(changelog, _UNRELEASED_RE)
    if body is None or not body.strip():
        return []
    if _placeholder_only(body):
        return [
            "CHANGELOG.md's '## [Unreleased]' section is placeholder-only (TODO/TBD/none/...). "
            "A placeholder defeats the content check while committing nothing: write the "
            "real entry or remove the placeholder."
        ]
    problems: list[str] = []
    for _, category, line in _entries(body):
        if category not in UNRELEASED_CATEGORIES:
            problems.append(
                f"CHANGELOG.md Unreleased entry {line[:60]!r} sits under "
                f"{category or 'no category'}. Entries belong under one of: "
                f"{', '.join(sorted(UNRELEASED_CATEGORIES))}."
            )
            continue
        if _PLACEHOLDER_RE.fullmatch(_entry_text(line)):
            problems.append(
                f"CHANGELOG.md Unreleased entry {line[:60]!r} is a placeholder, not an entry."
            )
            continue
        if _ISSUE_LINK_RE.search(line) is None and _NO_ISSUE_RE.search(line) is None:
            problems.append(
                f"CHANGELOG.md Unreleased entry {line[:60]!r} links no "
                "issue or PR. Add (#1234), or '(no linked issue: <reason>)' when the change "
                "has no tracked issue."
            )
    if not _entries(body):
        problems.append(
            "CHANGELOG.md's '## [Unreleased]' section has content but no entries under a "
            "recognized category. User-visible changes need a categorized bullet so the "
            "entry can be linked, reviewed and released."
        )
    return problems


def _release_readiness_problems(changelog: str, releasing: str) -> list[str]:
    """Why the section being published is not releasable (#385).

    `release_notes.py` publishes the curated `## [X.Y.Z]` section verbatim — it
    never substitutes generated output for the curated one — so a tag cut
    against an empty or placeholder-only section publishes exactly that. The
    rc form is reduced the same way `release_guard` reduces it: a candidate
    publishes the notes of the release it is a candidate for.
    """
    match = _RELEASE_TAG_RE.match(releasing) or re.match(
        r"^v(?P<version>\d+\.\d+\.\d+)-rc\d+$", releasing
    )
    if match is None:
        return []  # release_guard owns tag-shape errors
    version = match["version"]
    heading_re = re.compile(rf"^##\s*\[{re.escape(version)}\][^\n]*", re.M)
    body = section_body(changelog, heading_re)
    if body is None:
        return []  # the heading's existence is release_guard's check
    if body.strip() and not _placeholder_only(body):
        return []
    return [
        f"CHANGELOG.md's '## [{version}]' section is {'placeholder-only' if body.strip() else 'empty'} "
        f"and tag {releasing} is being cut against it. release_notes.py publishes exactly "
        "this section; an empty or placeholder-only Unreleased cannot satisfy release "
        "readiness (#385)."
    ]


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
    if releasing is not None:
        problems.extend(_release_readiness_problems(CHANGELOG.read_text(), releasing))
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
    else:
        # Presence of the heading is necessary and never sufficient (#385):
        # content, when it exists, must be categorized and traceable.
        problems.extend(unreleased_problems(changelog))

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
