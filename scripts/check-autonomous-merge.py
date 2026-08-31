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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH_INDEPENDENCE_REGISTRY = ROOT / "quality" / "branch-independence.json"
QUALITY_PREFIX = "quality/"
BRANCH_INDEPENDENT_EVIDENCE_KINDS = frozenset({"base_derived", "generated"})

AUTO_PREFIXES = (
    "claude/",
    "chatgpt/",
    "codex/",
    "agent/",
    "agents/",
    "rsi/",
    "dependabot/",
    "renovate/",
)
AUTO_LABELS = {"autonomous-merge", "agent-authored", "automerge-agent"}

# A candidate may not redefine the mechanism or policy inputs that decide
# whether candidates are safe. Human changes are allowed, but are never
# autonomously admissible. `quality/**` is handled separately through the
# protected-base branch-independence registry: a generated/base-derived result
# is not the judge once its checker reads the trusted base, while policy,
# legacy, unknown and ambiguous quality state remains trusted by default.
TRUSTED_PATTERNS = (
    ".github/workflows/**",
    ".github/actions/**",
    ".github/branch-protection.json",
    ".github/CODEOWNERS",
    ".gitattributes",
    "CODEOWNERS",
    "scripts/check-*.py",
    "packages/hive-conductor/cage/**",
    "packages/hive-conductor/eval/**",
)

# These surfaces are legitimate to change, but they enlarge blast radius enough
# that the initial autonomous policy requires a human. Include both directory
# families and filename-shaped modules: this repository has important auth,
# graph, scheduling and persistence boundaries represented both ways.
YELLOW_PATTERNS = (
    "pyproject.toml",
    "uv.lock",
    "requirements*.txt",
    "**/requirements*.txt",
    "**/package-lock.json",
    "**/package.json",
    "alembic/**",
    "**/migrations/**",
    "packages/maistro-core/src/maistro/container.py",
    "**/security/**",
    "**/auth/**",
    "**/auth.py",
    "**/auth_*.py",
    "**/*_auth.py",
    "**/vault/**",
    "**/vault.py",
    "**/warden/**",
    "**/warden.py",
    "**/outbound/**",
    "**/outbound.py",
    "**/execution/**",
    "**/execution.py",
    "**/runtime.py",
    "**/runs/**",
    "**/run.py",
    "**/runs.py",
    "**/scheduling/**",
    "**/scheduler.py",
    "**/schedule.py",
    "**/persistence/**",
    "**/persistence.py",
    "**/persisted.py",
    "**/graph/**",
    "**/graph.py",
)

SUPPRESSION_PATTERNS = (
    re.compile(r"\bpytest\.mark\.(?:skip|skipif|xfail)\b"),
    re.compile(r"\bpytest\.skip\s*\("),
    re.compile(r"\bunittest\.(?:skip|skipIf|skipUnless)\b"),
    re.compile(r"#\s*pragma:\s*no\s*cover\b", re.I),
    re.compile(r"#\s*noqa\b", re.I),
    re.compile(r"#\s*type:\s*ignore\b", re.I),
    re.compile(r"#\s*nosec\b", re.I),
    re.compile(r"coverage:\s*ignore", re.I),
)
TEST_DEFINITION_RE = re.compile(r"^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(")
TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+\.(?:test|spec)\.[^/]+)$",
    re.I,
)


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

    def finish(self) -> Assessment:
        if self.red_reasons:
            self.risk = "red"
        elif self.yellow_reasons or self.integrity_reasons:
            self.risk = "yellow"
        else:
            self.risk = "green"
        if self.merge_group:
            self.eligible = not self.red_reasons
        elif self.autonomous:
            self.eligible = self.risk == "green"
        else:
            self.eligible = True
        return self


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _quality_surfaces() -> list[tuple[str, tuple[str, ...]]] | None:
    """Read quality-state classes from the protected-base registry.

    The autonomous-merge checker is executed from the protected base, so this
    registry is protected policy too. A candidate may edit its own copy, but it
    cannot change the classification used to judge that edit. Any unreadable or
    malformed registry fails closed by returning no usable classification.
    """
    try:
        raw = json.loads(BRANCH_INDEPENDENCE_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return None
    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        return None

    classified: list[tuple[str, tuple[str, ...]]] = []
    for surface in surfaces:
        if not isinstance(surface, dict):
            return None
        kind = surface.get("kind")
        paths = surface.get("paths")
        if not isinstance(kind, str) or not kind:
            return None
        if not isinstance(paths, list) or not paths or any(
            not isinstance(path, str) or not path for path in paths
        ):
            return None
        classified.append((kind, tuple(paths)))
    return classified


def _quality_reason(
    path: str,
    surfaces: list[tuple[str, tuple[str, ...]]] | None,
) -> tuple[str, str]:
    """Return the risk class and reason for one `quality/**` path.

    Only a surface already classified by protected-base policy as generated or
    base-derived evidence may leave RED, and it leaves only to YELLOW. Unknown,
    multiply-classified, policy, legacy and durable-decision surfaces remain RED.
    """
    if surfaces is None:
        return "red", f"trusted quality surface changed; classification unavailable: {path}"
    matches = [kind for kind, patterns in surfaces if _matches(path, patterns)]
    if len(matches) != 1:
        detail = "unclassified" if not matches else "ambiguously classified"
        return "red", f"trusted quality surface changed; {detail}: {path}"
    kind = matches[0]
    if kind in BRANCH_INDEPENDENT_EVIDENCE_KINDS:
        return "yellow", f"branch-independent quality evidence changed ({kind}): {path}"
    return "red", f"trusted quality policy/legacy surface changed ({kind}): {path}"


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        "/tests/" in f"/{normalized}"
        or normalized.startswith("tests/")
        or bool(TEST_FILE_RE.search(normalized))
    )


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


def _patch_integrity_findings(patch: str) -> set[str]:
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
                findings.add(f"test definition removed in {current or '<unknown>'}: {body.strip()}")
    return findings


def integrity_findings(patch: str, changed: Iterable[ChangedFile]) -> list[str]:
    findings = _patch_integrity_findings(patch)
    for item in changed:
        if item.status.startswith("D") and _is_test_path(item.path):
            findings.add(f"test file deleted: {item.path}")
        if (
            item.status.startswith("R")
            and item.old_path
            and _is_test_path(item.old_path)
            and not _is_test_path(item.path)
        ):
            findings.add(f"test file moved out of test discovery: {item.old_path} -> {item.path}")
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
    quality_surfaces = _quality_surfaces() if any(
        candidate.startswith(QUALITY_PREFIX)
        for item in changed
        for candidate in ([item.path] if item.old_path is None else [item.path, item.old_path])
    ) else None
    for item in changed:
        result.changed_files.append(item.path)
        candidates = [item.path]
        if item.old_path:
            candidates.append(item.old_path)
        for path in candidates:
            if path.startswith(QUALITY_PREFIX):
                risk, reason = _quality_reason(path, quality_surfaces)
                if risk == "red":
                    result.red_reasons.append(reason)
                else:
                    result.yellow_reasons.append(reason)
            elif _matches(path, TRUSTED_PATTERNS):
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
        capture_output=True,
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
