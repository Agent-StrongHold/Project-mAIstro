"""Tests for the branch-protection ruleset gate (#162).

Branch protection names required checks as bare strings, and nothing in GitHub
links a string back to the job meant to produce it. So the failure worth testing
is not "the ruleset is wrong" — it is "the ruleset is wrong and says nothing",
which is what a renamed job produces today. Each test below drives one of the
three offline rules to failure and asserts on the diagnosis, not merely on the
exit code.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-branch-protection.py"
RULESET = ROOT / ".github" / "branch-protection.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_branch_protection", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: (workflow, check, scope) triples in the shape check-required-checks.collect()
#: returns. Small and synthetic: these tests are about the ruleset rules, and
#: pinning them to the live workflow set would make every CI change edit them.
ROWS = [
    ("CI", "test", "every PR"),
    ("CI", "workflow-lint", "every PR"),
    ("CodeQL Advanced", "Analyze (python)", "base `main`"),
    ("security", "Container scan + SBOM + cosign", "every PR, job `if:` on base_ref"),
]
#: The job-`if:` coupling the contract cannot read, declared per ADR-095's model.
DECLARED = {"Container scan + SBOM + cosign": ["main"]}


def _ruleset(develop, main, advisory=None, declared=None):
    return {
        "branches": {
            "develop": _rule(develop),
            "main": _rule(main),
        },
        "base_coupled_to": DECLARED if declared is None else declared,
        "advisory": advisory or {},
    }


def _rule(contexts, approvals=0):
    return {
        "required_status_checks": {"strict": True, "contexts": list(contexts)},
        "required_pull_request_reviews": {
            "required_approving_review_count": approvals,
            "dismiss_stale_reviews": True,
        },
        "enforce_admins": False,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_conversation_resolution": True,
    }


class TestTheThreeOfflineRules:
    def test_a_consistent_ruleset_passes(self, gate):
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
        )
        assert gate.audit(rules, ROWS) == []

    def test_a_required_name_matching_no_job_is_named(self, gate):
        """The failure this gate exists for: a job is renamed, the protection
        rule keeps the old string, and it silently stops requiring anything."""
        rules = _ruleset(develop=["tets"], main=["test"])
        problems = gate.audit(rules, ROWS)
        assert any("'tets' matches no job" in p for p in problems)
        assert any("detached it from its job" in p for p in problems)

    def test_a_base_coupled_check_required_on_develop_is_named(self, gate):
        """It never reports on a develop-based PR, so the PR waits on an
        `Expected` status forever — every merge blocked, by a rule intended to
        block only bad merges."""
        rules = _ruleset(develop=["test", "Analyze (python)"], main=["test", "Analyze (python)"])
        problems = gate.audit(rules, ROWS)
        assert any("never reports on a develop-based PR" in p for p in problems)
        assert not any(p.startswith("main:") for p in problems), "main may require it"

    def test_a_check_that_is_neither_required_nor_advisory_is_named(self, gate):
        """The rule with teeth. Adding a gate to CI is a decision about the
        merge contract, made in a diff — not a default reached by forgetting."""
        rules = _ruleset(develop=["test"], main=["test"])
        problems = gate.audit(rules, ROWS)
        assert any("'workflow-lint' is neither required" in p for p in problems)

    def test_an_advisory_entry_excuses_a_check(self, gate):
        rules = _ruleset(
            develop=["test"],
            main=["test", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "example reason"},
        )
        assert gate.audit(rules, ROWS) == []

    def test_an_advisory_entry_with_no_reason_is_refused(self, gate):
        """An unexplained exclusion is the thing this file exists to prevent."""
        rules = _ruleset(
            develop=["test"],
            main=["test", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "   "},
        )
        assert any("has no reason" in p for p in gate.audit(rules, ROWS))

    def test_a_check_cannot_be_both_required_and_advisory(self, gate):
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "a reason"},
        )
        assert any("both required and listed as advisory" in p for p in gate.audit(rules, ROWS))

    def test_a_stale_advisory_entry_is_refused(self, gate):
        """A check that no longer exists, still carrying an excuse, reads as a
        considered decision about something that is not there."""
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"long-deleted-job": "a reason"},
        )
        assert any("matches no PR check" in p for p in gate.audit(rules, ROWS))

    def test_a_duplicated_context_is_refused(self, gate):
        rules = _ruleset(
            develop=["test", "test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
        )
        assert any("listed twice" in p for p in gate.audit(rules, ROWS))


class TestTheShippedRuleset:
    def test_the_shipped_ruleset_agrees_with_the_live_workflows(self, gate):
        """The gate over the real thing — this is what `ci.yml` runs."""
        assert gate.main([]) == 0

    def test_main_requires_a_superset_of_develop(self, gate):
        """Aside from develop's integration aggregate, main requires every
        direct check develop requires and adds its release-only checks."""
        rules = gate.load_ruleset()["branches"]
        develop = set(rules["develop"]["required_status_checks"]["contexts"])
        main = set(rules["main"]["required_status_checks"]["contexts"])
        assert "integration-scope" in develop
        assert develop - {"integration-scope"} < main

    def test_the_ruleset_matches_ADR_095s_protection_table(self, gate) -> None:
        """The table in `docs/adr/ADR-095-four-tier-branch-model.md`, pinned.

        An earlier draft of the ruleset diverged from it in four places — one
        approval on `develop`, no `integration` entry, linear history off, and
        `enforce_admins` on — and the test here asserted *my* version rather
        than the ADR's, so it agreed with the mistake. Spelling the accepted
        table out is what makes the file checkable against its own governance
        instead of against itself.
        """
        #: branch -> required approvals, per ADR-095's protection table as
        #: amended by the M0 policy reconciliation: `integration` is retired
        #: (ADR-095 "integration is retired"), leaving the two live tiers.
        expected_approvals = {"develop": 0, "main": 1}
        rules = gate.load_ruleset()["branches"]
        assert set(rules) == set(expected_approvals), "ADR-095 protects both live tiers"
        for branch, rule in rules.items():
            reviews = rule["required_pull_request_reviews"]
            assert reviews["required_approving_review_count"] == expected_approvals[branch], branch
            # Linear history on develop -> merges are squash or rebase. `main`
            # "intentionally permits merge commits and does not require linear
            # history" (ADR-095 as amended): release merges are its markers.
            assert rule["required_linear_history"] is (branch != "main"), branch
            # "Admins are not enforced so a solo maintainer/agent isn't
            # deadlocked" — and the cage guard's own message promises an admin
            # can merge a legitimate cage/eval change past that required check.
            assert rule["enforce_admins"] is False, branch
            assert rule["allow_force_pushes"] is False, branch
            assert rule["allow_deletions"] is False, branch
            assert rule["required_status_checks"]["strict"] is True, branch
            assert rule["required_conversation_resolution"] is True, branch

    def test_main_requires_a_superset_of_the_other_tiers(self, gate) -> None:
        """Lower tiers may aggregate specialized checks, but every direct lower
        tier requirement must still be present on main."""
        rules = gate.load_ruleset()["branches"]
        main = set(rules["main"]["required_status_checks"]["contexts"])
        for lower in set(rules) - {"main"}:
            lower_contexts = set(rules[lower]["required_status_checks"]["contexts"])
            if lower == "develop":
                assert "integration-scope" in lower_contexts
                lower_contexts -= {"integration-scope"}
            assert lower_contexts < main, lower

    def test_the_apply_payload_carries_no_comment_keys(self, gate, capsys):
        """`$comment` keys are for the reader; GitHub's API rejects unknown
        fields, so the printed call must not contain them."""
        assert gate.main(["--apply", "develop"]) == 0
        out = capsys.readouterr().out
        assert "$comment" not in out
        payload = json.loads(out[out.index("{") : out.rindex("}") + 1])
        assert payload["required_conversation_resolution"] is True
        assert "contexts" in payload["required_status_checks"]

    def test_the_ruleset_file_is_the_one_the_gate_reads(self, gate):
        assert gate.RULESET == RULESET
        assert json.loads(RULESET.read_text())["repository"]["allow_auto_merge"] is True


class TestScopeAwareRequirability:
    """Rule 2 reads each check's own scope, not a "coupled means main" shortcut.

    That shortcut was wrong in both directions, and both are pinned here: a
    `paths:`-filtered check was in no coupled set and so could be required
    while never reporting, and a `branches-ignore: [main]` check was treated as
    valid on `main` — the one branch it does not run on. Either way the audit
    passed while branch protection waited on `Expected` forever.
    """

    @pytest.mark.parametrize("branch", ["develop", "integration", "main"])
    def test_a_paths_filtered_check_is_requirable_nowhere(self, gate, branch) -> None:
        """It never reports on a PR that misses the filter, and protection
        cannot tell "did not run" from "not finished yet"."""
        assert gate._requirable_on("paths", branch, {}, "c") is False

    def test_a_branches_ignore_check_is_refused_on_the_branch_it_ignores(self, gate) -> None:
        assert gate._requirable_on("base-ignore `main`", "main", {}, "c") is False
        assert gate._requirable_on("base-ignore `main`", "develop", {}, "c") is True

    def test_a_base_filtered_check_is_requirable_only_on_its_named_branches(self, gate) -> None:
        assert gate._requirable_on("base `main`", "main", {}, "c") is True
        assert gate._requirable_on("base `main`", "develop", {}, "c") is False

    def test_several_named_branches_are_all_honoured(self, gate) -> None:
        scope = "base `main`, `integration`"
        assert gate._requirable_on(scope, "integration", {}, "c") is True
        assert gate._requirable_on(scope, "develop", {}, "c") is False

    def test_a_job_if_coupling_must_be_declared_rather_than_guessed(self, gate) -> None:
        """A job `if:` narrows on a GitHub expression the contract does not
        evaluate. Guessing "main" would be right today and silently wrong the
        first time someone couples a job to a different branch."""
        scope = "every PR, job `if:` on base_ref"
        assert gate._requirable_on(scope, "main", {}, "c") is False
        assert gate._requirable_on(scope, "main", {"c": ["main"]}, "c") is True
        assert gate._requirable_on(scope, "develop", {"c": ["main"]}, "c") is False

    def test_an_unfiltered_check_is_requirable_everywhere(self, gate) -> None:
        assert gate._requirable_on("every PR", "develop", {}, "c") is True

    def test_a_stale_base_coupled_to_entry_is_refused(self, gate) -> None:
        """An entry for a check that no longer exists reads as a considered
        decision about something that is not there."""
        rules = _ruleset(develop=["test", "workflow-lint"], main=["test", "workflow-lint"])
        rules["base_coupled_to"] = {"long-deleted-job": ["main"]}
        rules["advisory"] = {
            "Analyze (python)": "CodeQL is main-only",
            "Container scan + SBOM + cosign": "main-only",
        }
        assert any("matches no PR check" in p for p in gate.audit(rules, ROWS))


class TestLiveVerification:
    """`--verify` must compare everything the file declares.

    It previously checked the context set and the approving-review count only,
    so it could print OK while up-to-date-with-base enforcement or stale-review
    dismissal was off — a verification that reassures without verifying is
    worse than none.
    """

    def _live(self, **overrides):
        live = {
            "required_status_checks": {"strict": True, "contexts": ["test"]},
            "required_pull_request_reviews": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews": True,
            },
            "enforce_admins": {"enabled": False},
            "required_linear_history": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_conversation_resolution": {"enabled": True},
        }
        live.update(overrides)
        return live

    def test_a_matching_rule_reports_no_differences(self, gate) -> None:
        assert gate._diff_live("develop", _rule(["test"]), self._live()) == []

    def test_strict_being_off_live_is_caught(self, gate) -> None:
        """Without `strict`, two individually-green PRs can merge into a broken
        branch — the failure mode this repo already sees on every concurrent
        pair of SUITE-INVENTORY edits."""
        live = self._live(required_status_checks={"strict": False, "contexts": ["test"]})
        assert any("strict" in line for line in gate._diff_live("develop", _rule(["test"]), live))

    def test_dismiss_stale_reviews_being_off_live_is_caught(self, gate) -> None:
        """Off, an approval survives a force-push that replaces the diff it
        approved."""
        live = self._live(
            required_pull_request_reviews={
                "required_approving_review_count": 0,
                "dismiss_stale_reviews": False,
            }
        )
        lines = gate._diff_live("develop", _rule(["test"]), live)
        assert any("dismiss_stale_reviews" in line for line in lines)

    def test_a_missing_context_is_caught(self, gate) -> None:
        live = self._live(required_status_checks={"strict": True, "contexts": []})
        lines = gate._diff_live("develop", _rule(["test"]), live)
        assert any("required by this file but not live" in line for line in lines)

    def test_linear_history_being_off_live_is_caught(self, gate) -> None:
        live = self._live(required_linear_history={"enabled": False})
        lines = gate._diff_live("develop", _rule(["test"]), live)
        assert any("required_linear_history" in line for line in lines)


# --- #268: the prose summary is generated, not remembered --------------------


def _doc_ruleset(contexts_by_branch: dict) -> dict:
    """A ruleset in the shape `render_doc_tables` reads."""
    return {
        "base_coupled_to": {"Container scan + SBOM + cosign": ["main"]},
        "branches": {
            branch: {
                "required_status_checks": {"strict": True, "contexts": contexts},
                "required_pull_request_reviews": {
                    "required_approving_review_count": 1 if branch == "main" else 0
                },
                "required_linear_history": True,
                "allow_force_pushes": False,
                "allow_deletions": False,
            }
            for branch, contexts in contexts_by_branch.items()
        },
    }


DOC_ROWS = [
    ("CI", "test", "every PR"),
    ("security", "Container scan + SBOM + cosign", "every PR, job `if:` on base_ref"),
]


class TestGeneratedTables:
    def test_the_count_column_comes_from_the_ruleset(self, gate) -> None:
        """The drift #268 found: the doc said 15 where the ruleset had 24."""
        ruleset = _doc_ruleset(
            {"develop": ["test"], "main": ["test", "Container scan + SBOM + cosign"]}
        )
        table = gate.render_doc_tables(ruleset, DOC_ROWS)
        assert "| `develop` | yes | **0** | yes | no | no | **1** |" in table
        assert "| `main` | yes | **1** | yes | no | no | **2** |" in table

    def test_a_check_that_cannot_report_is_a_circle_not_a_blank(self, gate) -> None:
        """`○` is a fact about GitHub — the trigger means it can never report
        there. Rendering it the same as a deliberate exclusion would let a
        judgement hide inside a constraint."""
        ruleset = _doc_ruleset(
            {"develop": ["test"], "main": ["test", "Container scan + SBOM + cosign"]}
        )
        table = gate.render_doc_tables(ruleset, DOC_ROWS)
        row = next(ln for ln in table.splitlines() if ln.startswith("| `Container scan"))
        assert row.endswith(f"| {gate.MARK_UNREPORTABLE} | {gate.MARK_REQUIRED} |")

    def test_a_check_that_could_be_required_but_is_not_reads_advisory(self, gate) -> None:
        """Distinct from `○`: this one *can* report here and someone chose it
        should not gate. The table has to say which of the two it is."""
        ruleset = _doc_ruleset({"develop": [], "main": ["test"]})
        table = gate.render_doc_tables(ruleset, [("CI", "test", "every PR")])
        row = next(ln for ln in table.splitlines() if ln.startswith("| `test`"))
        assert row.endswith(f"| {gate.MARK_ADVISORY} | {gate.MARK_REQUIRED} |")

    def test_the_live_document_matches_the_live_ruleset(self, gate) -> None:
        """The end-to-end claim: what ships agrees with what will be applied."""
        contract = gate._contract()
        assert gate.doc_problems(gate.load_ruleset(), contract.collect(), update=False) == []

    def test_a_changed_count_fails(self, gate, tmp_path, monkeypatch) -> None:
        """Acceptance for #268, half one: mutate a count, see it caught.

        The count is found in the rendered table rather than written here as a
        literal. A literal made this test fail the moment the required-check
        set grew: the replace stopped matching, the document went unmutated,
        and the gate correctly reported nothing — which is the one outcome a
        mutation test cannot tell apart from a broken gate.
        """
        doc = tmp_path / "BRANCH-PROTECTION.md"
        ruleset = gate.load_ruleset()
        contract = gate._contract()
        rows = contract.collect()
        rendered = gate.render_doc_tables(ruleset, rows)
        doc.write_text(
            f"{gate.DOC_BEGIN}\n\n{rendered}\n\n{gate.DOC_END}\n",
            encoding="utf-8",
        )

        counted = re.search(r"\| \*\*(\d+)\*\* \|", rendered)
        assert counted, "the branch table renders no bolded count to mutate"
        wrong = f"| **{int(counted.group(1)) + 1}** |"
        doc.write_text(
            doc.read_text(encoding="utf-8").replace(counted.group(0), wrong, 1), encoding="utf-8"
        )
        monkeypatch.setattr(gate, "DOC", doc)
        problems = gate.doc_problems(ruleset, rows, update=False)
        assert problems and "disagrees with" in problems[0]

    def test_a_changed_membership_mark_fails(self, gate, tmp_path, monkeypatch) -> None:
        """Half two, and the harder error: the totals still add up, but one
        check has moved between required and not."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        ruleset = gate.load_ruleset()
        contract = gate._contract()
        rows = contract.collect()
        rendered = gate.render_doc_tables(ruleset, rows)
        flipped = rendered.replace(
            f"| `test` | {gate.MARK_REQUIRED} |", f"| `test` | {gate.MARK_UNREPORTABLE} |", 1
        )
        assert flipped != rendered, "the mutation must actually change something"
        doc.write_text(f"{gate.DOC_BEGIN}\n\n{flipped}\n\n{gate.DOC_END}\n", encoding="utf-8")
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.doc_problems(ruleset, rows, update=False)

    def test_missing_markers_fail_rather_than_pass_quietly(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        """A document with the region deleted must not read as "nothing to
        check" — that is how a gate stops gating without saying so."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text("# Branch protection\n\nno markers here\n", encoding="utf-8")
        monkeypatch.setattr(gate, "DOC", doc)
        problems = gate.doc_problems(gate.load_ruleset(), gate._contract().collect(), update=False)
        assert problems and "markers" in problems[0]

    def test_prose_outside_the_region_is_not_touched(self, gate, tmp_path, monkeypatch) -> None:
        """The reasoning is the point of that document; the gate must not own
        it. A change to the prose alone is not a failure."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        ruleset = gate.load_ruleset()
        rows = gate._contract().collect()
        body = gate.render_doc_tables(ruleset, rows)
        doc.write_text(
            f"# Branch protection\n\nWhy strict costs what it costs.\n\n"
            f"{gate.DOC_BEGIN}\n\n{body}\n\n{gate.DOC_END}\n\nAnd the trailing argument.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.doc_problems(ruleset, rows, update=False) == []
        doc.write_text(
            doc.read_text(encoding="utf-8").replace(
                "the trailing argument", "a rewritten argument"
            ),
            encoding="utf-8",
        )
        assert gate.doc_problems(ruleset, rows, update=False) == []

    def test_update_doc_writes_a_region_that_then_passes(self, gate, tmp_path, monkeypatch) -> None:
        """The generator and the checker must agree, or `--update-doc` produces
        a document that still fails — or worse, one that passes while saying
        something the ruleset does not."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(
            f"# Branch protection\n\n{gate.DOC_BEGIN}\n{gate.DOC_END}\n\ntrailing prose\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.main(["--update-doc"]) == 0

        written = doc.read_text(encoding="utf-8")
        assert "| Branch | PR | Approvals" in written
        assert "trailing prose" in written, "the generator must not eat the narrative"
        assert (
            gate.doc_problems(gate.load_ruleset(), gate._contract().collect(), update=False) == []
        )

    def test_a_missing_document_is_reported_not_crashed_on(
        self, gate, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(gate, "DOC", tmp_path / "gone.md")
        problems = gate.doc_problems(gate.load_ruleset(), gate._contract().collect(), update=False)
        assert problems and "does not exist" in problems[0]

    def test_main_fails_and_says_so_when_the_document_drifts(
        self, gate, tmp_path, monkeypatch, capsys
    ) -> None:
        """End to end: the drift has to reach a non-zero exit and a diagnosis,
        not just a helper returning a list nobody prints."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(f"{gate.DOC_BEGIN}\n\nstale\n\n{gate.DOC_END}\n", encoding="utf-8")
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.main([]) == 1
        out = capsys.readouterr().out
        assert "does not hang together" in out
        assert "--update-doc" in out


# --- #85: the declared policy, the generated document and GitHub compared ----


def _live_view(
    contexts,
    *,
    approvals=0,
    stale=True,
    methods=("squash", "rebase"),
    rules=("creation", "deletion", "non_fast_forward", "required_linear_history"),
):
    """A ruleset read-back in the shape `normalize_ruleset` produces."""
    return {
        "id": 1,
        "name": "Pr merge",
        "enforcement": "active",
        "target": "refs/heads/develop",
        "required_status_checks": {"strict": True, "contexts": sorted(contexts)},
        "required_approving_review_count": approvals,
        "dismiss_stale_reviews_on_push": stale,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": True,
        "allowed_merge_methods": sorted(methods),
        "rules": sorted(rules),
        "merge_queue": None,
        "bypass": [{"actor_type": "OrganizationAdmin", "bypass_mode": "always"}],
    }


def _policy(develop=("test",), main=("test",), *, additional=None):
    """A declared policy in the shape `drift` reads."""

    def branch(contexts, approvals):
        return {
            "required_status_checks": {"strict": True, "contexts": sorted(contexts)},
            "required_pull_request_reviews": {
                "required_approving_review_count": approvals,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
                "require_last_push_approval": False,
            },
            "required_conversation_resolution": True,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "block_creations": True,
            "ruleset": {
                "allowed_merge_methods": ["squash", "rebase"],
                "bypass": {"OrganizationAdmin": "always"},
                "additional_required_checks": list(additional or []),
            },
        }

    return {
        "branches": {
            "develop": branch(develop, 0),
            "main": branch(main, 1),
        }
    }


def _snapshot(develop=("test",), main=("test",), **overrides):
    snap = {
        "read_at": "2026-11-25T00:00:00Z",
        "repo": "Agent-StrongHold/Project-mAIstro",
        "default_branch": "develop",
        "rulesets": {
            "develop": _live_view(develop),
            "main": _live_view(main, approvals=1),
        },
        "classic_protection": {"develop": None, "main": None},
    }
    snap["rulesets"]["main"]["target"] = "refs/heads/main"
    snap.update(overrides)
    return snap


@pytest.fixture
def no_live_queue(gate, monkeypatch, tmp_path):
    """Synthetic branch policies do not declare the repository's real queue."""
    monkeypatch.setattr(gate, "MERGE_QUEUE", tmp_path / "absent-queue.json")


@pytest.mark.usefixtures("no_live_queue")
class TestTheLiveReadBack:
    """#85: the boundary GitHub enforces is compared, and drift is red.

    The three offline rules compare the policy with the workflows; nothing
    compared the policy with GitHub, which is the only side that decides what
    actually merges. Each test below drives one divergence to a failure line
    and asserts on the diagnosis, because the line is what a human has to act
    on — and, once recorded, what `known_live_drift` has to match exactly.
    """

    def test_a_matching_read_back_reports_no_drift(self, gate) -> None:
        rows = [("CI", "test", "every PR")]
        assert gate.drift(_policy(), _snapshot(), rows) == []
        assert gate.drift_problems(_policy(), _snapshot(), rows) == []

    def test_a_check_required_live_but_not_declared_is_reported(self, gate) -> None:
        rows = [("CI", "test", "every PR"), ("CI", "docker-build", "every PR")]
        snap = _snapshot(develop=("test", "docker-build"))
        lines = gate.drift(_policy(), snap, rows)
        assert any(
            "the live ruleset requires but the policy does not declare" in line
            and "docker-build" in line
            for line in lines
        )

    def test_a_check_declared_but_not_required_live_is_reported(self, gate) -> None:
        """The enforcement gap: a gate the contract says blocks which GitHub
        does not require. Reporting it is the whole point of the comparison."""
        rows = [("CI", "test", "every PR"), ("CI", "cross-product-parity", "every PR")]
        policy = _policy(develop=("test", "cross-product-parity"))
        lines = gate.drift(policy, _snapshot(), rows)
        assert any(
            "the policy declares but the live ruleset does not require" in line
            and "cross-product-parity" in line
            for line in lines
        )

    def test_a_live_required_check_no_workflow_produces_is_reported(self, gate) -> None:
        """A required context with no producer is a permanent `Expected` —
        the branch it guards can never be merged to."""
        rows = [("CI", "test", "every PR")]
        snap = _snapshot(main=("test", "ghost-check"))
        lines = gate.drift(_policy(main=("test",)), snap, rows)
        assert any(
            "'ghost-check', which no workflow in this repository produces" in line for line in lines
        )

    def test_a_ruleset_only_check_is_not_called_unproduced(self, gate) -> None:
        """`additional_required_checks` is the policy's declaration that a
        context is published outside the PR job graph; counting it as missing
        would fail every workflow_run publisher the policy already knows."""
        rows = [("CI", "test", "every PR")]
        policy = _policy(additional=["gates-ran"])
        snap = _snapshot(main=("test", "gates-ran"))
        lines = gate.drift(policy, snap, rows)
        assert not any("which no workflow" in line for line in lines)

    @pytest.mark.parametrize(
        ("field", "value", "diagnosis"),
        [
            ("enforcement", "disabled", "not active"),
            ("enforcement", "evaluate", "not active"),
            ("target", "refs/heads/other", "does not cover"),
            ("required_approving_review_count", 0, "required_approving_review_count"),
            ("dismiss_stale_reviews_on_push", False, "dismiss_stale_reviews"),
            ("require_code_owner_review", True, "require_code_owner_reviews"),
            ("require_last_push_approval", True, "require_last_push_approval"),
        ],
    )
    def test_boundary_drift_is_red(self, gate, monkeypatch, field, value, diagnosis):
        monkeypatch.setattr(gate, "MERGE_QUEUE", Path("/nonexistent-issue85-queue"))
        snap = _snapshot()
        snap["rulesets"]["main"][field] = value
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        monkeypatch.setattr(gate, "load_snapshot", lambda: snap)
        lines = gate.verify_live(_policy(), "test-token", [("CI", "test", "every PR")])
        assert any(diagnosis in line for line in lines)

    def test_strict_checks_cannot_be_disabled_silently(self, gate):
        snap = _snapshot()
        snap["rulesets"]["develop"]["required_status_checks"]["strict"] = False
        assert any(
            "required_status_checks.strict" in line for line in gate.drift(_policy(), snap, [])
        )

    def test_documenting_drift_does_not_authorize_live_mismatch(self, gate, monkeypatch):
        monkeypatch.setattr(gate, "MERGE_QUEUE", Path("/nonexistent-issue85-queue"))
        policy = _policy()
        snap = _snapshot(develop=())
        rows = [("CI", "test", "every PR")]
        policy["known_live_drift"] = {
            line: {"reason": "documented enforcement gap", "owner": "maintainer"}
            for line in gate.drift(policy, snap, rows)
        }
        assert gate.drift_problems(policy, snap, rows) == []
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        monkeypatch.setattr(gate, "load_snapshot", lambda: snap)
        assert any(
            "does not require: test" in line for line in gate.verify_live(policy, "token", rows)
        )
        monkeypatch.setenv("GH_TOKEN", "test-token")
        assert gate.verify(policy, rows) == 1

    def test_explicit_verification_without_credentials_fails(self, gate, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert gate.verify(_policy(), []) == 1

    def test_default_branch_change_invalidates_read_back(self, gate):
        assert gate.snapshot_staleness(_snapshot(), _snapshot(default_branch="main"))

    def test_live_document_drift_reaches_nonzero_exit(self, gate, tmp_path, monkeypatch):
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(gate.DOC.read_text().replace("| **31** |", "| **999** |", 1))
        assert "**999**" in doc.read_text(), "mutation must change the live table"
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.main([]) == 1

    def test_refresh_and_verify_use_read_only_api_and_preserve_errors(self, gate, monkeypatch):
        import urllib.error

        responses = {
            "": {"default_branch": "develop"},
            "/rulesets?per_page=100": [],
            "/branches/develop/protection": urllib.error.HTTPError(
                "url", 403, "Forbidden", {}, None
            ),
        }

        def get(url, _token):
            response = responses[url.split(gate.REPO, 1)[1]]
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(gate, "_get", get)
        lines = gate.verify_live(_policy(), "token", [])
        assert lines == ["FAIL: reading the live rulesets failed: HTTP 403"]

    @pytest.mark.parametrize(
        "selector",
        [
            {"include": ["refs/heads/main", "refs/heads/develop"]},
            {"include": ["~ALL"], "exclude": ["refs/heads/main"]},
        ],
    )
    def test_unsupported_selectors_fail_closed(self, gate, selector):
        with pytest.raises(ValueError, match="unsupported ref selectors"):
            gate.normalize_ruleset({"conditions": {"ref_name": selector}})

    def test_overlapping_rulesets_fail_closed(self, gate, monkeypatch):
        def get(url, _token):
            if url.endswith(gate.REPO):
                return {"default_branch": "develop"}
            if "?per_page" in url:
                return [{"id": 1}, {"id": 2}]
            return {
                "target": "branch",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
            }

        monkeypatch.setattr(gate, "_get", get)
        with pytest.raises(ValueError, match="overlapping rulesets"):
            gate.fetch_live("token")


# --- #85 CI repair: every branch of the read-back machinery is exercised -----
#
# The first cut of these tests drove the happy path of the recorded read-back
# and the offline gate, and left the reduction, recording and refresh halves
# unexercised — the exact state the diff-coverage floor exists to name. Each
# test below pins one branch the first cut never ran, against synthetic API
# payloads, so the whole comparison machinery is provable without a token.


def _raw_ruleset(include=("~DEFAULT_BRANCH",)):
    """A ruleset as the GitHub API returns it, carrying every rule kind."""
    return {
        "id": 7,
        "name": "Pr merge",
        "enforcement": "active",
        "target": "branch",
        "conditions": {"ref_name": {"include": list(include), "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": "test", "app_id": None}],
                },
            },
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["squash", "rebase"],
                },
            },
            {
                "type": "merge_queue",
                "parameters": {"merge_method": "SQUASH", "min_entries_to_merge": 1},
            },
            {"type": "creation"},
        ],
        "bypass_actors": [{"actor_type": "OrganizationAdmin", "bypass_mode": "always"}],
    }


