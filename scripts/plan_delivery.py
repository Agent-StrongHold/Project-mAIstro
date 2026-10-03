#!/usr/bin/env python3
"""Read-only, acceptance-based delivery planning over a reviewed GitHub snapshot.

This is repository tooling, not a MAIstro execution or backlog authority. It
never fetches credentials, executes evidence commands, closes issues, merges,
or dispatches agents. Supplied evidence is bookkeeping, not an attestation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from graphlib import CycleError, TopologicalSorter
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY = "Agent-StrongHold/Project-mAIstro"
SHA = re.compile(r"[0-9a-f]{40}\Z")
KINDS = {"implement", "integrate", "verify", "decision"}


class PlanError(ValueError):
    """The supplied snapshot cannot support a deterministic plan."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def text(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{name}: nonempty text required")
    return str(value)


def positive(value: Any, name: str, *, zero: bool = False) -> int:
    require(type(value) is int and value >= (0 if zero else 1), f"{name}: invalid integer")
    return int(value)


def strings(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    require(isinstance(value, list), f"{name}: list required")
    result = [text(item, name) for item in value]
    require(len(set(result)) == len(result), f"{name}: duplicate entries")
    require(not nonempty or bool(result), f"{name}: empty list")
    return result


def timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(text(value, "observed_at").replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanError("observed_at: invalid timestamp") from exc
    require(result.tzinfo is not None, "observed_at: timezone required")
    return result.astimezone(UTC)


def scope_path(value: str) -> str:
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and not any(char in value for char in "*?[]:")
        and bool(path.parts),
        f"invalid repository path: {value!r}",
    )
    require(value.rstrip("/") == path.as_posix(), f"noncanonical path: {value!r}")
    return path.as_posix()


def scopes_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if set(left["resources"]) & set(right["resources"]):
        return True
    return any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for a in left["paths"]
        for b in right["paths"]
    )


def validate_scope(row: dict[str, Any]) -> None:
    row["paths"] = [scope_path(p) for p in strings(row.get("paths"), "paths")]
    strings(row.get("resources"), "resources")
    require(bool(row["paths"] or row["resources"]), "an explicit file/resource scope is required")


def task_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(isinstance(snapshot.get("tasks"), list) and bool(snapshot["tasks"]), "tasks required")
    result: dict[str, dict[str, Any]] = {}
    for original in snapshot["tasks"]:
        require(isinstance(original, dict), "task must be an object")
        row = dict(original)
        identifier = text(row.get("id"), "task.id")
        require(identifier not in result, f"duplicate task: {identifier}")
        positive(row.get("issue"), "task.issue")
        positive(row.get("milestone"), "task.milestone", zero=True)
        require(row.get("kind") in KINDS, f"{identifier}: unknown kind")
        require(type(row.get("implemented")) is bool, f"{identifier}: implemented must be boolean")
        positive(row.get("build_points"), "build_points", zero=True)
        positive(row.get("verify_points"), "verify_points")
        strings(row.get("depends_on"), "depends_on")
        strings(row.get("external_blockers"), "external_blockers")
        strings(row.get("acceptance"), "acceptance", nonempty=True)
        strings(row.get("sources"), "sources", nonempty=True)
        require(isinstance(row.get("evidence"), list), "evidence must be a list")
        validate_scope(row)
        result[identifier] = row
    for row in result.values():
        missing = set(row["depends_on"]) - result.keys()
        require(not missing, f"{row['id']}: missing dependency {sorted(missing)}")
    return result


def evidenced(row: dict[str, Any], base_sha: str) -> bool:
    """Credit only this slice's complete, reviewed, exact-base passed evidence."""
    covered: set[str] = set()
    seen: set[str] = set()
    for proof in row["evidence"]:
        require(isinstance(proof, dict), "evidence must be an object")
        criterion = text(proof.get("criterion"), "evidence.criterion")
        require(criterion in row["acceptance"], f"unknown acceptance criterion: {criterion}")
        require(criterion not in seen, f"duplicate evidence for {criterion}")
        seen.add(criterion)
        require(proof.get("result") in {"passed", "failed", "skipped", "error", "pending"}, "unknown evidence result")
        require(bool(SHA.fullmatch(str(proof.get("sha", "")))), "evidence needs SHA")
        for field in ("reference", "command", "author", "reviewer"):
            require(isinstance(proof.get(field, ""), str), f"evidence.{field}: text required")
        valid = (
            proof.get("result") == "passed"
            and proof.get("sha") == base_sha
            and bool(proof.get("reference", "").strip())
            and bool(proof.get("command", "").strip())
            and bool(proof.get("reviewer", "").strip())
            and bool(proof.get("author", "").strip())
            and proof["reviewer"] != proof["author"]
        )
        if valid:
            covered.add(criterion)
    return bool(row["implemented"] and covered == set(row["acceptance"]))


