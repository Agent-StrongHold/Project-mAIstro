"""Stage 4 (ADR-070126-6386): harvest a session's promotions into grouped PRs.

A session promotes N commits onto the in-container rsi-baseline; each commit
edits one target file. Harvest groups them by file (one focused PR per file
edited), names a safe branch per group, and produces PR title/body — the pure
logic here; the git/gh orchestration lives in tools/harvest_rsi_prs.sh.
"""

from __future__ import annotations

import json

import pytest

from maistro_rsi.harvest import (
    PromotedGate,
    PromotedPatch,
    branch_slug,
    group_by_file,
    manifest_records,
    pr_body,
    pr_title,
)


def _p(patch_file: str, file: str, subject: str = "RSI improvement") -> PromotedPatch:
    return PromotedPatch(patch_file=patch_file, file=file, subject=subject)


@pytest.mark.ac("ADR-070126-6386/persist")
def test_group_by_file_one_group_per_file() -> None:
    patches = [
        _p("0001.patch", "packages/maistro-evolve/src/maistro_evolve/serialize.py"),
        _p("0002.patch", "packages/maistro-evolve/src/maistro_evolve/audit.py"),
        _p("0003.patch", "packages/maistro-evolve/src/maistro_evolve/serialize.py"),
    ]
    groups = group_by_file(patches)
    assert set(groups) == {
        "packages/maistro-evolve/src/maistro_evolve/serialize.py",
        "packages/maistro-evolve/src/maistro_evolve/audit.py",
    }
    # serialize.py accumulates both its patches, in order.
    assert [p.patch_file for p in groups[patches[0].file]] == ["0001.patch", "0003.patch"]


def test_group_preserves_patch_order_within_file() -> None:
    patches = [_p("0005.patch", "a.py"), _p("0002.patch", "a.py"), _p("0009.patch", "a.py")]
    assert [p.patch_file for p in group_by_file(patches)["a.py"]] == [
        "0005.patch",
        "0002.patch",
        "0009.patch",
    ]


@pytest.mark.ac("ADR-070126-6386/persist")
def test_branch_slug_is_a_safe_ref() -> None:
    slug = branch_slug("packages/maistro-evolve/src/maistro_evolve/serialize.py", "sess1")
    assert slug.startswith("rsi/sess1/")
    # No path separators, no .py, only ref-safe characters.
    assert "/" not in slug[len("rsi/sess1/") :]
    assert ".py" not in slug
    assert all(c.isalnum() or c in "-/" for c in slug)


def test_branch_slug_distinct_files_distinct_slugs() -> None:
    a = branch_slug("pkg/a/mod.py", "s")
    b = branch_slug("pkg/b/mod.py", "s")
    assert a != b  # same basename, different path ⇒ different slug


def test_pr_title_and_body_name_the_file_and_count() -> None:
    patches = [_p("1.patch", "pkg/x.py", "RSI cycle 1: add docstring")]
    title = pr_title("pkg/x.py", patches)
    body = pr_body("pkg/x.py", patches)
    assert "pkg/x.py" in title
    assert "add docstring" in body and "pkg/x.py" in body


def _patch_with_gates(subject: str, gates: tuple[PromotedGate, ...]) -> PromotedPatch:
    return PromotedPatch("1.patch", "pkg/x.py", subject, gates=gates)


# The old hardcoded sentence (#820's target): it asserted tests, coverage,
# ruff, mypy, AND bandit had passed without reading any recorded result.
_FULL_PASS_CLAIM = "full fitness scorecard"


def test_pr_body_renders_only_recorded_gates_with_their_states() -> None:
    # #820 AC-1/AC-5: the body is generated from the recorded gate results —
    # a measured pass and a NOT RUN gate are rendered as what their records
    # say, and no gate without a record is claimed.
    patches = [
        _patch_with_gates(
            "RSI cycle 1: add guard",
            (
                PromotedGate("tests_pass", True, "exit 0"),
                PromotedGate(
                    "no_bandit_high",
                    False,
                    "NOT RUN: bandit unavailable (missing) — required gate fails closed",
                    not_run=True,
                ),
            ),
        )
    ]
    body = pr_body("pkg/x.py", patches)
    assert _FULL_PASS_CLAIM not in body
    assert "- tests_pass: passed" in body
    assert "- no_bandit_high: NOT RUN" in body
    assert "bandit unavailable (missing)" in body