_CLASSIC = {
    "required_status_checks": {"strict": True, "contexts": ["test", "Analyze (python)"]},
    "required_pull_request_reviews": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
    },
    "required_linear_history": {"enabled": True},
    "allow_force_pushes": {"enabled": False},
}


class TestNormalizingTheLiveApi:
    """The API's payload is reduced to the fields the policy declares."""

    def test_a_full_ruleset_reduces_to_the_declared_fields(self, gate):
        view = gate.normalize_ruleset(_raw_ruleset())
        assert view["id"] == 7
        assert view["name"] == "Pr merge"
        assert view["enforcement"] == "active"
        assert view["target"] == "~DEFAULT_BRANCH"
        assert view["required_status_checks"] == {"strict": True, "contexts": ["test"]}
        assert view["required_approving_review_count"] == 1
        assert view["dismiss_stale_reviews_on_push"] is True
        assert view["require_code_owner_review"] is False
        assert view["require_last_push_approval"] is False
        assert view["required_review_thread_resolution"] is True
        assert view["allowed_merge_methods"] == ["rebase", "squash"]
        assert view["merge_queue"] == {"merge_method": "SQUASH", "min_entries_to_merge": 1}
        # The queue is recorded twice: as its parameters and as a rule kind.
        # An unrecognised kind (creation) is kept as a name, not dropped.
        assert view["rules"] == ["creation", "merge_queue"]
        assert view["bypass"] == [
            {"actor_type": "OrganizationAdmin", "actor_id": None, "bypass_mode": "always"}
        ]

    def test_a_classic_payload_reduces_with_flags_unwrapped(self, gate):
        view = gate.normalize_classic(_CLASSIC)
        assert view["required_status_checks"] == {
            "strict": True,
            "contexts": ["Analyze (python)", "test"],
        }
        assert view["required_pull_request_reviews"]["required_approving_review_count"] == 1
        assert view["required_pull_request_reviews"]["dismiss_stale_reviews"] is True
        assert view["required_linear_history"] is True
        assert view["allow_force_pushes"] is False
        # A flag GitHub omits reads as None, not as an invented default.
        assert view["allow_deletions"] is None

    def test_branch_targets_map_to_the_vocabulary_both_sides_use(self, gate):
        assert gate.branch_for_target("~DEFAULT_BRANCH", "develop") == "develop"
        assert gate.branch_for_target("refs/heads/main", None) == "main"
        assert gate.branch_for_target("refs/tags/v1.0", "develop") is None
        assert gate.branch_for_target(None, "develop") is None