def reservations(snapshot: dict[str, Any], tasks: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(snapshot.get("reservations"), list), "reservations must be a list")
    result = []
    owners = set()
    for original in snapshot["reservations"]:
        require(isinstance(original, dict), "reservation must be an object")
        row = dict(original)
        owner = text(row.get("owner"), "reservation.owner")
        require(owner not in owners, f"duplicate reservation owner: {owner}")
        owners.add(owner)
        require(type(row.get("active")) is bool, "reservation.active must be explicit")
        strings(row.get("tasks"), "reservation.tasks")
        require(not (set(row["tasks"]) - tasks.keys()), "reservation names unknown task")
        text(row.get("reference"), "reservation.reference")
        require(bool(SHA.fullmatch(str(row.get("head_sha", "")))), "reservation needs head SHA")
        validate_scope(row)
        result.append(row)
    return result


def refresh_reasons(snapshot: dict[str, Any], current_sha: str, now: datetime, max_age: int) -> list[str]:
    require(type(snapshot.get("version")) is int and snapshot["version"] == 1, "unsupported snapshot version")
    require(snapshot.get("repository") == REPOSITORY, "wrong repository")
    require(bool(SHA.fullmatch(str(snapshot.get("base_sha", "")))), "base SHA required")
    require(bool(SHA.fullmatch(current_sha)), "current SHA required")
    require(now.tzinfo is not None, "current time must be timezone-aware")
    age = (now - timestamp(snapshot.get("observed_at"))).total_seconds()
    reasons = []
    if snapshot["base_sha"] != current_sha:
        reasons.append("develop changed; re-audit affected evidence and ownership")
    if age < 0 or age > max_age:
        reasons.append("snapshot is future-dated or stale")
    coverage = snapshot.get("coverage")
    require(isinstance(coverage, dict), "coverage required")
    for field in ("open_prs_complete", "branches_complete", "issue_comments_complete"):
        if coverage.get(field) is not True:
            reasons.append(f"incomplete {field}; no absence-of-owner inference")
    return reasons


def issue_states(snapshot: dict[str, Any], tasks: dict[str, Any]) -> dict[int, str]:
    require(isinstance(snapshot.get("issues"), list), "issues required")
    result = {}
    for row in snapshot["issues"]:
        require(isinstance(row, dict), "issue must be an object")
        number = positive(row.get("number"), "issue.number")
        require(number not in result, "duplicate issue")
        require(row.get("state") in {"open", "closed"}, "unknown issue state")
        result[number] = row["state"]
    require({t["issue"] for t in tasks.values()} <= result.keys(), "task issue not fetched")
    return result


def downstream(tasks: dict[str, Any], order: list[str], done: set[str]) -> tuple[dict[str, int], list[str]]:
    children: dict[str, list[str]] = {key: [] for key in tasks}
    for key, row in tasks.items():
        for parent in row["depends_on"]:
            children[parent].append(key)
    lengths: dict[str, int] = {}
    paths: dict[str, list[str]] = {}
    for key in reversed(order):
        row = tasks[key]
        weight = 0 if key in done else row["verify_points"] + (
            0 if row["implemented"] else row["build_points"]
        )
        child = min(children[key], key=lambda x: (-lengths[x], x), default=None)
        lengths[key] = weight + (lengths[child] if child else 0)
        paths[key] = ([] if key in done else [key]) + (paths[child] if child else [])
    root = min(tasks, key=lambda x: (-lengths[x], x))
    return lengths, paths[root]


