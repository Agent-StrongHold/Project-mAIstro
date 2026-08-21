"""Department DAGs — 45 optimizable DAG definitions (9 departments x 5 each).

Each DAG is a dict with:
  - id: unique identifier
  - name: human-readable name
  - department: which department owns it
  - description: what it does
  - nodes: list of {id, prompt, model, role}
  - edges: list of {from_node, to_node}
  - evals: list of eval class names to score against
"""

from __future__ import annotations

from typing import Any


def get_all_dags() -> list[dict[str, Any]]:
    """Return all 45 DAG definitions."""
    from dags import (
        creative_writing,
        deep_research,
        engineering,
        finance,
        hr_people_ops,
        legal,
        marketing,
        press_releases,
        product_management,
    )

    all_dags = []
    for mod in [
        deep_research,
        product_management,
        engineering,
        creative_writing,
        press_releases,
        finance,
        hr_people_ops,
        marketing,
        legal,
    ]:
        all_dags.extend(mod.DAGS)
    return all_dags


def get_dags_by_department(department: str) -> list[dict[str, Any]]:
    """Return DAGs for a specific department."""
    return [d for d in get_all_dags() if d["department"] == department]
