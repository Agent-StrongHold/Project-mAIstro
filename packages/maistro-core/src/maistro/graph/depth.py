from __future__ import annotations

from enum import StrEnum


class DepthRole(StrEnum):
    ROOT = "root"
    ORCHESTRATOR = "orchestrator"
    LEAF = "leaf"


def get_role(depth: int, max_depth: int) -> DepthRole:
    if depth == 0:
        return DepthRole.ROOT
    if depth >= max_depth:
        return DepthRole.LEAF
    return DepthRole.ORCHESTRATOR


def can_spawn(role: DepthRole) -> bool:
    return role != DepthRole.LEAF


def validate_depth(depth: int, max_depth: int) -> None:
    if depth > max_depth:
        raise ValueError(f"Depth {depth} exceeds max_depth {max_depth}")


def compute_subgraph_depths(parent_depth: int, max_depth: int, num_children: int) -> list[int]:
    child_depth = parent_depth + 1
    if child_depth > max_depth:
        raise ValueError(
            f"Cannot spawn subgraphs at depth {child_depth}: exceeds max_depth {max_depth}"
        )
    return [child_depth] * num_children
