#!/usr/bin/env python3
"""Audit native issue hierarchy; apply only a source-pinned reviewed link manifest.

No prose dependency, priority, state, body, assignee or milestone is mutated.
An API failure is not an empty graph. Reports and a per-write journal survive
partial failure. A repeated apply verifies existing links and performs no POST.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

PARENT = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?Parent"
    r"(?:\s+(?:epic|initiative|program|issue|milestone tracker))?"
    r"\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*\[?#(\d+)\b",
    re.IGNORECASE,
)
REVIEW_HOLDS = {1134: "Body says #446; reclassification comment 5853494178 says #452."}


def digest(body: str | None) -> str:
    """Pin the complete specification rather than an issue's mutable timestamp."""
    return hashlib.sha256((body or "").encode()).hexdigest()


def ownership_digest(comments: list[dict[str, Any]]) -> str:
    """Pin potential ownership decisions without pinning operational chatter."""
    pattern = r"\b(?:Parent(?:\s+(?:epic|initiative|program|milestone tracker))?\s*:|reclassif|reparent|milestone correction|ownership correction)"
    records = sorted(
        (x["id"], x.get("body", ""))
        for x in comments
        if re.search(pattern, x.get("body", ""), re.IGNORECASE)
    )
    return digest(json.dumps(records))


