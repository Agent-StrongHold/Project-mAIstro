"""Regression checks for metadata repair authorization and native graph evidence."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "issue_integrity", Path(__file__).parents[1] / "scripts/issue-metadata-integrity.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def issue(number, body="", labels=None, milestone=None):
    return {
        "number": number,
        "id": 1000 + number,
        "body": body,
        "title": f"issue {number}",
        "state": "open",
        "labels": labels or [],
        "milestone": milestone,
    }


def snapshot(*issues, edges=None):
    return {"repository": "owner/repo", "issues": list(issues), "native_edges": edges or []}


def manifest(child, parent):
    return {
        "repository": "owner/repo",
        "links": [
            {
                "child": child["number"],
                "parent": parent["number"],
                "child_id": child["id"],
                "child_body_sha256": gate.digest(child["body"]),
                "parent_body_sha256": gate.digest(parent["body"]),
                "child_ownership_sha256": gate.ownership_digest([]),
                "parent_ownership_sha256": gate.ownership_digest([]),
            }
        ],
    }


class FakeAPI:
    repository = "owner/repo"

    def __init__(self, child, parent, actual=None, lose_reverse=False):
        self.issues = {child["number"]: child, parent["number"]: parent}
        self.actual = actual
        self.posts = []
        self.lose_reverse = lose_reverse

    def request(self, method, path, payload=None):
        if method == "POST":
            self.posts.append((path, payload))
            self.actual = int(path.split("/")[2])
            return {}
        return self.issues[int(path.split("/")[2])]

    def parent(self, number):
        if self.actual is None:
            return None
        return {"number": self.actual, "repository_url": "https://api.github.com/repos/owner/repo"}

    def pages(self, path):
        return [] if self.lose_reverse else list(self.issues.values())


class TestIssueMetadataIntegrity(unittest.TestCase):
    def test_declarations_do_not_turn_dependencies_or_examples_into_parents(self):
        body = "Related: #3\nDepends on: #4\n```text\nParent: #5\n```\n> Parent: #6\nParent: [#2](https://github.com/owner/repo/issues/2)."
        self.assertEqual(gate.declared_parents(body), [2])

    def test_all_canonical_parent_forms_are_recognized(self):
        for kind in ["", " epic", " initiative", " program", " milestone tracker"]:
            self.assertEqual(gate.declared_parents(f"Parent{kind}: #2"), [2])

    def test_multiple_declarations_are_reviewed_not_flattened(self):
        report = gate.analyze(snapshot(issue(1, "Parent: #2\nParent epic: #3"), issue(2), issue(3)))
        self.assertEqual(report["issues"][0]["status"], "ambiguous")
        self.assertEqual(report["proposals"], [])

    def test_native_disagreement_is_not_a_reparent_proposal(self):
        report = gate.analyze(
            snapshot(issue(1, "Parent: #2"), issue(2), issue(3), edges=[{"child": 1, "parent": 3}])
        )
        self.assertEqual(report["issues"][0]["status"], "conflicting_parent")
        self.assertEqual(report["proposals"], [])

    def test_missing_reference_and_ownership_hold_are_exceptions(self):
        report = gate.analyze(
            snapshot(issue(1, "Parent: #99"), issue(1134, "Parent initiative: #446"), issue(446))
        )
        states = {x["number"]: x["status"] for x in report["issues"]}
        self.assertEqual(states[1], "invalid_reference")
        self.assertEqual(states[1134], "review_hold")
        self.assertEqual(report["proposals"], [])

    def test_cycle_is_rejected_across_native_and_proposed_edges(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            gate.analyze(
                snapshot(issue(1, "Parent: #2"), issue(2), edges=[{"child": 2, "parent": 1}])
            )

    def test_milestone_label_conflict_is_detected(self):
        report = gate.analyze(
            snapshot(
                issue(1, labels=[{"name": "milestone:M3"}], milestone={"title": "M1 — Convergence"})
            )
        )
        self.assertTrue(report["issues"][0]["milestone_label_conflict"])

    def test_apply_uses_database_identity_and_verifies_both_directions(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        api = FakeAPI(child, parent)
        with tempfile.TemporaryDirectory() as directory, patch.object(gate.time, "sleep"):
            journal = Path(directory) / "journal.jsonl"
            self.assertEqual(
                gate.apply_links(api, snapshot(child, parent), manifest(child, parent), journal), 1
            )
            self.assertEqual(
                api.posts,
                [("/issues/2/sub_issues", {"sub_issue_id": 1001, "replace_parent": False})],
            )
            self.assertIn('"verified": true', journal.read_text())

    def test_second_run_produces_no_post(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        api = FakeAPI(child, parent, actual=2)
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                gate.apply_links(
                    api,
                    snapshot(child, parent, edges=[{"child": 1, "parent": 2}]),
                    manifest(child, parent),
                    Path(directory) / "journal",
                ),
                0,
            )
        self.assertEqual(api.posts, [])

    def test_cross_repository_sub_issue_is_inventoried_separately(self):
        class CrossRepoAPI:
            repository = "owner/repo"

            def pages(self, path):
                if path.endswith("/sub_issues"):
                    return [
                        {"number": 8, "repository_url": "https://api.github.com/repos/owner/repo"},
                        {"number": 8, "repository_url": "https://api.github.com/repos/other/repo"},
                    ]
                return [{"number": 7, "labels": [], "milestone": None}]

        inventory = gate.collect(CrossRepoAPI())
        self.assertEqual(inventory["native_edges"], [{"child": 8, "parent": 7}])
        self.assertEqual(
            inventory["external_edges"],
            [
                {
                    "child": 8,
                    "parent": 7,
                    "repository_url": "https://api.github.com/repos/other/repo",
                }
            ],
        )

    def test_external_child_does_not_mask_the_same_numbered_local_issue(self):
        child, parent = issue(8, "Parent: #7"), issue(7)
        external = [
            {"child": 8, "parent": 7, "repository_url": "https://api.github.com/repos/other/repo"}
        ]
        snap = snapshot(child, parent)
        snap["external_edges"] = external
        report = gate.analyze(snap)
        row = next(x for x in report["issues"] if x["number"] == 8)
        self.assertEqual(row["status"], "missing_parent")
        self.assertEqual(report["summary"]["external_edges"], 1)
        api = FakeAPI(child, parent)
        with tempfile.TemporaryDirectory() as directory, patch.object(gate.time, "sleep"):
            self.assertEqual(
                gate.apply_links(api, snap, manifest(child, parent), Path(directory) / "journal"), 1
            )
        self.assertEqual(
            api.posts,
            [("/issues/7/sub_issues", {"sub_issue_id": 1008, "replace_parent": False})],
        )

    def test_live_conflicting_parent_refuses_write(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        api = FakeAPI(child, parent, actual=9)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "replace"),
        ):
            gate.apply_links(
                api, snapshot(child, parent), manifest(child, parent), Path(directory) / "journal"
            )
        self.assertEqual(api.posts, [])

    def test_stale_contract_refuses_write(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        reviewed = manifest(child, parent)
        child["body"] += "\nChanged contract"
        api = FakeAPI(child, parent)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "source contract changed"),
        ):
            gate.apply_links(api, snapshot(child, parent), reviewed, Path(directory) / "journal")
        self.assertEqual(api.posts, [])

    def test_missing_reverse_readback_does_not_claim_success(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        api = FakeAPI(child, parent, lose_reverse=True)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(gate.time, "sleep"),
            self.assertRaisesRegex(ValueError, "reverse"),
        ):
            gate.apply_links(
                api, snapshot(child, parent), manifest(child, parent), Path(directory) / "journal"
            )

    def test_pagination_continues_after_a_short_page(self):
        api = gate.API("owner/repo", "test-token")
        with patch.object(
            api, "request", side_effect=[[{"number": 1}], [{"number": 2}], []]
        ) as request:
            self.assertEqual(len(api.pages("/issues?state=all")), 2)
            self.assertEqual(request.call_count, 3)

    def test_new_ownership_comment_refuses_write(self):
        child, parent = issue(1, "Parent: #2"), issue(2)
        child["comments"] = 1
        api = FakeAPI(child, parent)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(api, "pages", return_value=[{"id": 77, "body": "Parent initiative: #9"}]),
            self.assertRaisesRegex(ValueError, "ownership discussion"),
        ):
            gate.apply_links(
                api, snapshot(child, parent), manifest(child, parent), Path(directory) / "journal"
            )
        self.assertEqual(api.posts, [])

    def test_missing_milestone_is_required_only_for_a_classified_family(self):
        report = gate.analyze(
            snapshot(
                issue(1, "Parent: #2", labels=[{"name": "type:issue"}]),
                issue(2, milestone={"title": "M1 — Convergence"}),
            )
        )
        self.assertIn("milestone", report["issues"][0]["classification_gaps"])

    def test_transport_error_is_not_an_empty_inventory(self):
        api = gate.API("owner/repo", "test-token")
        with (
            patch.object(api, "request", side_effect=OSError("offline")),
            self.assertRaises(OSError),
        ):
            gate.collect(api)


if __name__ == "__main__":
    unittest.main()
