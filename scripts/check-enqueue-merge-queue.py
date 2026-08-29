#!/usr/bin/env python3
"""Enqueue every currently admissible PR targeting develop.

This controller is intended to run only from protected default-branch workflow
code. It never checks out or executes candidate code. Admission is bound to the
PR's exact current head SHA and requires both trusted admission signals to be
successful on that SHA before asking GitHub to add the PR to the merge queue.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

API_VERSION = "2026-03-10"
BASE_BRANCH = "develop"
GATES_CONTEXT = "gates-ran"
ADMISSION_CHECK = "autonomous-merge-admissibility"


@dataclass(frozen=True)
class Candidate:
    number: int
    head_sha: str
    base_ref: str
    state: str
    draft: bool


def candidate_from_pr(pr: dict[str, Any]) -> Candidate:
    return Candidate(
        number=int(pr["number"]),
        head_sha=str(pr["head"]["sha"]),
        base_ref=str(pr["base"]["ref"]),
        state=str(pr["state"]),
        draft=bool(pr.get("draft", False)),
    )


def latest_status_state(statuses: list[dict[str, Any]], context: str) -> str | None:
    matches = [item for item in statuses if item.get("context") == context]
    if not matches:
        return None
    latest = max(
        matches,
        key=lambda item: str(item.get("created_at") or ""),
    )
    state = latest.get("state")
    return str(state) if state is not None else None


def latest_check_conclusion(checks: list[dict[str, Any]], name: str) -> str | None:
    matches = [item for item in checks if item.get("name") == name]
    if not matches:
        return None
    latest = max(
        matches,
        key=lambda item: str(
            item.get("completed_at") or item.get("started_at") or ""
        ),
    )
    conclusion = latest.get("conclusion")
    return str(conclusion) if conclusion is not None else None


def is_admissible(
    candidate: Candidate,
    statuses: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> bool:
    return (
        candidate.state == "open"
        and not candidate.draft
        and candidate.base_ref == BASE_BRANCH
        and latest_status_state(statuses, GATES_CONTEXT) == "success"
        and latest_check_conclusion(checks, ADMISSION_CHECK) == "success"
    )


def merge_async_payload(candidate: Candidate) -> dict[str, str]:
    return {
        "sha": candidate.head_sha,
        "merge_method": "squash",
        "merge_action": "merge_queue",
    }


class GitHubApi:
    def __init__(self, read_token: str, queue_token: str, repository: str) -> None:
        self._read_token = read_token
        self._queue_token = queue_token
        self._repository = repository

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        token: str | None = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.github.com{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token or self._read_token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "maistro-merge-queue-controller",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return None if not raw else json.loads(raw.decode("utf-8"))

    def open_develop_prs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode(
                {
                    "state": "open",
                    "base": BASE_BRANCH,
                    "per_page": 100,
                    "page": page,
                },
            )
            batch = self._request(
                "GET",
                f"/repos/{self._repository}/pulls?{query}",
            )
            assert isinstance(batch, list)
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self._repository}/commits/{sha}/statuses?per_page=100",
        )
        assert isinstance(data, list)
        return data

    def admission_checks(self, sha: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "check_name": ADMISSION_CHECK,
                "filter": "latest",
                "per_page": 100,
            },
        )
        data = self._request(
            "GET",
            f"/repos/{self._repository}/commits/{sha}/check-runs?{query}",
        )
        assert isinstance(data, dict)
        checks = data.get("check_runs", [])
        assert isinstance(checks, list)
        return checks

    def enqueue(self, candidate: Candidate) -> str:
        try:
            self._request(
                "PUT",
                f"/repos/{self._repository}/pulls/{candidate.number}/merge-async",
                merge_async_payload(candidate),
                token=self._queue_token,
            )
            return "accepted"
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                return "already-requested"
            if exc.code == 400:
                return "not-ready"
            raise


def run(api: GitHubApi) -> int:
    enqueued = 0
    for raw_pr in api.open_develop_prs():
        candidate = candidate_from_pr(raw_pr)
        statuses = api.statuses(candidate.head_sha)
        checks = api.admission_checks(candidate.head_sha)
        if not is_admissible(candidate, statuses, checks):
            print(f"PR #{candidate.number}: not admissible on {candidate.head_sha}")
            continue
        outcome = api.enqueue(candidate)
        print(f"PR #{candidate.number}: {outcome} on {candidate.head_sha}")
        if outcome in {"accepted", "already-requested"}:
            enqueued += 1
    print(f"admissible queue requests: {enqueued}")
    return 0


def main() -> int:
    read_token = os.environ.get("GH_TOKEN", "")
    queue_token = os.environ.get("MERGE_QUEUE_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not read_token:
        print("GH_TOKEN is required", file=sys.stderr)
        return 2
    if not queue_token:
        print("MERGE_QUEUE_TOKEN is required", file=sys.stderr)
        return 2
    if "/" not in repository:
        print("GITHUB_REPOSITORY must be owner/repo", file=sys.stderr)
        return 2
    return run(GitHubApi(read_token, queue_token, repository))


if __name__ == "__main__":
    raise SystemExit(main())
