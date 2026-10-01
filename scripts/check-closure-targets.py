#!/usr/bin/env python3
"""A PR may not close an epic by keyword (#56, Workspace Cutover S0.2).

A merged PR whose body says ``Closes #N`` closes issue N, whatever N is. #56
was an epic closed that way: one PR delivered one slice, the keyword closed
the whole epic, and every acceptance criterion the PR never touched read as
done. An epic, milestone or initiative closes by hand, once ``check-ac-state``
reports every criterion reachable -- evidence, not a keyword.

This parses the PR body for GitHub's closing keywords (``close``, ``closes``,
``closed``, ``fix``, ``fixes``, ``fixed``, ``resolve``, ``resolves``,
``resolved``; case-insensitive) followed by ``#N`` or ``owner/repo#N``. A
cross-repo reference to another repository is ignored. Each same-repo target
fails the check if its title opens with a bracketed tag naming ``EPIC``,
``MILESTONE`` or ``INITIATIVE`` (``[EPIC]``, ``[EPIC M1-B]``,
``[MASTER INITIATIVE]``), or if it has sub-issues.

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
    r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<number>\d+)\b",
    re.IGNORECASE,
)


class GitHubError(RuntimeError):
    """The issue lookup failed; the check cannot vouch for the target."""


@dataclass(frozen=True)
class Target:
    number: int
    title: str
    has_sub_issues: bool


def closing_targets(body: str, repo: str) -> list[int]:
    """Issue numbers in ``repo`` that ``body`` would close, in first-seen order."""
    numbers: list[int] = []
    for match in _CLOSING.finditer(body):
        other = match.group("repo")
        if other and other.lower() != repo.lower():
            continue
        number = int(match.group("number"))
        if number not in numbers:
            numbers.append(number)
    return numbers


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
    """Title and sub-issue presence of ``repo#number`` from the REST API."""
    base = f"{API_ROOT}/repos/{repo}/issues/{number}"
    try:
        issue = _get_json(base, token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError(f"GET {base}: {exc}") from exc
    if not isinstance(issue, dict):
        raise GitHubError(f"GET {base}: unexpected response shape")

    try:
        subs = _get_json(f"{base}/sub_issues?per_page=1", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise GitHubError(f"GET {base}/sub_issues: {exc}") from exc
        subs = []
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError(f"GET {base}/sub_issues: {exc}") from exc

    return Target(
        number=number,
        title=str(issue.get("title") or ""),
        has_sub_issues=isinstance(subs, list) and bool(subs),
    )


def problems_for(target: Target) -> list[str]:
    found: list[str] = []
    tag = _EPIC_TAG.match(target.title)
    if tag:
        kind = tag.group("kind").upper()
        found.append(f"#{target.number} is tagged {kind} ({target.title!r})")
    if target.has_sub_issues:
        found.append(f"#{target.number} has sub-issues")
    return found


def pull_request_body(event_path: str | None) -> str | None:
    """The PR body from the Actions event payload, or None if not a PR event."""
    if os.environ.get("GITHUB_EVENT_NAME", "") != "pull_request" or not event_path:
        return None
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    return str(pull_request.get("body") or "")


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
        body = pull_request_body(os.environ.get("GITHUB_EVENT_PATH"))
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
            f"{', '.join(f'#{n}' for n in numbers)} cannot be checked for epics."
        )
        return 1

    problems: list[str] = []
    for number in numbers:
        try:
            target = fetch_target(args.repo, number, token)
        except GitHubError as exc:
            print(f"::error::cannot look up #{number}: {exc}")
            return 1
        problems.extend(problems_for(target))

    for problem in problems:
        print(f"::error::closing keyword targets an epic: {problem}")
    if problems:
        print(
            "\nFAIL: an epic closes by hand once check-ac-state reports every "
            "criterion reachable, not by a PR keyword. Reference it without a "
            "closing keyword (e.g. 'Part of #N' or 'Refs #N')."
        )
        return 1
    print(f"ok: closing targets {', '.join(f'#{n}' for n in numbers)} are not epics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
