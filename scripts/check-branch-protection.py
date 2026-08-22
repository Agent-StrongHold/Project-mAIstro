#!/usr/bin/env python3
"""Keep `.github/branch-protection.json` honest against the workflows (#162).

Branch protection names required checks as **strings**. Nothing in GitHub links
that string back to the job meant to produce it, so a renamed job silently stops
being required and the protection rule keeps reporting green — the failure is
invisible by construction. `docs/ci/REQUIRED-CHECKS.md` (#161) pins the names
CI actually produces; this pins the ruleset against that, so the drift fails a
build instead of going unnoticed until something red merges.

Three offline rules, none of which needs a token or network:

1. **Every required context is a real check name.** A typo or a rename detaches
   the requirement from the job.
2. **No branch requires a check that cannot report there.** A required check
   whose workflow does not trigger never reports, and classic branch protection
   leaves the PR waiting on an `Expected` status forever. CodeQL and the
   container scan are base-coupled to `main`, so they are requirable on `main`
   and not on `develop`.
3. **Every PR check is required somewhere or listed as advisory with a reason.**
   This is the rule with teeth: adding a gate to CI now forces a decision about
   whether it belongs to the merge contract, rather than defaulting to advisory
   by being forgotten. Forgetting is how a gate ends up run, read, and
   unenforced — which is the state #162 was filed to end.

With `--verify` and a token in `GH_TOKEN`/`GITHUB_TOKEN` it also compares the
live protection against this file. That half needs admin scope to read
protection at all, so it is opt-in rather than part of the PR gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RULESET = ROOT / ".github" / "branch-protection.json"
CONTRACT_GATE = ROOT / "scripts" / "check-required-checks.py"
REPO = "Agent-StrongHold/Project-mAIstro"

#: Keys compared against the live API. `restrictions` is excluded: the API
#: returns a populated object where the request takes `null`, so a field-by-field
#: comparison would report a difference that cannot be resolved by editing
#: either side.
VERIFIED_KEYS = (
    "enforce_admins",
    "required_linear_history",
    "allow_force_pushes",
    "allow_deletions",
    "required_conversation_resolution",
    "block_creations",
    "lock_branch",
)


def _contract() -> Any:
    """Import the #161 gate rather than re-parsing the workflows.

    Two readers of one contract drift, and the drift would be silent in exactly
    the direction that matters — this file believing a check exists that CI no
    longer emits.
    """
    spec = importlib.util.spec_from_file_location("check_required_checks", CONTRACT_GATE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot import {CONTRACT_GATE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_ruleset() -> dict[str, Any]:
    return json.loads(RULESET.read_text(encoding="utf-8"))


def _audit_branch(branch: str, rule: dict, every_name: set, coupled_names: set) -> list[str]:
    """Rules 1 and 2, for one branch."""
    problems: list[str] = []
    contexts = rule["required_status_checks"]["contexts"]
    duplicates = {c for c in contexts if contexts.count(c) > 1}
    if duplicates:
        problems.append(f"{branch}: context listed twice: {', '.join(sorted(duplicates))}")
    for context in contexts:
        if context not in every_name:
            problems.append(
                f"{branch}: required context {context!r} matches no job in "
                f".github/workflows — a rename detached it from its job"
            )
        elif context in coupled_names and branch != "main":
            problems.append(
                f"{branch}: required context {context!r} is base-coupled to `main`, so it "
                f"never reports on a {branch}-based PR and would wait on `Expected` forever"
            )
    return problems


def _audit_coverage(every_name: set, required: set, advisory: dict) -> list[str]:
    """Rule 3: every PR check is required somewhere, or excused by name."""
    problems: list[str] = []
    for name in sorted(every_name - required - set(advisory)):
        problems.append(
            f"PR check {name!r} is neither required on any branch nor listed under "
            f'"advisory" with a reason — decide which it is'
        )
    for name in sorted(advisory):
        if name not in every_name:
            problems.append(f"advisory entry {name!r} matches no PR check; drop it")
        if name in required:
            problems.append(f"{name!r} is both required and listed as advisory")
        if not str(advisory[name]).strip():
            problems.append(f"advisory entry {name!r} has no reason")
    return problems


def audit(ruleset: dict[str, Any], rows: list[tuple[str, str, str]], coupled: set) -> list[str]:
    """The three offline rules. Returns one line per violation."""
    every_name = {check for _, check, _ in rows}
    # A base-coupled check is requirable only on the branch it is coupled to,
    # and today every one of them is coupled to `main`.
    coupled_names = {check for _, check in coupled}
    branches: dict[str, Any] = ruleset["branches"]

    problems: list[str] = []
    required: set[str] = set()
    for branch, rule in branches.items():
        required.update(rule["required_status_checks"]["contexts"])
        problems.extend(_audit_branch(branch, rule, every_name, coupled_names))

    advisory = {k: v for k, v in ruleset.get("advisory", {}).items() if not k.startswith("$")}
    problems.extend(_audit_coverage(every_name, required, advisory))
    return problems


def _get(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _live_protection(branch: str, token: str) -> tuple[dict | None, str | None]:
    """The live rule, or a one-line reason there is none to compare."""
    url = f"https://api.github.com/repos/{REPO}/branches/{branch}/protection"
    try:
        return _get(url, token), None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, f"FAIL: {branch} is not protected (the state #162 exists to change)"
        if exc.code in (401, 403):
            return None, f"SKIP: {branch}: the token cannot read branch protection (needs admin)"
        return None, f"FAIL: {branch}: HTTP {exc.code} reading protection"


def _diff_live(branch: str, want: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Every way the live rule and this file can disagree, as failure lines."""
    out: list[str] = []
    want_contexts = set(want["required_status_checks"]["contexts"])
    live_contexts = set(live.get("required_status_checks", {}).get("contexts", []))
    out += [
        f"FAIL: {branch}: {name!r} is required by this file but not live"
        for name in sorted(want_contexts - live_contexts)
    ]
    out += [
        f"FAIL: {branch}: {name!r} is required live but not in this file"
        for name in sorted(live_contexts - want_contexts)
    ]

    want_reviews = want["required_pull_request_reviews"]["required_approving_review_count"]
    live_reviews = live.get("required_pull_request_reviews", {}).get(
        "required_approving_review_count", 0
    )
    if live_reviews != want_reviews:
        out.append(
            f"FAIL: {branch}: {live_reviews} approving review(s) required, want {want_reviews}"
        )

    for key in VERIFIED_KEYS:
        if key not in want:
            continue
        value = live.get(key, {})
        value = value.get("enabled") if isinstance(value, dict) else value
        if value != want[key]:
            out.append(f"FAIL: {branch}: {key} is {value!r} live, want {want[key]!r}")
    return out


