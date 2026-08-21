from __future__ import annotations

import pytest

from maistro.graph.depth import (
    DepthRole,
    can_spawn,
    compute_subgraph_depths,
    get_role,
    validate_depth,
)


class TestDepthRole:
    def test_root_at_depth_zero(self):
        assert get_role(0, 3) == DepthRole.ROOT

    @pytest.mark.ac("ADR-066/AC-6")
    def test_orchestrator_at_intermediate_depth(self):
        assert get_role(1, 3) == DepthRole.ORCHESTRATOR
        assert get_role(2, 4) == DepthRole.ORCHESTRATOR

    def test_leaf_at_max_depth(self):
        assert get_role(3, 3) == DepthRole.LEAF

    def test_leaf_exceeding_max_depth(self):
        assert get_role(5, 3) == DepthRole.LEAF

    @pytest.mark.ac("ADR-066/AC-5")
    def test_max_depth_one(self):
        assert get_role(0, 1) == DepthRole.ROOT
        assert get_role(1, 1) == DepthRole.LEAF

    def test_max_depth_two(self):
        assert get_role(0, 2) == DepthRole.ROOT
        assert get_role(1, 2) == DepthRole.ORCHESTRATOR
        assert get_role(2, 2) == DepthRole.LEAF


class TestCanSpawn:
    def test_root_can_spawn(self):
        assert can_spawn(DepthRole.ROOT) is True

    def test_orchestrator_can_spawn(self):
        assert can_spawn(DepthRole.ORCHESTRATOR) is True

    @pytest.mark.ac("ADR-066/AC-5")
    def test_leaf_cannot_spawn(self):
        assert can_spawn(DepthRole.LEAF) is False


class TestValidateDepth:
    def test_valid_depth(self):
        validate_depth(0, 3)
        validate_depth(1, 3)
        validate_depth(3, 3)

    @pytest.mark.ac("ADR-066/AC-4")
    def test_depth_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="exceeds max_depth"):
            validate_depth(4, 3)

    def test_depth_far_exceeds_max(self):
        with pytest.raises(ValueError):
            validate_depth(10, 3)


class TestComputeSubgraphDepths:
    def test_single_child(self):
        result = compute_subgraph_depths(0, 3, 1)
        assert result == [1]

    def test_multiple_children(self):
        result = compute_subgraph_depths(1, 3, 4)
        assert result == [2, 2, 2, 2]

    def test_root_spawns_children_at_depth_1(self):
        result = compute_subgraph_depths(0, 3, 3)
        assert result == [1, 1, 1]

    @pytest.mark.ac("ADR-066/AC-6")
    def test_orchestrator_spawns_children(self):
        result = compute_subgraph_depths(1, 3, 2)
        assert result == [2, 2]

    @pytest.mark.ac("ADR-066/AC-4")
    def test_leaf_cannot_spawn_raises(self):
        with pytest.raises(ValueError, match="Cannot spawn"):
            compute_subgraph_depths(3, 3, 1)

    def test_zero_children(self):
        result = compute_subgraph_depths(0, 3, 0)
        assert result == []

    @pytest.mark.ac("ADR-066/AC-4")
    def test_near_max_depth(self):
        result = compute_subgraph_depths(2, 3, 2)
        assert result == [3, 3]
        assert get_role(3, 3) == DepthRole.LEAF
