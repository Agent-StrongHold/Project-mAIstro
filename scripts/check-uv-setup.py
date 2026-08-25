#!/usr/bin/env python3
"""Gate: every workflow installs uv through the one pinned wrapper (#213).

What it catches
---------------
A workflow that calls ``astral-sh/setup-uv`` directly, a wrapper that drops
below the pinned action release, and a wrapper whose uv version stops being an
exact one.

The first two are the #213 fix. The third is not, and the distinction is the
whole lesson of that issue.

**The manifest fetch is unconditional.** #213 assumed pinning the uv version
would avoid the request to

    https://raw.githubusercontent.com/astral-sh/versions/main/v1/uv.ndjson

It does not. Measured on this repository, on PR #264: ``v7`` with an exact
version fetches; ``v7`` with ``latest-known`` fetches and then fails outright
because that selector postdates v7; ``v10.0.1`` with an exact version fetches
too. No value of ``version`` skips it.

What differs is whether a transient failure of that fetch is **fatal**.
``v10.0.1`` ships as "Tolerate transient manifest timeouts". ``v7``, which this
repository used, has no tolerance — that is what killed ``exact-debt-ledger``
on #181 before a single test body ran. So ``PINNED_ACTION`` is the guarded
thing, and dropping back below it silently reinstates the flake.

The uv version is guarded for a different reason: ``quality.yml`` pinned
``0.5.x``, which resolved to uv 0.5.31 while every other job resolved ``latest``
to uv 0.12.5. That is a real defect — two uv versions seven minor releases
apart, split across jobs — but it is a *determinism* defect, not the flake. A
range here is refused because it is not a choice anyone made, not because
exactness removes a network request. It does not.
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

#: The action release the wrapper must use. Below this there is no tolerance
#: for a transient manifest outage, which is the whole #213 fix.
PINNED_ACTION = "astral-sh/setup-uv@v10.0.1"

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
    if f"uses: {PINNED_ACTION}" not in text:
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} does not use `{PINNED_ACTION}`. That "
            f"release is the actual #213 fix — it tolerates a transient manifest "
            f"outage, and the version it replaced does not. The manifest is fetched "
            f"either way; only the tolerance differs"
        ]

    version = wrapper_version(text)
    if version is None:
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} pins no uv version, so the action falls "
            f"back to whatever `latest` resolves to that day. Every job would then run "
            f"an unchosen uv, and two jobs a week apart could run different ones"
        ]
    if not EXACT_RE.match(version):
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} pins `{version}`, which is not an exact "
            f"uv version, so what installs is whatever the manifest happens to offer. "
            f"That was `0.5.x` here, quietly resolving to uv 0.5.31 while every other "
            f"job ran 0.12.5. Exactness is about determinism — it does NOT avoid the "
            f"manifest fetch, which happens either way"
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
            "\nEvery workflow installs uv through .github/actions/setup-uv, which pins both\n"
            f"the action release ({PINNED_ACTION}) and an exact uv version.\n"
            "\n"
            "The action release is the one that matters for CI reliability: the version\n"
            "manifest is fetched from raw.githubusercontent.com no matter what `version`\n"
            "says, and only this release tolerates that fetch failing. The exact uv version\n"
            "buys determinism, not network independence.\n"
            "\n"
            "Change either in the wrapper, never in a workflow. See ADR-082526-3011.",
            file=sys.stderr,
        )
        return 1

    version = wrapper_version(WRAPPER.read_text(encoding="utf-8"))
    print(f"ok: {routed_usages()} workflow step(s) install uv {version} through the wrapper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