def declared_parents(body: str | None) -> list[int]:
    """Read explicit declarations outside quotations and fenced examples."""
    found: list[int] = []
    fence = ""
    for line in (body or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = "" if fence == marker else (fence or marker)
            continue
        if fence or stripped.startswith(">"):
            continue
        match = PARENT.match(line)
        if match and int(match[1]) not in found:
            found.append(int(match[1]))
    return found


def check_cycles(edges: list[dict[str, int]]) -> None:
    """Reject conflicting native parents and cycles before any write."""
    parents: dict[int, int] = {}
    for edge in edges:
        child, parent = edge["child"], edge["parent"]
        if child in parents and parents[child] != parent:
            raise ValueError(f"#{child}: competing parents")
        parents[child] = parent
    for node in parents:
        seen: set[int] = set()
        current = node
        while current in parents:
            if current in seen:
                raise ValueError(f"cycle involving #{current}")
            seen.add(current)
            current = parents[current]


def analyze(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify every issue, retaining malformed declarations as exceptions."""
    issues = {x["number"]: x for x in snapshot["issues"] if not x.get("pull_request")}
    native = snapshot["native_edges"]
    check_cycles(native)
    parent_of = {x["child"]: x["parent"] for x in native}
    rows = []
    proposals = []
    for number, issue in sorted(issues.items()):
        declared = declared_parents(issue.get("body"))
        actual = parent_of.get(number)
        if number in REVIEW_HOLDS:
            status = "review_hold"
        elif len(declared) > 1:
            status = "ambiguous"
        elif not declared:
            status = (
                "native_only" if actual else ("exempt_root" if number == 453 else "unclassified")
            )
        elif declared[0] not in issues:
            status = "invalid_reference"
        elif actual is not None:
            status = "linked" if actual == declared[0] else "conflicting_parent"
        else:
            status = "missing_parent"
            parent = issues[declared[0]]
            proposals.append(
                {
                    "child": number,
                    "parent": parent["number"],
                    "child_id": issue["id"],
                    "child_body_sha256": digest(issue.get("body")),
                    "parent_body_sha256": digest(parent.get("body")),
                }
            )
        labels = [x["name"] if isinstance(x, dict) else x for x in issue["labels"]]
        milestone = issue.get("milestone")
        tags = [x for x in labels if re.fullmatch(r"milestone:M\d+", x)]
        milestone_tag = re.match(r"M\d+\b", milestone["title"]) if milestone else None
        mismatch = bool(
            len(tags) > 1 or (tags and milestone_tag and tags[0] != "milestone:" + milestone_tag[0])
        )
        gaps = []
        if not labels:
            gaps.append("labels")
        parent = issues.get(declared[0]) if len(declared) == 1 else None
        if not milestone and (tags or (parent and parent.get("milestone"))):
            gaps.append("milestone")
        if milestone and not tags:
            gaps.append("milestone_label")
        rows.append(
            {
                "number": number,
                "url": issue.get("html_url"),
                "title": issue["title"],
                "state": issue["state"],
                "declared_parents": declared,
                "native_parent": actual,
                "status": status,
                "missing_labels": not labels,
                "missing_milestone": milestone is None,
                "milestone_label_conflict": mismatch,
                "classification_gaps": gaps,
                "review_reason": REVIEW_HOLDS.get(number),
            }
        )
    check_cycles(native + proposals)
    return {
        "repository": snapshot["repository"],
        "summary": {
            "issues": len(issues),
            "open": sum(x["state"] == "open" for x in issues.values()),
            "native_edges": len(native),
            "status": dict(Counter(x["status"] for x in rows)),
            "missing_labels": sum(x["missing_labels"] for x in rows),
            "missing_milestone": sum(x["missing_milestone"] for x in rows),
            "milestone_label_conflicts": sum(x["milestone_label_conflict"] for x in rows),
            "classification_gaps": sum(bool(x["classification_gaps"]) for x in rows),
        },
        "issues": rows,
        "proposals": proposals,
    }


class API:
    """Restricted GitHub REST client; no redirect may forward its credential."""

    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("repository must be owner/name")
        if not token:
            raise ValueError("GITHUB_TOKEN is required for live operations")
        self.repository = repository
        self.token = token

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        """Use only repository-relative paths, fail on rate limits or bad shapes."""
        if not path.startswith("/") or ".." in path:
            raise ValueError("invalid repository-relative path")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "maistro-issue-integrity",
            },
        )
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(request, timeout=45) as response:
            return json.load(response)

    def pages(self, path: str) -> list[dict[str, Any]]:
        """Continue through an empty page, not an arbitrary search-result cap."""
        result: list[dict[str, Any]] = []
        for page in range(1, 10001):
            joiner = "&" if "?" in path else "?"
            data = self.request("GET", f"{path}{joiner}per_page=100&page={page}")
            if not isinstance(data, list):
                raise ValueError(f"{path}: expected list")
            if not data:
                return result
            result.extend(data)
        raise ValueError("pagination did not terminate")

    def parent(self, number: int) -> dict[str, Any] | None:
        """Only the specific no-parent response counts as absence."""
        try:
            parent = self.request("GET", f"/issues/{number}/parent")
            if not isinstance(parent, dict):
                raise ValueError("unexpected parent response")
            return parent
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                error = json.load(exc)
                if error.get("message") == "No parent issue found":
                    return None
            raise


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep authentication on the original API origin."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def collect(api: API, with_comments: bool = False) -> dict[str, Any]:
    """Inventory issues, comments and native edges across open and closed states."""
    records = api.pages("/issues?state=all&sort=created&direction=asc")
    issues = [x for x in records if not x.get("pull_request")]
    numbers = [x["number"] for x in issues]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate issue across inventory pages; retry a stable inventory")
    edges: list[dict[str, int]] = []
    comments = {}
    for issue in issues:
        number = issue["number"]
        if with_comments and issue.get("comments"):
            comments[str(number)] = api.pages(f"/issues/{number}/comments")
        summary = issue.get("sub_issues_summary")
        if summary is None or summary.get("total", 0):
            children = api.pages(f"/issues/{number}/sub_issues")
            if summary is not None and len(children) != summary["total"]:
                raise ValueError(f"#{number}: sub-issue count changed during inventory")
            edges.extend({"child": child["number"], "parent": number} for child in children)
    # All same-repository native edges are covered by the parent summaries.
    # The direct parent endpoint is checked again before every POST, including
    # refusal of external parents. Avoid 800 redundant API calls on each cron.
    return {
        "repository": api.repository,
        "issues": issues,
        "native_edges": edges,
        "comments": comments,
    }


def collect_issue(api: API, number: int) -> dict[str, Any]:
    """Validate a newly edited issue and its ancestors without a backlog scan."""
    pending = [number]
    issues: dict[int, Any] = {}
    edges = []
    while pending:
        current = pending.pop()
        if current in issues:
            continue
        if len(issues) >= 100:
            raise ValueError("unexpectedly large ancestor graph")
        issue = api.request("GET", f"/issues/{current}")
        issues[current] = issue
        pending.extend(declared_parents(issue.get("body")))
        parent = api.parent(current)
        if parent:
            if parent["repository_url"] != f"https://api.github.com/repos/{api.repository}":
                raise ValueError(f"#{current}: external parent requires review")
            pending.append(parent["number"])
            edges.append({"child": current, "parent": parent["number"]})
    return {"repository": api.repository, "issues": list(issues.values()), "native_edges": edges}


def validate_source(edge: dict[str, Any], child: dict[str, Any], parent: dict[str, Any]) -> None:
    """Require the reviewed declaration, identities and source bodies."""
    if edge["child"] in REVIEW_HOLDS:
        raise ValueError(f"#{edge['child']}: unresolved ownership")
    if declared_parents(child.get("body")) != [edge["parent"]]:
        raise ValueError(f"#{edge['child']}: declaration changed or ambiguous")
    if child["id"] != edge["child_id"]:
        raise ValueError("issue identity changed")
    for kind, issue in [("child", child), ("parent", parent)]:
        if digest(issue.get("body")) != edge[f"{kind}_body_sha256"]:
            raise ValueError(f"#{issue['number']}: source contract changed")


def verify_parent(api: API, edge: dict[str, Any], parent: dict[str, Any] | None) -> bool:
    """Never replace a parent, including one in another repository."""
    if parent is None:
        return False
    if (
        parent["number"] != edge["parent"]
        or parent["repository_url"] != f"https://api.github.com/repos/{api.repository}"
    ):
        raise ValueError("refusing to replace an existing parent")
    return True


def apply_link(api: API, edge: dict[str, Any], output: Any) -> bool:
    """Revalidate live source and persist intent before a single bounded write."""
    child = api.request("GET", f"/issues/{edge['child']}")
    parent = api.request("GET", f"/issues/{edge['parent']}")
    validate_source(edge, child, parent)
    for kind, issue in [("child", child), ("parent", parent)]:
        comments = api.pages(f"/issues/{issue['number']}/comments") if issue.get("comments") else []
        if ownership_digest(comments) != edge[f"{kind}_ownership_sha256"]:
            raise ValueError(f"#{issue['number']}: ownership discussion changed; review again")
    linked = verify_parent(api, edge, api.parent(edge["child"]))
    if not linked:
        output.write(json.dumps({**edge, "action": "intent"}) + "\n")
        output.flush()
        api.request(
            "POST",
            f"/issues/{edge['parent']}/sub_issues",
            {"sub_issue_id": child["id"], "replace_parent": False},
        )
        time.sleep(1)  # Pace content creation under secondary rate limits.
    if not verify_parent(api, edge, api.parent(edge["child"])):
        raise ValueError("parent read-back failed")
    children = api.pages(f"/issues/{edge['parent']}/sub_issues")
    if child["id"] not in {x["id"] for x in children}:
        raise ValueError("reverse sub-issue read-back failed")
    output.write(
        json.dumps({**edge, "action": "already_linked" if linked else "linked", "verified": True})
        + "\n"
    )
    output.flush()
    return not linked


def apply_links(
    api: API, snapshot: dict[str, Any], manifest: dict[str, Any], journal: Path, limit: int = 25
) -> int:
    """Preflight the entire batch, resume safely, then verify each mutation."""
    if manifest.get("repository") != api.repository:
        raise ValueError("manifest repository mismatch")
    issues = {x["number"]: x for x in snapshot["issues"]}
    edges = manifest["links"]
    if len({x["child"] for x in edges}) != len(edges):
        raise ValueError("duplicate manifest child")
    check_cycles(snapshot["native_edges"] + edges)
    existing = {(x["child"], x["parent"]) for x in snapshot["native_edges"]}
    edges = [x for x in edges if (x["child"], x["parent"]) not in existing][:limit]
    for edge in edges:
        validate_source(edge, issues[edge["child"]], issues[edge["parent"]])
    with journal.open("a", encoding="utf-8") as output:
        return sum(apply_link(api, edge, output) for edge in edges)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Offline inventory JSON")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--output", type=Path, default=Path("issue-integrity-output"))
    parser.add_argument("--apply-manifest", type=Path)
    parser.add_argument("--issue", type=int, help="Validate one issue and its ancestor graph")
    parser.add_argument("--limit", type=int, default=25, choices=range(1, 51), metavar="1..50")
    parser.add_argument(
        "--with-comments",
        action="store_true",
        help="Include full comment history for human review (additional API cost)",
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail when any hierarchy exception remains"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    api = None
    if args.snapshot:
        if args.apply_manifest:
            parser.error("offline snapshots cannot authorize live writes")
        snapshot = json.loads(args.snapshot.read_text())
    else:
        api = API(args.repo or "", os.environ.get("GITHUB_TOKEN", ""))
        if args.issue and args.apply_manifest:
            parser.error("targeted issue checks cannot apply a manifest")
        snapshot = (
            collect_issue(api, args.issue) if args.issue else collect(api, args.with_comments)
        )
    (args.output / "before.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    report = analyze(snapshot)
    (args.output / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    if args.apply_manifest and api:
        manifest = json.loads(args.apply_manifest.read_text())
        changed = apply_links(api, snapshot, manifest, args.output / "mutations.jsonl", args.limit)
        snapshot = collect(api)
        report = analyze(snapshot)
        (args.output / "after.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        (args.output / "after-audit.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Verified new native links: {changed}")
    print(json.dumps(report["summary"], indent=2))
    bad = {
        "missing_parent",
        "ambiguous",
        "review_hold",
        "invalid_reference",
        "conflicting_parent",
        "unclassified",
    }
    return int(
        args.check
        and any(
            x["status"] in bad or x["milestone_label_conflict"] or x["classification_gaps"]
            for x in report["issues"]
            if not args.issue or x["number"] == args.issue
        )
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError, urllib.error.URLError) as error:
        print(f"Issue integrity failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