def test_pr_body_renders_a_failed_gate_as_failed() -> None:
    patches = [
        _patch_with_gates(
            "RSI cycle 1",
            (PromotedGate("ruff_clean", False, "3 lint violation(s)"),),
        )
    ]
    body = pr_body("pkg/x.py", patches)
    assert _FULL_PASS_CLAIM not in body
    assert "- ruff_clean: FAILED — 3 lint violation(s)" in body


def test_pr_body_without_gate_evidence_claims_nothing() -> None:
    # #820 stop condition's rendering half: no recorded evidence must read as
    # "unverified", never as a pass.
    body = pr_body("pkg/x.py", [_p("1.patch", "pkg/x.py", "RSI cycle 1")])
    assert _FULL_PASS_CLAIM not in body
    assert "No gate results were recorded" in body
    assert "unverified" in body


def test_pr_body_aggregates_gates_across_a_file_group() -> None:
    # One PR groups several promotions of one file; a gate that ran on only
    # some of them (or failed on one) must not read as a clean pass.
    patches = [
        PromotedPatch(
            "1.patch",
            "pkg/x.py",
            "cycle 1",
            gates=(PromotedGate("tests_pass", True, "exit 0"),),
        ),
        PromotedPatch(
            "2.patch",
            "pkg/x.py",
            "cycle 2",
            gates=(
                PromotedGate("tests_pass", False, "exit 1: 2 failed"),
                PromotedGate(
                    "no_bandit_high",
                    False,
                    "NOT RUN: bandit unavailable (timeout) — required gate fails closed",
                    not_run=True,
                ),
            ),
        ),
    ]
    body = pr_body("pkg/x.py", patches)
    assert _FULL_PASS_CLAIM not in body
    # tests_pass measured on both, failed on one → FAILED, not passed.
    assert "- tests_pass: FAILED — exit 1: 2 failed" in body
    assert "- no_bandit_high: NOT RUN" in body
    assert "measured on 2 of 2 promotion(s)" in body
    assert "measured on 0 of 2 promotion(s)" in body


def test_manifest_records_project_gate_results() -> None:
    value = [
        {
            "patch_file": "0001.patch",
            "file": "a.py",
            "subject": "s1",
            "gates": {"tests_pass": True},
            "gate_results": [
                {
                    "name": "no_bandit_high",
                    "passed": False,
                    "not_run": True,
                    "reason": "NOT RUN: bandit unavailable",
                },
                {"name": "tests_pass", "passed": True, "not_run": False, "reason": "exit 0"},
            ],
        },
        # Legacy entry: bool map only (a note that predates per-gate records).
        {
            "patch_file": "0002.patch",
            "file": "b.py",
            "subject": "s2",
            "gates": {"tests_pass": True},
        },
        # Pre-evidence entry: no gate record at all → NO gates, not invented ones.
        {"patch_file": "0003.patch", "file": "c.py", "subject": "s3"},
    ]
    patches = manifest_records(value)
    assert patches[0].gates == (
        PromotedGate("no_bandit_high", False, "NOT RUN: bandit unavailable", not_run=True),
        PromotedGate("tests_pass", True, "exit 0"),
    )
    assert patches[1].gates == (PromotedGate("tests_pass", True),)
    assert patches[2].gates == ()


def test_manifest_records_roundtrip(tmp_path) -> None:
    # Mirrors the production read path in maistro_rsi.__main__._harvest: the
    # manifest is read and parsed once (Warden-scanned in production) and the
    # admitted value is projected through manifest_records; the module
    # deliberately exposes no re-reading load_manifest helper (TOCTOU).
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"patch_file": "0001.patch", "file": "a.py", "subject": "s1"},
                {"patch_file": "0002.patch", "file": "b.py", "subject": "s2"},
            ]
        ),
        encoding="utf-8",
    )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    patches = manifest_records(value)
    assert patches == [
        PromotedPatch("0001.patch", "a.py", "s1"),
        PromotedPatch("0002.patch", "b.py", "s2"),
    ]
