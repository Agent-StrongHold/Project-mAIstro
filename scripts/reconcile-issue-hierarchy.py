#!/usr/bin/env python3
"""Audit and cautiously backfill native GitHub sub-issue relationships (#2503).

Default is an offline, read-only review of the committed issue snapshot.
Writes require --apply --confirm APPLY, a GitHub Issues-write token, and a
per-invocation limit. Never infer an issue's parent from Depends on/Related.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
MANIFEST = Path("docs/testing/issue-2503-native-hierarchy-audit.json")
MAX_DIRECT_CHILDREN = 100
MAX_NESTED_LEVELS = 8


class HierarchyError(RuntimeError):
    """The evidence does not authorize the proposed mutation."""


def _milestone(issue: dict[str, Any]) -> str | None:
    title = str(issue.get("native_milestone_title") or "")
    return title.split(" ", 1)[0] if title.startswith("M") else None


def _parent_number(issue: dict[str, Any]) -> int | None:
    url = issue.get("parent_issue_url")
    if not url:
        return None
    if not isinstance(url, str) or "/issues/" not in url:
        raise HierarchyError("malformed live parent issue URL")
    try:
        return int(url.rsplit("/issues/", 1)[1])
    except ValueError as exc:
        raise HierarchyError("malformed live parent issue number") from exc


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise HierarchyError("unsupported hierarchy manifest schema")
    issues = data.get("issues")
    if not isinstance(issues, list) or not issues:
        raise HierarchyError("empty or malformed issue inventory")
    numbers = [row.get("number") for row in issues if isinstance(row, dict)]
    if len(numbers) != len(issues) or len(set(numbers)) != len(numbers):
        raise HierarchyError("duplicate or malformed issue numbers")
    if data.get("summary", {}).get("issues_total") != len(issues):
        raise HierarchyError("partial inventory: issue count mismatch")
    return data


def plan(data: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Return unique, source-backed edges in parent-before-child order."""
    issues = data["issues"]
    by_number = {row["number"]: row for row in issues}
    skipped: Counter[str] = Counter()
    proposed: list[dict[str, Any]] = []

    for issue in issues:
        number = issue["number"]
        declared = issue.get("declared_parent")
        native = issue.get("native_parent")
        if declared is not None and declared not in by_number:
            raise HierarchyError(
                f"#{number}: declared parent #{declared} not inventoried"
            )
        if declared is not None and native not in (None, declared):
            raise HierarchyError(f"#{number}: declared #{declared}, native #{native}")
        if not declared or native == declared:
            continue
        if issue.get("ambiguous_parent_line"):
            skipped["multiple_refs_on_parent_line"] += 1
            continue
        if not issue.get("parent_line_verified") or not issue.get(
            "declared_parent_line"
        ):
            skipped["unverified_source_line"] += 1
            continue
        if issue["issue_id"] <= 0 or number == declared:
            raise HierarchyError(f"#{number}: invalid issue id/self-parent")
        parent = by_number[declared]
        child_milestone, parent_milestone = _milestone(issue), _milestone(parent)
        if child_milestone and parent_milestone and child_milestone != parent_milestone:
            skipped["cross_milestone_review"] += 1
            continue
        proposed.append(issue)

    # Detect cycles over BOTH existing native and declared edges, including
    # nodes excluded from automatic application. Any cycle fails the entire
    # migration instead of relying on GitHub to refuse a partial write.
    depths: dict[int, int] = {}

    def depth(number: int, visiting: set[int]) -> int:
        if number in depths:
            return depths[number]
        if number in visiting:
            raise HierarchyError(f"cycle through issue #{number}")
        issue = by_number[number]
        parent = issue.get("declared_parent") or issue.get("native_parent")
        if parent is None:
            depths[number] = 0
        else:
            if parent not in by_number:
                raise HierarchyError(f"#{number}: missing graph ancestor #{parent}")
            depths[number] = depth(parent, visiting | {number}) + 1
        return depths[number]

    for number in by_number:
        if depth(number, set()) > MAX_NESTED_LEVELS:
            raise HierarchyError(
                f"#{number}: nested hierarchy exceeds {MAX_NESTED_LEVELS} levels"
            )

    per_parent = Counter(row["declared_parent"] for row in proposed)
    for number, added in per_parent.items():
        current = int(by_number[number].get("native_child_count") or 0)
        if current + added > MAX_DIRECT_CHILDREN:
            raise HierarchyError(
                f"#{number} would exceed {MAX_DIRECT_CHILDREN} direct children"
            )

    proposed.sort(
        key=lambda row: (depths[row["number"]], row["declared_parent"], row["number"])
    )
    return proposed, skipped


