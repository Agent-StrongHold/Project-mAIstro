"""GitHub API operations via gh CLI.

Raw `gh --json` output is not agent-sized: PR `files`/`reviews` and issue
`body` fields can run to thousands of tokens of nested JSON. The
_project_* helpers below flatten and truncate that output before it
reaches the model, the same way AtlassianMCPClient projects Jira/Confluence
responses.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

logger = structlog.get_logger()

_MAX_PR_BODY = 4000
_MAX_REVIEW_BODY = 1000
_MAX_ISSUE_BODY = 1000


async def _run_gh(*args: str, timeout: int = 30) -> tuple[int, str]:
    """Run a gh CLI command and return (exit_code, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        return proc.returncode or 0, output
    except FileNotFoundError:
        return 1, "gh CLI binary not found — install GitHub CLI"
    except TimeoutError:
        return 1, f"gh command timed out after {timeout}s"


async def create_pr(
    repo: str,
    branch: str,
    title: str,
    body: str,
    base: str = "main",
) -> dict[str, Any]:
    """Create a pull request via gh CLI.

    Returns {success, exit_code, url, output}. `url` is the created PR's
    URL on success (gh prints it as the last line of stdout) or None.
    """
    code, output = await _run_gh(
        "pr",
        "create",
        "--repo",
        repo,
        "--head",
        branch,
        "--base",
        base,
        "--title",
        title,
        "--body",
        body,
    )
    success = code == 0
    last_line = output.strip().splitlines()[-1].strip() if output.strip() else ""
    url = last_line if success and last_line.startswith("http") else None
    return {"success": success, "exit_code": code, "url": url, "output": output}


def _project_pr(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten gh's PR JSON to title/state/body + lightweight file and review summaries."""
    files = data.get("files")
    files = files if isinstance(files, list) else []
    reviews = data.get("reviews")
    reviews = reviews if isinstance(reviews, list) else []

    changed_files = [
        {
            "path": f.get("path", ""),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
        }
        for f in files
        if isinstance(f, dict)
    ]
    review_summaries = []
    for r in reviews:
        if not isinstance(r, dict):
            continue
        author = r.get("author")
        author_login = author.get("login", "") if isinstance(author, dict) else str(author or "")
        review_summaries.append(
            {
                "author": author_login,
                "state": r.get("state", ""),
                "body": str(r.get("body") or "")[:_MAX_REVIEW_BODY],
            }
        )

    return {
        "title": data.get("title", ""),
        "state": data.get("state", ""),
        "body": str(data.get("body") or "")[:_MAX_PR_BODY],
        "changed_file_count": len(files),
        "changed_files": changed_files,
        "reviews": review_summaries,
    }


async def get_pr(repo: str, number: int) -> dict[str, Any]:
    """Get PR details, projected to an agent-sized shape (see _project_pr)."""
    code, output = await _run_gh(
        "pr",
        "view",
        str(number),
        "--repo",
        repo,
        "--json",
        "title,body,state,files,reviews",
    )
    if code != 0:
        return {"error": output}
    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        logger.warning("gh_pr_invalid_json", repo=repo, number=number, output=output[:200])
        return {"error": f"Invalid JSON from gh: {output[:200]}"}
    if not isinstance(raw, dict):
        return {"error": f"Unexpected gh output shape: {output[:200]}"}
    return _project_pr(raw)


def _project_issue(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten gh's issue JSON: truncate body, flatten label objects to names."""
    labels = data.get("labels")
    labels = labels if isinstance(labels, list) else []
    return {
        "number": data.get("number"),
        "title": data.get("title", ""),
        "body_excerpt": str(data.get("body") or "")[:_MAX_ISSUE_BODY],
        "labels": [lbl.get("name", "") if isinstance(lbl, dict) else str(lbl) for lbl in labels],
    }


async def list_issues(repo: str, limit: int = 10) -> list[dict[str, Any]]:
    """List open issues, projected to an agent-sized shape (see _project_issue)."""
    code, output = await _run_gh(
        "issue",
        "list",
        "--repo",
        repo,
        "--limit",
        str(limit),
        "--json",
        "number,title,body,labels",
    )
    if code == 0:
        try:
            raw = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("gh_issues_invalid_json", repo=repo, output=output[:200])
            return []
        if not isinstance(raw, list):
            return []
        return [_project_issue(i) for i in raw if isinstance(i, dict)]
    return []
