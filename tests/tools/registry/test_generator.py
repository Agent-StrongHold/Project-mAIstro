"""Registry generator tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maistro_registry.generator import (
    Registry,
    RegistryEntry,
    build_registry,
    write_registry,
)
from maistro_registry.schema import FrontMatter


def _make_fm(
    item_id: str,
    *,
    repo: str = "maistro-engine",
    title: str | None = None,
    substrate: list[str] | None = None,
    related: list[str] | None = None,
    supersedes: list[str] | None = None,
    blocks: list[str] | None = None,
    contracts: list[str] | None = None,
) -> FrontMatter:
    payload: dict[str, Any] = {
        "id": item_id,
        "title": title or item_id,
        "repo": repo,
        "kind": "adr",
        "status": "Accepted",
        "created": "2026-05-07",
        "substrate": substrate or [],
        "implements": [],
        "related": related or [],
        "supersedes": supersedes or [],
        "blocks": blocks or [],
        "blocked-by": [],
        "contracts": contracts or [],
        "tests": [],
        "layer": "Foundation",
        "owners": ["@BlakeMatthews-dev"],
    }
    return FrontMatter.model_validate(payload)


def test_empty_registry_renders_cleanly() -> None:
    registry = Registry()
    payload = json.loads(registry.to_json())
    assert payload == {}
    md = registry.to_markdown()
    assert "0 artifacts" in md
    assert "# Registry" in md


def test_single_entry_round_trips() -> None:
    fm = _make_fm("ADR-030", title="Four-Repo Governance")
    reg = build_registry([fm])
    payload = json.loads(reg.to_json())

    assert "maistro-engine#ADR-030" in payload
    entry = payload["maistro-engine#ADR-030"]
    assert entry["id"] == "ADR-030"
    assert entry["title"] == "Four-Repo Governance"
    assert entry["repo"] == "maistro-engine"
    assert entry["status"] == "Accepted"
    assert entry["layer"] == "Foundation"


def test_back_references_computed_for_supersedes() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002")
    reg = build_registry([a, b])
    assert reg.entries["maistro-engine#ADR-002"].superseded_by == ["maistro-engine#ADR-001"]
    # Forward ref preserved
    assert reg.entries["maistro-engine#ADR-001"].supersedes == ["maistro-engine#ADR-002"]


def test_back_references_computed_for_blocks() -> None:
    a = _make_fm("ADR-001", blocks=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002")
    reg = build_registry([a, b])
    assert reg.entries["maistro-engine#ADR-002"].blocked_by_inverse == ["maistro-engine#ADR-001"]


def test_referenced_by_aggregates_substrate_related_implements() -> None:
    a = _make_fm(
        "ADR-001",
        substrate=["maistro-engine#ADR-002"],
        related=["maistro-engine#ADR-003"],
    )
    b = _make_fm("ADR-002")
    c = _make_fm("ADR-003")
    reg = build_registry([a, b, c])

    assert reg.entries["maistro-engine#ADR-002"].referenced_by == ["maistro-engine#ADR-001"]
    assert reg.entries["maistro-engine#ADR-003"].referenced_by == ["maistro-engine#ADR-001"]


def test_back_references_idempotent() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002")
    reg = build_registry([a, b])
    # Second computation should not duplicate back-refs
    reg.compute_back_references()
    assert reg.entries["maistro-engine#ADR-002"].superseded_by == ["maistro-engine#ADR-001"]


def test_back_references_skip_unknown_targets() -> None:
    """References to artifacts not in the registry don't crash and don't appear."""
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-999"])
    reg = build_registry([a])
    # No entry for ADR-999, nothing crashes, ADR-001 still has its forward ref
    assert "maistro-engine#ADR-999" not in reg.entries
    assert reg.entries["maistro-engine#ADR-001"].supersedes == ["maistro-engine#ADR-999"]


def test_json_keys_are_sorted() -> None:
    a = _make_fm("ADR-002")
    b = _make_fm("ADR-001")
    reg = build_registry([a, b])
    payload = reg.to_json()
    # Sorted keys means ADR-001 comes before ADR-002 in the serialization
    pos_001 = payload.find("maistro-engine#ADR-001")
    pos_002 = payload.find("maistro-engine#ADR-002")
    assert 0 < pos_001 < pos_002


def test_markdown_groups_by_repo() -> None:
    # The registry is single-repo, so grouping renders exactly one section --
    # the header, its per-group count, and the overall tally still come from
    # the by-repo grouping path.
    first_fm = _make_fm("ADR-001", repo="maistro-engine", title="Engine ADR")
    second_fm = _make_fm("ADR-002", repo="maistro-engine", title="Second ADR")
    reg = build_registry([first_fm, second_fm])
    md = reg.to_markdown()
    assert "## `maistro-engine` (2 artifacts)" in md
    # Both titles present
    assert "Engine ADR" in md
    assert "Second ADR" in md
    # Two artifacts overall, one repo
    assert "**2 artifacts** across 1 repos" in md


def test_markdown_escapes_pipes_in_titles() -> None:
    fm = _make_fm("ADR-001", title="Has | pipe")
    reg = build_registry([fm])
    md = reg.to_markdown()
    # Pipe in title should be escaped so the table doesn't break
    assert "Has \\| pipe" in md


def test_write_registry_creates_files(tmp_path: Path) -> None:
    fm = _make_fm("ADR-030", title="Test ADR")
    reg = build_registry([fm])
    json_path, md_path = write_registry(reg, tmp_path / "registry")

    assert json_path.exists()
    assert md_path.exists()

    payload = json.loads(json_path.read_text())
    assert "maistro-engine#ADR-030" in payload

    md = md_path.read_text()
    assert "Test ADR" in md


def test_registry_entry_serializes_optional_dates() -> None:
    fm = _make_fm("ADR-001")  # no accepted, no implemented
    entry = RegistryEntry.from_front_matter(fm)
    assert entry.accepted is None
    assert entry.implemented is None
    assert entry.created == "2026-05-07"
