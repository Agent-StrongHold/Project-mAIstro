"""Pack contract. A pack is a catalog, not a product identity."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RubricDimension:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class DomainPack:
    pack_id: str
    graph_template: str
    rubric_dimensions: tuple[RubricDimension, ...]
    backends: tuple[str, ...]
    artifact_kinds: tuple[str, ...]
    fence_points: tuple[str, ...]
    run_identity: str = field(default="canonical")

    def binds_goal(self, goal_id: str) -> dict[str, object]:
        """Instantiate the catalog onto a Goal. Does not own Goal identity."""
        return {
            "goal_id": goal_id,
            "pack_id": self.pack_id,
            "run_identity": self.run_identity,
            "rubric_dimension_ids": [d.id for d in self.rubric_dimensions],
            "graph_template": self.graph_template,
        }
