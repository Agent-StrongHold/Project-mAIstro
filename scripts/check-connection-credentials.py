#!/usr/bin/env python3
"""A connection default must not carry a literal password (#432).

`packages/maistro-canvas/frontend` shipped the same URL twice:

    # server/models/db.py
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders"
    )
    # alembic.ini
    sqlalchemy.url = postgresql+asyncpg://mcp:mcp@localhost:5441/mcp_orders

Port 5441 is published to the host by that package's Compose profile, so this
was a working credential for a reachable service, published in this repository.

#367 established the same rule for tracked Compose files and added
`check-compose-secrets.py` to hold it. That gate reads Compose YAML, so a
Python module and an ini file were outside it -- which is precisely where these
two survived review. This is the sibling gate for the other two shapes.

## What is checked, and why only this

A URL with inline credentials appears legitimately all over this repository:
in tests for the redaction and URL-parsing code, in docstrings explaining a
format, in the text of the error `require_database_url` raises. Flagging every
`user:pass@host` would bury the finding that matters under dozens that do not,
and a gate people learn to route around protects nothing.

The property that separates them is not the value -- `mcp:mcp` looks as fake as
`user:pass` -- but the **position**. A credential-bearing URL is a finding when
it sits where an unconfigured process will pick it up:

- Python: the default argument of `os.environ.get` / `os.getenv`, or the value
  assigned to a name ending `_URL`, `_URI` or `_DSN`.
- ini/cfg: the value of a `*url` / `*uri` / `*dsn` key, unless it is an
  interpolation (`%(x)s`, `${X}`, `$X`) rather than a literal.

Everything else -- a docstring, a comment, an error message, a test fixture --
is text about a URL rather than a URL something will connect with.

## Not a secret scanner

gitleaks looks for values shaped like real credentials. `mcp:mcp` is shaped
like a placeholder, which is why it was never flagged. This asks the question
`check-compose-secrets.py` asks, in the two file types that gate cannot read:
can an unconfigured process here open a database with a password this
repository already told everyone?
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories that are not this repository's source, or are text *about*
#: connection URLs rather than connection URLs.
EXCLUDED_PARTS = ("node_modules", ".venv", "third_party", ".git", "tests", "test")

#: `scheme://user:secret@host`. The password may not contain `/`, `@` or
#: whitespace, which is what keeps `https://example.com/a:b@c` -- a path, not a
#: userinfo -- from matching.
_CREDENTIALED_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/@\s:]+:[^/@\s]+@")

#: Names whose value is a connection string. Matched on the `_`-delimited tail
#: so `DATABASE_URL` and `SQLALCHEMY_DATABASE_URI` match and `URLLIB_TIMEOUT`
#: does not.
_URL_SUFFIXES = ("URL", "URI", "DSN")

#: ini keys whose value is a connection string, e.g. `sqlalchemy.url`.
_INI_KEY = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*[:=]\s*(\S.*?)\s*$")

#: An ini value that defers to something else rather than stating a credential:
#: configparser interpolation, and the two shell/Compose spellings.
_INTERPOLATED = re.compile(r"%\([^)]+\)s|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    where: str
    why: str


def _has_inline_credentials(value: str) -> bool:
    return bool(_CREDENTIALED_URL.search(value))


def _is_url_name(name: str) -> bool:
    return name.upper().rsplit("_", 1)[-1] in _URL_SUFFIXES


def _env_default(node: ast.Call) -> ast.expr | None:
    """The default argument of `os.environ.get(...)` / `os.getenv(...)`, if any."""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name not in {"get", "getenv"}:
        return None
    if len(node.args) >= 2:
        return node.args[1]
    for keyword in node.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_python(path: Path, text: str) -> list[Finding]:
    """Credential-bearing URLs in a position an unconfigured process would use."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            value = _string(_env_default(node))
            if value and _has_inline_credentials(value):
                findings.append(
                    Finding(
                        _display(path),
                        node.lineno,
                        "environment default",
                        "an unset variable falls back to this credential",
                    )
                )
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            value = _string(node.value)
            if value and _has_inline_credentials(value) and any(_is_url_name(n) for n in names):
                findings.append(
                    Finding(
                        _display(path),
                        node.lineno,
                        f"assignment to {names[0]}",
                        "a connection string with a password nobody had to supply",
                    )
                )
    return findings


def scan_ini(path: Path, text: str) -> list[Finding]:
    """Credential-bearing URLs in a `*url`/`*uri`/`*dsn` ini key."""
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped[0] in "#;[":
            continue
        match = _INI_KEY.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2)
        if not _is_url_name(key.replace(".", "_")):
            continue
        if _INTERPOLATED.search(value) or not _has_inline_credentials(value):
            continue
        findings.append(
            Finding(
                _display(path),
                line_no,
                f"ini key {key}",
                "a connection string with a password nobody had to supply",
            )
        )
    return findings


def _display(path: Path) -> str:
    """Repo-relative where possible; a path outside the tree is not an error."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sources(root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in ("**/*.py", "**/*.ini", "**/*.cfg"):
        for path in sorted(root.glob(pattern)):
            parts = set(path.parts)
            if parts & set(EXCLUDED_PARTS):
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                continue
            paths.append(path)
    return paths


def audit(root: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    paths = _sources(root)
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix == ".py":
            findings.extend(scan_python(path, text))
        else:
            findings.extend(scan_ini(path, text))
    return findings, len(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(REPO_ROOT))
    args = parser.parse_args(argv)

    findings, scanned = audit(Path(args.root).resolve())
    if findings:
        print("FAIL: a connection default carries a literal credential")
        print()
        for finding in findings:
            print(f"  {finding.path}:{finding.line_no} ({finding.where})")
            print(f"      {finding.why}")
        print()
        print(
            "Read the credential from the environment and fail when it is unset, "
            "rather than shipping one. See packages/maistro-canvas/frontend/"
            "server/config.py for the shape (#432)."
        )
        return 1
    print(f"OK: {scanned} source files, no connection default carries a literal credential")
    return 0


if __name__ == "__main__":
    sys.exit(main())
