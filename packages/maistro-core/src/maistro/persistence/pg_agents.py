"""PostgreSQL agent registry using SQLAlchemy.

Reads and writes agent definitions to the ``agents`` table and (de)serializes
rows into :class:`~maistro.types.agent.AgentIdentity` instances so the agent
factory can load agents from the database without losing fields.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from maistro.types.agent import AgentIdentity

logger = logging.getLogger("maistro.persistence.pg_agents")

# Columns persisted as JSON text (lists become tuples / dicts on read).
_LIST_FIELDS = ("tools", "skills", "model_fallbacks")
_DICT_FIELDS = ("model_constraints", "memory_config")

# Full column set the registry both writes and reads, keeping the INSERT and
# _coerce_row in lock-step so agents round-trip without losing fields.
_COLUMNS = (
    "name",
    "version",
    "description",
    "soul",
    "model",
    "model_fallbacks",
    "model_constraints",
    "tools",
    "skills",
    "rules",
    "trust_tier",
    "priority_tier",
    "max_tool_rounds",
    "reasoning_strategy",
    "memory_config",
    "provenance",
    "active",
    "created_at",
    "updated_at",
)

_INSERT_SQL = text(
    """
    INSERT INTO agents (
        name, version, description, soul, model,
        model_fallbacks, model_constraints, tools, skills, rules,
        trust_tier, priority_tier, max_tool_rounds, reasoning_strategy,
        memory_config, provenance, active, created_at, updated_at
    ) VALUES (
        :name, :version, :description, :soul, :model,
        :model_fallbacks, :model_constraints, :tools, :skills, :rules,
        :trust_tier, :priority_tier, :max_tool_rounds, :reasoning_strategy,
        :memory_config, :provenance, :active, :created_at, :updated_at
    )
    ON CONFLICT (name) DO UPDATE SET
        version = EXCLUDED.version,
        description = EXCLUDED.description,
        soul = EXCLUDED.soul,
        model = EXCLUDED.model,
        model_fallbacks = EXCLUDED.model_fallbacks,
        model_constraints = EXCLUDED.model_constraints,
        tools = EXCLUDED.tools,
        skills = EXCLUDED.skills,
        rules = EXCLUDED.rules,
        trust_tier = EXCLUDED.trust_tier,
        priority_tier = EXCLUDED.priority_tier,
        max_tool_rounds = EXCLUDED.max_tool_rounds,
        reasoning_strategy = EXCLUDED.reasoning_strategy,
        memory_config = EXCLUDED.memory_config,
        provenance = EXCLUDED.provenance,
        active = EXCLUDED.active,
        updated_at = EXCLUDED.updated_at
    """
)


class PgAgentRegistry:
    """CRUD for agent definitions in PostgreSQL via SQLAlchemy."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def list_active(self) -> list[AgentIdentity]:
        """List all active agents as :class:`AgentIdentity` objects."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM agents WHERE active = TRUE ORDER BY name"),
            )
            rows = result.mappings().all()
            return [_coerce_row(r) for r in rows]

    async def get(self, name: str) -> AgentIdentity | None:
        """Get a single agent by name, or ``None`` if absent."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM agents WHERE name = :name"),
                {"name": name},
            )
            row = result.mappings().first()
            return _coerce_row(row) if row else None

    async def upsert(self, record: AgentIdentity | Mapping[str, Any]) -> dict[str, Any]:
        """Atomically insert or update an agent definition.

        Accepts either an :class:`AgentIdentity` or a mapping of column values.
        List/dict fields are serialized to JSON so they survive the round-trip.
        Returns the params dict that was persisted.
        """
        params = _to_params(record)
        async with AsyncSession(self._engine) as session:
            await session.execute(_INSERT_SQL, params)
            await session.commit()
        return params

    async def souls(self) -> dict[str, str]:
        """Return the stored soul prompt text for each active agent by name.

        The soul prompt is not part of :class:`AgentIdentity` (it lives in the
        prompt store), so it is fetched separately for callers that need to
        re-seed the prompt manager from the database.
        """
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT name, soul FROM agents WHERE active = TRUE"),
            )
            return {row["name"]: (row["soul"] or "") for row in result.mappings().all()}

    async def count(self) -> int:
        """Count active agents in the database."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(text("SELECT COUNT(*) FROM agents WHERE active = TRUE"))
            row = result.first()
            return int(row[0]) if row else 0

    async def delete(self, name: str) -> bool:
        """Soft-delete an agent."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text(
                    "UPDATE agents SET active = FALSE, updated_at = :updated_at"
                    " WHERE name = :name AND active = TRUE"
                ),
                {"name": name, "updated_at": datetime.now(UTC)},
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0) > 0)


