"""CLI walk discovery and strict-mode flag handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_registry.cli import _walk, main

_VALID_SPEC = """\
---
id: SPEC-001
title: "A real record"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-10
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-001: A real record
"""


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    adr = tmp_path / "docs" / "adr"
    specs = tmp_path / "docs" / "specs"
    adr.mkdir(parents=True)
    specs.mkdir(parents=True)
    (specs / "SPEC-001-real-record.md").write_text(_VALID_SPEC)
    return tmp_path


class TestWalkDiscovery:
    def test_skips_templates_and_index_docs(self, repo_root: Path) -> None:
        adr = repo_root / "docs" / "adr"
        specs = repo_root / "docs" / "specs"
        (adr / "ADR-000-template.md").write_text("# placeholder")
        (adr / "ADR-INDEX.md").write_text("# index, no front-matter by design")
        (specs / "README.md").write_text("# navigation, no front-matter by design")

        found = {p.name for p in _walk(repo_root)}
        assert found == {"SPEC-001-real-record.md"}

    def test_finds_nested_spec_files(self, repo_root: Path) -> None:
        nested = repo_root / "docs" / "specs" / "sub"
        nested.mkdir()
        (nested / "SPEC-002-nested.md").write_text(_VALID_SPEC)
        found = {p.name for p in _walk(repo_root)}
        assert "SPEC-002-nested.md" in found


class TestStrictFlag:
    @pytest.fixture
    def warning_root(self, repo_root: Path) -> Path:
        # A walked file with no front-matter produces a warning, not an error.
        (repo_root / "docs" / "specs" / "SPEC-099-unmigrated.md").write_text("# no front-matter")
        return repo_root

    def test_walk_warnings_pass_without_strict(self, warning_root: Path) -> None:
        assert main(["walk", str(warning_root)]) == 0

    def test_strict_before_subcommand_fails_warnings(self, warning_root: Path) -> None:
        assert main(["--strict", "walk", str(warning_root)]) == 1

    def test_strict_after_subcommand_fails_warnings(self, warning_root: Path) -> None:
        # The documented form: maistro-registry walk . --strict
        assert main(["walk", str(warning_root), "--strict"]) == 1

    def test_errors_fail_even_without_strict(self, repo_root: Path) -> None:
        bad = _VALID_SPEC.replace("layer: Foundation", "layer: NotALayer").replace(
            "SPEC-001", "SPEC-098"
        )
        (repo_root / "docs" / "specs" / "SPEC-098-bad-layer.md").write_text(bad)
        assert main(["walk", str(repo_root)]) == 1


class TestSharedCommandPipeline:
    def test_lint_and_generate_share_missing_root_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "missing"
        assert main(["lint", str(missing)]) == 2
        lint_err = capsys.readouterr().err
        assert f"error: {missing} is not a directory" in lint_err

        assert main(["generate", str(missing)]) == 2
        generate_err = capsys.readouterr().err
        assert generate_err == lint_err

    def test_generate_refuses_errored_files_with_exact_message(
        self, repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = _VALID_SPEC.replace("layer: Foundation", "layer: NotALayer").replace(
            "SPEC-001", "SPEC-098"
        )
        (repo_root / "docs" / "specs" / "SPEC-098-bad-layer.md").write_text(bad)

        assert main(["generate", str(repo_root), "--output", str(tmp_path / "registry")]) == 1
        err = capsys.readouterr().err
        assert (
            "error: refusing to generate registry with 1 errored files; "
            "pass --allow-errors to skip them and generate anyway"
        ) in err
