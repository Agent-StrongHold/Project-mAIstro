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
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WRAPPER = REPO_ROOT / ".github" / "actions" / "setup-uv" / "action.yml"
WRAPPER_REF = "./.github/actions/setup-uv"

#: The action this repository must not call outside the wrapper.
ACTION = "astral-sh/setup-uv"

#: The action release the wrapper must use. Below this there is no tolerance
#: for a transient manifest outage, which is the whole #213 fix.
PINNED_ACTION = f"{ACTION}@v10.0.1"

#: An exact version: three dot-separated numbers and nothing else. A range
#: (`0.5.x`, `>=0.8`, `^1.2`) or `latest` must not match.
EXACT_RE = re.compile(r"^\d+\.\d+\.\d+$")

#: GitHub accepts both spellings for workflow files, so both are scanned.
WORKFLOW_GLOBS = ("*.yml", "*.yaml")


def workflow_files() -> list[Path]:
    return sorted(p for g in WORKFLOW_GLOBS for p in WORKFLOWS.glob(g))


def iter_uses(node: Any):
    """Every ``uses:`` value anywhere in a parsed workflow.

    Walks the whole document rather than assuming jobs->steps: ``uses`` also
    appears at job level for reusable workflows, and a gate that only looked
    where it expected would miss exactly the call it exists to forbid.
    """
    if isinstance(node, dict):
        value = node.get("uses")
        if isinstance(value, str):
            yield value.strip()
        for child in node.values():
            yield from iter_uses(child)
    elif isinstance(node, list):
        for child in node:
            yield from iter_uses(child)


def _line_of(path: Path, needle: str) -> int:
    """Best-effort line number for an error message."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return number
    return 0


def direct_usages() -> list[str]:
    """Workflow steps calling the action directly instead of the wrapper.

    Parsed, not pattern-matched. A regex over raw lines misses valid spellings
    the runner honours all the same — a trailing comment, a quoted scalar — and
    a gate that can be evaded by quoting is not a gate.
    """
    found = []
    for path in workflow_files():
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # actionlint owns malformed workflows; this gate does not
        for value in iter_uses(document):
            if value == ACTION or value.startswith(f"{ACTION}@"):
                found.append(f"{path.relative_to(REPO_ROOT)}:{_line_of(path, value)} -> {value}")
    return found


def wrapper_step() -> dict[str, Any] | None:
    """The wrapper's own ``setup-uv`` step, from its parsed ``runs.steps``.

    Parsed for the reason above and one more: this file's comment block names
    the action and its version repeatedly, so any substring check over the raw
    text is satisfied by the prose explaining the pin rather than by the pin.
    """
    document = yaml.safe_load(WRAPPER.read_text(encoding="utf-8"))
    steps = (document or {}).get("runs", {}).get("steps") or []
    for step in steps:
        if isinstance(step, dict) and str(step.get("uses", "")).startswith(ACTION):
            return step
    return None


def wrapper_version(text: str) -> str | None:
    """The uv version the wrapper pins, or ``None`` if its step pins none."""
    document = yaml.safe_load(text)
    steps = (document or {}).get("runs", {}).get("steps") or []
    for step in steps:
        if isinstance(step, dict) and str(step.get("uses", "")).startswith(ACTION):
            version = (step.get("with") or {}).get("version")
            return None if version is None else str(version)
    return None


def wrapper_problems() -> list[str]:
    """Whether the wrapper exists, pins the right release, and an exact uv."""
    if not WRAPPER.is_file():
        return [f"{WRAPPER.relative_to(REPO_ROOT)} is missing"]
    text = WRAPPER.read_text(encoding="utf-8")
    try:
        step = wrapper_step()
    except yaml.YAMLError as exc:
        return [f"{WRAPPER.relative_to(REPO_ROOT)} is not valid YAML: {exc}"]

    if step is None:
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} has no `runs.steps` entry using {ACTION}. "
            f"Its comments mention the action, which is not the same as invoking it"
        ]
    if step["uses"] != PINNED_ACTION:
        return [
            f"{WRAPPER.relative_to(REPO_ROOT)} uses `{step['uses']}`, not "
            f"`{PINNED_ACTION}`. That release is the actual #213 fix — it tolerates a "
            f"transient manifest outage, and the version it replaced does not. The "
            f"manifest is fetched either way; only the tolerance differs"
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
        for path in workflow_files()
        for value in iter_uses(yaml.safe_load(path.read_text(encoding="utf-8")))
        if value == WRAPPER_REF
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
