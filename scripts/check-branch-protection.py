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

A fourth check, added for #85, is about the boundary itself rather than the
workflows: `.github/live-merge-boundary.json` is a recorded read-back of the
live repository rulesets and classic protection, `--refresh-live` re-reads
GitHub and rewrites it, and the offline gate compares it with this file and
with the generated document. Divergence is red unless it is written down in
`known_live_drift` with a reason and an owner — and a written-down divergence
that no longer exists is red too, so the record cannot outlive its fact.
`--verify` takes the comparison to GitHub itself: with a token it re-reads
the rulesets and fails on ALL policy differences (including documented ones)
or if the recorded read-back has gone stale. Missing credentials fail closed. CI cannot do
that half (no admin-scoped token on a pull request), so it is run by hand.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RULESET = ROOT / ".github" / "branch-protection.json"
CONTRACT_GATE = ROOT / "scripts" / "check-required-checks.py"
DOC = ROOT / "docs" / "ci" / "BRANCH-PROTECTION.md"
REPO = "Agent-StrongHold/Project-mAIstro"

#: The recorded read-back of the live merge boundary (#85).
#:
#: CI has no admin-scoped token, so the live rulesets cannot be read from a
#: pull request. What can be checked there is the *recorded* read-back: a
#: normalised snapshot of what GitHub enforced when it was last read. The
#: snapshot is evidence, not authority -- the authority is
#: `.github/branch-protection.json`, and every divergence between the two has
#: to be written down (see `known_live_drift`).
LIVE_SNAPSHOT = ROOT / ".github" / "live-merge-boundary.json"

#: The reviewed merge-queue policy. It is a separate file because the queue
#: parameters live on the ruleset's `merge_queue` rule, not on classic
#: protection, but the queue is part of the merge boundary and so is compared
#: against the live ruleset with everything else.
MERGE_QUEUE = ROOT / ".github" / "merge-queue.json"

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

#: The second generated region: the live read-back, rendered from
#: `.github/live-merge-boundary.json`. The first region says what the policy
#: *declares*; this one says what GitHub *enforces*. Keeping them in one
#: document, side by side, is what makes the difference between them visible
#: to a reader instead of a fact only the gate knows.
LIVE_DOC_BEGIN = "<!-- protection:live -->"
LIVE_DOC_END = "<!-- /protection:live -->"

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


# ---------------------------------------------------------------------------
# The live merge boundary (#85)
# ---------------------------------------------------------------------------
#
# Everything above compares the declared policy with the workflows. This
# section compares the declared policy with *GitHub*, which is the only
# comparison that can say whether the merge boundary is the one the policy
# describes.
#
# Two things were wrong about that comparison before, and both were invisible
# from the workflow side:
#
# 1. It read `/branches/{branch}/protection`. ADR-095 moved enforcement to
#    repository Rulesets, so that endpoint is no longer the merge boundary --
#    on `main` it does not even exist (404), and on `develop` it carries no
#    required status checks at all. So `--verify` reported every required
#    check as "required by this file but not live" while the ruleset that
#    actually enforces them was never read.
# 2. It needed an admin-scoped token, so in CI it printed SKIP and the drift
#    it was written to find was never found.
#
# The fix is a recorded read-back. `--refresh-live` reads the live rulesets
# with a token and writes `.github/live-merge-boundary.json`; the offline gate
# compares that snapshot with the declared policy, and the generated document
# shows both side by side. Every divergence has to be written down in the
# policy's `known_live_drift` map with a reason and an owner, so a divergence
# nobody has looked at is a failure and an excuse that outlives its fact is a
# failure too.


