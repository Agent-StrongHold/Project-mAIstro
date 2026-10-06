#!/usr/bin/env python3
"""A PR keyword may not close what the repository's acceptance evidence cannot (#1141).

A merged PR whose body says ``Closes #N`` closes issue N, whatever N is, and
whatever N's own acceptance record still says is open. #56 was an epic closed
that way: one PR delivered one slice, the keyword closed the whole epic, and
every acceptance criterion the PR never touched read as done. #76 was closed
completed by a keyword while its acceptance record still demanded the canonical
sandbox authority and no direct bypasses -- a locally green diff that registers
one backend proves none of that, yet the keyword outran the record (#76, PR
#583).

For every same-repo ``#N`` a closing keyword names, this check refuses closure
when any of the following holds:

* the title opens with a bracketed tag naming ``EPIC``, ``MILESTONE`` or
  ``INITIATIVE`` (``[EPIC M1-B]``, ``[MASTER INITIATIVE]``) -- epics and
  initiatives close by explicit reviewed action, once ``check-ac-state``
  reports every criterion reachable, never by a child PR's keyword;
* the target has open direct children (sub-issues) -- a child PR's keyword
  must not close its unmerged siblings' parent out from under them;
* the target registers acceptance criteria as checkbox items under an
  acceptance heading and any of them is still unticked in the issue body --
  the tick is the closeout record; an unticked box is the repository's own
  statement that the criterion is unproven, however green the PR is.

The proof is the acceptance record itself, never the PR's diff. A PR may
satisfy a criterion through tests, config, removal or migration without
touching the file the prose cites, and touching a cited file proves nothing
by itself -- so the diff is not an input to this verdict at all. Where the PR
claims a specific criterion on the same line as its keyword (``Closes #76
AC-2``), that criterion must be ticked in the record; an unsupported claim is
rejected by name.

A target that is already closed is skipped: a keyword cannot transition a
closed issue, so there is nothing here to vouch for. An open leaf with no
children and every registered criterion ticked stays eligible -- useful
auto-close is preserved; only claims that outrun evidence are not.

Outside a ``pull_request`` event (push, merge_group, local run without
``--body-file``) there is no body to judge, so it skips with exit 0. On a
pull_request event a missing ``GITHUB_TOKEN`` or an API error fails closed.

Usage:
    python3 scripts/check-closure-targets.py                  # in CI
    python3 scripts/check-closure-targets.py --body-file PR.md --repo owner/repo
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API_ROOT = "https://api.github.com"

# Real titles carry a qualifier inside the tag -- `[EPIC M1-B] ...`,
# `[MILESTONE M4] ...`, `[MASTER INITIATIVE] ...` -- so a literal `[EPIC]`
# prefix match would miss every epic this repository actually has.
_EPIC_TAG = re.compile(
    r"^\s*\[[^\]]*\b(?P<kind>EPIC|MILESTONE|INITIATIVE)\b[^\]]*\]",
    re.IGNORECASE,
)

_CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
    r"(?:"
    r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<number>\d+)\b"
    r"|"
    r"https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/(?P<url_number>\d+)\b"
    r")",
    re.IGNORECASE,
)

# The acceptance record: a heading that opens one (``## Acceptance``,
# ``## Acceptance criteria``, a bare ``Acceptance:`` paragraph -- the corpus
# carries both), then checkbox items until the next heading of any level.
# Case-insensitive: issues write the heading both ways. The heading text is
# anchored on ``acceptance`` (optionally qualified by criteria/criterion/
# checklist) so lookalikes -- ``## Non-acceptance criteria`` -- open nothing:
# an unchecked out-of-scope checklist there must not register as unproven
# acceptance evidence (review: exclude non-acceptance headings).
_ACCEPTANCE_HEADING = re.compile(
    r"^\s{0,3}"
    r"(?:"
    r"#{1,6}\s+acceptance(?:\s+(?:criteria|criterion|checklist))?\s*:?"
    r"|acceptance\b:?"
    r")\s*$",
    re.IGNORECASE,
)
_ANY_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
# A bare ``Label:`` paragraph (``Tasks:``, ``Notes:``) is the plain-paragraph
# counterpart of a heading: it ends an open record, so a checkbox under
# ``Tasks:`` stays a task instead of registering as an acceptance criterion.
# Trailing text after the colon keeps prose like ``plan: see doc`` out.
_BARE_SECTION = re.compile(r"^\s{0,3}[A-Za-z][\w '/-]{0,40}:\s*$")
_CHECKBOX = re.compile(r"^\s{0,3}[-*]\s+\[(?P<box>[ xX])\]\s*(?P<text>\S.*)$")

# ``Closes #76 AC-2`` / ``fixes #56 (AC-3)``: a criterion claimed on the same
# line as the keyword. Both orders, with or without the hyphen.
_CLAIMED_AC = re.compile(
    r"(?P<number>\d+)[^\n#]{0,80}?\bAC-?(?P<ac>\d+)\b"
    r"|\bAC-?(?P<ac2>\d+)\b[^\n#]{0,80}#(?P<number2>\d+)",
    re.IGNORECASE,
)


class GitHubError(RuntimeError):
    """The issue lookup failed; the check cannot vouch for the target."""


@dataclass(frozen=True)
class Criterion:
    """One registered acceptance criterion, as the issue's record carries it."""

    index: int
    text: str
    ticked: bool