class TestFetchLiveRecordsTheBoundary:
    """`--refresh-live` walks the rulesets, then classic protection."""

    @staticmethod
    def _install(gate, monkeypatch, responses):
        def get(url, _token):
            body = responses[url.split(gate.REPO, 1)[1]]
            if isinstance(body, Exception):
                raise body
            return body

        monkeypatch.setattr(gate, "_get", get)

    def test_fetch_live_walks_rulesets_and_records_classic_protection(self, gate, monkeypatch):
        import urllib.error

        self._install(
            gate,
            monkeypatch,
            {
                "": {"default_branch": "develop"},
                "/rulesets?per_page=100": [{"id": 1}, {"id": 2}],
                # A repository-scoped ruleset is skipped, not verified.
                "/rulesets/1": {"target": "repository", "conditions": {}},
                "/rulesets/2": _raw_ruleset(),
                "/branches/develop/protection": urllib.error.HTTPError(
                    "url", 404, "Not Found", {}, None
                ),
                "/branches/main/protection": _CLASSIC,
            },
        )
        snap = gate.fetch_live("token")
        assert snap["default_branch"] == "develop"
        assert set(snap["rulesets"]) == {"develop"}
        assert snap["rulesets"]["develop"]["target"] == "~DEFAULT_BRANCH"
        # Absent classic protection is recorded as None — the post-ADR-095
        # shape — and a live classic surface is recorded in full.
        assert snap["classic_protection"]["develop"] is None
        assert snap["classic_protection"]["main"]["required_status_checks"]["contexts"] == [
            "Analyze (python)",
            "test",
        ]

    def test_a_truncated_ruleset_listing_refuses_to_verify(self, gate, monkeypatch):
        self._install(
            gate,
            monkeypatch,
            {
                "": {"default_branch": "develop"},
                "/rulesets?per_page=100": [{"id": i} for i in range(100)],
            },
        )
        with pytest.raises(ValueError, match="may be truncated"):
            gate.fetch_live("token")

    def test_an_unmappable_branch_target_refuses_to_verify(self, gate, monkeypatch):
        self._install(
            gate,
            monkeypatch,
            {
                "": {"default_branch": "develop"},
                "/rulesets?per_page=100": [{"id": 1}],
                "/rulesets/1": _raw_ruleset(include=("refs/tags/v1",)),
            },
        )
        with pytest.raises(ValueError, match="unsupported branch target"):
            gate.fetch_live("token")