def normalize_ruleset(raw: dict[str, Any]) -> dict[str, Any]:
    """A live ruleset, reduced to the fields the policy declares."""
    view: dict[str, Any] = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "enforcement": raw.get("enforcement"),
        "target": None,
        "required_status_checks": {"strict": None, "contexts": []},
        "required_approving_review_count": None,
        "dismiss_stale_reviews_on_push": None,
        "require_code_owner_review": None,
        "require_last_push_approval": None,
        "required_review_thread_resolution": None,
        "allowed_merge_methods": [],
        "rules": [],
        "merge_queue": None,
        "bypass": [],
    }
    conditions = raw.get("conditions") or {}
    refs = conditions.get("ref_name") or {}
    include = refs.get("include") or []
    if len(include) != 1 or refs.get("exclude"):
        raise ValueError(
            f"ruleset {raw.get('id')}: unsupported ref selectors; cannot verify safely"
        )
    view["target"] = include[0]
    for rule in raw.get("rules") or []:
        kind = rule.get("type")
        params = rule.get("parameters") or {}
        if kind == "required_status_checks":
            checks = params.get("required_status_checks") or []
            view["required_status_checks"] = {
                "strict": params.get("strict_required_status_checks_policy"),
                "contexts": sorted(str(c.get("context")) for c in checks),
            }
        elif kind == "pull_request":
            view["required_approving_review_count"] = params.get("required_approving_review_count")
            view["dismiss_stale_reviews_on_push"] = params.get("dismiss_stale_reviews_on_push")
            view["require_code_owner_review"] = params.get("require_code_owner_review")
            view["require_last_push_approval"] = params.get("require_last_push_approval")
            view["required_review_thread_resolution"] = params.get(
                "required_review_thread_resolution"
            )
            view["allowed_merge_methods"] = sorted(params.get("allowed_merge_methods") or [])
        elif kind == "merge_queue":
            view["merge_queue"] = dict(params)
            view["rules"].append(kind)
        else:
            view["rules"].append(kind)
    view["rules"] = sorted(view["rules"])
    view["bypass"] = [
        {
            "actor_type": actor.get("actor_type"),
            "actor_id": actor.get("actor_id"),
            "bypass_mode": actor.get("bypass_mode"),
        }
        for actor in raw.get("bypass_actors") or []
    ]
    return view