@dataclass(frozen=True)
class Target:
    number: int
    title: str
    state: str
    body: str
    has_open_sub_issues: bool


def closing_targets(body: str, repo: str) -> list[int]:
    """Issue numbers in ``repo`` that ``body`` would close, in first-seen order."""
    numbers: list[int] = []
    for match in _CLOSING.finditer(body):
        other = match.group("repo") or match.group("url_repo")
        number_text = match.group("number") or match.group("url_number")
        if other and other.lower() != repo.lower():
            continue
        number = int(number_text)
        if number not in numbers:
            numbers.append(number)
    return numbers


def acceptance_criteria(body: str) -> list[Criterion]:
    """Checkbox items registered under an acceptance heading, in issue order.

    A criterion is *registered* when the issue carries it as a checkbox under
    an acceptance heading; the box is the author's closeout record. Prose
    bullets under ``Acceptance:`` are intent, not a machine-checkable record,
    and register nothing.
    """
    criteria: list[Criterion] = []
    in_record = False
    for line in body.splitlines():
        if _ACCEPTANCE_HEADING.match(line):
            in_record = True
            continue
        if not in_record:
            continue
        if _ANY_HEADING.match(line) or _BARE_SECTION.match(line):
            in_record = False
            continue
        checkbox = _CHECKBOX.match(line)
        if checkbox:
            criteria.append(
                Criterion(
                    index=len(criteria) + 1,
                    text=checkbox.group("text").strip(),
                    ticked=checkbox.group("box").lower() == "x",
                )
            )
    return criteria


def claimed_criteria(pr_text: str, numbers: list[int]) -> dict[int, set[int]]:
    """Acceptance-criterion ids each *closing* target claims on its own line.

    Only lines that would actually close ``#N`` count as claiming its criteria:
    ``Part of #76 AC-2 still failing`` is progress language and must not be
    read as a closure claim.
    """
    claims: dict[int, set[int]] = {}
    for line in pr_text.splitlines():
        closed_here = {
            int(m.group("number") or m.group("url_number")) for m in _CLOSING.finditer(line)
        } & set(numbers)
        if not closed_here:
            continue
        for match in _CLAIMED_AC.finditer(line):
            number_text = match.group("number") or match.group("number2")
            ac_text = match.group("ac") or match.group("ac2")
            number = int(number_text)
            if number in closed_here:
                claims.setdefault(number, set()).add(int(ac_text))
    return claims


