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
    PromotedPatch,
    branch_slug,
    group_by_file,
    load_manifest,
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


def test_load_manifest_roundtrip(tmp_path) -> None:
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
    patches = load_manifest(manifest)
    assert patches == [
        PromotedPatch("0001.patch", "a.py", "s1"),
        PromotedPatch("0002.patch", "b.py", "s2"),
    ]
