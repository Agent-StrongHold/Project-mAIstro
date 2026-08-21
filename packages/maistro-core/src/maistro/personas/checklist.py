"""Derive a proposed capability checklist from a persona's declared spawns.

Persona/Workspace system, Phase C. The checklist a workspace-creation wizard
presents (accept/modify) is not a separate hardcoded catalog -- it's derived
directly from the chosen `PersonaTemplate`'s own `spawns[].tools`/`skills`, so
adding a new persona (a YAML file) automatically gets a correct checklist with
no code change here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from maistro.personas.schema import PersonaTemplate


class CapabilityItem(BaseModel):
    """One checklist row: one declared tool or skill, bound to the agent that owns it.

    ``id`` is stable and unique within a single persona template (not globally)
    -- `f"{agent}.tool.{name}"` / `f"{agent}.skill.{name}"` -- so the same tool
    name declared under two different agents produces two distinct, individually
    acceptable checklist rows rather than colliding.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    agent: str
    kind: str  # "tool" | "skill"
    name: str
    label: str


def _label(name: str) -> str:
    return name.replace("_", " ").title()


def capability_checklist(template: PersonaTemplate) -> list[CapabilityItem]:
    """One CapabilityItem per (agent, tool) and (agent, skill) declared in spawns.

    Order matches `spawns` order, tools before skills within each spawn --
    deterministic, so a checklist UI renders stably across reloads. A
    template that repeats a tool/skill within one spawn, or repeats an agent
    name across spawns, would otherwise produce two rows sharing one `id`;
    the first occurrence wins and later duplicates are skipped so every id
    stays unique and independently accept/reject-able.
    """
    items: list[CapabilityItem] = []
    seen_ids: set[str] = set()
    for spawn in template.spawns:
        for tool in spawn.tools:
            item_id = f"{spawn.agent}.tool.{tool}"
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            items.append(
                CapabilityItem(
                    id=item_id,
                    agent=spawn.agent,
                    kind="tool",
                    name=tool,
                    label=_label(tool),
                )
            )
        for skill in spawn.skills:
            item_id = f"{spawn.agent}.skill.{skill}"
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            items.append(
                CapabilityItem(
                    id=item_id,
                    agent=spawn.agent,
                    kind="skill",
                    name=skill,
                    label=_label(skill),
                )
            )
    return items


def default_checklist_ids(template: PersonaTemplate) -> list[str]:
    """Every declared capability, pre-checked -- the wizard starts from "everything
    this persona declares" and the user unchecks what they don't want."""
    return [item.id for item in capability_checklist(template)]
