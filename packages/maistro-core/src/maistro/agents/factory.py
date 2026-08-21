"""Agent factory: seed from filesystem, load from database.

Boot sequence:
  1. If SQLAlchemy engine provided and agents exist in DB: load from DB.
  2. If not: seed from agents/ directory -> persist to DB (if available).
  3. InMemory mode (no DB): always seeds from filesystem.

The agents/ directory is SEED DATA for first boot. After seeding, the database
is the source of truth. CRUD via API, not filesystem edits.

GitAgent format on disk:
  agents/
  ├── PREAMBLE.md          # Shared system preamble (prepended to all souls)
  ├── arbiter/
  │   ├── agent.yaml       # Identity manifest
  │   ├── SOUL.md          # System prompt
  │   └── RULES.md         # Hard constraints (optional)
  └── ...
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from maistro.agents.base import Agent
from maistro.agents.strategies.direct import DirectStrategy
from maistro.types.agent import AgentIdentity
from maistro.types.errors import ConfigError

logger = logging.getLogger("maistro.agents.factory")

_STRATEGY_REGISTRY: dict[str, Any] = {
    "direct": DirectStrategy,
}


def register_strategy(name: str, cls: type) -> None:
    _STRATEGY_REGISTRY[name] = cls


def _load_preamble(agents_dir: Path) -> str:
    preamble_path = agents_dir / "PREAMBLE.md"
    if preamble_path.exists():
        return preamble_path.read_text(encoding="utf-8")
    logger.warning("No PREAMBLE.md in %s", agents_dir)
    return ""


_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

_PREAMBLE_DEFAULTS: dict[str, str] = {
    "agent_name": "Maistro Agent",
    "agent_description": "a specialist agent operating within the Maistro platform",
    "capabilities": (
        "You are a **text-based AI assistant**. You can:\n"
        "- Analyze, explain, summarize, compare, and reason about information\n"
        "- Generate and review code\n"
        "- Write professional and creative content\n"
        "- Answer factual questions\n"
        "- Execute **approved tools only** through the Sentinel-validated dispatch system\n"
        "- Remember context within a session and learn from corrections over time"
    ),
    "boundaries": (
        "These are platform limitations, not suggestions:\n"
        "- **No image generation or editing.** Route image requests to the Canvas agent.\n"
        "- **No audio, video, or multimedia.**\n"
        "- **No direct internet access.** Approved tools handle external data.\n"
        "- **No arbitrary code execution** outside Sentinel-approved tools.\n"
        "- **No file system access** outside the approved workspace.\n"
        "- **No cross-tenant data access.** You see only your org's data."
    ),
}


def _render_preamble(template: str, manifest: dict[str, Any]) -> str:
    variables = dict(_PREAMBLE_DEFAULTS)
    variables["agent_name"] = manifest.get("name", variables["agent_name"])
    variables["agent_description"] = manifest.get("description", variables["agent_description"])

    for key in ("capabilities", "boundaries"):
        if key in manifest:
            val = manifest[key]
            if isinstance(val, str):
                variables[key] = val.strip()

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return variables.get(var_name, "")

    return _VAR_PATTERN.sub(_replace, template)


def _parse_agent_dir(agent_dir: Path) -> tuple[dict[str, Any], str, str] | None:
    manifest_path = agent_dir / "agent.yaml"
    if not manifest_path.exists():
        return None

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "name" not in manifest:
        logger.warning("Invalid agent.yaml in %s -- skipping", agent_dir)
        return None

    soul_file = manifest.get("soul", "SOUL.md")
    soul_path = agent_dir / soul_file
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

    rules_path = agent_dir / "RULES.md"
    rules = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

    return manifest, soul, rules


def _safe_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return () if not value else (value,)
    if isinstance(value, (list, tuple)):
        return tuple(
            item["name"] if isinstance(item, dict) and "name" in item else item for item in value
        )
    return ()


def _strict_str_tuple(value: Any, *, field: str, agent_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        msg = (
            f"agent '{agent_name}': field '{field}' has type "
            f"{type(value).__name__}; expected list of strings"
        )
        raise ConfigError(msg)
    bad = [item for item in value if not isinstance(item, str)]
    if bad:
        msg = (
            f"agent '{agent_name}': field '{field}' contains non-string entries "
            f"(types: {sorted({type(x).__name__ for x in bad})}); "
            f"expected list of strings"
        )
        raise ConfigError(msg)
    return tuple(value)


def _build_identity_from_manifest(manifest: dict[str, Any]) -> AgentIdentity:
    name = manifest["name"]
    reasoning = manifest.get("reasoning", {}) or {}
    return AgentIdentity(
        name=name,
        version=manifest.get("version", "1.0.0"),
        description=manifest.get("description", ""),
        soul_prompt_name=f"agent.{name}.soul",
        model=manifest.get("model", "auto"),
        model_fallbacks=_strict_str_tuple(
            manifest.get("model_fallbacks"), field="model_fallbacks", agent_name=name
        ),
        model_constraints=manifest.get("model_constraints", {}) or {},
        tools=_strict_str_tuple(manifest.get("tools"), field="tools", agent_name=name),
        skills=_strict_str_tuple(manifest.get("skills"), field="skills", agent_name=name),
        rules=_safe_tuple(manifest.get("rules")),
        sub_agents=_strict_str_tuple(
            manifest.get("sub_agents"), field="sub_agents", agent_name=name
        ),
        trust_tier=manifest.get("trust_tier", "t2"),
        priority_tier=manifest.get("priority_tier", "P2"),
        max_tool_rounds=reasoning.get("max_subtasks", reasoning.get("max_rounds", 3)),
        reasoning_strategy=reasoning.get("strategy", "direct"),
        memory_config=manifest.get("memory", {}) or {},
        phases=_safe_tuple(reasoning.get("phases")),
    )


_DELEGATE_ROUTING_DEFAULTS: dict[str, str] = {
    "code": "artificer",
    "code_gen": "mason",
    "automation": "warden-at-arms",
    "search": "ranger",
    "creative": "scribe",
    "creative_image": "davinci",
    "story": "fabulist",
    "reasoning": "artificer",
}


def _build_delegate_strategy(identity: AgentIdentity) -> Any:
    from maistro.agents.strategies.delegate import DelegateStrategy

    if not identity.sub_agents:
        msg = (
            f"agent '{identity.name}': reasoning.strategy='delegate' requires a "
            f"non-empty 'sub_agents' list"
        )
        raise ConfigError(msg)
    available = set(identity.sub_agents)
    routing = {tt: agent for tt, agent in _DELEGATE_ROUTING_DEFAULTS.items() if agent in available}
    default_agent = "default" if "default" in available else identity.sub_agents[0]
    return DelegateStrategy(routing_table=routing, default_agent=default_agent)


def _build_strategy(identity: AgentIdentity) -> Any:
    strategy_name = identity.reasoning_strategy
    if strategy_name == "delegate":
        return _build_delegate_strategy(identity)
    strategy_cls = _STRATEGY_REGISTRY.get(strategy_name)
    if strategy_cls is None:
        logger.warning(
            "Unknown strategy '%s' for agent '%s' -- falling back to direct",
            strategy_name,
            identity.name,
        )
        return DirectStrategy()
    try:
        return strategy_cls()
    except TypeError as exc:
        msg = f"agent '{identity.name}': strategy '{strategy_name}' could not be constructed: {exc}"
        raise ConfigError(msg) from exc


def _register_custom_strategies() -> None:
    try:
        from maistro.agents.strategies.react import ReactStrategy

        register_strategy("react", ReactStrategy)
    except ImportError:
        pass

    try:
        from maistro.agents.strategies.delegate import DelegateStrategy

        register_strategy("delegate", DelegateStrategy)
    except ImportError:
        pass

    try:
        from maistro.agents.strategies.builders_learning import BuildersLearningStrategy

        register_strategy("builders_learning", BuildersLearningStrategy)
    except ImportError:
        pass

    try:
        from maistro.agents.strategies.plan_execute import PlanExecuteStrategy

        register_strategy("plan_execute", PlanExecuteStrategy)
    except ImportError:
        pass

    try:
        from maistro.agents.artificer.strategy import ArtificerStrategy

        register_strategy("artificer", ArtificerStrategy)
    except ImportError:
        pass


def _instantiate(identity: AgentIdentity, *, agent_resolver: Any = None, **deps: Any) -> Agent:
    strategy = _build_strategy(identity)
    tool_executor = deps.pop("tool_executor", None)
    return Agent(
        identity=identity,
        strategy=strategy,
        tool_executor=tool_executor if identity.tools else None,
        agent_resolver=agent_resolver,
        **deps,
    )


def _build_persist_registry(sa_engine: Any) -> Any:
    """Construct a ``PgAgentRegistry`` for write-back, or ``None`` if unavailable."""
    if not sa_engine:
        return None
    try:
        from maistro.persistence.pg_agents import PgAgentRegistry

        return PgAgentRegistry(sa_engine)
    except Exception as _exc:
        logger.warning(
            "error_swallowed file=%s line=%d: %s",
            "packages/maistro-core/src/maistro/agents/factory.py",
            374,
            _exc,
        )
        return None


async def _load_agents_from_db(
    sa_engine: Any,
    prompt_manager: Any,
    deps: dict[str, Any],
) -> dict[str, Agent] | None:
    """Load active agents from the Postgres registry. Returns the agent map, or
    ``None`` to signal the caller should fall back to the filesystem (no agents
    in DB, or a load failure)."""
    try:
        from maistro.persistence.pg_agents import PgAgentRegistry

        registry = PgAgentRegistry(sa_engine)
        if await registry.count() <= 0:
            return None
        identities = await registry.list_active()
        souls = await registry.souls()
        agents: dict[str, Agent] = {}
        for identity in identities:
            await prompt_manager.upsert(
                f"agent.{identity.name}.soul",
                souls.get(identity.name, ""),
                label="production",
            )
            agents[identity.name] = _instantiate(identity, agent_resolver=agents.get, **{**deps})
        logger.info("Loaded %d agents from database", len(agents))
        return agents
    except Exception:
        logger.warning("Failed to load agents from DB -- falling back to filesystem", exc_info=True)
        return None


async def _persist_agent_record(
    persist_registry: Any,
    identity: Any,
    full_soul: str,
    rules: Any,
) -> None:
    """Upsert a built-in agent identity into the Postgres registry (best-effort)."""
    try:
        # maistro.models lives in the hive-conductor app (no py.typed); owned elsewhere.
        from maistro.models.agent import AgentRecord

        record = AgentRecord(
            name=identity.name,
            version=identity.version,
            description=identity.description,
            soul=full_soul,
            rules=rules,
            reasoning_strategy=identity.reasoning_strategy,
            model=identity.model,
            model_fallbacks=list(identity.model_fallbacks),
            model_constraints=identity.model_constraints,
            tools=list(identity.tools),
            skills=list(identity.skills),
            max_tool_rounds=identity.max_tool_rounds,
            memory_config=identity.memory_config,
            trust_tier=identity.trust_tier,
            priority_tier=identity.priority_tier,
            provenance="builtin",
            org_id="",
            preamble=True,
            active=True,
        )
        await persist_registry.upsert(record)
    except Exception:
        logger.warning("Failed to persist agent '%s' to DB", identity.name, exc_info=True)


async def create_agents(
    *,
    agents_dir: str | Path,
    prompt_manager: Any,
    llm: Any,
    context_builder: Any,
    warden: Any,
    sentinel: Any,
    learning_store: Any,
    learning_extractor: Any,
    outcome_store: Any,
    session_store: Any,
    quota_tracker: Any,
    tracer: Any,
    coin_ledger: Any = None,
    tool_executor: Any = None,
    sa_engine: Any = None,
    rca_extractor: Any = None,
    learning_promoter: Any = None,
    tool_registry: Any = None,
) -> dict[str, Agent]:
    _register_custom_strategies()

    deps = {
        "llm": llm,
        "context_builder": context_builder,
        "prompt_manager": prompt_manager,
        "warden": warden,
        "sentinel": sentinel,
        "learning_store": learning_store,
        "learning_extractor": learning_extractor,
        "outcome_store": outcome_store,
        "session_store": session_store,
        "quota_tracker": quota_tracker,
        "coin_ledger": coin_ledger,
        "tracer": tracer,
        "tool_executor": tool_executor,
        "rca_extractor": rca_extractor,
        "learning_promoter": learning_promoter,
        "tool_registry": tool_registry,
    }

    if sa_engine:
        db_agents = await _load_agents_from_db(sa_engine, prompt_manager, deps)
        if db_agents is not None:
            return db_agents

    agents_path = Path(agents_dir)
    if not agents_path.is_dir():
        logger.warning("Agents directory %s not found -- no agents loaded", agents_dir)
        return {}

    preamble = _load_preamble(agents_path)
    agents: dict[str, Agent] = {}

    persist_registry: Any = _build_persist_registry(sa_engine)

    for agent_dir in sorted(agents_path.iterdir()):
        if not agent_dir.is_dir():
            continue

        parsed = _parse_agent_dir(agent_dir)
        if parsed is None:
            continue

        manifest, soul, rules = parsed
        identity = _build_identity_from_manifest(manifest)

        rendered_preamble = _render_preamble(preamble, manifest)
        full_soul = rendered_preamble + soul

        await prompt_manager.upsert(
            f"agent.{identity.name}.soul",
            full_soul,
            label="production",
        )

        if persist_registry:
            await _persist_agent_record(persist_registry, identity, full_soul, rules)

        agents[identity.name] = _instantiate(identity, agent_resolver=agents.get, **{**deps})
        logger.info(
            "Seeded agent '%s' (strategy=%s, tools=%d, db=%s)",
            identity.name,
            identity.reasoning_strategy,
            len(identity.tools),
            persist_registry is not None,
        )

    if not agents:
        logger.warning("No agents loaded from %s", agents_dir)

    return agents
