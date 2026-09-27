"""Domain pack registry contracts (#1614, #793)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maistro_design.packs import (
    DomainPackRegistry,
    PackContractError,
    bundled_pack_dir,
    load_bundled_packs,
)

REQUIRED = {
    "book",
    "game",
    "interactive",
    "novel",
    "product",
    "small_business",
    "training_program",
    "website",
}


def test_bundled_packs_load_through_one_registry() -> None:
    registry = load_bundled_packs()
    assert set(registry.ids()) == REQUIRED
    for pack_id in REQUIRED:
        pack = registry.get(pack_id)
        assert pack.run_identity == "canonical"
        assert pack.graph_template == "loop.explore-execute-evaluate-refine"
        assert pack.rubric_dimensions
        assert "canvas" != pack.pack_id


def test_same_goal_two_packs_share_identity_scheme() -> None:
    registry = load_bundled_packs()
    goal = "goal-atelier-workspace"
    game = registry.bind("game", goal)
    novel = registry.bind("novel", goal)
    training = registry.bind("training_program", goal)
    deck = registry.bind("product", goal)
    assert game["goal_id"] == novel["goal_id"] == training["goal_id"] == deck["goal_id"]
    assert game["run_identity"] == deck["run_identity"] == "canonical"
    assert game["rubric_dimension_ids"] != novel["rubric_dimension_ids"]
    assert game["pack_id"] == "game"
    assert deck["pack_id"] == "product"


def test_missing_rubric_is_rejected() -> None:
    registry = DomainPackRegistry()
    path = bundled_pack_dir() / "product.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["rubric_dimensions"] = []
    broken = Path(path.as_posix() + ".broken")
    with pytest.raises(PackContractError, match="rubric"):
        registry.load_file  # keep import used; validate via _as_pack path
        from maistro_design.packs.registry import _as_pack

        _as_pack(raw)


def test_canvas_cannot_be_a_pack_id() -> None:
    from maistro_design.packs.registry import _as_pack

    with pytest.raises(PackContractError, match="backend"):
        _as_pack(
            {
                "pack_id": "canvas",
                "graph_template": "loop.explore-execute-evaluate-refine",
                "rubric_dimensions": [{"id": "x", "label": "X"}],
                "backends": ["builders"],
                "artifact_kinds": ["page"],
                "fence_points": ["rubric-lock"],
            }
        )