def _request(
    repo: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"{API_ROOT}/repos/{repo}/{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "maistro-hierarchy-reconciliation",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HierarchyError(f"{method} {path} failed: {exc}") from exc


def _live_issue(repo: str, token: str, number: int) -> dict[str, Any]:
    issue = _request(repo, token, "GET", f"issues/{number}")
    if not isinstance(issue, dict) or issue.get("number") != number:
        raise HierarchyError(f"#{number}: invalid live issue response")
    return issue


def apply_one(
    repo: str,
    token: str,
    row: dict[str, Any],
    by_number: dict[int, dict[str, Any]],
) -> str:
    """Write one exact edge only after fresh verification; never auto-reparent."""
    number, parent_number = row["number"], row["declared_parent"]
    issue = _live_issue(repo, token, number)
    parent = _live_issue(repo, token, parent_number)
    native = _parent_number(issue)

    if native == parent_number:
        return "already_linked"
    if native is not None:
        raise HierarchyError(
            f"#{number}: now parented to #{native}, expected #{parent_number}"
        )
    if issue.get("id") != row["issue_id"]:
        raise HierarchyError(f"#{number}: issue identity changed")
    if issue.get("state") != row.get("state"):
        raise HierarchyError(f"#{number}: issue state changed since snapshot")
    current_labels = sorted(
        item.get("name") for item in (issue.get("labels") or [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    if current_labels != sorted(row.get("labels", [])):
        raise HierarchyError(f"#{number}: labels changed since snapshot")

    # The entire explicit source line must still be unchanged. There is no
    # automatic repair based on stale titles, historical comments or siblings.
    if row["declared_parent_line"] not in (issue.get("body") or "").splitlines():
        if row["declared_parent_line"].strip() not in [
            line.strip() for line in (issue.get("body") or "").splitlines()
        ]:
            raise HierarchyError(
                f"#{number}: parent declaration changed since snapshot"
            )

    snapshot_ms = row.get("native_milestone")
    live_ms = (issue.get("milestone") or {}).get("number")
    if snapshot_ms != live_ms:
        raise HierarchyError(f"#{number}: child milestone changed since snapshot")
    expected_parent = by_number[parent_number]
    if parent.get("id") != expected_parent.get("issue_id"):
        raise HierarchyError(f"#{parent_number}: parent identity changed")
    if (parent.get("milestone") or {}).get("number") != expected_parent.get(
        "native_milestone"
    ):
        raise HierarchyError(
            f"#{parent_number}: parent milestone changed since snapshot"
        )
    if (parent.get("sub_issues_summary") or {}).get("total", 0) >= MAX_DIRECT_CHILDREN:
        raise HierarchyError(f"#{parent_number}: direct-child limit reached")

    path = f"issues/{parent_number}/sub_issues"
    try:
        _request(repo, token, "POST", path, {"sub_issue_id": row["issue_id"]})
    except HierarchyError as exc:
        # A timeout after the POST may mean it committed. Re-read once and
        # reconcile the result; do not blindly retry a non-idempotent write.
        if _parent_number(_live_issue(repo, token, number)) != parent_number:
            raise exc

    if _parent_number(_live_issue(repo, token, number)) != parent_number:
        raise HierarchyError(f"#{number}: native parent verification failed")
    children = _request(repo, token, "GET", f"{path}?per_page=100")
    if not isinstance(children, list) or not any(
        isinstance(child, dict) and child.get("number") == number for child in children
    ):
        raise HierarchyError(
            f"#{parent_number}: native child verification failed for #{number}"
        )
    return "linked"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--max-writes", type=int, default=25)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result: dict[str, Any] = {"mode": "apply" if args.apply else "dry-run", "writes": []}

    try:
        data = load_manifest(args.manifest)
        proposed, skipped = plan(data)
        if args.issue_number is not None:
            proposed = [row for row in proposed if row["number"] == args.issue_number]
        result: dict[str, Any] = {
            "repository": data["repository"],
            "inventory_issues": len(data["issues"]),
            "candidates": len(proposed),
            "skipped": dict(skipped),
            "mode": "apply" if args.apply else "dry-run",
            "writes": [],
        }

        if args.apply:
            if args.confirm != "APPLY" or not (1 <= args.max_writes <= 50):
                raise HierarchyError(
                    "--apply requires --confirm APPLY and 1-50 max writes"
                )
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                raise HierarchyError("GITHUB_TOKEN is required for --apply")
            if (
                os.environ.get("GITHUB_REPOSITORY", data["repository"])
                != data["repository"]
            ):
                raise HierarchyError("connected repository differs from manifest")
            by_number = {row["number"]: row for row in data["issues"]}
            writes = 0
            for row in proposed:
                action = apply_one(data["repository"], token, row, by_number)
                if action == "linked":
                    writes += 1
                result["writes"].append({"issue": row["number"], "result": action})
                if writes >= args.max_writes:
                    break
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.report:
            args.report.write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
        return 0
    except (HierarchyError, OSError, ValueError, TypeError) as exc:
        result["error"] = str(exc)
        print(f"error: {exc}", file=sys.stderr)
        if args.report:
            try:
                args.report.write_text(
                    json.dumps(result, indent=2) + "\n", encoding="utf-8"
                )
            except OSError as report_error:
                print(f"error: could not save failure report: {report_error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
