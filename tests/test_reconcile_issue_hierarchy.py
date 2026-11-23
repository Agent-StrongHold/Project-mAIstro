"""Manifest-backed GitHub hierarchy migration: negative safety oracles (#2503)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/reconcile-issue-hierarchy.py"


@pytest.fixture(scope="module")
def repair():
    spec = importlib.util.spec_from_file_location("reconcile_issue_hierarchy", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def row(number: int, parent=None, native=None, milestone="M1"):
    return {
        "number": number,
        "issue_id": number + 1000,
        "title": f"issue #{number}",
        "state": "open",
        "labels": ["type:issue"],
        "declared_parent": parent,
        "native_parent": native,
        "ambiguous_parent_line": False,
        "parent_line_verified": True,
        "declared_parent_line": f"Parent: #{parent}" if parent else None,
        "native_milestone": 2 if milestone == "M1" else 4,
        "native_milestone_title": f"{milestone} — Tracker" if milestone else None,
        "native_child_count": 0,
    }


def test_proposes_exact_native_link_and_skips_existing(repair) -> None:
    rows = [row(1), row(2, parent=1), row(3, parent=1, native=1)]
    proposed, skipped = repair.plan({"issues": rows})
    assert [item["number"] for item in proposed] == [2]
    assert not skipped


def test_ancestor_before_leaf_and_no_cycle(repair) -> None:
    rows = [row(3, parent=2), row(2, parent=1), row(1)]
    proposed, _ = repair.plan({"issues": rows})
    assert [item["number"] for item in proposed] == [2, 3]


def test_multiple_parent_line_references_are_never_auto_applied(repair) -> None:
    rows = [row(1), row(2, parent=1)]
    rows[1]["ambiguous_parent_line"] = True
    proposed, skipped = repair.plan({"issues": rows})
    assert proposed == []
    assert skipped["multiple_refs_on_parent_line"] == 1


def test_cross_milestone_mismatch_requires_review(repair) -> None:
    rows = [row(1, milestone="M1"), row(2, parent=1, milestone="M3")]
    proposed, skipped = repair.plan({"issues": rows})
    assert proposed == []
    assert skipped["cross_milestone_review"] == 1


@pytest.mark.parametrize(
    "rows, error",
    [
        ([row(1, parent=2), row(2, parent=1)], "cycle"),
        ([row(1, parent=99)], "not inventoried"),
        ([row(1), row(2, parent=1, native=3), row(3)], "declared"),
        ([row(1, parent=1)], "self-parent"),
    ],
)
def test_invalid_graph_refuses_to_plan(repair, rows, error) -> None:
    with pytest.raises(repair.HierarchyError, match=error):
        repair.plan({"issues": rows})


def test_live_link_uses_github_database_id_and_verifies_both_sides(
    repair, monkeypatch
) -> None:
    parent = {
        "number": 1,
        "id": 1001,
        "milestone": {"number": 2},
        "sub_issues_summary": {"total": 0},
    }
    child = {
        "number": 2,
        "id": 1002,
        "state": "open",
        "labels": [{"name": "type:issue"}],
        "milestone": {"number": 2},
        "body": "Parent: #1",
        "parent_issue_url": None,
    }
    calls = []

    def fake_request(repo, token, method, path, payload=None):
        calls.append((method, path, payload))
        if method == "POST":
            child["parent_issue_url"] = "https://api.github.com/repos/o/r/issues/1"
            return {}
        return [{"number": 2}]

    monkeypatch.setattr(repair, "_request", fake_request)
    monkeypatch.setattr(
        repair, "_live_issue", lambda repo, token, number: {1: parent, 2: child}[number]
    )
    outcome = repair.apply_one("o/r", "token", row(2, parent=1), {1: row(1)})
    assert outcome == "linked"
    assert ("POST", "issues/1/sub_issues", {"sub_issue_id": 1002}) in calls
    assert any(method == "GET" for method, _, _ in calls)


def test_already_linked_is_idempotent_and_never_posts(repair, monkeypatch) -> None:
    issue = {
        "number": 2,
        "parent_issue_url": "https://api.github.com/repos/o/r/issues/1",
    }
    parent = {"number": 1}
    monkeypatch.setattr(
        repair, "_live_issue", lambda repo, token, number: {1: parent, 2: issue}[number]
    )
    monkeypatch.setattr(
        repair, "_request", lambda *args, **kwargs: pytest.fail("unexpected API POST")
    )
    assert (
        repair.apply_one("o/r", "token", row(2, parent=1), {1: row(1)})
        == "already_linked"
    )


def test_stale_parent_line_blocks_native_mutation(repair, monkeypatch) -> None:
    parent = {"number": 1, "id": 1001, "milestone": {"number": 2}}
    child = {
        "number": 2,
        "id": 1002,
        "state": "open",
        "labels": [{"name": "type:issue"}],
        "milestone": {"number": 2},
        "body": "Parent: #999",
        "parent_issue_url": None,
    }
    monkeypatch.setattr(
        repair, "_live_issue", lambda repo, token, number: {1: parent, 2: child}[number]
    )
    with pytest.raises(repair.HierarchyError, match="declaration changed"):
        repair.apply_one("o/r", "token", row(2, parent=1), {1: row(1)})


def test_offline_dry_run_and_apply_requires_explicit_confirmation(
    repair, monkeypatch, tmp_path, capsys
) -> None:
    doc = {
        "schema_version": 1,
        "repository": "o/r",
        "summary": {"issues_total": 2},
        "issues": [row(1), row(2, parent=1)],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert repair.main(["--manifest", str(manifest)]) == 0
    assert '"candidates": 1' in capsys.readouterr().out
    assert repair.main(["--manifest", str(manifest), "--apply"]) == 1
    assert (
        repair.main(["--manifest", str(manifest), "--apply", "--confirm", "APPLY"])
        == 1
    )
