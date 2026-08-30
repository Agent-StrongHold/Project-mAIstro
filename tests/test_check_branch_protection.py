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
