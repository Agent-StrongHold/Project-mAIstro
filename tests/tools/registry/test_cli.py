"""CLI walk discovery and strict-mode flag handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_registry.cli import NON_RECORD_FILES, _walk, disposition, main

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


_VALID_ADR = _VALID_SPEC.replace("SPEC-001", "ADR-901").replace("kind: spec", "kind: adr")

#: The real repository root (tests/tools/registry/test_cli.py -> parents[3]).
REPO_ROOT = Path(__file__).resolve().parents[3]


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

    def test_finds_nested_adr_files(self, repo_root: Path) -> None:
        # Discovery asymmetry regression (#813 AC-4): specs were walked
        # recursively while ADRs were not, so a decision document in a
        # subdirectory silently bypassed validation. A nested ADR must be
        # discovered exactly like a nested spec.
        nested = repo_root / "docs" / "adr" / "sub"
        nested.mkdir()
        (nested / "ADR-901-nested.md").write_text(_VALID_ADR)
        found = {p.name for p in _walk(repo_root)}
        assert "ADR-901-nested.md" in found

    def test_unprefixed_decision_document_is_walked(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The #813 stop condition: a decision-bearing file must not be
        # invisible merely because its filename lacks the `ADR-` prefix. The
        # old `docs/adr/ADR-*.md` glob excluded it silently; the recursive
        # walk validates it by default, and --strict fails loudly until it
        # carries front matter — it cannot fall outside validation quietly.
        adr = repo_root / "docs" / "adr"
        (adr / "PLATFORM-DECISION.md").write_text("# decision, no front matter yet")
        assert "PLATFORM-DECISION.md" in {p.name for p in _walk(repo_root)}
        assert main(["walk", str(repo_root), "--strict"]) == 1
        assert "PLATFORM-DECISION.md" in capsys.readouterr().out

    def test_non_record_disposition_is_by_declared_name_not_prefix(self, repo_root: Path) -> None:
        # OUT-OF-SCOPE.md is skipped because NON_RECORD_FILES declares it, not
        # because of how it is spelt: the same bytes under a different name are
        # walked (#813 AC-3 + stop condition).
        adr = repo_root / "docs" / "adr"
        (adr / "OUT-OF-SCOPE.md").write_text("# ledger")
        (adr / "OUT-OF-SCOPE-COPY.md").write_text("# same content, different name")
        found = {p.name for p in _walk(repo_root)}
        assert "OUT-OF-SCOPE.md" not in found
        assert "OUT-OF-SCOPE-COPY.md" in found

    def test_decision_ledgers_are_declared_non_records(self) -> None:
        # The declared contract must name both ledgers explicitly, each with a
        # stated reason — a bare filename would recreate the implicit
        # exclusion set #813 began from.
        for name in ("OUT-OF-SCOPE.md", "DECISION-BACKLOG.md"):
            assert name in NON_RECORD_FILES
            assert NON_RECORD_FILES[name].strip()
        assert disposition(Path("docs/adr/OUT-OF-SCOPE.md")).startswith("declared non-record:")
        assert disposition(Path("docs/adr/ADR-000-template.md")).startswith("scaffolding template")
        assert disposition(Path("docs/adr/ADR-031-front-matter-and-registry.md")) == "record"

    @pytest.mark.skipif(
        not (REPO_ROOT / "docs" / "adr").is_dir(),
        reason="real docs/adr corpus not present (installed-package context)",
    )
    def test_real_corpus_fully_dispositioned(self) -> None:
        # Totality, against the corpus CI actually gates (#813 AC-1/2/3):
        # every Markdown file under either walked tree is either validated as
        # a record or carries an explicit disposition — none is silently
        # outside. In particular the two decision ledgers must be explicitly
        # dispositioned rather than missed by the old non-recursive,
        # ADR-prefixed glob.
        corpus = {
            p
            for tree in ("docs/adr", "docs/specs")
            for p in (REPO_ROOT / tree).rglob("*.md")
            if p.is_file()
        }
        walked = set(_walk(REPO_ROOT))
        assert corpus, "sanity: the real corpus is non-empty"
        for path in corpus:
            if disposition(path) == "record":
                assert path in walked, f"{path} is a record but the walk missed it"
            else:
                assert path not in walked, f"{path} has a disposition but was walked"
        ledger_names = {p.name for p in corpus} & set(NON_RECORD_FILES)
        assert {"OUT-OF-SCOPE.md", "DECISION-BACKLOG.md"} <= ledger_names


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


class TestContractsWithoutTests:
    """Contracts declared with no cited tests are surfaced, never silent (#812)."""

    def _with_contracts(self, repo_root: Path, spec_id: str, status: str) -> Path:
        body = (
            _VALID_SPEC.replace("contracts: []", "contracts:\n  - behavioral")
            .replace("status: Proposed", f"status: {status}")
            .replace("SPEC-001", spec_id)
        )
        path = repo_root / "docs" / "specs" / f"{spec_id}-contracts-no-tests.md"
        path.write_text(body)
        return repo_root

    def test_proof_claiming_status_warns_and_fails_strict(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._with_contracts(repo_root, "SPEC-010", "Implemented")
        assert main(["lint", str(root)]) == 0  # warning only, non-strict passes
        assert main(["lint", str(root), "--strict"]) == 1  # strict fails: silent proof refused
        assert "declares contracts but cites no tests while claiming status 'Implemented'" in (
            capsys.readouterr().out
        )

    def test_tests_passing_status_warns_too(self, repo_root: Path) -> None:
        root = self._with_contracts(repo_root, "SPEC-011", "Tests Passing")
        assert main(["lint", str(root), "--strict"]) == 1

    def test_other_status_records_debt_without_failing(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._with_contracts(repo_root, "SPEC-012", "Proposed")
        assert main(["lint", str(root), "--strict"]) == 0
        out = capsys.readouterr()
        assert "DEBT:  declares contracts but cites no tests (test-evidence debt)" in out.out
        assert "1 test-evidence debts" in out.err

    def test_tests_and_contracts_together_stay_clean(self, repo_root: Path) -> None:
        body = (
            _VALID_SPEC.replace("contracts: []", "contracts:\n  - behavioral")
            .replace("tests: []", "tests:\n  - packages/real.py")
            .replace("SPEC-001", "SPEC-013")
        )
        (repo_root / "packages").mkdir()
        (repo_root / "packages" / "real.py").write_text("def test_ok():\n    pass\n")
        (repo_root / "docs" / "specs" / "SPEC-013-evidenced.md").write_text(body)
        assert main(["lint", str(repo_root), "--strict"]) == 0


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


class TestCitedTestPaths:
    """Cited `tests:` paths must resolve against the repo root (#812)."""

    def _with_dead_test_citation(self, repo_root: Path) -> Path:
        citing = _VALID_SPEC.replace(
            "tests: []", "tests:\n  - packages/maistro-core/tests/agents/test_gone.py"
        ).replace("SPEC-001", "SPEC-002")
        (repo_root / "docs" / "specs" / "SPEC-002-dead-citation.md").write_text(citing)
        return repo_root

    def test_dead_cited_path_fails_strict_lint(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._with_dead_test_citation(repo_root)
        assert main(["lint", str(root), "--strict"]) == 1
        out = capsys.readouterr().out
        assert "TEST-PATH: maistro-engine#SPEC-002.tests" in out
        assert "does not exist under the repository root" in out

    def test_dead_cited_path_fails_lint_even_without_strict(self, repo_root: Path) -> None:
        # A dead citation is a false evidence claim, not a style nit: it must
        # not survive the non-strict run that CI never invokes.
        assert main(["lint", str(self._with_dead_test_citation(repo_root))]) == 1

    def test_live_cited_path_passes_strict_lint(self, repo_root: Path) -> None:
        citing = _VALID_SPEC.replace("tests: []", "tests:\n  - packages/real.py").replace(
            "SPEC-001", "SPEC-003"
        )
        (repo_root / "packages").mkdir()
        (repo_root / "packages" / "real.py").write_text("def test_ok():\n    pass\n")
        (repo_root / "docs" / "specs" / "SPEC-003-live-citation.md").write_text(citing)
        assert main(["lint", str(repo_root), "--strict"]) == 0

    def test_node_id_suffix_does_not_mask_a_dead_file(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        citing = _VALID_SPEC.replace("tests: []", "tests:\n  - packages/gone.py::test_ok").replace(
            "SPEC-001", "SPEC-004"
        )
        (repo_root / "docs" / "specs" / "SPEC-004-dead-node-id.md").write_text(citing)
        assert main(["lint", str(repo_root), "--strict"]) == 1
        assert "packages/gone.py" in capsys.readouterr().out
