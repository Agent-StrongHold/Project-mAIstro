"""One Goal, several packs. Not a second product."""

from __future__ import annotations

from maistro_design.packs.registry import DomainPackRegistry, load_bundled_packs

ATELIER_SCENARIO = (
    "game",
    "novel",
    "training_program",
    "product",
)


def compose_workspace_goal(
    goal_id: str,
    *,
    registry: DomainPackRegistry | None = None,
    pack_ids: tuple[str, ...] = ATELIER_SCENARIO,
) -> dict[str, object]:
    """Bind several packs onto one Goal.

    ``game`` can be a board game about making a novel.
    ``novel`` is that novel.
    ``training_program`` is the curriculum inside it.
    ``product`` is the pitch deck. Atelier is the loop name, not a pack.
    """
    packs = registry if registry is not None else load_bundled_packs()
    bindings = [packs.bind(pack_id, goal_id) for pack_id in pack_ids]
    return {
        "goal_id": goal_id,
        "run_identity": "canonical",
        "pack_ids": [row["pack_id"] for row in bindings],
        "bindings": bindings,
    }
