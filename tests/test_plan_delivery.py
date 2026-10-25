"""Delivery recommendations must not invent completion or unowned work."""

from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plan_delivery", ROOT / "scripts/plan_delivery.py")
assert SPEC is not None and SPEC.loader is not None
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)
BASE = "a" * 40
NOW = datetime(2026, 9, 27, 8, tzinfo=UTC)


def task(identifier="core", issue=1047, **changes):
    value = {
        "id": identifier, "issue": issue, "milestone": 1, "kind": "implement",
        "implemented": False, "build_points": 3, "verify_points": 2,
        "depends_on": [], "external_blockers": [], "acceptance": ["behavior"],
        "sources": [f"https://github.com/Agent-StrongHold/Project-mAIstro/issues/{issue}"],
        "paths": [f"packages/{identifier}"], "resources": [], "evidence": [],
    }
    value.update(changes)
    return value


def snapshot(*tasks):
    rows = list(tasks) or [task()]
    return {
        "version": 1, "repository": planner.REPOSITORY, "base_sha": BASE,
        "observed_at": NOW.isoformat(),
        "coverage": {"open_prs_complete": True, "branches_complete": True,
                     "issue_comments_complete": True},
        "issues": [{"number": number, "state": "open"}
                   for number in sorted({row["issue"] for row in rows})],
        "reservations": [], "tasks": rows,
    }


def proof(criterion="behavior", **changes):
    value = {"criterion": criterion, "result": "passed", "sha": BASE,
             "command": "pytest test_behavior.py", "reference": "https://example.test/evidence/1",
             "author": "implementer", "reviewer": "independent-reviewer"}
    value.update(changes)
    return value


def reservation(*, owner="PR #1575", tasks=None, paths=None, active=True, resources=None):
    return {"owner": owner, "tasks": tasks or [], "paths": paths or ["packages/core"],
            "resources": resources or [], "active": active, "head_sha": "b" * 40,
            "reference": "https://github.com/Agent-StrongHold/Project-mAIstro/pull/1575"}


def run(value, **kwargs):
    return planner.plan(value, current_sha=BASE, now=NOW, **kwargs)


def test_selects_bounded_implementation():
    report = run(snapshot())
    assert report["frontier"][0]["selected"]
    assert report["advisory_only"]
    assert report["evidenced_slices"] == []


def test_closed_issue_with_remaining_work_is_not_completed():
    value = snapshot()
    value["issues"][0]["state"] = "closed"
    report = run(value)
    assert report["closed_issues_requiring_reconciliation"] == [1047]
    assert report["evidenced_slices"] == []


def test_landed_code_without_execution_evidence_is_verification_work():
    report = run(snapshot(task(implemented=True)))
    assert report["frontier"][0]["action"] == "verify"
    assert not report["evidenced_slices"]


def test_docs_only_proof_does_not_complete_full_feature():
    row = task(implemented=True, acceptance=["decision", "durability"], evidence=[proof("decision")])
    assert run(snapshot(row))["evidenced_slices"] == []


@pytest.mark.parametrize("result", ["failed", "skipped", "error", "pending"])
def test_nonpassing_evidence_is_never_completion(result):
    assert not run(snapshot(task(implemented=True, evidence=[proof(result=result)])))["evidenced_slices"]


@pytest.mark.parametrize("changes", [{"sha": "c" * 40}, {"reviewer": "implementer"},
                                     {"command": ""}, {"reference": ""}, {"author": ""},
                                     {"reviewer": " "}])
def test_stale_unreviewed_or_untraceable_evidence_gets_no_credit(changes):
    report = run(snapshot(task(implemented=True, evidence=[proof(**changes)])))
    assert report["evidenced_slices"] == []


def test_evidenced_dependency_unblocks_child():
    parent = task(implemented=True, evidence=[proof()])
    child = task("child", depends_on=["core"])
    report = run(snapshot(parent, child))
    assert report["evidenced_slices"] == ["core"]
    assert report["frontier"][0]["id"] == "child"


def test_child_proof_cannot_hide_unresolved_prerequisite():
    child = task("child", depends_on=["core"], implemented=True, evidence=[proof()])
    report = run(snapshot(task(), child))
    assert not report["evidenced_slices"]
    assert report["blocked"][0]["blockers"] == ["core"]


def test_external_blocker_prevents_completion():
    row = task(implemented=True, evidence=[proof()], external_blockers=["required backend proof"])
    assert not run(snapshot(row))["evidenced_slices"]


def test_conflicting_duplicate_proof_is_rejected():
    row = task(implemented=True, evidence=[proof(), proof(result="failed")])
    with pytest.raises(planner.PlanError, match="duplicate evidence"):
        run(snapshot(row))


@pytest.mark.parametrize("coverage", ["open_prs_complete", "branches_complete", "issue_comments_complete"])
def test_incomplete_census_suppresses_dispatch(coverage):
    value = snapshot()
    value["coverage"][coverage] = False
    report = run(value)
    assert report["refresh_required"]
    assert not any(t["selected"] for t in report["frontier"])


@pytest.mark.parametrize("seconds", [-1, 901])
def test_future_or_old_snapshot_suppresses_dispatch(seconds):
    value = snapshot()
    value["observed_at"] = (NOW - timedelta(seconds=seconds)).isoformat()
    report = run(value)
    assert report["refresh_required"]
    assert not report["frontier"][0]["selected"]


def test_changed_develop_suppresses_dispatch():
    report = planner.plan(snapshot(), current_sha="d" * 40, now=NOW)
    assert report["refresh_required"]
    assert not report["frontier"][0]["selected"]


def test_missing_dependency_is_not_silently_satisfied():
    with pytest.raises(planner.PlanError, match="missing dependency"):
        run(snapshot(task(depends_on=["not-fetched"])))


