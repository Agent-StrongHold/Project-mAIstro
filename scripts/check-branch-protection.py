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
live classic protection against this file. That half needs admin scope to read
protection at all, so it is opt-in rather than part of the PR gate. Since #162
the required contexts actually live in repository **Rulesets**, which the classic
endpoint does not carry — so `--verify-rulesets` compares against the Rulesets
API with an ordinary repository-read token instead, which is what lets CI run it
on a schedule (#564): declared/live drift is detected when it appears, not when
someone applies. `--apply` prints the apply payload for a branch only after
checking that the apply would not newly require a check that open PRs currently
fail or have never reported — the repository-wide freeze #564 was filed to
prevent — and refuses, naming the PRs, unless `--allow-freeze` makes the freeze
explicit.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RULESET = ROOT / ".github" / "branch-protection.json"
MERGE_QUEUE_FILE = ROOT / ".github" / "merge-queue.json"
CONTRACT_GATE = ROOT / "scripts" / "check-required-checks.py"
DOC = ROOT / "docs" / "ci" / "BRANCH-PROTECTION.md"
REPO = "Agent-StrongHold/Project-mAIstro"

#: The machine-checked region of the prose document. Everything outside it is
#: narrative and is deliberately not generated: the value of that document is
#: its reasoning — why `strict: true` costs what it costs, why a circle means
#: *cannot be required* rather than *chosen not to be* — and a generator that
#: flattened the reasoning into a table would trade the useful half of the
#: document for the checkable half.
#:
#: The tables inside it were hand-maintained and drifted (#268): the summary
#: said 15/15/19 required checks while the ruleset had 24/24/28, and the
#: per-check table was missing nine rows. That drifted precisely because this
#: gate read `REQUIRED-CHECKS.md` and never read the document a human opens
#: before applying protection — leaving the one artifact in the set that looks
#: like the summary as the only one nothing checked.
DOC_BEGIN = "<!-- protection:tables -->"
DOC_END = "<!-- /protection:tables -->"

#: Required here, cannot report here, advisory by declaration.
#:
#: ASCII for the third one on purpose. `ruff` refuses an en dash here as an
#: ambiguous character (RUF001), and it is right to: branch protection keys
#: checks by exact string, and this repository already carries one required
#: context whose name contains an en dash (`Quality gate (Pillars 1-4, 7, 8)`
#: is spelled with one). A table legend that is hard to retype correctly is a
#: bad legend for a document whose whole subject is exact names.
MARK_REQUIRED = "●"
MARK_UNREPORTABLE = "○"
MARK_ADVISORY = "adv"

#: Top-level booleans compared against the live API. The nested blocks
#: (`required_status_checks`, `required_pull_request_reviews`) are compared
#: field by field in `_diff_live` instead — an earlier version checked only the
#: context set and the approving-review count, so `--verify` could print OK
#: while up-to-date-with-base enforcement or stale-review dismissal was off.
#:
#: `restrictions` stays excluded: the API returns a populated object where the
#: request takes `null`, so comparing it would report a difference that cannot
#: be resolved by editing either side.
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


#: `base `main`, `integration`` — the contract joins several branches with
#: "`, `", so the capture has to span every quoted name rather than stop at the
#: first closing backtick. It did stop there, and a two-branch filter parsed as
#: one: the second branch would then be refused a check that does run on it.
_BASE_LABEL_RE = re.compile(r"base(?:-ignore)? (`[^`]+`(?:, `[^`]+`)*)")


def _named_branches(scope: str) -> set[str]:
    """The branch names a `base ...` / `base-ignore ...` scope label carries."""
    match = _BASE_LABEL_RE.search(scope)
    return set(re.findall(r"`([^`]+)`", match.group(1))) if match else set()


def _requirable_on(scope: str, branch: str, declared: dict[str, list[str]], check: str) -> bool:
    """Whether a check with this trigger scope can ever report on a PR into `branch`.

    Reading the scope string per row, rather than reducing every coupled check
    to "assume main-only". That shortcut was wrong in both directions: a future
    `paths:`-filtered check is in no coupled set, so it could be required while
    never reporting; and a `branches-ignore: [main]` check would be treated as
    valid on `main`, which is precisely the one branch it does not run on.
    Either way the audit passes while branch protection waits on `Expected`
    forever — the failure this file exists to prevent.
    """
    if "paths" in scope:
        # Never reports on a PR that misses the filter, and branch protection
        # cannot tell "did not run" from "not finished yet".
        return False
    if "base-ignore" in scope:
        return branch not in _named_branches(scope)
    if "base `" in scope:
        return branch in _named_branches(scope)
    if "base_ref" in scope:
        # A job `if:` narrows on a GitHub expression the contract does not
        # evaluate, so the target branch has to be declared rather than guessed.
        return branch in declared.get(check, [])
    return True


def _audit_branch(
    branch: str,
    rule: dict,
    scopes: dict[str, str],
    declared: dict[str, list[str]],
) -> list[str]:
    """Rules 1 and 2, for one branch."""
    problems: list[str] = []
    contexts = rule["required_status_checks"]["contexts"]
    duplicates = {c for c in contexts if contexts.count(c) > 1}
    if duplicates:
        problems.append(f"{branch}: context listed twice: {', '.join(sorted(duplicates))}")
    for context in contexts:
        scope = scopes.get(context)
        if scope is None:
            problems.append(
                f"{branch}: required context {context!r} matches no job in "
                f".github/workflows — a rename detached it from its job"
            )
        elif not _requirable_on(scope, branch, declared, context):
            problems.append(
                f"{branch}: required context {context!r} has scope {scope!r}, so it never "
                f"reports on a {branch}-based PR and would wait on `Expected` forever"
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


def audit(ruleset: dict[str, Any], rows: list[tuple[str, str, str]]) -> list[str]:
    """The three offline rules. Returns one line per violation."""
    scopes = {check: scope for _, check, scope in rows}
    every_name = set(scopes)
    declared = {
        k: v for k, v in ruleset.get("base_coupled_to", {}).items() if not k.startswith("$")
    }
    branches: dict[str, Any] = ruleset["branches"]

    problems: list[str] = []
    required: set[str] = set()
    for branch, rule in branches.items():
        required.update(rule["required_status_checks"]["contexts"])
        problems.extend(_audit_branch(branch, rule, scopes, declared))

    for name in sorted(declared):
        if name not in every_name:
            problems.append(f'"base_coupled_to" names {name!r}, which matches no PR check')

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

    # `strict` is up-to-date-with-base enforcement and lives *inside*
    # required_status_checks, so a comparison that stops at `contexts` reports
    # OK while two individually-green PRs can still merge into a broken branch.
    want_strict = want["required_status_checks"].get("strict")
    live_strict = live.get("required_status_checks", {}).get("strict")
    if live_strict != want_strict:
        out.append(
            f"FAIL: {branch}: required_status_checks.strict is {live_strict!r}, want {want_strict!r}"
        )

    # Every declared review setting, not just the count. `dismiss_stale_reviews`
    # being off means an approval survives a force-push that replaces the diff
    # it approved — and `--verify` printing OK over that is worse than not
    # having run it.
    want_reviews = want["required_pull_request_reviews"]
    live_reviews = live.get("required_pull_request_reviews") or {}
    for key, wanted in want_reviews.items():
        if key.startswith("$"):
            continue
        actual = live_reviews.get(key)
        if actual != wanted:
            out.append(
                f"FAIL: {branch}: required_pull_request_reviews.{key} is {actual!r}, "
                f"want {wanted!r}"
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


# ---------------------------------------------------------------------------
# The Rulesets surface (#564)
#
# The classic endpoint above needs admin scope, and since #162 moved the
# required contexts into repository Rulesets it does not even carry them: its
# `required_status_checks` key is simply absent, so against this repo `--verify`
# can only ever report every declared context as "not live". The Rulesets API
# is readable with ordinary repository read access, which is what makes
# scheduled declared/live drift detection (AC-4) possible at all.
# ---------------------------------------------------------------------------


def load_merge_queue() -> dict[str, Any]:
    """The reviewed queue posture, or an empty document when the file is gone."""
    if not MERGE_QUEUE_FILE.is_file():
        return {}
    return json.loads(MERGE_QUEUE_FILE.read_text(encoding="utf-8"))


def declared_required(rule: dict[str, Any]) -> list[str]:
    """Everything this file requires on `branch`.

    Includes the Ruleset-only `additional_required_checks` (`gates-ran`): it is
    required by declaration even though the classic request vocabulary cannot
    carry it, so any declared/live comparison that dropped it would silently
    bless its removal live.
    """
    contexts = set(rule["required_status_checks"]["contexts"])
    extra = (rule.get("ruleset") or {}).get("additional_required_checks") or []
    return sorted(contexts | set(extra))


def _refs_match(refs: list[str] | set[str], branch: str, default_branch: str) -> bool:
    """Whether one side of a ruleset `ref_name` condition names `branch`."""
    for ref in refs:
        if ref == "~ALL":
            return True
        if ref == "~DEFAULT_BRANCH" and branch == default_branch:
            return True
        if ref == f"refs/heads/{branch}":
            return True
    return False


def _governs(ruleset: dict[str, Any], branch: str, default_branch: str) -> bool:
    """Whether an active ruleset's conditions target `branch`.

    GitHub's rule: some `include` entry must match and no `exclude` entry may.
    The live API returns `conditions` as a single `ref_name` object; an older
    list-of-conditions shape is tolerated rather than trusted.
    """
    if ruleset.get("state", "active") == "disabled":
        return False
    conditions = ruleset.get("conditions") or {}
    ref_name: dict[str, Any] = {}
    if isinstance(conditions, dict):
        ref_name = conditions.get("ref_name") or {}
    else:
        for condition in conditions:
            if isinstance(condition, dict):
                ref_name.update(condition.get("ref_name") or {})
    if not ref_name:
        return False
    if _refs_match(ref_name.get("exclude") or [], branch, default_branch):
        return False
    return _refs_match(ref_name.get("include") or [], branch, default_branch)


def required_contexts_from_ruleset(ruleset: dict[str, Any]) -> tuple[list[str], bool | None]:
    """(contexts, strict) from a ruleset's required_status_checks rule.

    Contexts arrive as `{integration_id, context}` objects; plain strings are
    accepted too so a shape change fails as a compare difference rather than a
    traceback.
    """
    for rule in ruleset.get("rules") or []:
        if rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters") or {}
        raw = params.get("required_status_checks") or []
        contexts = sorted({entry["context"] if isinstance(entry, dict) else entry for entry in raw})
        strict = params.get("strict_required_status_checks_policy")
        return contexts, strict
    return [], None


def queue_params_from_ruleset(ruleset: dict[str, Any]) -> dict[str, Any] | None:
    """The ruleset's merge_queue parameters, or None when it carries none."""
    for rule in ruleset.get("rules") or []:
        if rule.get("type") == "merge_queue":
            return rule.get("parameters") or {}
    return None


def fetch_rulesets(token: str) -> list[dict[str, Any]]:
    """Every repository ruleset, fully expanded (the list endpoint omits rules)."""
    listing = _get(f"https://api.github.com/repos/{REPO}/rulesets?per_page=100", token)
    return [
        _get(f"https://api.github.com/repos/{REPO}/rulesets/{entry['id']}", token)
        for entry in listing
    ]


def _ruleset_requirement(
    rulesets: list[dict[str, Any]],
) -> tuple[set[str], bool | None, dict[str, Any] | None]:
    """The union requirement of every ruleset governing one branch.

    Several rulesets may target the same branch; GitHub enforces all of them,
    so their contexts union, strictness reads as any rule's declared value, and
    the last queue rule wins (a branch with two queue rules is not a state
    this repository has, and the compare would surface it as drift anyway).
    """
    contexts: set[str] = set()
    strict: bool | None = None
    queue: dict[str, Any] | None = None
    for live in rulesets:
        found, found_strict = required_contexts_from_ruleset(live)
        contexts |= set(found)
        if found_strict is not None:
            strict = found_strict
        found_queue = queue_params_from_ruleset(live)
        if found_queue is not None:
            queue = {**(queue or {}), **found_queue}
    return contexts, strict, queue


def _context_failures(branch: str, want_contexts: set[str], live_contexts: set[str]) -> list[str]:
    out = [
        f"FAIL: {branch}: {name!r} is required by this file but not by any live ruleset"
        for name in sorted(want_contexts - live_contexts)
    ]
    out += [
        f"FAIL: {branch}: {name!r} is required by a live ruleset but not in this file"
        for name in sorted(live_contexts - want_contexts)
    ]
    return out


def _queue_failures(
    branch: str, queue_want: dict[str, Any] | None, live_queue: dict[str, Any] | None
) -> list[str]:
    """The reviewed `.github/merge-queue.json` posture against the live rule."""
    if queue_want is None:
        return []
    if live_queue is None:
        return [
            f"FAIL: {branch}: .github/merge-queue.json declares a queue posture "
            f"but no governing live ruleset carries a merge_queue rule"
        ]
    return [
        f"FAIL: {branch}: merge queue {key} is {live_queue.get(key)!r} live, want "
        f"{queue_want[key]!r} (.github/merge-queue.json)"
        for key in sorted(queue_want)
        if not key.startswith("$") and live_queue.get(key) != queue_want[key]
    ]


def verify_rulesets(ruleset: dict[str, Any], token: str) -> int:
    """Compare the live Rulesets against this file. No admin scope needed.

    Fails on: required contexts in either direction (the declared set includes
    `additional_required_checks`), the strict-freshness flag, a declared branch
    with no governing ruleset, and merge-queue posture divergence against
    `.github/merge-queue.json`.
    """
    default_branch = str(_get(f"https://api.github.com/repos/{REPO}", token)["default_branch"])
    live_rulesets = fetch_rulesets(token)
    reviewed_queue = load_merge_queue().get("branches", {})
    failures = 0
    for branch, want in ruleset["branches"].items():
        before = failures
        governing = [live for live in live_rulesets if _governs(live, branch, default_branch)]
        if not governing:
            print(f"FAIL: {branch}: no active ruleset targets it")
            failures += 1
            continue
        live_contexts, live_strict, live_queue = _ruleset_requirement(governing)
        lines = _context_failures(branch, set(declared_required(want)), live_contexts)
        want_strict = want["required_status_checks"].get("strict")
        if live_strict is not None and live_strict != want_strict:
            lines.append(
                f"FAIL: {branch}: strict_required_status_checks_policy is {live_strict!r} "
                f"live, want {want_strict!r}"
            )
        lines += _queue_failures(branch, reviewed_queue.get(branch), live_queue)
        for line in lines:
            print(line)
        failures += len(lines)
        if failures == before:
            print(f"OK: {branch} live rulesets match .github/branch-protection.json")
    return 1 if failures else 0


#: Commit-status and check-run conclusions that do NOT satisfy a required
#: context. Only `success` passes; everything completed-but-not-success blocks
#: a merge, and a context that never reported leaves the PR waiting on
#: `Expected` forever — both are freeze conditions, not advisories.
_BLOCKING_CONCLUSIONS = {
    "failure",
    "error",
    "cancelled",
    "timed_out",
    "action_required",
    "skipped",
    "stale",
    "neutral",
}
_PENDING_STATES = {"pending", "queued", "in_progress", "waiting", "requested", "expected"}


def _head_report(token: str, head_sha: str) -> dict[str, str]:
    """Per-context state GitHub last reported on one PR head SHA.

    A context with any `success` report passes; several runs of one name are
    folded so a re-run's green outranks an earlier red.
    """
    report: dict[str, str] = {}
    runs = _get(
        f"https://api.github.com/repos/{REPO}/commits/{head_sha}/check-runs?per_page=100",
        token,
    )
    for run in runs.get("check_runs") or []:
        name = run.get("name") or ""
        if run.get("status") == "completed":
            conclusion = run.get("conclusion") or ""
            if conclusion == "success" or report.get(name) != "success":
                report[name] = conclusion
        else:
            report.setdefault(name, run.get("status") or "in_progress")
    combined = _get(f"https://api.github.com/repos/{REPO}/commits/{head_sha}/status", token)
    for status in combined.get("statuses") or []:
        name = status.get("context") or ""
        state = status.get("state") or ""
        if state == "success" or report.get(name) != "success":
            report[name] = state
    return report


def _classify(context: str, report: dict[str, str]) -> str | None:
    """Why `context` freezes this PR, or None when it is satisfied there."""
    state = report.get(context)
    if state == "success":
        return None
    if state in _BLOCKING_CONCLUSIONS:
        return f"reports {state!r}"
    if state is None:
        return "has never reported it (the PR would wait on `Expected` forever)"
    return f"is still {state!r} on it"


def freeze_offenders(
    token: str, contexts: list[str], max_prs: int = 200
) -> list[tuple[int, str, str]]:
    """(PR number, context, reason) for every open PR the contexts would freeze."""
    pulls = _get(f"https://api.github.com/repos/{REPO}/pulls?state=open&per_page=100", token)
    examined = pulls[:max_prs]
    if len(pulls) > len(examined):
        print(f"NOTE: examined the first {len(examined)} of {len(pulls)} open PRs")
    offenders: list[tuple[int, str, str]] = []
    for pr in examined:
        head_sha = (pr.get("head") or {}).get("sha") or ""
        if not head_sha:
            continue
        report = _head_report(token, head_sha)
        for context in contexts:
            reason = _classify(context, report)
            if reason is not None:
                offenders.append((int(pr["number"]), context, reason))
    return sorted(offenders)


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


def apply_protection(ruleset: dict[str, Any], branch: str, *, allow_freeze: bool) -> int:
    """Print `branch`'s apply payload — after checking it would not freeze open PRs (#564).

    Making a check required does not re-run CI on heads that already exist. A
    PR whose head never reported the newly required context waits on `Expected`
    forever; one whose head failed it flips from mergeable to blocked with no
    error message naming the cause. Applying such a ruleset is the
    repository-wide freeze #564 was filed to prevent, so this guard refuses and
    names the PRs; `--allow-freeze` is the explicit override once they have
    been read. Without a token the guard cannot run, and an apply whose freeze
    impact is unknown is precisely the accident this exists to prevent — so
    that refusal is unconditional.
    """
    if branch not in ruleset["branches"]:
        print(f"FAIL: no rule for branch {branch!r}", file=sys.stderr)
        return 1
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print(
            "FAIL: --apply refuses to run without GH_TOKEN/GITHUB_TOKEN (#564): the freeze "
            "guard must read the live ruleset and every open PR head first, and an apply "
            "whose freeze impact is unknown is the accident this guard exists to prevent."
        )
        return 1
    live_rulesets = fetch_rulesets(token)
    default_branch = str(_get(f"https://api.github.com/repos/{REPO}", token)["default_branch"])
    live_contexts: set[str] = set()
    governed = False
    for live in live_rulesets:
        if not _governs(live, branch, default_branch):
            continue
        governed = True
        contexts, _ = required_contexts_from_ruleset(live)
        live_contexts |= set(contexts)
    newly = sorted(set(declared_required(ruleset["branches"][branch])) - live_contexts)
    if governed and newly:
        offenders = freeze_offenders(token, newly)
        if offenders:
            print(
                "Applying this ruleset would newly require checks that open PRs do not "
                "currently satisfy — each named PR below would freeze:"
            )
            for number, context, reason in offenders:
                print(f"  - PR #{number}: newly required {context!r} {reason}")
            if not allow_freeze:
                print(
                    "FAIL: --apply refuses to print a payload that freezes the open-PR "
                    "queue (#564). Apply it knowingly: re-run with --allow-freeze after "
                    "reading the named PRs."
                )
                return 1
            print(
                "--allow-freeze override recorded: printing the payload anyway; the PRs "
                "named above were a known consequence of this apply."
            )
    return print_apply(ruleset, branch)


def _rel(path: Path) -> str:
    """Repo-relative when it can be, the raw path when it cannot.

    `Path.relative_to` raises for a path outside the repository, and every use
    of it here is inside an error message. A diagnostic that throws while
    describing a problem replaces a clear failure with an opaque one, which is
    the opposite of this file's job.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _branch_order(ruleset: dict[str, Any]) -> list[str]:
    """Branches in the ruleset's own order, so the tables follow the file."""
    return list(ruleset["branches"])


def _mark(
    ruleset: dict[str, Any], rows: list[tuple[str, str, str]], branch: str, check: str
) -> str:
    """How `check` stands on `branch`: required, unreportable, or advisory.

    The distinction is the whole point of the circle in this table. A check
    absent from a branch's contexts because its trigger means it can never
    report there is a fact about GitHub; one absent because someone decided it
    should not gate is a judgement. Rendering both as a blank would let the
    second hide inside the first.
    """
    rule = ruleset["branches"][branch]
    if check in rule["required_status_checks"]["contexts"]:
        return MARK_REQUIRED
    declared = ruleset.get("base_coupled_to", {})
    scope = next((sc for _, name, sc in rows if name == check), "")
    if not _requirable_on(scope, branch, declared, check):
        return MARK_UNREPORTABLE
    return MARK_ADVISORY


def render_doc_tables(ruleset: dict[str, Any], rows: list[tuple[str, str, str]]) -> str:
    """Both machine-checked tables, generated from the ruleset.

    No `Why` column: the reasoning is per-category and lives in the prose
    around this region, where it can say more than a cell holds.
    """
    branches = _branch_order(ruleset)

    head = [
        "| Branch | PR | Approvals | Linear history | Force-push | Deletion | Required checks |"
    ]
    head.append("|---|:--:|:--:|:--:|:--:|:--:|:--:|")
    for branch in branches:
        rule = ruleset["branches"][branch]
        reviews = rule.get("required_pull_request_reviews") or {}
        approvals = reviews.get("required_approving_review_count", 0)
        head.append(
            f"| `{branch}` | yes | **{approvals}** "
            f"| {'yes' if rule.get('required_linear_history') else 'no'} "
            f"| {'yes' if rule.get('allow_force_pushes') else 'no'} "
            f"| {'yes' if rule.get('allow_deletions') else 'no'} "
            f"| **{len(rule['required_status_checks']['contexts'])}** |"
        )

    every = sorted({name for _, name, _ in rows})
    grid = ["| Check | " + " | ".join(f"`{b}`" for b in branches) + " |"]
    grid.append("|---|" + "|".join([":--:"] * len(branches)) + "|")
    for check in every:
        marks = " | ".join(_mark(ruleset, rows, b, check) for b in branches)
        grid.append(f"| `{check}` | {marks} |")

    return "\n".join(head) + "\n\n" + "\n".join(grid)


def doc_problems(
    ruleset: dict[str, Any], rows: list[tuple[str, str, str]], *, update: bool
) -> list[str]:
    """Whether the prose document's tables still match the ruleset."""
    if not DOC.is_file():
        return [f"{_rel(DOC)} does not exist"]
    text = DOC.read_text(encoding="utf-8")
    if DOC_BEGIN not in text or DOC_END not in text:
        return [
            f"{_rel(DOC)} has no {DOC_BEGIN} / {DOC_END} markers, so its "
            f"tables are not checked against {_rel(RULESET)}"
        ]
    head, rest = text.split(DOC_BEGIN, 1)
    _, tail = rest.split(DOC_END, 1)
    rebuilt = f"{head}{DOC_BEGIN}\n\n{render_doc_tables(ruleset, rows)}\n\n{DOC_END}{tail}"

    if update:
        DOC.write_text(rebuilt, encoding="utf-8")
        return []
    if rebuilt != text:
        return [
            f"{_rel(DOC)} disagrees with {_rel(RULESET)}.\n"
            f"         A branch's required set, review count or protection flags changed and the\n"
            f"         summary a human reads before applying protection did not. That document\n"
            f"         said 15/15/19 required checks while the ruleset had 24/24/28 (#268).\n"
            f"         Refresh with: python3 scripts/check-branch-protection.py --update-doc"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="also compare against the live API (needs a token)"
    )
    parser.add_argument(
        "--verify-rulesets",
        action="store_true",
        help="compare the declared required set against the live Rulesets API; needs only a "
        "repository-read token, so CI can run it on a schedule (#564)",
    )
    parser.add_argument("--apply", metavar="BRANCH", help="print the API call that applies a rule")
    parser.add_argument(
        "--allow-freeze",
        action="store_true",
        help="with --apply: override the open-PR freeze guard after reading the named PRs (#564)",
    )
    parser.add_argument(
        "--update-doc",
        action="store_true",
        help="rewrite the generated tables in docs/ci/BRANCH-PROTECTION.md",
    )
    args = parser.parse_args(argv)

    ruleset = load_ruleset()
    if args.apply:
        return apply_protection(ruleset, args.apply, allow_freeze=args.allow_freeze)

    contract = _contract()
    rows = contract.collect()

    if args.update_doc:
        doc_problems(ruleset, rows, update=True)
        print(f"updated {_rel(DOC)} from {_rel(RULESET)}")
        return 0

    problems = audit(ruleset, rows)
    # The prose document is checked in the same pass, and its failures are
    # reported alongside the ruleset's rather than after them: a PR that
    # changes a branch's required set gets both halves of the consequence at
    # once instead of fixing one and rediscovering the other on the next run.
    problems += doc_problems(ruleset, rows, update=False)
    if problems:
        print("FAIL: the branch-protection contract does not hang together\n")
        for line in problems:
            print(f"  - {line}")
        print(
            "\nBranch protection keys checks by bare name, so a name that matches no job is "
            "a requirement that silently does nothing.\nRefresh the contract first "
            "(scripts/check-required-checks.py --update), then edit the ruleset to match,\n"
            "then regenerate the prose summary (check-branch-protection.py --update-doc)."
        )
        return 1

    counts = ", ".join(
        f"{len(rule['required_status_checks']['contexts'])} on {branch}"
        for branch, rule in ruleset["branches"].items()
    )
    print(
        f"OK: branch-protection ruleset agrees with the workflows ({counts}); "
        f"every PR check is required or explicitly advisory"
    )
    if args.verify:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("SKIP: --verify needs GH_TOKEN or GITHUB_TOKEN")
            return 0
        return verify_live(ruleset, token)
    if args.verify_rulesets:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("SKIP: --verify-rulesets needs GH_TOKEN or GITHUB_TOKEN")
            return 0
        return verify_rulesets(ruleset, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