def _as_iterable(value: Any) -> list[Any]:
    """Normalize a value into a list (None -> [], scalar -> [scalar])."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _to_params(record: AgentIdentity | Mapping[str, Any]) -> dict[str, Any]:
    """Build the bound-parameter dict for an INSERT/UPSERT.

    Defaults mirror :class:`AgentIdentity` so a sparse mapping still produces a
    complete, persistable row. List/dict fields are JSON-encoded.
    """
    if isinstance(record, AgentIdentity):
        source: dict[str, Any] = {
            "name": record.name,
            "version": record.version,
            "description": record.description,
            "soul": "",
            "model": record.model,
            "model_fallbacks": list(record.model_fallbacks),
            "model_constraints": dict(record.model_constraints),
            "tools": list(record.tools),
            "skills": list(record.skills),
            "rules": "\n".join(record.rules),
            "trust_tier": record.trust_tier,
            "priority_tier": record.priority_tier,
            "max_tool_rounds": record.max_tool_rounds,
            "reasoning_strategy": record.reasoning_strategy,
            "memory_config": dict(record.memory_config),
            "provenance": record.provenance,
            "active": record.active,
        }
    else:
        source = dict(record)

    now = datetime.now(UTC)
    rules = source.get("rules", "")
    if isinstance(rules, (list, tuple)):
        rules = "\n".join(str(r) for r in rules)

    params: dict[str, Any] = {
        "name": source["name"],
        "version": source.get("version", "1.0.0"),
        "description": source.get("description", ""),
        "soul": source.get("soul", ""),
        "model": source.get("model", "auto"),
        "model_fallbacks": json.dumps(_as_iterable(source.get("model_fallbacks"))),
        "model_constraints": json.dumps(dict(source.get("model_constraints") or {})),
        "tools": json.dumps(_as_iterable(source.get("tools"))),
        "skills": json.dumps(_as_iterable(source.get("skills"))),
        "rules": rules or "",
        "trust_tier": source.get("trust_tier", "t4"),
        "priority_tier": source.get("priority_tier", "P2"),
        "max_tool_rounds": int(source.get("max_tool_rounds", 3)),
        "reasoning_strategy": source.get("reasoning_strategy", "direct"),
        "memory_config": json.dumps(dict(source.get("memory_config") or {})),
        "provenance": source.get("provenance", "user"),
        "active": bool(source.get("active", True)),
        "created_at": source.get("created_at") or now,
        "updated_at": now,
    }
    return params


def _decode_json(value: Any, default: Any) -> Any:
    """Decode a JSON column that may already be a native list/dict."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        if not value:
            return default
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return default


def _coerce_row(row: Any) -> AgentIdentity:
    """Coerce a raw SQL row mapping into an :class:`AgentIdentity`."""
    data = dict(row)

    fallbacks = _decode_json(data.get("model_fallbacks"), [])
    tools = _decode_json(data.get("tools"), [])
    skills = _decode_json(data.get("skills"), [])
    constraints = _decode_json(data.get("model_constraints"), {})
    memory_config = _decode_json(data.get("memory_config"), {})

    rules_raw = data.get("rules") or ""
    rules = tuple(line for line in rules_raw.splitlines() if line) if rules_raw else ()

    name = data["name"]
    return AgentIdentity(
        name=name,
        version=data.get("version") or "1.0.0",
        description=data.get("description") or "",
        soul_prompt_name=f"agent.{name}.soul",
        model=data.get("model") or "auto",
        model_fallbacks=tuple(fallbacks),
        model_constraints=dict(constraints),
        tools=tuple(tools),
        skills=tuple(skills),
        rules=rules,
        trust_tier=data.get("trust_tier") or "t4",
        priority_tier=data.get("priority_tier") or "P2",
        max_tool_rounds=int(data["max_tool_rounds"])
        if data.get("max_tool_rounds") is not None
        else 3,
        reasoning_strategy=data.get("reasoning_strategy") or "direct",
        memory_config=dict(memory_config),
        provenance=data.get("provenance") or "user",
        active=bool(data["active"]) if data.get("active") is not None else True,
    )