def verify_live(ruleset: dict[str, Any], token: str) -> int:
    """Compare the live protection against this file. Needs admin scope."""
    failures = 0
    for branch, want in ruleset["branches"].items():
        live, reason = _live_protection(branch, token)
        if live is None:
            print(reason)
            failures += not str(reason).startswith("SKIP")
            continue
        lines = _diff_live(branch, want, live)
        for line in lines:
            print(line)
        failures += len(lines)
        if not lines:
            print(f"OK: {branch} protection matches .github/branch-protection.json")
    return 1 if failures else 0


def print_apply(ruleset: dict[str, Any], branch: str) -> int:
    """Print the exact API call. Deliberately does not make it.

    Applying protection needs admin scope, and a script that silently held such
    a token would be a worse problem than the one it solves.
    """
    if branch not in ruleset["branches"]:
        print(f"FAIL: no rule for branch {branch!r}", file=sys.stderr)
        return 1
    payload = {k: v for k, v in ruleset["branches"][branch].items() if not k.startswith("$")}
    print(f"# Requires a token with admin scope on {REPO}.")
    print(f"cat <<'EOF' | gh api -X PUT /repos/{REPO}/branches/{branch}/protection --input -")
    print(json.dumps(payload, indent=2))
    print("EOF")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="also compare against the live API (needs a token)"
    )
    parser.add_argument("--apply", metavar="BRANCH", help="print the API call that applies a rule")
    args = parser.parse_args(argv)

    ruleset = load_ruleset()
    if args.apply:
        return print_apply(ruleset, args.apply)

    contract = _contract()
    rows = contract.collect()
    problems = audit(ruleset, rows, contract.base_coupled(rows))
    if problems:
        print("FAIL: .github/branch-protection.json disagrees with .github/workflows/\n")
        for line in problems:
            print(f"  - {line}")
        print(
            "\nBranch protection keys checks by bare name, so a name that matches no job is "
            "a requirement that silently does nothing.\nRefresh the contract first "
            "(scripts/check-required-checks.py --update), then edit the ruleset to match."
        )
        return 1

    develop = len(ruleset["branches"]["develop"]["required_status_checks"]["contexts"])
    main_ = len(ruleset["branches"]["main"]["required_status_checks"]["contexts"])
    print(
        f"OK: branch-protection ruleset agrees with the workflows "
        f"({develop} required on develop, {main_} on main); every PR check is "
        f"required or explicitly advisory"
    )
    if args.verify:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("SKIP: --verify needs GH_TOKEN or GITHUB_TOKEN")
            return 0
        return verify_live(ruleset, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