def test_cycle_is_not_a_partial_ready_plan():
    with pytest.raises(planner.PlanError, match="cycle"):
        run(snapshot(task(depends_on=["child"]), task("child", depends_on=["core"])))


def test_duplicate_task_is_not_overwritten():
    with pytest.raises(planner.PlanError, match="duplicate task"):
        run(snapshot(task(), task()))


@pytest.mark.parametrize("path", ["../secrets", "/tmp", "packages/../core", "packages\\core",
                                  "packages/*", "packages//core", "./packages/core", "."])
def test_invalid_write_scope_fails_closed(path):
    with pytest.raises(planner.PlanError):
        run(snapshot(task(paths=[path])))


def test_directory_reservation_blocks_descendant_edit():
    value = snapshot(task(paths=["packages/core/child.py"]))
    value["reservations"] = [reservation()]
    report = run(value)
    assert not report["frontier"]
    assert "PR #1575" in report["blocked"][0]["blockers"][0]


def test_sibling_prefix_is_not_false_conflict():
    value = snapshot(task(paths=["packages/core2"]))
    value["reservations"] = [reservation()]
    assert run(value)["frontier"][0]["selected"]


def test_shared_semantic_resource_serializes_disjoint_files():
    first = task(resources=["canonical-run-admission"])
    second = task("child", resources=["canonical-run-admission"])
    report = run(snapshot(first, second))
    assert sum(t["selected"] for t in report["frontier"]) == 1


def test_existing_owner_is_reused_not_duplicated():
    value = snapshot()
    value["reservations"] = [reservation(tasks=["core"])]
    report = run(value, wip=1)
    assert report["frontier"][0]["action"] == "continue_existing"
    assert report["frontier"][0]["selected"]


def test_existing_active_work_consumes_new_work_budget():
    value = snapshot(task("new"))
    value["reservations"] = [reservation()]
    assert not run(value, wip=1)["frontier"][0]["selected"]


def test_inactive_reservation_still_protects_ownership():
    value = snapshot()
    value["reservations"] = [reservation(active=False)]
    assert not run(value)["frontier"]


def test_multiple_owners_require_reconciliation():
    value = snapshot()
    value["reservations"] = [reservation(tasks=["core"]), reservation(owner="PR #999", tasks=["core"])]
    report = run(value)
    assert not report["frontier"]
    assert "multiple owners" in report["blocked"][0]["blockers"][0]


def test_one_owner_cannot_receive_two_simultaneous_tasks():
    value = snapshot(task(), task("child"))
    value["reservations"] = [reservation(tasks=["core", "child"])]
    assert sum(t["selected"] for t in run(value)["frontier"]) == 1


def test_critical_chain_prioritizes_dependency_work_over_isolated_cleanup():
    report = run(snapshot(task("cleanup", build_points=0), task(), task("child", depends_on=["core"])))
    assert report["frontier"][0]["id"] == "core"
    assert report["critical_chain"] == ["core", "child"]


def test_new_frontier_is_capped_and_deterministic():
    value = snapshot(*(task(str(i)) for i in range(8)))
    report = run(value, wip=2)
    assert sum(t["selected"] for t in report["frontier"]) == 2
    value["tasks"].reverse()
    assert report == run(value, wip=2)


def test_unknown_issue_state_is_not_a_closed_issue():
    value = snapshot()
    value["issues"][0]["state"] = None
    with pytest.raises(planner.PlanError, match="unknown issue state"):
        run(value)


def test_empty_acceptance_cannot_be_vacuously_complete():
    with pytest.raises(planner.PlanError, match="empty list"):
        run(snapshot(task(acceptance=[], implemented=True)))


def test_plan_does_not_mutate_snapshot():
    value = snapshot(task(paths=["packages/core/"]))
    original = deepcopy(value)
    run(value)
    assert value == original


def test_cli_reports_refresh_and_nonzero(tmp_path, capsys):
    value = snapshot()
    value["coverage"]["branches_complete"] = False
    target = tmp_path / "snapshot.json"
    target.write_text(json.dumps(value))
    assert planner.main([str(target), "--current-sha", BASE]) == 2
    assert json.loads(capsys.readouterr().out)["refresh_required"]


def test_cli_refuses_invalid_json(tmp_path, capsys):
    target = tmp_path / "snapshot.json"
    target.write_text("{")
    assert planner.main([str(target), "--current-sha", BASE]) == 1
    assert "refused" in capsys.readouterr().err


def test_closed_issue_requires_reconciliation_before_selection():
    value = snapshot()
    value["issues"][0]["state"] = "closed"
    report = run(value)
    assert not report["frontier"]
    assert "issue closed" in report["blocked"][0]["blockers"][0]


def test_invalid_timestamp_is_refused():
    value = snapshot()
    value["observed_at"] = "not-a-date"
    with pytest.raises(planner.PlanError, match="invalid timestamp"):
        run(value)


def test_duplicate_json_keys_are_not_last_writer_wins(tmp_path, capsys):
    target = tmp_path / "snapshot.json"
    target.write_text('{"version": 1, "version": 2}')
    assert planner.main([str(target), "--current-sha", BASE]) == 1
    assert "duplicate JSON key" in capsys.readouterr().err


def test_cli_returns_zero_only_for_fresh_complete_input(tmp_path, capsys):
    value = snapshot()
    value["observed_at"] = datetime.now(UTC).isoformat()
    target = tmp_path / "snapshot.json"
    target.write_text(json.dumps(value))
    assert planner.main([str(target), "--current-sha", BASE]) == 0
    assert not json.loads(capsys.readouterr().out)["refresh_required"]
