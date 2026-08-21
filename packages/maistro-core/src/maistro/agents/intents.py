"""Intent registry: static routing table mapping task_type to agent_name."""

from __future__ import annotations

import os

_PM_ROUTING: dict[str, str] = {
    "intake": "intake",
    "program_management": "program_manager",
    "delivery": "delivery",
    "risk": "risk_dependency",
    "reporting": "reporting",
}

_ENGINEERING_ROUTING: dict[str, str] = {
    "code": "artificer",
    "code_gen": "mason",
    "automation": "warden-at-arms",
    "search": "ranger",
    "creative": "scribe",
    "reasoning": "artificer",
}


def poc_mode_from_env() -> str:
    return os.getenv("MAISTRO_POC_MODE", "").strip().lower()


def build_intent_registry(poc_mode: str | None = None) -> IntentRegistry:
    mode = (poc_mode or poc_mode_from_env()).strip().lower()
    if mode == "pm":
        return IntentRegistry(dict(_PM_ROUTING))
    return IntentRegistry(dict(_ENGINEERING_ROUTING))


class IntentRegistry:
    """Maps task types to agent names."""

    def __init__(self, routing_table: dict[str, str] | None = None) -> None:
        self._table = routing_table or dict(_ENGINEERING_ROUTING)

    def get_agent_for_intent(self, task_type: str) -> str | None:
        return self._table.get(task_type)

    def resolve(self, task_type: str) -> str:
        """Return agent name or engineering default."""
        if poc_mode_from_env() == "pm":
            return self._table.get(task_type, "intake")
        return self._table.get(task_type, "artificer")

    def register(self, task_type: str, agent_name: str) -> None:
        self._table[task_type] = agent_name