def normalize_classic(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Classic branch protection, reduced to the fields the policy declares."""
    if raw is None:
        return None
    reviews = raw.get("required_pull_request_reviews") or {}
    checks = raw.get("required_status_checks") or {}
    view: dict[str, Any] = {
        "required_status_checks": {
            "strict": checks.get("strict"),
            "contexts": sorted(checks.get("contexts") or []),
        },
        "required_pull_request_reviews": {
            "required_approving_review_count": reviews.get("required_approving_review_count"),
            "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews"),
            "require_code_owner_reviews": reviews.get("require_code_owner_reviews"),
            "require_last_push_approval": reviews.get("require_last_push_approval"),
        },
    }
    for key in VERIFIED_KEYS:
        value = raw.get(key)
        view[key] = value.get("enabled") if isinstance(value, dict) else value
    return view


def branch_for_target(target: str | None, default_branch: str | None) -> str | None:
    """The branch a ruleset target names, in the vocabulary both sides use."""
    if target == "~DEFAULT_BRANCH":
        return default_branch
    if target and target.startswith("refs/heads/"):
        return target[len("refs/heads/") :]
    return None


def fetch_live(token: str) -> dict[str, Any]:
    """Read the live merge boundary: the repository rulesets and classic protection."""
    repo = _get(f"https://api.github.com/repos/{REPO}", token)
    default_branch = repo.get("default_branch")
    listing = _get(f"https://api.github.com/repos/{REPO}/rulesets?per_page=100", token)
    if len(listing) >= 100:
        raise ValueError("ruleset listing may be truncated; cannot verify safely")
    rulesets: dict[str, Any] = {}
    for entry in listing:
        raw = _get(f"https://api.github.com/repos/{REPO}/rulesets/{entry['id']}", token)
        if raw.get("target") != "branch":
            continue
        view = normalize_ruleset(raw)
        branch = branch_for_target(view["target"], default_branch)
        if branch is None:
            raise ValueError(f"ruleset {entry['id']}: unsupported branch target {view['target']!r}")
        if branch in rulesets:
            raise ValueError(f"{branch}: overlapping rulesets; cannot verify safely")
        rulesets[branch] = view
    classic: dict[str, Any] = {}
    for branch in ("develop", "main"):
        url = f"https://api.github.com/repos/{REPO}/branches/{branch}/protection"
        try:
            raw_classic = _get(url, token)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            raw_classic = None
        classic[branch] = normalize_classic(raw_classic)
    return {
        "read_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO,
        "default_branch": default_branch,
        "rulesets": rulesets,
        "classic_protection": classic,
    }


def write_snapshot(snapshot: dict[str, Any]) -> None:
    LIVE_SNAPSHOT.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_snapshot() -> dict[str, Any]:
    if not LIVE_SNAPSHOT.is_file():
        return {}
    return json.loads(LIVE_SNAPSHOT.read_text(encoding="utf-8"))


def _declared_required(rule: dict[str, Any]) -> set[str]:
    """Every context the policy requires on a branch."""
    contexts = set(rule["required_status_checks"]["contexts"])
    contexts |= set((rule.get("ruleset") or {}).get("additional_required_checks") or [])
    return contexts


def _review_drift(branch: str, rule: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """The review settings the two sides can disagree about."""
    reviews = rule.get("required_pull_request_reviews") or {}
    pairs = (
        ("required_approving_review_count", "required_approving_review_count"),
        ("dismiss_stale_reviews", "dismiss_stale_reviews_on_push"),
        ("require_code_owner_reviews", "require_code_owner_review"),
        ("require_last_push_approval", "require_last_push_approval"),
    )
    out = []
    for declared_key, live_key in pairs:
        want = reviews.get(declared_key)
        got = live.get(live_key)
        if want != got:
            out.append(f"{branch}: {declared_key} is {want!r} in the policy and {got!r} live")
    want = rule.get("required_conversation_resolution")
    got = live.get("required_review_thread_resolution")
    if want != got:
        out.append(
            f"{branch}: required_conversation_resolution is {want!r} in the policy and {got!r} live"
        )
    return out


def _flag_drift(branch: str, rule: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """The protection flags, expressed the way a ruleset expresses them."""
    live_rules = set(live.get("rules") or [])
    mapping = (
        ("required_linear_history", "required_linear_history" in live_rules),
        ("allow_force_pushes", "non_fast_forward" not in live_rules),
        ("allow_deletions", "deletion" not in live_rules),
        ("block_creations", "creation" in live_rules),
    )
    out = []
    for key, live_value in mapping:
        want = rule.get(key)
        if want != live_value:
            out.append(f"{branch}: {key} is {want!r} in the policy and {live_value!r} live")
    return out


def _method_drift(branch: str, rule: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """The merge methods the two sides allow."""
    want = sorted((rule.get("ruleset") or {}).get("allowed_merge_methods") or [])
    got = sorted(live.get("allowed_merge_methods") or [])
    if want != got:
        out = [f"{branch}: allowed_merge_methods are {want} in the policy and {got} live"]
    else:
        out = []
    return out


def _bypass_view(entries: Any) -> list[str]:
    """Actor identities and modes; changing an app/role must not look unchanged."""
    if isinstance(entries, dict):
        role_ids = {"admin": 5, "maintain": 4, "write": 2, "read": 1}
        pairs = []
        for actor, mode in entries.items():
            kind, _, identity = actor.partition(":")
            actor_id = role_ids.get(identity, identity) if kind == "RepositoryRole" else identity
            label = f"{kind}:{actor_id}" if actor_id else kind
            pairs.append((label, mode))
    else:
        pairs = []
        for entry in entries or []:
            kind = entry.get("actor_type")
            actor_id = entry.get("actor_id")
            label = f"{kind}:{actor_id}" if actor_id is not None else str(kind)
            pairs.append((label, entry.get("bypass_mode")))
    return sorted(f"{actor}:{mode}" for actor, mode in pairs)


def _bypass_drift(branch: str, rule: dict[str, Any], live: dict[str, Any]) -> list[str]:
    want = _bypass_view((rule.get("ruleset") or {}).get("bypass") or {})
    got = _bypass_view(live.get("bypass") or [])
    if want == got:
        return []
    return [f"{branch}: bypass actors are {want} in the policy and {got} live"]


def _queue_drift(policy: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """The merge-queue posture, which is part of the merge boundary too."""
    if not MERGE_QUEUE.is_file():
        return []
    declared = json.loads(MERGE_QUEUE.read_text(encoding="utf-8"))
    out = []
    for branch, want in (declared.get("branches") or {}).items():
        live_rule = (live.get("rulesets") or {}).get(branch) or {}
        live_queue = live_rule.get("merge_queue")
        if live_queue is None:
            out.append(f"{branch}: the policy declares a merge queue and the live ruleset has none")
            continue
        differing = []
        for key, value in sorted(want.items()):
            if key.startswith("$"):
                continue
            got = live_queue.get(key)
            if got != value:
                differing.append(f"{key} is {value!r} in the policy and {got!r} live")
        if differing:
            out.append(f"{branch}: merge queue differs: " + "; ".join(differing))
    return out


def _classic_drift(policy: dict[str, Any], live: dict[str, Any]) -> list[str]:
    """Classic protection, where it still exists alongside a ruleset.

    GitHub applies both surfaces when both cover a branch, so the effective
    policy is their intersection. Two surfaces with different values is not
    itself a failure -- but it is invisible unless somebody writes it down,
    and it is where a policy that says one thing and a repository that
    enforces another hides.
    """
    classic = live.get("classic_protection") or {}
    out = []
    for branch, rule in policy["branches"].items():
        surface = classic.get(branch)
        if surface is None:
            # Absent is the post-ADR-095 shape, not a divergence: the ruleset
            # is the declared mechanism and classic protection is the legacy
            # surface. Recording this as drift would write a permanent
            # exception for a state the policy intends.
            continue
        differences = []
        want_reviews = rule.get("required_pull_request_reviews") or {}
        live_reviews = surface.get("required_pull_request_reviews") or {}
        for declared_key, live_key in (
            ("required_approving_review_count", "required_approving_review_count"),
            ("dismiss_stale_reviews", "dismiss_stale_reviews"),
            ("require_code_owner_reviews", "require_code_owner_reviews"),
            ("require_last_push_approval", "require_last_push_approval"),
        ):
            want = want_reviews.get(declared_key)
            got = live_reviews.get(live_key)
            if want != got:
                differences.append(f"{declared_key} is {want!r} in the policy and {got!r} live")
        for key in VERIFIED_KEYS:
            want = rule.get(key)
            got = surface.get(key)
            if want != got:
                differences.append(f"{key} is {want!r} in the policy and {got!r} live")
        if differences:
            out.append(
                f"{branch}: classic branch protection is active alongside the ruleset and "
                f"differs from the policy: " + "; ".join(differences)
            )
    return out


def _unproduced_drift(policy: dict[str, Any], live: dict[str, Any], rows: list) -> list[str]:
    """Live-required contexts that nothing in this repository can report.

    A required check that no workflow produces is not a gate -- it is a
    permanent `Expected`, and the branch it guards can never be merged to.
    The context may be produced outside the pull-request job graph (a
    `workflow_run` publisher writes a commit status instead), which is why the
    policy's Ruleset-only `additional_required_checks` are counted as
    producers: that list is exactly the set of contexts the policy already
    knows are published outside the job graph.
    """
    produced = {name for _workflow, name, _scope in rows}
    out = []
    for branch, rule in policy["branches"].items():
        live_rule = (live.get("rulesets") or {}).get(branch) or {}
        live_contexts = set(live_rule.get("required_status_checks", {}).get("contexts") or [])
        declared_only = (rule.get("ruleset") or {}).get("additional_required_checks") or []
        for context in sorted(live_contexts - produced - set(declared_only)):
            out.append(
                f"{branch}: the live ruleset requires {context!r}, which no workflow in this "
                f"repository produces"
            )
    return out


def drift(policy: dict[str, Any], live: dict[str, Any], rows: list) -> list[str]:
    """Every way the declared policy and the live merge boundary disagree."""
    out: list[str] = []
    for branch, rule in policy["branches"].items():
        live_rule = (live.get("rulesets") or {}).get(branch)
        if live_rule is None:
            out.append(f"{branch}: the live rulesets do not cover this branch")
            continue
        if live_rule.get("enforcement") != "active":
            out.append(f"{branch}: the live ruleset is not active")
        target = (rule.get("ruleset") or {}).get("target")
        if target is not None and live_rule.get("target") != target:
            out.append(f"{branch}: ruleset target differs from the policy")
        if branch_for_target(live_rule.get("target"), live.get("default_branch")) != branch:
            out.append(f"{branch}: the live ruleset target does not cover this branch")
        want_strict = rule["required_status_checks"].get("strict")
        got_strict = live_rule.get("required_status_checks", {}).get("strict")
        if want_strict != got_strict:
            out.append(
                f"{branch}: required_status_checks.strict is {want_strict!r} in the policy "
                f"and {got_strict!r} live"
            )
        declared = _declared_required(rule)
        live_contexts = set(live_rule["required_status_checks"]["contexts"])
        only_declared = sorted(declared - live_contexts)
        only_live = sorted(live_contexts - declared)
        if only_declared:
            out.append(
                f"{branch}: required checks the policy declares but the live ruleset does not "
                f"require: {', '.join(only_declared)}"
            )
        if only_live:
            out.append(
                f"{branch}: required checks the live ruleset requires but the policy does not "
                f"declare: {', '.join(only_live)}"
            )
        out.extend(_review_drift(branch, rule, live_rule))
        out.extend(_flag_drift(branch, rule, live_rule))
        out.extend(_method_drift(branch, rule, live_rule))
        out.extend(_bypass_drift(branch, rule, live_rule))
    out.extend(_queue_drift(policy, live))
    out.extend(_classic_drift(policy, live))
    out.extend(_unproduced_drift(policy, live, rows))
    return sorted(out)


def drift_problems(policy: dict[str, Any], live: dict[str, Any], rows: list) -> list[str]:
    """Drift nobody has written down, and written-down drift that is gone.

    Both halves fail. An unreviewed divergence is the state this issue was
    filed about. A recorded divergence that no longer exists is worse in one
    way: the exception outlives the fact it was written for, and the next
    divergence of the same shape inherits an excuse nobody re-read.
    """
    computed = drift(policy, live, rows)
    known = policy.get("known_live_drift") or {}
    problems = []
    for entry in computed:
        if entry not in known:
            problems.append(f"live drift nobody has recorded: {entry}")
    for entry, note in sorted(known.items()):
        if entry not in computed:
            problems.append(f"recorded live drift that no longer exists: {entry}")
        elif not str(note.get("reason", "")).strip():
            problems.append(f"recorded live drift has no reason: {entry}")
        elif not str(note.get("owner", "")).strip():
            problems.append(f"recorded live drift has no owner: {entry}")
    return problems


def snapshot_staleness(recorded: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Where the recorded read-back no longer matches GitHub."""
    problems = []
    for key in ("repo", "default_branch", "rulesets", "classic_protection"):
        for path in _diff_paths(recorded.get(key), fresh.get(key), key):
            problems.append(
                f"the recorded live read-back is stale: {path} changed on GitHub since it was "
                f"recorded; refresh with: python3 scripts/check-branch-protection.py --refresh-live"
            )
    return problems


def _diff_paths(old: Any, new: Any, path: str) -> list[str]:
    """The leaf paths at which two snapshots differ."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            out.extend(_diff_paths(old.get(key), new.get(key), f"{path}.{key}"))
        return out
    if isinstance(old, list) and isinstance(new, list):
        if old == new:
            return []
        return [path]
    return [] if old == new else [path]


def render_live_tables(live: dict[str, Any], rows: list) -> str:
    """The live read-back, rendered from the recorded snapshot."""
    rulesets = live.get("rulesets") or {}
    branches = list(rulesets)
    head = [
        "| Branch | Ruleset | Enforcement | Approvals | Stale dismissal | Code-owner review |"
        " Last-push approval | Merge methods | Required checks (live) |",
        "|---|---|:--:|:--:|:--:|:--:|:--:|---|:--:|",
    ]
    for branch in branches:
        entry = rulesets[branch]
        head.append(
            f"| `{branch}` | {entry['name']} | {entry['enforcement']} "
            f"| **{entry['required_approving_review_count']}** "
            f"| {'yes' if entry['dismiss_stale_reviews_on_push'] else 'no'} "
            f"| {'yes' if entry['require_code_owner_review'] else 'no'} "
            f"| {'yes' if entry['require_last_push_approval'] else 'no'} "
            f"| {', '.join(entry['allowed_merge_methods'])} "
            f"| **{len(entry['required_status_checks']['contexts'])}** |"
        )
    grid = ["| Check | " + " | ".join(f"`{b}`" for b in branches) + " |"]
    grid.append("|---|" + "|".join([":--:"] * len(branches)) + "|")
    live_contexts = {
        branch: set(rulesets[branch]["required_status_checks"]["contexts"]) for branch in branches
    }
    for name in sorted({name for _workflow, name, _scope in rows}):
        marks = " | ".join(
            MARK_REQUIRED if name in live_contexts[branch] else "-" for branch in branches
        )
        grid.append(f"| `{name}` | {marks} |")
    # Checks GitHub requires that no PR job in this repository produces are
    # the ones a reader most needs to see, and they are exactly the ones the
    # row set above cannot show: `workflow_run` and `pull_request_target`
    # publishers are invisible to the contract that walks `pull_request`
    # workflows. Leaving them out of the generated region would make the live
    # table look complete while hiding the only rows that can be a permanent
    # `Expected`.
    row_names = {name for _workflow, name, _scope in rows}
    outside = [
        f"- `{name}` on `{branch}`"
        for branch in branches
        for name in sorted(live_contexts[branch] - row_names)
    ]
    if outside:
        grid.append("")
        grid.append(
            "Required live but published outside the PR-job grid "
            "(a `workflow_run` or `pull_request_target` publisher):"
        )
        grid.extend(outside)
    return "\n".join(head) + "\n\n" + "\n".join(grid)


def live_doc_problems(live: dict[str, Any], rows: list, *, update: bool) -> list[str]:
    """Whether the document's live table still matches the recorded read-back."""
    if not DOC.is_file():
        return [f"{_rel(DOC)} does not exist"]
    text = DOC.read_text(encoding="utf-8")
    region = f"{LIVE_DOC_BEGIN}\n\n{render_live_tables(live, rows)}\n\n{LIVE_DOC_END}"
    if LIVE_DOC_BEGIN not in text or LIVE_DOC_END not in text:
        if not update:
            return [
                f"{_rel(DOC)} has no {LIVE_DOC_BEGIN} / {LIVE_DOC_END} markers, so the live "
                f"read-back is not checked against {_rel(LIVE_SNAPSHOT)}"
            ]
        # `--update-doc` is the writer for both regions, so it creates the
        # second one rather than requiring a hand-edit of the document it is
        # meant to own. It lands directly after the declared region: the two
        # tables are meant to be read against each other.
        if DOC_END in text:
            head, rest = text.split(DOC_END, 1)
            text = f"{head}{DOC_END}\n\n{region}{rest}"
        else:
            text = text.rstrip("\n") + f"\n\n{region}\n"
        DOC.write_text(text, encoding="utf-8")
        return []
    head, rest = text.split(LIVE_DOC_BEGIN, 1)
    _, tail = rest.split(LIVE_DOC_END, 1)
    rebuilt = f"{head}{region}{tail}"
    if update:
        DOC.write_text(rebuilt, encoding="utf-8")
        return []
    if rebuilt != text:
        return [
            f"{_rel(DOC)} disagrees with the recorded live read-back in {_rel(LIVE_SNAPSHOT)}.\n"
            f"         The table above says what GitHub enforces; if it no longer does, the\n"
            f"         read-back is stale. Refresh with:\n"
            f"         python3 scripts/check-branch-protection.py --refresh-live --update-doc"
        ]
    return []


def verify_live(ruleset: dict[str, Any], token: str, rows: list) -> list[str]:
    """Compare the live rulesets with the recorded read-back and the policy."""
    try:
        fresh = fetch_live(token)
    except urllib.error.HTTPError as exc:
        return [f"FAIL: reading the live rulesets failed: HTTP {exc.code}"]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [f"FAIL: reading the live rulesets failed: {exc}"]
    recorded = load_snapshot()
    problems = snapshot_staleness(recorded, fresh)
    # Recording a divergence documents it; it must never authorize it. In
    # particular, --verify used to fail on declared-vs-live differences, so
    # accepting known_live_drift here would weaken the existing live gate.
    problems.extend(drift(ruleset, fresh, rows))
    return problems


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


def refresh_live(rows: list, *, update_doc: bool) -> int:
    """Read GitHub and record what it enforces in the committed snapshot."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("FAIL: --refresh-live needs GH_TOKEN or GITHUB_TOKEN")
        return 1
    try:
        fresh = fetch_live(token)
    except urllib.error.HTTPError as exc:
        print(f"FAIL: reading the live rulesets failed: HTTP {exc.code}")
        return 1
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"FAIL: reading the live rulesets failed: {exc}")
        return 1
    write_snapshot(fresh)
    print(f"recorded the live merge boundary in {_rel(LIVE_SNAPSHOT)}")
    if update_doc:
        live_doc_problems(fresh, rows, update=True)
        print(f"updated the live read-back region of {_rel(DOC)}")
    return 0


def update_doc(ruleset: dict[str, Any], rows: list) -> int:
    """Regenerate both machine-checked regions of the prose document."""
    doc_problems(ruleset, rows, update=True)
    print(f"updated {_rel(DOC)} from {_rel(RULESET)}")
    if LIVE_SNAPSHOT.is_file():
        live_doc_problems(load_snapshot(), rows, update=True)
        print(f"updated the live read-back region of {_rel(DOC)}")
    else:
        print(f"SKIP: {_rel(LIVE_SNAPSHOT)} does not exist; record it with --refresh-live")
    return 0


def offline_problems(ruleset: dict[str, Any], rows: list) -> list[str]:
    """Everything CI can check without a token, in one report.

    The prose document is checked in the same pass as the ruleset, and so is
    the recorded read-back of what GitHub actually enforces. This is the half
    #85 is about: a declared policy, a generated document and a live boundary
    that are each internally consistent and mutually different is the state
    where "documented and matches live" is only true of the sentence saying
    it. No token here -- CI compares against the committed snapshot, and
    `--verify` re-reads GitHub to catch a stale one.
    """
    problems = audit(ruleset, rows)
    problems += doc_problems(ruleset, rows, update=False)
    if not LIVE_SNAPSHOT.is_file():
        problems.append(
            f"no recorded live read-back in {_rel(LIVE_SNAPSHOT)}; record what GitHub "
            "enforces with: python3 scripts/check-branch-protection.py --refresh-live"
        )
        return problems
    snapshot = load_snapshot()
    problems += live_doc_problems(snapshot, rows, update=False)
    problems += drift_problems(ruleset, snapshot, rows)
    return problems


def _report(problems: list[str]) -> None:
    print("FAIL: the branch-protection contract does not hang together\n")
    for line in problems:
        print(f"  - {line}")
    print(
        "\nBranch protection keys checks by bare name, so a name that matches no job is "
        "a requirement that silently does nothing.\nRefresh the contract first "
        "(scripts/check-required-checks.py --update), then edit the ruleset to match,\n"
        "then regenerate the prose summary (check-branch-protection.py --update-doc)."
        "\nA line about the live read-back means GitHub and this repository disagree: "
        "re-read it with\n--refresh-live, and either reconcile the settings or record "
        "the divergence in known_live_drift."
    )


def verify(ruleset: dict[str, Any], rows: list) -> int:
    """The half CI cannot do: re-read GitHub and compare it to the record."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("FAIL: --verify needs GH_TOKEN or GITHUB_TOKEN; live policy is UNVERIFIED")
        return 1
    problems = verify_live(ruleset, token, rows)
    if problems:
        print("FAIL: the live merge boundary has drifted from what is recorded\n")
        for line in problems:
            print(f"  - {line}")
        return 1
    print("OK: GitHub enforces the merge boundary this repository records")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="also compare against the live API (needs a token)"
    )
    parser.add_argument("--apply", metavar="BRANCH", help="print the API call that applies a rule")
    parser.add_argument(
        "--update-doc",
        action="store_true",
        help="rewrite the generated tables in docs/ci/BRANCH-PROTECTION.md",
    )
    parser.add_argument(
        "--refresh-live",
        action="store_true",
        help=(
            "read the live rulesets with a token and record them in "
            f"{LIVE_SNAPSHOT.relative_to(ROOT)}"
        ),
    )
    args = parser.parse_args(argv)

    ruleset = load_ruleset()
    if args.apply:
        return print_apply(ruleset, args.apply)

    rows = _contract().collect()
    if args.refresh_live:
        return refresh_live(rows, update_doc=args.update_doc)
    if args.update_doc:
        return update_doc(ruleset, rows)

    problems = offline_problems(ruleset, rows)
    if problems:
        _report(problems)
        return 1

    counts = ", ".join(
        f"{len(rule['required_status_checks']['contexts'])} on {branch}"
        for branch, rule in ruleset["branches"].items()
    )
    print(
        f"OK: branch-protection ruleset agrees with the workflows ({counts}); "
        f"every PR check is required or explicitly advisory"
    )
    print(
        f"OK: the recorded live read-back in {_rel(LIVE_SNAPSHOT)} matches the generated "
        "document; recorded divergences are NOT approval of the live policy"
    )
    if args.verify:
        return verify(ruleset, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
