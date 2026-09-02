#!/usr/bin/env python3
"""Enqueue every currently bot-admissible PR targeting develop.

This controller runs only from protected default-branch workflow code. It never
checks out or executes candidate code. Candidate git objects are fetched only
for diff inspection, then the repository's base-owned autonomous-merge policy
classifies the candidate's contribution to the prospective merge tree against
the fetched current base. Only policy-green changes whose exact head has
completed ``gates-ran`` successfully may be requested for the merge queue.

The policy is only trustworthy for the revision it was loaded from: if the
fetched base has advanced past the workflow's own checkout, a protected commit
in between may have tightened the policy, and assessing the newer base with the
older policy could classify a newly-sensitive path as green. Assessment
therefore refuses whenever the fetched base differs from the revision this
controller was loaded from, and a trusted run from the newer revision retries.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

API_VERSION = "2026-03-10"
BASE_BRANCH = "develop"
GATES_CONTEXT = "gates-ran"
POLICY_PATH = Path(__file__).with_name("check-autonomous-merge.py")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "maistro_trusted_autonomous_merge_policy",
        POLICY_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load autonomous merge policy from {POLICY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUTONOMOUS_POLICY = _load_policy()


@dataclass(frozen=True)
class Candidate:
    number: int
    head_sha: str
    base_ref: str
    base_sha: str
    state: str
    draft: bool
    auto_merge_requested: bool = False


def candidate_from_pr(pr: dict[str, Any]) -> Candidate:
    return Candidate(
        number=int(pr["number"]),
        head_sha=str(pr["head"]["sha"]),
        base_ref=str(pr["base"]["ref"]),
        base_sha=str(pr["base"]["sha"]),
        state=str(pr["state"]),
        draft=bool(pr.get("draft", False)),
        auto_merge_requested=pr.get("auto_merge") is not None,
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


def _git_bytes(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode:
        stderr = proc.stderr
        detail = (
            stderr.decode("utf-8", errors="replace").strip()
            if isinstance(stderr, bytes)
            else str(stderr).strip()
        )
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {detail}")
    stdout = proc.stdout
    return stdout if isinstance(stdout, bytes) else str(stdout).encode("utf-8")


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> str:
    raw = _git_bytes(repo, *args, env=env)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"git {' '.join(args)} returned non-UTF-8 output") from exc


def _git_auth_env(token: str) -> dict[str, str]:
    """Provide read auth to one git subprocess without persisting credentials."""

    env = os.environ.copy()
    try:
        slot = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError as exc:
        raise RuntimeError("GIT_CONFIG_COUNT is not an integer") from exc
    credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env["GIT_CONFIG_COUNT"] = str(slot + 1)
    env[f"GIT_CONFIG_KEY_{slot}"] = "http.https://github.com/.extraheader"
    env[f"GIT_CONFIG_VALUE_{slot}"] = f"AUTHORIZATION: basic {credential}"
    return env


def _path(raw: bytes) -> str:
    """Decode a Git pathname without allowing invalid bytes to crash rendering."""

    return raw.decode("utf-8", errors="replace")


def _parse_name_status_z(raw: bytes) -> list[Any]:
    """Parse ``git diff --name-status -z`` without C-quoted pathname ambiguity."""

    fields = raw.split(b"\0")
    if not fields or fields[-1] != b"":
        raise RuntimeError("git name-status output is not NUL terminated")
    fields.pop()
    changed: list[Any] = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise RuntimeError("git name-status emitted a non-ASCII status") from exc
        index += 1
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                raise RuntimeError(f"incomplete git rename/copy record: {status}")
            old_path = _path(fields[index])
            path = _path(fields[index + 1])
            index += 2
            changed.append(
                AUTONOMOUS_POLICY.ChangedFile(
                    status=status,
                    old_path=old_path,
                    path=path,
                )
            )
            continue
        if index >= len(fields):
            raise RuntimeError(f"incomplete git name-status record: {status}")
        path = _path(fields[index])
        index += 1
        changed.append(AUTONOMOUS_POLICY.ChangedFile(status=status, path=path))
    return changed


def policy_assessment(repo: Path, candidate: Candidate) -> Any:
    """Classify the candidate's contribution to its prospective merge tree.

    Comparing the fetched current base tree with Git's prospective merge result
    keeps unrelated changes that landed on ``develop`` out of the candidate's
    policy evidence while still exposing rename/modify carry-through at the
    path it would occupy after merging. The diff is read as bytes and pathnames
    are parsed from NUL-delimited records so candidate-controlled encoding and
    quoting cannot alter the trusted-path classification.
    """

    merge_tree = _git(
        repo,
        "merge-tree",
        "--write-tree",
        candidate.base_sha,
        candidate.head_sha,
    ).strip()
    if not merge_tree:
        detail = (
            "no merge base-compatible prospective merge tree for "
            f"{candidate.base_sha} and {candidate.head_sha}"
        )
        raise RuntimeError(detail)
    _git(repo, "cat-file", "-e", f"{merge_tree}^{{tree}}")

    changed = _parse_name_status_z(
        _git_bytes(
            repo,
            "diff",
            "--name-status",
            "-z",
            candidate.base_sha,
            merge_tree,
        )
    )
    patch_bytes = _git_bytes(
        repo,
        "diff",
        "--unified=0",
        "--no-ext-diff",
        candidate.base_sha,
        merge_tree,
    )
    try:
        patch = patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        detail = "candidate diff contains non-UTF-8 content; human merge required"
        raise RuntimeError(detail) from exc
    return AUTONOMOUS_POLICY.assess(
        changed,
        patch,
        force_autonomous=True,
    )


def is_admissible(
    candidate: Candidate,
    statuses: list[dict[str, Any]],
    *,
    policy_eligible: bool,
) -> bool:
    """Whether the repository-owned bot may request queue admission."""

    return (
        candidate.state == "open"
        and not candidate.draft
        and not candidate.auto_merge_requested
        and candidate.base_ref == BASE_BRANCH
        and policy_eligible
        and latest_status_state(statuses, GATES_CONTEXT) == "success"
    )


def merge_async_payload(candidate: Candidate) -> dict[str, str]:
    return {
        "sha": candidate.head_sha,
        "merge_method": "squash",
        "merge_action": "merge_queue",
    }


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except OSError:
        raw = b""
    if not raw:
        return str(exc.reason or "no response body")
    return raw.decode("utf-8", errors="replace").strip()


class GitHubApi:
    def __init__(
        self,
        read_token: str,
        queue_token: str,
        repository: str,
        repo: Path = REPOSITORY_ROOT,
        controller_revision: str | None = None,
    ) -> None:
        self._read_token = read_token
        self._queue_token = queue_token
        self._repository = repository
        self._repo = repo
        self._controller_revision = controller_revision
        self._assessed_bases: dict[tuple[int, str], str] = {}

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

    def pull_request(self, number: int) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/repos/{self._repository}/pulls/{number}",
        )
        assert isinstance(data, dict)
        return data

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/repos/{self._repository}/commits/{sha}/statuses?per_page=100",
        )
        assert isinstance(data, list)
        return data

    def _fetch_base(self) -> str:
        _git(
            self._repo,
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/heads/{BASE_BRANCH}:refs/remotes/origin/{BASE_BRANCH}",
            env=_git_auth_env(self._read_token),
        )
        return _git(
            self._repo,
            "rev-parse",
            f"refs/remotes/origin/{BASE_BRANCH}",
        ).strip()

    def policy_assessment(self, candidate: Candidate) -> Any | None:
        """Fetch candidate objects and classify them; never check candidate code out."""

        remote_ref = f"refs/remotes/maistro-queue/pr-{candidate.number}"
        _git(
            self._repo,
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/heads/{BASE_BRANCH}:refs/remotes/origin/{BASE_BRANCH}",
            f"+refs/pull/{candidate.number}/head:{remote_ref}",
            env=_git_auth_env(self._read_token),
        )
        actual_head = _git(self._repo, "rev-parse", remote_ref).strip()
        if actual_head != candidate.head_sha:
            # The PR changed after the exact-head gate evidence was read. A new
            # Gates Ran completion for the new SHA will retry this controller.
            return None
        current_base = _git(
            self._repo,
            "rev-parse",
            f"refs/remotes/origin/{BASE_BRANCH}",
        ).strip()
        if self._controller_revision and current_base != self._controller_revision:
            # The policy module was loaded from the workflow's checkout. A base
            # that has advanced past it may carry a tightened policy this
            # process never loaded, so evidence computed against that base with
            # the older policy is not trustworthy. Refuse loudly; the run
            # triggered from the newer revision carries the matching policy.
            raise RuntimeError(
                f"fetched {BASE_BRANCH} head {current_base} does not match "
                f"{self._controller_revision}, the revision this controller and "
                "its policy were loaded from; refusing stale-policy assessment"
            )
        for sha in (candidate.base_sha, current_base, candidate.head_sha):
            _git(self._repo, "cat-file", "-e", f"{sha}^{{commit}}")
        current = Candidate(
            number=candidate.number,
            head_sha=candidate.head_sha,
            base_ref=candidate.base_ref,
            base_sha=current_base,
            state=candidate.state,
            draft=candidate.draft,
            auto_merge_requested=candidate.auto_merge_requested,
        )
        assessment = policy_assessment(self._repo, current)
        self._assessed_bases[(candidate.number, candidate.head_sha)] = current_base
        return assessment

    def enqueue(self, candidate: Candidate) -> str:
        assessed_base = self._assessed_bases.get((candidate.number, candidate.head_sha))
        if assessed_base is not None and self._fetch_base() != assessed_base:
            return "base-moved"
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

            detail = _http_error_detail(exc)
            if exc.code == 422:
                # A human/agent may have armed auto-merge after our last PR
                # read. Treat that race as idempotent; a genuinely unarmed 422
                # remains a hard failure with GitHub's body preserved.
                latest = candidate_from_pr(self.pull_request(candidate.number))
                if latest.auto_merge_requested:
                    return "already-requested"
            raise RuntimeError(
                f"merge-async rejected PR #{candidate.number} with HTTP {exc.code}: {detail}"
            ) from exc


def run(api: GitHubApi) -> int:
    enqueued = 0
    failures = 0
    for raw_pr in api.open_develop_prs():
        listed = candidate_from_pr(raw_pr)
        candidate = candidate_from_pr(api.pull_request(listed.number))

        if candidate.auto_merge_requested:
            print(f"PR #{candidate.number}: already requested on {candidate.head_sha}")
            continue

        statuses = api.statuses(candidate.head_sha)
        if latest_status_state(statuses, GATES_CONTEXT) != "success":
            print(f"PR #{candidate.number}: gates-ran not green on {candidate.head_sha}")
            continue

        try:
            assessment = api.policy_assessment(candidate)
        except RuntimeError as exc:
            failures += 1
            print(
                f"PR #{candidate.number}: trusted policy evidence failed: {exc}",
                file=sys.stderr,
            )
            continue
        if assessment is None:
            print(f"PR #{candidate.number}: head moved; waiting for new exact-head gates")
            continue

        print(f"PR #{candidate.number}: {AUTONOMOUS_POLICY.render(assessment)}")
        if not is_admissible(
            candidate,
            statuses,
            policy_eligible=bool(assessment.eligible),
        ):
            print(f"PR #{candidate.number}: human merge required on {candidate.head_sha}")
            continue

        try:
            outcome = api.enqueue(candidate)
        except RuntimeError as exc:
            failures += 1
            print(f"PR #{candidate.number}: queue request failed: {exc}", file=sys.stderr)
            continue
        print(f"PR #{candidate.number}: {outcome} on {candidate.head_sha}")
        if outcome in {"accepted", "already-requested"}:
            enqueued += 1
    print(f"bot queue requests: {enqueued}; controller failures: {failures}")
    return 1 if failures else 0


def main() -> int:
    read_token = os.environ.get("GH_TOKEN", "")
    queue_token = os.environ.get("MERGE_QUEUE_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    controller_revision = os.environ.get("GITHUB_SHA", "")
    if not read_token:
        print("GH_TOKEN is required", file=sys.stderr)
        return 2
    if not queue_token:
        print("MERGE_QUEUE_TOKEN is required", file=sys.stderr)
        return 2
    if "/" not in repository:
        print("GITHUB_REPOSITORY must be owner/repo", file=sys.stderr)
        return 2
    if not controller_revision:
        # Without the checkout revision the policy cannot be bound to the base
        # it judges, and an unverifiable binding is a refusal, not a default.
        print("GITHUB_SHA is required", file=sys.stderr)
        return 2
    return run(
        GitHubApi(
            read_token,
            queue_token,
            repository,
            controller_revision=controller_revision,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
