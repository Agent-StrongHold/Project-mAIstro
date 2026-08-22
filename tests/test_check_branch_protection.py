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
COUPLED = {("CodeQL Advanced", "Analyze (python)"), ("security", "Container scan + SBOM + cosign")}


def _ruleset(develop, main, advisory=None):
    return {
        "branches": {
            "develop": {"required_status_checks": {"strict": True, "contexts": list(develop)}},
            "main": {"required_status_checks": {"strict": True, "contexts": list(main)}},
        },
        "advisory": advisory or {},
    }


class TestTheThreeOfflineRules:
    def test_a_consistent_ruleset_passes(self, gate):
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
        )
        assert gate.audit(rules, ROWS, COUPLED) == []

    def test_a_required_name_matching_no_job_is_named(self, gate):
        """The failure this gate exists for: a job is renamed, the protection
        rule keeps the old string, and it silently stops requiring anything."""
        rules = _ruleset(develop=["tets"], main=["test"])
        problems = gate.audit(rules, ROWS, COUPLED)
        assert any("'tets' matches no job" in p for p in problems)
        assert any("detached it from its job" in p for p in problems)

    def test_a_base_coupled_check_required_on_develop_is_named(self, gate):
        """It never reports on a develop-based PR, so the PR waits on an
        `Expected` status forever — every merge blocked, by a rule intended to
        block only bad merges."""
        rules = _ruleset(develop=["test", "Analyze (python)"], main=["test", "Analyze (python)"])
        problems = gate.audit(rules, ROWS, COUPLED)
        assert any("base-coupled to `main`" in p and "develop" in p for p in problems)
        assert not any("main:" in p for p in problems), "main may require it; that is the point"

    def test_a_check_that_is_neither_required_nor_advisory_is_named(self, gate):
        """The rule with teeth. Adding a gate to CI is a decision about the
        merge contract, made in a diff — not a default reached by forgetting."""
        rules = _ruleset(develop=["test"], main=["test"])
        problems = gate.audit(rules, ROWS, COUPLED)
        assert any("'workflow-lint' is neither required" in p for p in problems)

    def test_an_advisory_entry_excuses_a_check(self, gate):
        rules = _ruleset(
            develop=["test"],
            main=["test", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "example reason"},
        )
        assert gate.audit(rules, ROWS, COUPLED) == []

    def test_an_advisory_entry_with_no_reason_is_refused(self, gate):
        """An unexplained exclusion is the thing this file exists to prevent."""
        rules = _ruleset(
            develop=["test"],
            main=["test", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "   "},
        )
        assert any("has no reason" in p for p in gate.audit(rules, ROWS, COUPLED))

    def test_a_check_cannot_be_both_required_and_advisory(self, gate):
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"workflow-lint": "a reason"},
        )
        assert any(
            "both required and listed as advisory" in p for p in gate.audit(rules, ROWS, COUPLED)
        )

    def test_a_stale_advisory_entry_is_refused(self, gate):
        """A check that no longer exists, still carrying an excuse, reads as a
        considered decision about something that is not there."""
        rules = _ruleset(
            develop=["test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
            advisory={"long-deleted-job": "a reason"},
        )
        assert any("matches no PR check" in p for p in gate.audit(rules, ROWS, COUPLED))

    def test_a_duplicated_context_is_refused(self, gate):
        rules = _ruleset(
            develop=["test", "test", "workflow-lint"],
            main=["test", "workflow-lint", "Analyze (python)", "Container scan + SBOM + cosign"],
        )
        assert any("listed twice" in p for p in gate.audit(rules, ROWS, COUPLED))


class TestTheShippedRuleset:
    def test_the_shipped_ruleset_agrees_with_the_live_workflows(self, gate):
        """The gate over the real thing — this is what `ci.yml` runs."""
        assert gate.main([]) == 0

    def test_main_requires_a_superset_of_develop(self, gate):
        """develop's set is the checks that run everywhere; main adds the ones
        that only run there. A check required on develop and not on main would
        mean the published branch is the more weakly gated of the two."""
        rules = gate.load_ruleset()["branches"]
        develop = set(rules["develop"]["required_status_checks"]["contexts"])
        main = set(rules["main"]["required_status_checks"]["contexts"])
        assert develop < main

    def test_both_branches_require_review_and_conversation_resolution(self, gate):
        """CI cannot tell whether a test proves its criterion or restates it, so
        the approving review is part of the merge contract rather than an
        optional courtesy — and the resolution requirement is what makes an
        unresolved thread actually block, which #162 found was assumed already."""
        for branch, rule in gate.load_ruleset()["branches"].items():
            assert rule["required_pull_request_reviews"]["required_approving_review_count"] >= 1, (
                branch
            )
            assert rule["required_conversation_resolution"] is True, branch
            assert rule["required_status_checks"]["strict"] is True, branch
            assert rule["allow_force_pushes"] is False, branch
            assert rule["allow_deletions"] is False, branch

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
