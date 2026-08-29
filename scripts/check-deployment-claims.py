#!/usr/bin/env python3
"""Deployment docs may not name a service or backend that does not exist (#81).

`docs/product/DEPLOYMENT-STANCE.md` listed a `maistro-sandbox-worker` in all
four supported profiles, assigned sandbox execution to it, said "official
installs always include a sandbox worker", and claimed the installer verifies
it is "configured and reachable". There is no such package, no such compose
service, and no such check. It also listed Kata Containers as the "recommended
first backend" and offered gVisor as a fallback; neither is implemented, and
the only backend that ships is bubblewrap.

A deployment document is read by an operator deciding what to trust. Naming a
component that does not exist is worse than saying nothing: it converts a known
gap into a believed guarantee, and it survives precisely because nothing
compares the prose to the tree.

Two rules:

1. **Every component named in the supported-profile table resolves.** A name is
   satisfied by a package directory under `packages/`, a service in one of the
   compose files, or an entry in `KNOWN_NON_COMPONENTS` -- the vocabulary of
   things that are legitimately not services (`persistence`, `Hive`).
2. **Every sandbox backend named as shipping resolves to a module.** The tier
   table has a "Ships?" column, so the claim is explicit and checkable: a row
   that says it ships must name a backend module that exists under
   `maistro/sandbox/backends/`.

What this deliberately does not check is the rest of the prose. The limits are
the same as every other document gate here: it holds names to the tree, not
sentences to reality.

Run: python scripts/check-deployment-claims.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANCE = ROOT / "docs" / "product" / "DEPLOYMENT-STANCE.md"
PACKAGES = ROOT / "packages"
BACKENDS = PACKAGES / "maistro-core" / "src" / "maistro" / "sandbox" / "backends"

#: Where a compose service may be declared. A name satisfied by any of these is
#: a real service an operator can run.
COMPOSE_FILES = (
    ROOT / "deploy" / "docker-compose.prod.yml",
    ROOT / "packages" / "hive-conductor" / "docker-compose.yml",
    ROOT / "packages" / "hive-conductor" / "docker-compose.test.yml",
)

#: Words in the Components column that name a capability rather than a
#: deployable unit. Kept explicit so the list is reviewable: adding a name here
#: is a decision, not a silent exemption.
KNOWN_NON_COMPONENTS = frozenset(
    {"persistence", "hive", "ui", "dashboard", "separate vms preferred"}
)

#: `| `full-ui` | maistro-server + Hive + persistence | ... |`
_PROFILE_ROW = re.compile(r"^\|\s*`(?P<profile>[a-z0-9-]+)`\s*\|(?P<components>[^|]*)\|")

#: A row of the tier table, whose third column says whether it ships.
_TIER_ROW = re.compile(
    r"^\|\s*(?P<tier>[^|]*?)\s*\|\s*(?P<backend>[^|]*?)\s*\|\s*(?P<ships>[^|]*?)\s*\|\s*$"
)

_CODE_SPAN = re.compile(r"`([^`]+)`")


def _display(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise.

    `relative_to` raises for a path outside the repo, and both call sites take
    a path a caller can override -- so the crash lands in the error-reporting
    branch, exactly where it is least likely to be exercised and most likely to
    hide the finding it was printing.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class Claim:
    where: str
    name: str
    message: str

    def render(self) -> str:
        return f"{self.where}: {self.message}"


def compose_services(paths: tuple[Path, ...] = COMPOSE_FILES) -> set[str]:
    """Top-level keys under `services:`, read as text.

    Text rather than YAML on purpose: this runs in the lint job, which installs
    no YAML parser, and the shape needed here is one indent level deep.
    """
    found: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        in_services = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("services:"):
                in_services = True
                continue
            if in_services and line and not line[0].isspace():
                in_services = False
            match = re.match(r"^  ([a-z0-9][a-z0-9._-]*):\s*$", line)
            if in_services and match:
                found.add(match.group(1))
    return found


def known_packages(root: Path = PACKAGES) -> set[str]:
    return {path.name for path in root.iterdir() if path.is_dir()} if root.is_dir() else set()


def _resolves(name: str, packages: set[str], services: set[str]) -> bool:
    cleaned = name.strip().strip("`*").lower()
    if not cleaned or cleaned in KNOWN_NON_COMPONENTS:
        return True
    return cleaned in packages or cleaned in services


def profile_claims(text: str, packages: set[str], services: set[str]) -> list[Claim]:
    failures: list[Claim] = []
    for line in text.splitlines():
        match = _PROFILE_ROW.match(line)
        if match is None:
            continue
        for part in match.group("components").split("+"):
            name = part.strip().strip("()").strip()
            if _resolves(name, packages, services):
                continue
            failures.append(
                Claim(
                    f"profile `{match.group('profile')}`",
                    name,
                    f"names {name!r}, which is neither a package under packages/ nor a "
                    "service in any compose file",
                )
            )
    return failures


def backend_claims(text: str, backends: Path = BACKENDS) -> list[Claim]:
    modules = {path.stem for path in backends.glob("*.py")} if backends.is_dir() else set()
    failures: list[Claim] = []
    for line in text.splitlines():
        match = _TIER_ROW.match(line)
        if match is None or not match.group("ships").lower().startswith("**yes"):
            continue
        named = _CODE_SPAN.findall(match.group("backend"))
        if not named:
            failures.append(
                Claim("tier table", match.group("tier"), "says it ships but names no module")
            )
            continue
        for module in named:
            if module.rsplit(".", 1)[-1] not in modules:
                failures.append(
                    Claim(
                        "tier table",
                        module,
                        f"says {module} ships, but no such module exists under "
                        f"{_display(backends)}",
                    )
                )
    return failures


def audit(text: str | None = None) -> list[Claim]:
    body = STANCE.read_text(encoding="utf-8") if text is None else text
    return [
        *profile_claims(body, known_packages(), compose_services()),
        *backend_claims(body),
    ]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)

    if not STANCE.is_file():
        print(f"FAIL: {_display(STANCE)} is missing", file=sys.stderr)
        return 1

    failures = audit()
    if failures:
        print(f"FAIL: {len(failures)} deployment claim(s) name something that does not exist\n")
        for failure in failures:
            print(f"  {failure.render()}")
        print(
            "\nAn operator reads this document to decide what to trust. Name what ships, and "
            "mark what is planned as planned (#81)."
        )
        return 1

    print("OK: every component and shipping backend named in DEPLOYMENT-STANCE.md exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
