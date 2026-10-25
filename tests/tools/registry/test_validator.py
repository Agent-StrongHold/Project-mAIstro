"""End-to-end validator tests using fixture markdown files."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from maistro_registry.validator import validate_file

_VALID = dedent(
    """\
    ---
    id: ADR-030
    title: Four-Repo Governance
    repo: maistro-engine
    kind: adr
    status: Accepted
    created: 2026-05-07
    accepted: 2026-05-07
    substrate: [maistro-engine#ADR-019]
    implements: []
    related: []
    supersedes: []
    blocks: []
    blocked-by: []
    contracts: []
    tests: []
    layer: Foundation
    owners: ['@BlakeMatthews-dev']
    ---
    # ADR-030
    """
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_valid_file_validates(tmp_path: Path) -> None:
    p = _write(tmp_path, "ADR-030.md", _VALID)
    result = validate_file(p)
    assert result.ok
    assert result.warnings == []
    assert result.front_matter is not None
    assert result.front_matter.id == "ADR-030"


def test_missing_front_matter_warns(tmp_path: Path) -> None:
    p = _write(tmp_path, "ADR-030.md", "# No front matter\n")
    result = validate_file(p)
    assert result.ok  # missing front-matter is a warning, not an error
    assert any("no front-matter block" in w for w in result.warnings)


def test_invalid_schema_errors(tmp_path: Path) -> None:
    bad = _VALID.replace("status: Accepted", "status: BadStatus")
    p = _write(tmp_path, "ADR-030.md", bad)
    result = validate_file(p)
    assert not result.ok
    assert any("status" in e for e in result.errors)


def test_invalid_yaml_errors(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\nid: [unclosed\n---\nbody\n")
    result = validate_file(p)
    assert not result.ok
    assert any("invalid YAML" in e for e in result.errors)


def test_render_produces_path_and_messages(tmp_path: Path) -> None:
    bad = _VALID.replace("status: Accepted", "status: BadStatus")
    p = _write(tmp_path, "ADR-030.md", bad)
    result = validate_file(p)
    rendered = result.render()
    assert str(p) in rendered
    assert "ERROR:" in rendered


def _contracts_without_tests(content: str, status: str) -> str:
    return content.replace("contracts: []", "contracts: [behavioral]").replace(
        "status: Accepted", f"status: {status}"
    )


def test_contracts_without_tests_on_a_proof_claim_warns(tmp_path: Path) -> None:
    p = _write(tmp_path, "ADR-030.md", _contracts_without_tests(_VALID, "Implemented"))
    result = validate_file(p)
    assert result.ok
    assert result.debts == []
    assert any("while claiming status 'Implemented'" in w for w in result.warnings)
    # Rendered too: an implementation claim never scrolls past silently.
    assert "WARN:" in result.render()


def test_contracts_without_tests_elsewhere_is_explicit_debt(tmp_path: Path) -> None:
    p = _write(tmp_path, "ADR-030.md", _contracts_without_tests(_VALID, "Accepted"))
    result = validate_file(p)
    assert result.ok  # debt is surfaced, not fatal
    assert result.warnings == []
    assert result.debts == ["declares contracts but cites no tests (test-evidence debt)"]
    assert "DEBT:" in result.render()


def test_empty_tests_without_contracts_stays_clean(tmp_path: Path) -> None:
    # No contracts declared, nothing claimed: neither a warning nor a debt.
    p = _write(tmp_path, "ADR-030.md", _VALID)
    result = validate_file(p)
    assert result.ok
    assert result.warnings == []
    assert result.debts == []


def test_cited_tests_satisfy_the_contracts_evidence_state(tmp_path: Path) -> None:
    evidenced = _contracts_without_tests(_VALID, "Implemented").replace(
        "tests: []", "tests: [packages/x/test_real.py]"
    )
    p = _write(tmp_path, "ADR-030.md", evidenced)
    result = validate_file(p)
    assert result.ok
    assert result.warnings == []
    assert result.debts == []