def recommendation(row: dict[str, Any], done: set[str], held: list[dict[str, Any]]) -> dict[str, Any]:
    owners = [r["owner"] for r in held if row["id"] in r["tasks"]]
    conflicts = [r["owner"] for r in held if r["owner"] not in owners and scopes_overlap(row, r)]
    blockers = [*row["external_blockers"], *[d for d in row["depends_on"] if d not in done]]
    if len(owners) > 1:
        blockers.append("multiple owners; reconcile before editing")
    if conflicts:
        blockers.append("reserved scope: " + ", ".join(sorted(conflicts)))
    action = "continue_existing" if owners else ("verify" if row["implemented"] else row["kind"])
    return {"id": row["id"], "issue": row["issue"], "action": action, "owners": owners,
            "blockers": blockers, "selected": False}


def select_frontier(frontier: list[dict[str, Any]], tasks: dict[str, Any], held: list[dict[str, Any]], limit: int) -> None:
    available = max(0, limit - sum(r["active"] for r in held))
    selected: list[dict[str, Any]] = []
    active_owners = {r["owner"] for r in held if r["active"]}
    selected_owners: set[str] = set()
    for item in frontier:
        existing = bool(set(item["owners"]) & active_owners)
        row = tasks[item["id"]]
        if set(item["owners"]) & selected_owners:
            continue
        if len(selected) >= limit or (not existing and available == 0):
            continue
        if any(scopes_overlap(row, previous) for previous in selected):
            continue
        item["selected"] = True
        selected.append(row)
        selected_owners.update(item["owners"])
        if not existing:
            available -= 1


def plan(snapshot: dict[str, Any], *, current_sha: str, now: datetime, max_age: int = 900, wip: int = 3) -> dict[str, Any]:
    positive(wip, "wip")
    positive(max_age, "max_age")
    refresh = refresh_reasons(snapshot, current_sha, now, max_age)
    tasks = task_map(snapshot)
    states = issue_states(snapshot, tasks)
    held = reservations(snapshot, tasks)
    try:
        order = list(TopologicalSorter({k: r["depends_on"] for k, r in tasks.items()}).static_order())
    except CycleError as exc:
        raise PlanError("dependency cycle; no dispatch") from exc
    evidence_complete = {key for key, row in tasks.items() if evidenced(row, snapshot["base_sha"])}
    done: set[str] = set()
    for key in order:
        row = tasks[key]
        if key in evidence_complete and not row["external_blockers"] and set(row["depends_on"]) <= done:
            done.add(key)
    lengths, critical = downstream(tasks, order, done)
    pending = [recommendation(row, done, held) for key, row in tasks.items() if key not in done]
    for item in pending:
        if states[item["issue"]] == "closed":
            item["blockers"].append("issue closed; reconcile acceptance before implementation")
    pending.sort(key=lambda item: (tasks[item["id"]]["milestone"], -lengths[item["id"]],
                                   item["action"] != "continue_existing", item["id"]))
    frontier = [row for row in pending if not row["blockers"]]
    if not refresh:
        select_frontier(frontier, tasks, held, wip)
    anomalies = sorted({row["issue"] for key, row in tasks.items()
                        if states[row["issue"]] == "closed" and key not in done})
    return {
        "repository": REPOSITORY, "base_sha": snapshot["base_sha"],
        "advisory_only": True, "refresh_required": refresh,
        "coverage": "selected slices only; not a complete milestone forecast",
        "closed_issues_requiring_reconciliation": anomalies,
        "evidenced_slices": sorted(done), "frontier": frontier,
        "blocked": [row for row in pending if row["blockers"]],
        "critical_chain": critical,
        "effort_note": "Relative build + verification points, not hours or calendar dates; external waits excluded.",
        "active_reservations": sum(r["active"] for r in held), "wip_limit": wip,
    }


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--current-sha", required=True, help="freshly fetched develop SHA")
    parser.add_argument("--wip", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        require(isinstance(snapshot, dict), "snapshot must be an object")
        report = plan(snapshot, current_sha=args.current_sha, now=datetime.now(UTC), wip=args.wip)
    except (OSError, ValueError, TypeError) as exc:
        print(f"delivery plan refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["refresh_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
