"""Markdown front-matter parser tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_registry.parser import parse_file


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parses_valid_front_matter(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\nid: ADR-001\n---\n# Title\n")
    result = parse_file(p)
    assert result.front_matter == {"id": "ADR-001"}
    assert result.body == "# Title\n"


def test_no_front_matter_returns_none(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "# Just a heading\n")
    result = parse_file(p)
    assert result.front_matter is None
    assert result.body == "# Just a heading\n"


def test_open_without_close_treated_as_no_front_matter(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\nid: ADR-001\n# heading\n")
    result = parse_file(p)
    assert result.front_matter is None


def test_empty_front_matter_returns_empty_dict(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\n---\n# body\n")
    result = parse_file(p)
    assert result.front_matter == {}


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\nid: [unclosed\n---\n")
    with pytest.raises(ValueError, match="invalid YAML"):
        parse_file(p)


def test_non_mapping_front_matter_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "x.md", "---\n- listitem\n---\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_file(p)


def test_yaml_list_of_strings_in_value_works(tmp_path: Path) -> None:
    """YAML lists as field values must parse correctly."""
    p = _write(
        tmp_path,
        "x.md",
        "---\nrelated:\n  - maistro-engine#ADR-001\n  - maistro-engine#ADR-002\n---\nbody",
    )
    result = parse_file(p)
    assert result.front_matter == {"related": ["maistro-engine#ADR-001", "maistro-engine#ADR-002"]}