def _get_json(url: str, token: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_target(repo: str, number: int, token: str) -> Target:
    """Title, state, body and open-children presence of ``repo#number``."""
    base = f"{API_ROOT}/repos/{repo}/issues/{number}"

    try:
        issue = _get_json(base, token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError(f"GET {base}: {exc}") from exc
    if not isinstance(issue, dict):
        raise GitHubError(f"GET {base}: unexpected response shape")

    # The sub-issues endpoint has no state filter, so page until a page comes
    # back empty or an open child is found. A bounded page cap keeps a
    # pathological parent from spinning the gate; a parent with more closed
    # children than the cap and an open one beyond it fails closed as
    # "cannot rule out open children" only via the API-error path, never by
    # silently passing.
    has_open_sub_issues = False
    for page in range(1, 11):
        try:
            subs = _get_json(f"{base}/sub_issues?per_page=100&page={page}", token)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                subs = []
            else:
                raise GitHubError(f"GET {base}/sub_issues: {exc}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise GitHubError(f"GET {base}/sub_issues: {exc}") from exc
        if not isinstance(subs, list):
            raise GitHubError(f"GET {base}/sub_issues: unexpected response shape")
        if any(isinstance(sub, dict) and sub.get("state") == "open" for sub in subs):
            has_open_sub_issues = True
            break
        if len(subs) < 100:
            break

    return Target(
        number=number,
        title=str(issue.get("title") or ""),
        state=str(issue.get("state") or "open"),
        body=str(issue.get("body") or ""),
        has_open_sub_issues=has_open_sub_issues,
    )


def problems_for(target: Target, claims: set[int] | None = None) -> list[str]:
    """Every reason a closing keyword must not transition ``target``."""
    found: list[str] = []
    tag = _EPIC_TAG.match(target.title)
    if tag:
        kind = tag.group("kind").upper()
        found.append(
            f"#{target.number} is tagged {kind} ({target.title!r}); an epic closes "
            "by explicit reviewed action, never by a PR keyword"
        )
    if target.has_open_sub_issues:
        found.append(
            f"#{target.number} has open direct children; a child PR's keyword "
            "must not close their parent"
        )

    criteria = acceptance_criteria(target.body)
    unticked = [c for c in criteria if not c.ticked]
    if unticked:
        found.append(
            f"#{target.number}'s acceptance record shows "
            f"{len(unticked)} of {len(criteria)} registered criteria unproven "
            f"(unticked: {', '.join(f'AC-{c.index}' for c in unticked[:5])}"
            f"{' ...' if len(unticked) > 5 else ''}); a locally green diff "
            "does not discharge them"
        )
    registered = {c.index for c in criteria}
    for claimed in sorted(claims or set()):
        if claimed not in registered:
            found.append(
                f"the PR claims AC-{claimed} of #{target.number}, which the "
                f"acceptance record does not register ({len(criteria)} "
                "criteria exist); the unsupported claim is rejected"
            )
        elif claimed in {c.index for c in unticked}:
            found.append(
                f"the PR claims AC-{claimed} of #{target.number}, but the "
                "acceptance record does not show it proven"
            )
    return found


def pull_request_text(event_path: str | None) -> str | None:
    """PR title and body from the Actions event payload, or None if not a PR event."""
    if os.environ.get("GITHUB_EVENT_NAME", "") != "pull_request" or not event_path:
        return None
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    title = str(pull_request.get("title") or "")
    body = str(pull_request.get("body") or "")
    return f"{title}\n{body}" if title or body else ""


def evaluate_targets(
    repo: str, body: str, numbers: list[int], token: str
) -> tuple[list[str], list[int]] | None:
    """Problems for each closing target and the targets skipped as closed.

    Returns None when a target cannot be looked up: with no verdict possible
    the caller fails closed rather than on the reported problems.
    """
    claims = claimed_criteria(body, numbers)
    problems: list[str] = []
    skipped: list[int] = []
    for number in numbers:
        try:
            target = fetch_target(repo, number, token)
        except GitHubError as exc:
            print(f"::error::cannot look up #{number}: {exc}")
            return None
        if target.state == "closed":
            skipped.append(number)
            continue
        problems.extend(problems_for(target, claims.get(number)))
    return problems, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--body-file", type=Path, help="judge this PR body instead of the event")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/repo (default: $GITHUB_REPOSITORY)",
    )
    args = parser.parse_args(argv)

    if args.body_file is not None:
        body: str | None = args.body_file.read_text(encoding="utf-8")
    else:
        body = pull_request_text(os.environ.get("GITHUB_EVENT_PATH"))
    if body is None:
        print("skip: not a pull_request event and no --body-file; no PR body to judge")
        return 0

    if not args.repo:
        print("::error::no repository: set GITHUB_REPOSITORY or pass --repo owner/repo")
        return 1
    numbers = closing_targets(body, args.repo)
    if not numbers:
        print("ok: PR body closes no issue by keyword")
        return 0

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "::error::GITHUB_TOKEN is not set, so the closing targets "
            f"{', '.join(f'#{n}' for n in numbers)} cannot be checked against "
            "their acceptance records."
        )
        return 1

    evaluated = evaluate_targets(args.repo, body, numbers, token)
    if evaluated is None:
        return 1
    problems, skipped = evaluated

    for problem in problems:
        print(f"::error::closing keyword outruns the acceptance evidence: {problem}")
    if problems:
        print(
            "\nFAIL: a closing keyword may not claim more than the target's "
            "acceptance record proves. For slices say 'Part of #N', 'Refs #N' or "
            "'Progresses #N'; an epic or initiative closes by explicit reviewed "
            "action once check-ac-state reports every criterion reachable; a leaf "
            "closes once every criterion registered in its acceptance record is "
            "proven there."
        )
        return 1
    if skipped:
        print(
            "ok: closing target(s) "
            f"{', '.join(f'#{n}' for n in skipped)} already closed; a keyword "
            "cannot close them again"
        )
    else:
        print(
            f"ok: closing targets {', '.join(f'#{n}' for n in numbers)} are not "
            "epics, have no open children, and their acceptance records are met"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
