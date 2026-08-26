#!/usr/bin/env python3
"""Classify whether a change is eligible for autonomous merge.

The judge is intended to run from the protected base branch, not from the
candidate tree. It inspects git objects only and never imports candidate code.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

AUTO_PREFIXES = (
    "claude/",
    "chatgpt/",
    "codex/",
    "agent/",
    "agents/",
    "dependabot/",
    "renovate/",
)
AUTO_LABELS = {"autonomous-merge", "agent-authored", "automerge-agent"}

# A candidate may not redefine the mechanism that decides whether candidates
# are safe. Human changes are allowed, but are never autonomously admissible.
TRUSTED_PATTERNS = (
    ".github/workflows/**",
    ".github/actions/**",
    ".github/branch-protection.json",
    "CODEOWNERS",
    "scripts/check-autonomous-merge.py",
    "scripts/check-required-checks.py",
    "scripts/check-branch-protection.py",
    "scripts/check-gates-ran.py",
    "scripts/check-workflow-write-safety.py",
    "quality/*baseline*",
    "quality/**/*baseline*",
    "packages/hive-conductor/cage/**",
    "packages/hive-conductor/eval/**",
)

# These surfaces are legitimate to change, but they enlarge blast radius enough
# that the initial autonomous policy requires a human. We can ratchet specific
# classes back to green after targeted invariant/fault gates exist.
YELLOW_PATTERNS = (
    "pyproject.toml",
    "uv.lock",
    "**/package-lock.json",
    "**/package.json",
    "alembic/**",
    "**/migrations/**",
    "**/security/**",
    "**/auth/**",
    "**/vault/**",
    "**/warden/**",
    "**/outbound/**",
    "**/execution/**",
    "**/runs/**",
    "**/scheduling/**",
    "**/persistence/**",
    "**/graph/**",
)

SUPPRESSION_PATTERNS = (
    re.compile(r"\bpytest\.mark\.(?:skip|skipif|xfail)\b"),
    re.compile(r"#\s*pragma:\s*no\s*cover\b", re.I),
    re.compile(r"#\s*noqa\b", re.I),
    re.compile(r"#\s*type:\s*ignore\b", re.I),
    re.compile(r"#\s*nosec\b", re.I),
    re.compile(r"coverage:\s*ignore", re.I),
)
TEST_DEFINITION_RE = re.compile(r"^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(")


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str
    old_path: str | None = None


@dataclass
class Assessment:
    autonomous: bool
    risk: str
    eligible: bool
    merge_group: bool
    changed_files: list[str] = field(default_factory=list)
    red_reasons: list[str] = field(default_factory=list)
    yellow_reasons: list[str] = field(default_factory=list)
    integrity_reasons: list[str] = field(default_factory=list)

    def finish(self) -> "Assessment":
        if self.red_reasons:
            self.risk = "red"
        elif self.yellow_reasons or self.integrity_reasons:
            self.risk = "yellow"
        else:
            self.risk = "green"
        # Initial policy deliberately allows only green autonomous PRs. Human
        # changes remain mergeable through ordinary review. Merge-group mode
        # has no reliable original branch/label identity, so it only vetoes a
        # trusted-surface change; PR-time admissibility already handled yellow.
        if self.merge_group:
            self.eligible = not self.red_reasons
        elif self.autonomous:
            self.eligible = self.risk == "green"
        else:
            self.eligible = True
        return self


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_autonomous(head_ref: str, labels: Iterable[str], force: bool = False) -> bool:
    if force:
        return True
    normalized = head_ref.removeprefix("refs/heads/")
    return normalized.startswith(AUTO_PREFIXES) or bool(set(labels) & AUTO_LABELS)


def parse_name_status(text: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status = parts[0]
        if status.startswith(("R", "C")):
            if len(parts) != 3:
                raise ValueError(f"unreadable rename/copy row: {raw!r}")
            files.append(ChangedFile(status=status, old_path=parts[1], path=parts[2]))
        else:
            if len(parts) != 2:
                raise ValueError(f"unreadable name-status row: {raw!r}")
            files.append(ChangedFile(status=status, path=parts[1]))
    return files


def integrity_findings(patch: str, changed: Iterable[ChangedFile]) -> list[str]:
    findings: set[str] = set()
    current = ""
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            if any(pattern.search(body) for pattern in SUPPRESSION_PATTERNS):
                findings.add(
                    f"new test/type/security suppression in {current or '<unknown>'}: "
                    f"{body.strip()}"
                )
        elif line.startswith("-") and not line.startswith("---"):
            body = line[1:]
            if TEST_DEFINITION_RE.match(body):
                findings.add(
                    f"test definition removed in {current or '<unknown>'}: {body.strip()}"
                )
    for item in changed:
        is_test_path = "/tests/" in f"/{item.path}" or item.path.startswith("tests/")
        if item.status.startswith("D") and is_test_path:
            findings.add(f"test file deleted: {item.path}")
    return sorted(findings)


def assess(
    changed: list[ChangedFile],
    patch: str,
    *,
    head_ref: str = "",
    labels: Iterable[str] = (),
    force_autonomous: bool = False,
    merge_group: bool = False,
) -> Assessment:
    autonomous = is_autonomous(head_ref, labels, force_autonomous)
    result = Assessment(
        autonomous=autonomous,
        risk="green",
        eligible=False,
        merge_group=merge_group,
    )
    for item in changed:
        result.changed_files.append(item.path)
        candidates = [item.path]
        if item.old_path:
            candidates.append(item.old_path)
        for path in candidates:
            if _matches(path, TRUSTED_PATTERNS):
                result.red_reasons.append(f"trusted CI/eval surface changed: {path}")
            elif _matches(path, YELLOW_PATTERNS):
                result.yellow_reasons.append(f"high-blast-radius surface changed: {path}")
    result.integrity_reasons.extend(integrity_findings(patch, changed))
    result.red_reasons = sorted(set(result.red_reasons))
    result.yellow_reasons = sorted(set(result.yellow_reasons))
    result.integrity_reasons = sorted(set(result.integrity_reasons))
    return result.finish()


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def assess_git(
    repo: Path,
    base: str,
    head: str,
    **kwargs: object,
) -> Assessment:
    # Two-dot is intentional. The workflow passes the exact current base SHA
    # and candidate SHA; for merge_group the head already contains the base.
    changed = parse_name_status(_git(repo, "diff", "--name-status", base, head))
    patch = _git(repo, "diff", "--unified=0", "--no-ext-diff", base, head)
    return assess(changed, patch, **kwargs)


def _labels(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if decoded is None:
        return []
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("--labels-json must decode to a list of strings")
    return decoded


def render(result: Assessment) -> str:
    lines = [
        f"risk={result.risk}",
        f"autonomous={str(result.autonomous).lower()}",
        f"eligible={str(result.eligible).lower()}",
        f"changed_files={len(result.changed_files)}",
    ]
    for title, values in (
        ("RED", result.red_reasons),
        ("YELLOW", result.yellow_reasons),
        ("INTEGRITY", result.integrity_reasons),
    ):
        if values:
            lines.append(f"{title}:")
            lines.extend(f"  - {value}" for value in values)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--labels-json", default="[]")
    parser.add_argument("--force-autonomous", action="store_true")
    parser.add_argument("--merge-group", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--check",
        choices=("all", "trusted", "integrity", "risk", "admissibility"),
        default="all",
        help="select which policy slice controls the exit status",
    )
    return parser


def exit_ok(result: Assessment, check: str) -> bool:
    if check == "trusted":
        return not (result.red_reasons and (result.autonomous or result.merge_group))
    if check == "integrity":
        return not (result.integrity_reasons and result.autonomous and not result.merge_group)
    if check == "risk":
        return True
    return result.eligible


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = assess_git(
            args.repo,
            args.base,
            args.head,
            head_ref=args.head_ref,
            labels=_labels(args.labels_json),
            force_autonomous=args.force_autonomous,
            merge_group=args.merge_group,
        )
    except (RuntimeError, ValueError) as exc:
        print(
            f"ERROR: autonomous merge assessment could not be completed: {exc}",
            file=sys.stderr,
        )
        return 2

    print(render(result))
    if args.json_output:
        args.json_output.write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if exit_ok(result, args.check):
        return 0
    print(
        "Autonomous merge is not admissible; human review/merge is required.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
