"""Pi agent-config importer (SPEC-208).

Minimal documented Pi agent format (dict, or a JSON/YAML string of it):

    kind: pi.agent           # required discriminator ("pi." prefix)
    name: research-helper    # required
    description: ...
    model: { preferred: claude-sonnet-4-6 }   # or a plain string
    tools: [web_search, ...]
    instructions: |          # the agent's system/soul prompt
      ...
    trust_tier: t2

The imported agent binds to the "pi" harness_runner provider: the binding and
the source instructions are carried in ``AgentIdentity.model_constraints``
(``{"harness_runner": "pi", "instructions": ...}``) since AgentIdentity has no
dedicated harness field yet.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from maistro.types.agent import AgentIdentity

_NAME_SANITIZE_RE = re.compile(r"[^a-z0-9_]+")


def sanitize_agent_name(raw: str) -> str:
    """Coerce a foreign agent name into maistro's snake_case name shape."""
    name = _NAME_SANITIZE_RE.sub("_", raw.strip().lower()).strip("_")
    if not name or not name[0].isalpha() or len(name) < 2:
        name = f"agent_{name}".rstrip("_") if name else "agent_imported"
    return name[:51]


def _coerce(source: dict[str, Any] | str) -> dict[str, Any] | None:
    if isinstance(source, dict):
        return source
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


class PiAgentImporter:
    """Imports a Pi agent/task config into AgentIdentity."""

    @property
    def format(self) -> str:
        return "pi"

    def detect(self, source: dict[str, Any] | str) -> bool:
        data = _coerce(source)
        if data is None:
            return False
        kind = data.get("kind", "")
        return isinstance(kind, str) and kind.startswith("pi.") and "name" in data

    def to_agent_config(self, source: dict[str, Any] | str) -> AgentIdentity:
        data = _coerce(source)
        if data is None or not self.detect(data):
            raise ValueError("not a Pi agent config")

        name_raw = data.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            raise ValueError("Pi agent config missing 'name'")

        model_field = data.get("model", "auto")
        if isinstance(model_field, dict):
            model = str(model_field.get("preferred", "auto"))
        else:
            model = str(model_field) or "auto"

        tools_raw = data.get("tools", [])
        tools = tuple(str(t) for t in tools_raw) if isinstance(tools_raw, list) else ()

        return AgentIdentity(
            name=sanitize_agent_name(name_raw),
            version=str(data.get("version", "1.0.0")),
            description=str(data.get("description", "")),
            model=model,
            tools=tools,
            trust_tier=str(data.get("trust_tier", "t2")),
            model_constraints={
                "harness_runner": "pi",
                "instructions": str(data.get("instructions", "")),
            },
            provenance="import:pi",
        )
