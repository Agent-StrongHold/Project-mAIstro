#!/usr/bin/env python3
"""A tracked Compose file must not carry a credential anyone can read (#367).

`docker-compose.pm-poc.yml` shipped this, alongside `REQUIRE_AUTH=true`:

    - API_KEYS=alice:changeme-alice,bob:changeme-bob
    - MAISTRO_ROUTER_API_KEY=${API_KEYS:-alice:changeme-alice}

So the overlay read as a ready-to-run authenticated deployment whose keys are
published in this repository, and the `:-` on the second line meant a caller who
set nothing still got the known value rather than an error.

Every other tracked profile already had the right shape -- `${DB_PASSWORD:?Set
DB_PASSWORD in .env}`, `${API_KEYS:?Run ./install.sh to generate API_KEYS}` --
which is what makes this checkable rather than a matter of taste. The rule is
the convention the repository already follows:

**A secret-shaped environment variable in a tracked Compose file is either
required (`${VAR:?message}`) or optional-and-empty (`${VAR:-}`). Never a
literal, and never a non-empty fallback.**

## Why `:-` with a value is the worse half

A bare literal at least looks like what it is. `${API_KEYS:-alice:changeme}`
reads as parameterised -- a reviewer skims it as "comes from the environment" --
and silently supplies the known credential to anyone who does not set it. The
failure is invisible precisely to the person most likely to be affected.

## Not a secret scanner

gitleaks and detect-secrets look for things shaped like real credentials, and
`changeme-alice` is shaped like a placeholder, which is why it was never
flagged. This asks a different question -- "can this file hand someone a working
credential?" -- and a deliberately fake-looking value answers yes just as well
as a realistic one.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Compose files anywhere in the tree, excluding vendored and generated trees.
COMPOSE_GLOBS = (
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "*/docker-compose*.yml",
    "packages/*/docker-compose*.yml",
    "deploy/**/docker-compose*.yml",
    "deploy/**/*.compose.yml",
)

EXCLUDED_PARTS = ("node_modules", ".venv", "third_party", ".git")

#: Names that carry a credential. Substring match, upper-cased, so
#: `LANGFUSE_SECRET_KEY` and `POSTGRES_PASSWORD` are both caught without
#: enumerating every variable this repository will ever add.
SECRET_MARKERS = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "API_KEYS", "MASTER_KEY", "PRIVATE_KEY")

#: `NAME=value`, in either the list form (`- NAME=value`) or the mapping form
#: (`NAME: value`). Leading `#` is handled by the caller: a commented line is
#: documentation, and `.env.example`-style guidance is not a deployment.
_LIST_FORM = re.compile(r"^\s*-\s*([A-Z][A-Z0-9_]*)=(.*)$")
_MAP_FORM = re.compile(r"^\s*([A-Z][A-Z0-9_]*):\s+(\S.*)$")

#: `${VAR:?msg}` — required, refuses to start when unset. Always allowed.
_REQUIRED = re.compile(r"^\$\{[A-Z0-9_]+:\?[^}]*\}$")
#: `${VAR:-}` or `${VAR-}` — optional and empty. Allowed.
_EMPTY_DEFAULT = re.compile(r"^\$\{[A-Z0-9_]+:?-\s*\}$")
#: `${VAR}` — plain substitution, no default. Allowed: unset becomes empty.
_PLAIN = re.compile(r"^\$\{?[A-Z0-9_]+\}?$")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    name: str
    value: str
    why: str


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SECRET_MARKERS)


def classify(value: str) -> str:
    """Return why `value` is unacceptable, or "" when it is fine."""
    stripped = value.strip().strip('"').strip("'")
    if not stripped:
        return ""
    if _REQUIRED.match(stripped) or _EMPTY_DEFAULT.match(stripped) or _PLAIN.match(stripped):
        return ""
    if re.match(r"^\$\{[A-Z0-9_]+:?-.+\}$", stripped):
        return (
            "falls back to a non-empty default, so a caller who sets nothing "
            "still gets this value — use ${VAR:?message} so it refuses to start"
        )
    if stripped.startswith("$"):
        # Some other substitution form. Not a literal, so not a committed
        # credential; left alone rather than guessed at.
        return ""
    return (
        "is a literal value committed to the repository — use ${VAR:?message} "
        "so the deployment refuses to start without one"
    )


def compose_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    seen: set[Path] = set()
    for pattern in COMPOSE_GLOBS:
        for path in repo_root.glob(pattern):
            if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts):
                seen.add(path)
    return sorted(seen)


def scan_text(text: str, *, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        match = _LIST_FORM.match(line) or _MAP_FORM.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        # An inline comment is not part of the value.
        value = value.split(" #", 1)[0].strip()
        if not is_secret_name(name):
            continue
        why = classify(value)
        if why:
            findings.append(Finding(path=path, line_no=line_no, name=name, value=value, why=why))
    return findings


def scan(repo_root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in compose_files(repo_root):
        findings.extend(
            scan_text(path.read_text(encoding="utf-8"), path=str(path.relative_to(repo_root)))
        )
    return findings


def render(findings: list[Finding], scanned: int) -> str:
    if not findings:
        return f"ok: {scanned} tracked Compose file(s) hand out no credential"
    lines = [f"FAIL: {len(findings)} credential(s) committed in a deployment profile", ""]
    for finding in findings:
        lines.append(f"  {finding.path}:{finding.line_no}")
        # The name and the reason, never the value: printing it into a CI log
        # is the same exposure one more time.
        lines.append(f"    {finding.name} {finding.why}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    findings = scan(args.root)
    print(render(findings, len(compose_files(args.root))))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
