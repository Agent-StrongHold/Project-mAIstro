#!/usr/bin/env python3
"""Gate: every workflow installs uv through the one pinned wrapper (#213).

What it catches
---------------
A workflow that calls ``astral-sh/setup-uv`` directly, and a wrapper whose
version stops being an exact one.

Both matter for the same reason, and it is not tidiness. ``setup-uv`` resolves
its ``version`` input through ``CONCRETE_VERSION_RESOLVERS`` in
``src/version/resolve.ts``: an **exact** version is served by the exact
resolver and returns with no network call, while ``latest`` and any semantic
range fall through to resolvers that fetch

    https://raw.githubusercontent.com/astral-sh/versions/main/v1/uv.ndjson

That fetch failed ``exact-debt-ledger`` on #181 before a single test ran, on a
commit that only edited a markdown table. It is an external request on the
critical path of jobs that have nothing to do with the network.

So the two failures this gate prevents are:

1. **A direct usage.** #213 asks for the mechanism to be applied uniformly,
   because "a mix of pinned and floating usages means the flake merely gets
   rarer and harder to attribute". One unrouted job restores the dependency for
   that job and makes the next failure harder to read, not easier.
2. **A range in the wrapper.** ``version: "0.5.x"`` *looks* like a pin and
   protects nothing — it resolved over the network to uv 0.5.31 while every
   unpinned job resolved ``latest`` over the network to uv 0.12.5. A gate that
   only counted direct usages would have called that state compliant.

``latest-known`` also skips the fetch, and is deliberately not accepted here: it
installs whatever version the action's own release happens to know about, which
is a version nobody in this repository chose. ADR-082526-3011 records that.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WRAPPER = REPO_ROOT / ".github" / "actions" / "setup-uv" / "action.yml"
WRAPPER_REF = "./.github/actions/setup-uv"

#: `uses: astral-sh/setup-uv@v7` — the call this gate exists to centralise.
DIRECT_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*astral-sh/setup-uv(?:@\S+)?\s*$")

#: `version: "0.12.5"` inside the wrapper.
VERSION_RE = re.compile(r"^\s*version:\s*[\"']?([^\"'\s]+)[\"']?\s*$")

#: An exact version: three dot-separated numbers and nothing else. A range
#: (`0.5.x`, `>=0.8`, `^1.2`) or `latest` must not match.
EXACT_RE = re.compile(r"^\d+\.\d+\.\d+$")


def direct_usages() -> list[str]:
    """Workflow lines calling ``astral-sh/setup-uv`` instead of the wrapper."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DIRECT_RE.match(line):
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    return found


def wrapper_version(text: str) -> str | None:
    """The version the wrapper pins, or ``None`` if it pins none."""
    for line in text.splitlines():
        if (m := VERSION_RE.match(line)) and not line.lstrip().startswith("#"):
            return m.group(1)
    return None


def wrapper_problems() -> list[str]:
    """Whether the wrapper exists, is used, and pins an exact version."""
    if not WRAPPER.is_file():
        return [f"{WRAPPER.relative_to(REPO_ROOT)} is missing"]
    text = WRAPPER.read_text(encoding="utf-8")
    if "astral-sh/setup-uv" not in text:
        return [f"{WRAPPER.relative_to(REPO_ROOT)} no longer wraps astral-sh/setup-uv"]

    version = wrapper_version(text)
    if version is None:
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} pins no version, so the action falls back "
            f"to `latest` and resolves it over the network — the failure #213 is about"
        ]
    if not EXACT_RE.match(version):
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} pins `{version}`, which is not an exact "
            f"version. Only an exact version skips the manifest fetch; a range looks "
            f"like a pin and protects nothing (that was `0.5.x`, resolving over the "
            f"network to 0.5.31)"
        ]
    return []


def routed_usages() -> int:
    """How many workflow steps go through the wrapper."""
    return sum(
        1
        for path in WORKFLOWS.glob("*.yml")
        for line in path.read_text(encoding="utf-8").splitlines()
        if WRAPPER_REF in line and "uses:" in line
    )


def main() -> int:
    problems = wrapper_problems()

    if direct := direct_usages():
        problems.append(
            "workflow steps call astral-sh/setup-uv directly instead of "
            f"`uses: {WRAPPER_REF}`:\n         " + "\n         ".join(direct)
        )

    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(
            "\nEvery workflow installs uv through .github/actions/setup-uv, which pins one\n"
            "exact version. Exact is the whole point: setup-uv resolves a range or `latest`\n"
            "by fetching raw.githubusercontent.com, and that fetch has already failed a job\n"
            "before any test ran (#181). Change the version in the wrapper, not in a\n"
            "workflow. See ADR-082526-3011.",
            file=sys.stderr,
        )
        return 1

    version = wrapper_version(WRAPPER.read_text(encoding="utf-8"))
    print(f"ok: {routed_usages()} workflow step(s) install uv {version} through the wrapper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