class TestSnapshotRoundTrip:
    def test_a_missing_snapshot_reads_as_empty(self, gate, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", tmp_path / "absent.json")
        assert gate.load_snapshot() == {}

    def test_write_then_load_round_trips(self, gate, tmp_path, monkeypatch):
        path = tmp_path / "live.json"
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", path)
        snap = _snapshot()
        gate.write_snapshot(snap)
        assert path.is_file()
        assert gate.load_snapshot() == snap


@pytest.mark.usefixtures("no_live_queue")
class TestEveryDriftSurfaceIsNamed:
    """Each comparison surface names the branch and both sides of the value.

    A drift check that cannot say *what* drifted cannot be reconciled, and one
    that silently passes a surface cannot be trusted. These pin the surfaces
    the boundary-drift table above does not parametrize over.
    """

    ROWS: typing.ClassVar = [("CI", "test", "every PR")]

    def test_review_thread_resolution_drift_is_reported(self, gate):
        snap = _snapshot()
        snap["rulesets"]["develop"]["required_review_thread_resolution"] = False
        lines = gate.drift(_policy(), snap, self.ROWS)
        assert any(
            "required_conversation_resolution is True in the policy and False live" in line
            for line in lines
        )

    def test_a_missing_protection_flag_is_reported_as_the_policy_side_of_it(self, gate):
        """No `non_fast_forward` rule live means force pushes are allowed."""
        snap = _snapshot()
        snap["rulesets"]["develop"]["rules"] = [
            "creation",
            "deletion",
            "required_linear_history",
        ]
        lines = gate.drift(_policy(), snap, self.ROWS)
        assert any(
            "allow_force_pushes is False in the policy and True live" in line for line in lines
        )

    def test_merge_method_drift_is_reported(self, gate):
        snap = _snapshot()
        snap["rulesets"]["main"]["allowed_merge_methods"] = ["merge"]
        lines = gate.drift(_policy(), snap, self.ROWS)
        assert any("main: allowed_merge_methods" in line for line in lines)

    def test_a_declared_queue_with_no_live_counterpart_is_reported(
        self, gate, tmp_path, monkeypatch
    ):
        queue = tmp_path / "merge-queue.json"
        queue.write_text(
            json.dumps(
                {
                    "$comment": ["reviewed posture"],
                    "branches": {"develop": {"merge_method": "SQUASH"}},
                }
            )
        )
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        lines = gate.drift(_policy(), _snapshot(), self.ROWS)
        assert any("declares a merge queue and the live ruleset has none" in line for line in lines)

    def test_comment_keys_do_not_read_as_queue_drift(self, gate, tmp_path, monkeypatch):
        """The `$`-prefixed prose in the queue file is for the reader."""
        queue = tmp_path / "merge-queue.json"
        queue.write_text(
            json.dumps(
                {
                    "$comment": ["why"],
                    "branches": {"develop": {"$note": "prose", "merge_method": "SQUASH"}},
                }
            )
        )
        monkeypatch.setattr(gate, "MERGE_QUEUE", queue)
        snap = _snapshot()
        snap["rulesets"]["develop"]["merge_queue"] = {"merge_method": "SQUASH"}
        assert gate.drift(_policy(), snap, self.ROWS) == []

    def test_classic_protection_diverging_from_the_policy_is_reported(self, gate):
        snap = _snapshot()
        snap["classic_protection"]["develop"] = {
            "required_pull_request_reviews": {"required_approving_review_count": 2},
            "required_status_checks": {},
        }
        lines = gate.drift(_policy(), snap, self.ROWS)
        assert any(
            "classic branch protection is active alongside the ruleset and differs" in line
            and "required_approving_review_count is 0 in the policy and 2 live" in line
            for line in lines
        )

    def test_a_branch_no_ruleset_covers_is_reported(self, gate):
        snap = _snapshot()
        del snap["rulesets"]["main"]
        lines = gate.drift(_policy(), snap, self.ROWS)
        assert any("main: the live rulesets do not cover this branch" in line for line in lines)

    def test_a_ruleset_target_that_differs_from_the_policy_is_reported(self, gate):
        policy = _policy()
        policy["branches"]["main"]["ruleset"]["target"] = "refs/heads/develop"
        lines = gate.drift(policy, _snapshot(), self.ROWS)
        assert any("main: ruleset target differs from the policy" in line for line in lines)


class TestDriftMustBeRecordedWhileItExists:
    """Both halves of `known_live_drift` accounting, and the leaf-path walker
    `snapshot_staleness` reports through."""

    ROWS: typing.ClassVar = [("CI", "test", "every PR")]

    def test_unrecorded_drift_is_named(self, gate):
        snap = _snapshot(develop=())
        problems = gate.drift_problems(_policy(), snap, self.ROWS)
        assert any("live drift nobody has recorded" in p for p in problems)

    def test_a_recorded_entry_without_a_reason_is_refused(self, gate):
        snap = _snapshot(develop=())
        policy = _policy()
        known = policy.setdefault("known_live_drift", {})
        for line in gate.drift(policy, snap, self.ROWS):
            known[line] = {"reason": "   ", "owner": "maintainer"}
        problems = gate.drift_problems(policy, snap, self.ROWS)
        assert any("recorded live drift has no reason" in p for p in problems)
        assert not any("nobody has recorded" in p for p in problems)

    def test_a_recorded_entry_without_an_owner_is_refused(self, gate):
        snap = _snapshot(develop=())
        policy = _policy()
        known = policy.setdefault("known_live_drift", {})
        for line in gate.drift(policy, snap, self.ROWS):
            known[line] = {"reason": "why", "owner": ""}
        assert any(
            "recorded live drift has no owner" in p
            for p in gate.drift_problems(policy, snap, self.ROWS)
        )

    def test_lists_that_differ_are_reported_at_their_leaf(self, gate):
        assert gate._diff_paths({"a": [1]}, {"a": [2]}, "root") == ["root.a"]


class TestTheLiveDocumentRegion:
    """The generated live region is written by `--update-doc` and checked
    offline; every writer branch and the missing-document branch are pinned
    here, the way `TestGeneratedTables` pins the declared region's."""

    ROWS: typing.ClassVar = [("CI", "test", "every PR")]

    def test_a_missing_document_is_reported(self, gate, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "DOC", tmp_path / "gone.md")
        problems = gate.live_doc_problems(_snapshot(), self.ROWS, update=False)
        assert problems and "does not exist" in problems[0]

    def test_update_rewrites_the_region_in_place(self, gate, tmp_path, monkeypatch):
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(
            f"prose\n\n{gate.LIVE_DOC_BEGIN}\n\nstale\n\n{gate.LIVE_DOC_END}\n\nmore prose\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.live_doc_problems(_snapshot(), self.ROWS, update=True) == []
        written = doc.read_text(encoding="utf-8")
        assert "stale" not in written
        assert "| `develop` |" in written
        assert "more prose" in written, "the generator must not eat the narrative"

    def test_update_lands_the_region_after_the_declared_one(self, gate, tmp_path, monkeypatch):
        """The two tables are meant to be read against each other."""
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(
            f"prose\n\n{gate.DOC_BEGIN}\n\ntables\n\n{gate.DOC_END}\n\ntrailing\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.live_doc_problems(_snapshot(), self.ROWS, update=True) == []
        written = doc.read_text(encoding="utf-8")
        assert written.index(gate.DOC_END) < written.index(gate.LIVE_DOC_BEGIN)
        assert "trailing" in written

    def test_update_creates_the_region_in_a_document_without_markers(
        self, gate, tmp_path, monkeypatch
    ):
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text("# Branch protection\n", encoding="utf-8")
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.live_doc_problems(_snapshot(), self.ROWS, update=True) == []
        assert gate.LIVE_DOC_BEGIN in doc.read_text(encoding="utf-8")

    def test_a_transport_failure_while_verifying_fails_with_the_reason(self, gate, monkeypatch):
        import urllib.error

        def boom(_token):
            raise urllib.error.URLError("name resolution failed")

        monkeypatch.setattr(gate, "fetch_live", boom)
        lines = gate.verify_live(_policy(), "token", self.ROWS)
        assert lines and lines[0].startswith("FAIL: reading the live rulesets failed:")
        assert "name resolution failed" in lines[0]


@pytest.mark.usefixtures("no_live_queue")
class TestRefreshLive:
    """`--refresh-live` refuses without credentials and records with them."""

    @staticmethod
    def _no_credentials(monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def test_without_credentials_it_refuses(self, gate, monkeypatch, capsys):
        self._no_credentials(monkeypatch)
        assert gate.refresh_live([], update_doc=False) == 1
        assert "needs GH_TOKEN or GITHUB_TOKEN" in capsys.readouterr().out

    def test_an_http_failure_is_reported_not_raised(self, gate, monkeypatch, capsys):
        import urllib.error

        monkeypatch.setenv("GH_TOKEN", "t")

        def boom(_token):
            raise urllib.error.HTTPError("url", 503, "nope", {}, None)

        monkeypatch.setattr(gate, "fetch_live", boom)
        assert gate.refresh_live([], update_doc=False) == 1
        assert "HTTP 503" in capsys.readouterr().out

    def test_a_transport_failure_is_reported_not_raised(self, gate, monkeypatch, capsys):
        monkeypatch.setenv("GH_TOKEN", "t")

        def boom(_token):
            raise OSError("connection reset")

        monkeypatch.setattr(gate, "fetch_live", boom)
        assert gate.refresh_live([], update_doc=False) == 1
        assert "connection reset" in capsys.readouterr().out

    def test_a_successful_read_is_recorded(self, gate, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("GH_TOKEN", "t")
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", tmp_path / "live.json")
        snap = _snapshot()
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        assert gate.refresh_live([], update_doc=False) == 0
        assert gate.load_snapshot() == snap
        assert "recorded the live merge boundary" in capsys.readouterr().out

    def test_refresh_can_update_the_document_in_the_same_pass(
        self, gate, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("GH_TOKEN", "t")
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", tmp_path / "live.json")
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(
            f"p\n\n{gate.LIVE_DOC_BEGIN}\n\nold\n\n{gate.LIVE_DOC_END}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        snap = _snapshot()
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        assert gate.refresh_live([], update_doc=True) == 0
        assert "old" not in doc.read_text(encoding="utf-8")
        assert "updated the live read-back region" in capsys.readouterr().out

    #: `main()` renders the `--refresh-live` help eagerly, which resolves the
    #: snapshot path against the repository root — so these main-level tests
    #: stand in a repo-relative stand-in path rather than a tmp_path one, and
    #: keep the recorded write out of the tree with a recorder.
    ABSENT = ROOT / ".github" / "live-merge-boundary.issue85-absent.json"

    def test_update_doc_skips_the_live_region_when_nothing_is_recorded(
        self, gate, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", self.ABSENT)
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(f"p\n\n{gate.DOC_BEGIN}\n{gate.DOC_END}\n\ntrailing\n", encoding="utf-8")
        monkeypatch.setattr(gate, "DOC", doc)
        assert gate.main(["--update-doc"]) == 0
        out = capsys.readouterr().out
        assert "SKIP" in out and "record it with --refresh-live" in out

    def test_no_recorded_read_back_fails_ci_rather_than_passing_quietly(
        self, gate, monkeypatch, tmp_path, capsys
    ):
        """A missing snapshot is an unrecorded boundary, not a passing one."""
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", self.ABSENT)
        assert gate.main([]) == 1
        out = capsys.readouterr().out
        assert "no recorded live read-back" in out
        assert "--refresh-live" in out


# --- #85: --verify end to end, against a GitHub that obeys the policy -------


_ROLE_IDS = {"admin": 5, "maintain": 4, "write": 2, "read": 1}


def _policy_consistent_snapshot(ruleset):
    """A read-back of a GitHub that enforces exactly what the policy declares.

    Built from the ruleset itself rather than written by hand: if a setting is
    added to the policy, the fake GitHub enforces it too, and the test stays
    about the comparison instead of about a hand-copied payload that slowly
    rots away from the file it mirrors.
    """
    rulesets = {}
    for branch, rule in ruleset["branches"].items():
        reviews = rule["required_pull_request_reviews"]
        rs = rule["ruleset"]
        bypass = []
        for actor, mode in rs["bypass"].items():
            kind, _, identity = actor.partition(":")
            bypass.append(
                {
                    "actor_type": kind,
                    "actor_id": (
                        _ROLE_IDS.get(identity, identity) if kind == "RepositoryRole" else None
                    ),
                    "bypass_mode": mode,
                }
            )
        rulesets[branch] = {
            "id": len(rulesets) + 1,
            "name": rs["name"],
            "enforcement": "active",
            "target": rs["target"],
            "required_status_checks": {
                "strict": rule["required_status_checks"]["strict"],
                "contexts": sorted(
                    set(rule["required_status_checks"]["contexts"])
                    | set(rs.get("additional_required_checks") or [])
                ),
            },
            "required_approving_review_count": reviews["required_approving_review_count"],
            "dismiss_stale_reviews_on_push": reviews["dismiss_stale_reviews"],
            "require_code_owner_review": reviews["require_code_owner_reviews"],
            "require_last_push_approval": reviews["require_last_push_approval"],
            "required_review_thread_resolution": rule["required_conversation_resolution"],
            "allowed_merge_methods": sorted(rs["allowed_merge_methods"]),
            "rules": sorted(
                (["creation"] if rule["block_creations"] else [])
                + ([] if rule["allow_deletions"] else ["deletion"])
                + ([] if rule["allow_force_pushes"] else ["non_fast_forward"])
                + (["required_linear_history"] if rule["required_linear_history"] else [])
            ),
            "merge_queue": None,
            "bypass": bypass,
        }
    return {
        "read_at": "2026-01-01T00:00:00Z",
        "repo": "Agent-StrongHold/Project-mAIstro",
        "default_branch": "develop",
        "rulesets": rulesets,
        "classic_protection": {"develop": None, "main": None},
    }


@pytest.mark.usefixtures("no_live_queue")
class TestEndToEndVerification:
    """`--verify` is green against a policy-obeying GitHub, without a token
    scope or a network — the half CI cannot run, proven here instead."""

    @pytest.fixture
    def obeying_github(self, gate, monkeypatch, tmp_path):
        """A synthetic GitHub that enforces the policy, and a document whose
        live region was rendered from it.

        `main([])` runs the offline gate before `--verify`, and the offline
        gate compares the committed document with `load_snapshot()`. Both
        halves see the same synthetic read-back, so the only way `main` can
        return 0 is for the whole chain — policy, document, snapshot, and the
        fresh re-read — to agree.
        """
        snap = _policy_consistent_snapshot(gate.load_ruleset())
        rows = gate._contract().collect()
        # On a GitHub that enforces the policy there is nothing to excuse: the
        # shipped drift record describes the real boundary and must not leak
        # into this synthetic one.
        ruleset = {**gate.load_ruleset(), "known_live_drift": {}}
        monkeypatch.setattr(gate, "load_ruleset", lambda: ruleset)
        declared = gate.DOC.read_text(encoding="utf-8")
        declared = declared.split(gate.DOC_BEGIN, 1)[1].split(gate.DOC_END, 1)[0]
        doc = tmp_path / "BRANCH-PROTECTION.md"
        doc.write_text(
            f"{gate.DOC_BEGIN}{declared}{gate.DOC_END}\n\n"
            f"{gate.LIVE_DOC_BEGIN}\n\n{gate.render_live_tables(snap, rows)}\n\n"
            f"{gate.LIVE_DOC_END}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "DOC", doc)
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        monkeypatch.setattr(gate, "load_snapshot", lambda: snap)
        monkeypatch.setenv("GH_TOKEN", "test-token")
        return snap

    def test_verify_passes_when_github_matches_the_policy(self, gate, obeying_github):
        assert gate.verify(gate.load_ruleset(), gate._contract().collect()) == 0

    def test_main_verify_passes_and_says_so(self, gate, obeying_github, capsys):
        assert gate.main(["--verify"]) == 0
        out = capsys.readouterr().out
        assert "GitHub enforces the merge boundary this repository records" in out

    def test_main_refresh_live_records_without_a_network(self, gate, monkeypatch, tmp_path, capsys):
        snap = _policy_consistent_snapshot(gate.load_ruleset())
        monkeypatch.setattr(gate, "fetch_live", lambda _token: snap)
        monkeypatch.setattr(gate, "LIVE_SNAPSHOT", TestRefreshLive.ABSENT)
        recorded = {}
        monkeypatch.setattr(gate, "write_snapshot", lambda fresh: recorded.update(fresh))
        monkeypatch.setenv("GH_TOKEN", "test-token")
        assert gate.main(["--refresh-live"]) == 0
        assert recorded["default_branch"] == "develop"
        assert set(recorded["rulesets"]) == {"develop", "main"}
        assert "recorded the live merge boundary" in capsys.readouterr().out
