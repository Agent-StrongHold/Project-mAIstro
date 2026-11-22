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

A head that already failed inside the merge queue is not requested again. With
batched groups, GitHub builds one entry per queued PR on top of the entry ahead
of it and, under ALLGREEN, ejects a failing entry and rebuilds everything
behind it; a head that fails on its own tree and is re-queued every scan would
drag each new group through that rebuild. The controller therefore reads the
recent merge-group run history, attributes each failed entry to its own tree or
to a failed entry ahead of it (the entry branch name carries the SHA it was
built on), and quarantines any head whose own entry failed after that head's
``gates-ran`` went green — the earliest moment an entry for it could exist. A
new push (new head) or a human enqueue lifts the quarantine; the bot never
does. If the history cannot be read the controller refuses every admission,
because it cannot prove any head has not already failed.
"""

from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import os
import re
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

#: Pages of merge-group runs (100 each) the quarantine reads. Every queued PR
#: fans out to one run per merge-group workflow (~9 today), so five pages is
#: roughly the last 50 queue entries. A failure older than that is retried
#: once, fails inside the window, and is quarantined from then on — bounded,
#: and far cheaper than reading the full history on every scan.
QUEUE_HISTORY_PAGES = 5

#: The branch GitHub synthesizes for one queue entry. The trailing SHA is the
#: commit the entry was built on: the entry ahead's head, or the base head at
#: the front of the queue. That link is what lets a failure be attributed.
_QUEUE_ENTRY = re.compile(r"^gh-readonly-queue/(?P<base>.+)/pr-(?P<pr>\d+)-(?P<parent>\w+)$")

#: Conclusions that mean the entry's own tree failed verification. ``cancelled``
#: is deliberately absent: GitHub cancels the entries behind a failed one when
#: it rebuilds them, and a head that moved cancels its own entry.
OWN_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure", "action_required"})

#: Conclusions that do not count against an entry ahead: still running, or
#: passed. Anything else (including ``cancelled``) means that entry did not
#: verify, so an entry stacked on it was rebuilt through no fault of its own.
_BENIGN_CONCLUSIONS = frozenset({None, "success", "skipped", "neutral"})


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


@dataclass(frozen=True)
class QueueFailure:
    """One merge-queue entry that failed on its own tree, not behind another."""

    number: int
    parent: str
    created_at: dt.datetime
    workflows: tuple[str, ...]


class GitCommandError(RuntimeError):
    """A failed Git command with its exit status available to callers."""

    def __init__(self, message: str, returncode: int) -> None:
        super().__init__(message)
        self.returncode = returncode


class UnmergeableCandidate(RuntimeError):
    """Expected: the candidate cannot be merged with the current base."""


def candidate_from_pr(pr: dict[str, Any]) -> Candidate:
    try:
        return Candidate(
            number=int(pr["number"]),
            head_sha=str(pr["head"]["sha"]),
            base_ref=str(pr["base"]["ref"]),
            base_sha=str(pr["base"]["sha"]),
            state=str(pr["state"]),
            draft=bool(pr.get("draft", False)),
            auto_merge_requested=pr.get("auto_merge") is not None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("GitHub returned an invalid pull request payload") from exc


def _parse_time(stamp: object) -> dt.datetime:
    """A GitHub timestamp as an aware datetime; anything else is a hard failure."""

    if not isinstance(stamp, str) or not stamp:
        raise RuntimeError(f"GitHub returned an unusable timestamp: {stamp!r}")
    try:
        parsed = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"GitHub returned an unusable timestamp: {stamp!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _behind_failed_entry(
    number: int,
    parent: str,
    entries: dict[tuple[int, str], dict[str, Any]],
    by_head: dict[str, tuple[int, str]],
) -> bool:
    """Whether the chain of entries this one was built on holds a failed one."""

    seen: set[str] = set()
    while parent in by_head and parent not in seen:
        seen.add(parent)
        ahead_key = by_head[parent]
        if ahead_key[0] == number:
            return False
        if entries[ahead_key]["unsuccessful"]:
            return True
        parent = ahead_key[1]
    return False


def own_queue_failures(
    runs: list[dict[str, Any]],
    base: str = BASE_BRANCH,
) -> dict[int, list[QueueFailure]]:
    """Merge-queue entries that failed on their own tree, keyed by PR number.

    One entry is every merge-group run sharing a ``pr-N-<parent>`` branch. An
    entry with a failing run is attributed to itself unless the parent chain
    (its branch's SHA is the head of the entry ahead, and so on) reaches an
    entry of another PR that did not verify — then it was rebuilt behind that
    failure and is not the bad candidate. A parent outside the fetched history
    is treated as the base head, which is the fail-closed reading: the entry
    owns its failure.
    """

    entries: dict[tuple[int, str], dict[str, Any]] = {}
    for run in runs:
        if run.get("event") != "merge_group":
            continue
        match = _QUEUE_ENTRY.match(str(run.get("head_branch") or ""))
        if not match or match.group("base") != base:
            continue
        key = (int(match.group("pr")), match.group("parent"))
        entry = entries.setdefault(
            key, {"heads": set(), "created": None, "failed": set(), "unsuccessful": False}
        )
        head = run.get("head_sha")
        if head:
            entry["heads"].add(str(head))
        conclusion = run.get("conclusion")
        if conclusion in OWN_FAILURE_CONCLUSIONS:
            entry["failed"].add(str(run.get("name") or run.get("id") or "unnamed workflow"))
            created = _parse_time(run.get("created_at"))
            if entry["created"] is None or created < entry["created"]:
                entry["created"] = created
        if conclusion not in _BENIGN_CONCLUSIONS:
            entry["unsuccessful"] = True

    by_head = {head: key for key, entry in entries.items() for head in entry["heads"]}
    failures: dict[int, list[QueueFailure]] = {}
    for (number, parent), entry in entries.items():
        if not entry["failed"] or _behind_failed_entry(number, parent, entries, by_head):
            continue
        failures.setdefault(number, []).append(
            QueueFailure(
                number=number,
                parent=parent,
                created_at=entry["created"],
                workflows=tuple(sorted(entry["failed"])),
            )
        )
    return failures


def queue_failure_for_head(
    candidate: Candidate,
    statuses: list[dict[str, Any]],
    failures: dict[int, list[QueueFailure]],
) -> QueueFailure | None:
    """The own-tree queue failure that quarantines this exact head, if any.

    A queue entry for a head cannot exist before that head's ``gates-ran``
    first succeeded (it is a required context), so an own-tree failure for the
    PR recorded at or after that moment belongs to this head. Failures from
    an earlier head are older than the bound and do not count; a push lifts
    the quarantine by moving the bound past them.
    """

    successes = [
        _parse_time(item.get("created_at"))
        for item in statuses
        if item.get("context") == GATES_CONTEXT and item.get("state") == "success"
    ]
    if not successes:
        return None
    bound = min(successes)
    for failure in sorted(failures.get(candidate.number, []), key=lambda item: item.created_at):
        if failure.created_at >= bound:
            return failure
    return None


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
        raise GitCommandError(
            f"git {' '.join(args)} failed ({proc.returncode}): {detail}",
            proc.returncode,
        )
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

    try:
        merge_tree = _git(
            repo,
            "merge-tree",
            "--write-tree",
            candidate.base_sha,
            candidate.head_sha,
        ).strip()
    except GitCommandError as exc:
        if exc.returncode == 1:
            raise UnmergeableCandidate(
                "candidate does not merge cleanly with the current develop head"
            ) from exc
        raise
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
    """Queue enqueues take the PR head SHA and merge_action only.

    ``merge_method`` is a property of the merge queue itself (pinned to
    SQUASH in .github/merge-queue.json, audited by check-required-checks);
    echoing it into the enqueue mutation is rejected with HTTP 422, which is
    what burst-failed the 09-02 enqueues.
    """
    return {
        "sha": candidate.head_sha,
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
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub API returned invalid JSON") from exc

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

    def merge_group_runs(self) -> list[dict[str, Any]]:
        """Recent merge-group workflow runs, newest first, bounded by pages."""

        runs: list[dict[str, Any]] = []
        for page in range(1, QUEUE_HISTORY_PAGES + 1):
            query = urllib.parse.urlencode({"event": "merge_group", "per_page": 100, "page": page})
            data = self._request("GET", f"/repos/{self._repository}/actions/runs?{query}")
            batch = data.get("workflow_runs") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                raise RuntimeError("GitHub returned an invalid workflow-run listing")
            runs.extend(batch)
            if len(batch) < 100:
                break
        return runs

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


def _admission_hold(
    candidate: Candidate,
    statuses: list[dict[str, Any]],
    quarantine: dict[int, list[QueueFailure]],
) -> tuple[str, bool] | None:
    """Why this head is not requested now, as ``(message, controller_failure)``.

    ``None`` means the head may proceed to policy assessment. A hold is not a
    controller failure unless the evidence itself was unusable.
    """

    if latest_status_state(statuses, GATES_CONTEXT) != "success":
        return f"gates-ran not green on {candidate.head_sha}", False
    try:
        failed = queue_failure_for_head(candidate, statuses, quarantine)
    except RuntimeError as exc:
        return f"queue history unusable: {exc}", True
    if failed is None:
        return None
    return (
        f"quarantined on {candidate.head_sha}: its merge-queue entry failed "
        f"{', '.join(failed.workflows)} at {failed.created_at:%Y-%m-%dT%H:%M:%SZ}; "
        "a new push or a human enqueue lifts this",
        False,
    )


def _admit(
    api: GitHubApi,
    number: int,
    quarantine: dict[int, list[QueueFailure]],
) -> str:
    """One PR's pass through the controller: ``enqueued``, ``held`` or ``failed``."""

    candidate = candidate_from_pr(api.pull_request(number))
    if candidate.auto_merge_requested:
        print(f"PR #{candidate.number}: already requested on {candidate.head_sha}")
        return "held"

    statuses = api.statuses(candidate.head_sha)
    hold = _admission_hold(candidate, statuses, quarantine)
    if hold is not None:
        message, controller_failure = hold
        if controller_failure:
            print(f"PR #{candidate.number}: {message}", file=sys.stderr)
            return "failed"
        print(f"PR #{candidate.number}: {message}")
        return "held"

    try:
        assessment = api.policy_assessment(candidate)
    except UnmergeableCandidate as exc:
        print(f"PR #{candidate.number}: not queueable: {exc}")
        return "held"
    except RuntimeError as exc:
        print(
            f"PR #{candidate.number}: trusted policy evidence failed: {exc}",
            file=sys.stderr,
        )
        return "failed"
    if assessment is None:
        print(f"PR #{candidate.number}: head moved; waiting for new exact-head gates")
        return "held"

    print(f"PR #{candidate.number}: {AUTONOMOUS_POLICY.render(assessment)}")
    if not is_admissible(
        candidate,
        statuses,
        policy_eligible=bool(assessment.eligible),
    ):
        print(f"PR #{candidate.number}: human merge required on {candidate.head_sha}")
        return "held"

    try:
        outcome = api.enqueue(candidate)
    except RuntimeError as exc:
        print(f"PR #{candidate.number}: queue request failed: {exc}", file=sys.stderr)
        return "failed"
    print(f"PR #{candidate.number}: {outcome} on {candidate.head_sha}")
    if outcome in {"accepted", "already-requested"}:
        return "enqueued"
    return "held"


def run(api: GitHubApi) -> int:
    try:
        quarantine = own_queue_failures(api.merge_group_runs())
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        # Without the history no head can be proven not to have failed in the
        # queue already; refusing every admission is the fail-closed answer.
        print(f"merge-group history unreadable; refusing every admission: {exc}", file=sys.stderr)
        return 1

    enqueued = 0
    failures = 0
    for raw_pr in api.open_develop_prs():
        outcome = _admit(api, candidate_from_pr(raw_pr).number, quarantine)
        if outcome == "enqueued":
            enqueued += 1
        elif outcome == "failed":
            failures += 1
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
