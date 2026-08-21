"""Coverage for maistro.agents.store.InMemoryAgentStore (was 0%).

Exercises CRUD, name validation, GitAgent export/import round-tripping,
and the zip-slip path-traversal guard, with assertions on exact field
values rather than "didn't raise".
"""

from __future__ import annotations

import io
import re
import zipfile

import pytest
import yaml

from maistro.agents.base import Agent
from maistro.agents.store import InMemoryAgentStore
from maistro.agents.strategies.direct import DirectStrategy
from maistro.types.agent import AgentIdentity


class _StubLLM:
    pass


class _StubContextBuilder:
    pass


class _StubPromptManager:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, str, str]] = []
        self.get_with_config_calls: list[tuple[str, str]] = []
        self.stored_soul = "soul from prompt manager"

    async def upsert(self, name: str, content: str, *, label: str) -> None:
        self.upserts.append((name, content, label))

    async def get_with_config(self, name: str, *, label: str) -> tuple[str, dict]:
        self.get_with_config_calls.append((name, label))
        return self.stored_soul, {}


def _identity(name: str = "base-agent", **overrides) -> AgentIdentity:
    return AgentIdentity(name=name, **overrides)


def _agent(name: str = "base-agent", *, prompt_manager: object | None = None) -> Agent:
    return Agent(
        identity=_identity(name),
        strategy=DirectStrategy(),
        llm=_StubLLM(),
        context_builder=_StubContextBuilder(),
        prompt_manager=prompt_manager,
        warden=None,
        session_store=None,
    )


def _store(
    *, with_seed_agent: bool = True, prompt_manager: object | None = None
) -> InMemoryAgentStore:
    agents = {"base-agent": _agent(prompt_manager=prompt_manager)} if with_seed_agent else {}
    return InMemoryAgentStore(agents, prompt_manager=prompt_manager)


# ─── create() ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_clones_dependencies_from_existing_agent() -> None:
    store = _store()
    seed = store._agents["base-agent"]

    name = await store.create(_identity("new-agent"), "You are helpful.", "Be nice.")

    assert name == "new-agent"
    created = store._agents["new-agent"]
    # New agent must share the seed's infra deps (the only "DI source" available).
    assert created._llm is seed._llm
    assert created._context_builder is seed._context_builder
    assert created._session_store is seed._session_store
    assert created.identity.name == "new-agent"
    assert store._souls["new-agent"] == "You are helpful."
    assert store._rules["new-agent"] == "Be nice."


@pytest.mark.asyncio
async def test_create_uses_react_strategy_when_requested() -> None:
    store = _store()
    await store.create(_identity("react-agent", reasoning_strategy="react"), "soul")

    created = store._agents["react-agent"]
    from maistro.agents.strategies.react import ReactStrategy

    assert isinstance(created._strategy, ReactStrategy)


@pytest.mark.asyncio
async def test_create_falls_back_to_direct_strategy_for_unknown_strategy() -> None:
    store = _store()
    await store.create(_identity("weird-agent", reasoning_strategy="nonexistent"), "soul")

    created = store._agents["weird-agent"]
    assert isinstance(created._strategy, DirectStrategy)


@pytest.mark.asyncio
async def test_create_rejects_invalid_names() -> None:
    store = _store()
    # Uppercase, too long, leading digit, leading hyphen are all invalid per _NAME_PATTERN.
    for bad_name in ["UpperCase", "1starts-with-digit", "-leading-hyphen", "a" * 51, ""]:
        with pytest.raises(ValueError, match="Invalid agent name"):
            await store.create(_identity(bad_name), "soul")


@pytest.mark.asyncio
async def test_create_accepts_boundary_valid_names() -> None:
    store = _store()
    # Exactly 50 chars, single lowercase letter, with hyphens/underscores/digits.
    fifty_chars = "a" + "b" * 49
    assert len(fifty_chars) == 50
    await store.create(_identity(fifty_chars), "soul")
    assert fifty_chars in store._agents

    await store.create(_identity("a"), "soul")
    assert "a" in store._agents

    await store.create(_identity("a-b_c9"), "soul")
    assert "a-b_c9" in store._agents


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name() -> None:
    store = _store()
    with pytest.raises(ValueError, match="already exists"):
        await store.create(_identity("base-agent"), "soul")


@pytest.mark.asyncio
async def test_create_raises_when_no_existing_agents_to_clone_from() -> None:
    store = _store(with_seed_agent=False)
    with pytest.raises(ValueError, match="No existing agents to clone dependencies from"):
        await store.create(_identity("orphan"), "soul")


@pytest.mark.asyncio
async def test_create_upserts_soul_via_prompt_manager_when_present_and_nonempty() -> None:
    pm = _StubPromptManager()
    store = _store(prompt_manager=pm)

    await store.create(_identity("new-agent"), "the soul text")

    assert pm.upserts == [("agent.new-agent.soul", "the soul text", "production")]


@pytest.mark.asyncio
async def test_create_skips_prompt_manager_upsert_when_soul_content_empty() -> None:
    pm = _StubPromptManager()
    store = _store(prompt_manager=pm)

    await store.create(_identity("new-agent"), "")

    assert pm.upserts == []
    # Soul still recorded locally, just empty.
    assert store._souls["new-agent"] == ""


@pytest.mark.asyncio
async def test_create_defaults_rules_to_empty_string() -> None:
    store = _store()
    await store.create(_identity("new-agent"), "soul")
    assert store._rules["new-agent"] == ""


# ─── get() ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_agent() -> None:
    store = _store()
    assert await store.get("does-not-exist") is None


@pytest.mark.asyncio
async def test_get_returns_full_detail_dict() -> None:
    store = _store()
    await store.create(
        _identity(
            "detailed-agent",
            description="desc",
            version="2.0.0",
            model="gpt-4",
            tools=("tool_a", "tool_b"),
            trust_tier="t2",
            priority_tier="P1",
            max_tool_rounds=5,
            memory_config={"k": "v"},
        ),
        "the soul",
        "the rules",
    )

    detail = await store.get("detailed-agent")

    assert detail == {
        "name": "detailed-agent",
        "description": "desc",
        "version": "2.0.0",
        "reasoning_strategy": "direct",
        "model": "gpt-4",
        "tools": ["tool_a", "tool_b"],
        "trust_tier": "t2",
        "priority_tier": "P1",
        "max_tool_rounds": 5,
        "soul_prompt_preview": "the soul",
        "rules_preview": "the rules",
        "memory_config": {"k": "v"},
    }


@pytest.mark.asyncio
async def test_get_previews_are_truncated_to_200_chars() -> None:
    store = _store()
    long_soul = "s" * 250
    long_rules = "r" * 250
    await store.create(_identity("long-agent"), long_soul, long_rules)

    detail = await store.get("long-agent")

    assert detail is not None
    assert len(detail["soul_prompt_preview"]) == 200
    assert detail["soul_prompt_preview"] == "s" * 200
    assert len(detail["rules_preview"]) == 200
    assert detail["rules_preview"] == "r" * 200


@pytest.mark.asyncio
async def test_get_tools_returned_as_list_not_tuple() -> None:
    store = _store()
    await store.create(_identity("tooled", tools=("x", "y")), "soul")
    detail = await store.get("tooled")
    assert detail is not None
    assert isinstance(detail["tools"], list)
    assert detail["tools"] == ["x", "y"]


# ─── list_all() ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_all_empty_store() -> None:
    store = _store(with_seed_agent=False)
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_list_all_sorted_by_name() -> None:
    store = _store()
    await store.create(_identity("zebra"), "soul")
    await store.create(_identity("alpha"), "soul")

    results = await store.list_all()

    names = [r["name"] for r in results]
    assert names == ["alpha", "base-agent", "zebra"]


# ─── update() ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_raises_for_missing_agent() -> None:
    store = _store()
    with pytest.raises(ValueError, match="not found"):
        await store.update("missing", {"rules": "x"})


@pytest.mark.asyncio
async def test_update_soul_prompt_calls_prompt_manager_and_updates_local_cache() -> None:
    pm = _StubPromptManager()
    store = _store(prompt_manager=pm)

    result = await store.update("base-agent", {"soul_prompt": "new soul"})

    assert pm.upserts == [("agent.base-agent.soul", "new soul", "production")]
    assert store._souls["base-agent"] == "new soul"
    assert result["soul_prompt_preview"] == "new soul"


@pytest.mark.asyncio
async def test_update_soul_prompt_skipped_without_prompt_manager() -> None:
    store = _store(prompt_manager=None)
    # No prompt_manager configured -> branch is a no-op, but local cache is
    # also untouched since the assignment is nested inside the `if` guard.
    result = await store.update("base-agent", {"soul_prompt": "new soul"})

    assert "base-agent" not in store._souls
    assert result["soul_prompt_preview"] == ""


@pytest.mark.asyncio
async def test_update_rules_sets_local_cache() -> None:
    store = _store()
    result = await store.update("base-agent", {"rules": "new rules"})
    assert store._rules["base-agent"] == "new rules"
    assert result["rules_preview"] == "new rules"


@pytest.mark.asyncio
async def test_update_with_empty_updates_dict_is_a_noop_get() -> None:
    store = _store()
    result = await store.update("base-agent", {})
    assert result["name"] == "base-agent"


# ─── delete() ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_returns_false_for_missing_agent() -> None:
    store = _store()
    assert await store.delete("missing") is False


@pytest.mark.asyncio
async def test_delete_removes_agent_and_caches() -> None:
    store = _store()
    await store.create(_identity("temp"), "soul", "rules")

    assert await store.delete("temp") is True
    assert "temp" not in store._agents
    assert "temp" not in store._souls
    assert "temp" not in store._rules


@pytest.mark.asyncio
async def test_delete_missing_caches_does_not_raise() -> None:
    store = _store()
    # base-agent was seeded directly into _agents, bypassing create(), so it
    # has no entries in _souls/_rules. pop(..., None) must tolerate that.
    assert await store.delete("base-agent") is True


# ─── export_gitagent() ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_gitagent_raises_for_missing_agent() -> None:
    store = _store()
    with pytest.raises(ValueError, match="not found"):
        await store.export_gitagent("missing")


@pytest.mark.asyncio
async def test_export_gitagent_produces_expected_zip_layout() -> None:
    store = _store()
    await store.create(
        _identity(
            "exported",
            version="3.1.4",
            description="an agent",
            model="gpt-5",
            tools=("a", "b"),
            trust_tier="t1",
            priority_tier="P0",
            max_tool_rounds=7,
            memory_config={"x": 1},
        ),
        "soul text",
        "rules text",
    )

    data = await store.export_gitagent("exported")
    zf = zipfile.ZipFile(io.BytesIO(data))

    names = set(zf.namelist())
    assert names == {"exported/agent.yaml", "exported/SOUL.md", "exported/RULES.md"}

    manifest = yaml.safe_load(zf.read("exported/agent.yaml"))
    assert manifest == {
        "spec_version": "0.1.0",
        "name": "exported",
        "version": "3.1.4",
        "description": "an agent",
        "reasoning": {"strategy": "direct", "max_rounds": 7},
        "model": "gpt-5",
        "tools": ["a", "b"],
        "trust_tier": "t1",
        "priority_tier": "P0",
        "memory": {"x": 1},
    }
    assert zf.read("exported/SOUL.md").decode() == "soul text"
    assert zf.read("exported/RULES.md").decode() == "rules text"


@pytest.mark.asyncio
async def test_export_gitagent_omits_rules_file_when_rules_empty() -> None:
    store = _store()
    await store.create(_identity("norules"), "soul text")

    data = await store.export_gitagent("norules")
    zf = zipfile.ZipFile(io.BytesIO(data))

    assert "norules/RULES.md" not in zf.namelist()


@pytest.mark.asyncio
async def test_export_gitagent_falls_back_to_prompt_manager_when_soul_cache_empty() -> None:
    pm = _StubPromptManager()
    store = InMemoryAgentStore({"base-agent": _agent()}, prompt_manager=pm)
    # No call to create() -> _souls has no entry for "base-agent".

    data = await store.export_gitagent("base-agent")
    zf = zipfile.ZipFile(io.BytesIO(data))

    assert zf.read("base-agent/SOUL.md").decode() == pm.stored_soul
    assert pm.get_with_config_calls == [("agent.base-agent.soul", "production")]


# ─── import_gitagent() ───────────────────────────────────────────────────────


def _make_gitagent_zip(
    *,
    agent_dir: str = "myagent",
    manifest: dict | None = None,
    soul: str | None = "soul content",
    rules: str | None = None,
    extra_entries: dict[str, str] | None = None,
) -> bytes:
    if manifest is None:
        manifest = {"name": "myagent", "version": "1.0.0"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{agent_dir}/agent.yaml", yaml.dump(manifest))
        if soul is not None:
            zf.writestr(f"{agent_dir}/SOUL.md", soul)
        if rules is not None:
            zf.writestr(f"{agent_dir}/RULES.md", rules)
        for path, content in (extra_entries or {}).items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_gitagent_raises_when_no_agent_yaml() -> None:
    store = _store()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("myagent/SOUL.md", "soul")
    with pytest.raises(ValueError, match=re.escape("No agent.yaml found")):
        await store.import_gitagent(buf.getvalue())


@pytest.mark.asyncio
async def test_import_gitagent_rejects_path_traversal_entries() -> None:
    store = _store()
    zip_bytes = _make_gitagent_zip(extra_entries={"../evil.txt": "pwned"})
    with pytest.raises(ValueError, match="path traversal"):
        await store.import_gitagent(zip_bytes)


@pytest.mark.asyncio
async def test_import_gitagent_rejects_absolute_path_entries() -> None:
    store = _store()
    zip_bytes = _make_gitagent_zip(extra_entries={"/etc/evil.txt": "pwned"})
    with pytest.raises(ValueError, match="path traversal"):
        await store.import_gitagent(zip_bytes)


@pytest.mark.asyncio
async def test_import_gitagent_rejects_non_dict_manifest() -> None:
    store = _store()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("myagent/agent.yaml", yaml.dump(["not", "a", "dict"]))
    with pytest.raises(ValueError, match=re.escape("Invalid agent.yaml format")):
        await store.import_gitagent(buf.getvalue())


@pytest.mark.asyncio
async def test_import_gitagent_rejects_manifest_missing_name() -> None:
    store = _store()
    zip_bytes = _make_gitagent_zip(manifest={"version": "1.0.0"})
    with pytest.raises(ValueError, match="missing 'name' field"):
        await store.import_gitagent(zip_bytes)


@pytest.mark.asyncio
async def test_import_gitagent_creates_agent_with_manifest_fields() -> None:
    store = _store()
    manifest = {
        "name": "imported-agent",
        "version": "9.9.9",
        "description": "from zip",
        "model": "claude-x",
        "tools": ["t1", "t2"],
        "reasoning": {"strategy": "direct", "max_rounds": 11},
        "memory": {"enabled": True},
    }
    zip_bytes = _make_gitagent_zip(
        agent_dir="imported-agent", manifest=manifest, soul="the soul", rules="the rules"
    )

    name = await store.import_gitagent(zip_bytes)

    assert name == "imported-agent"
    created = store._agents["imported-agent"]
    identity = created.identity
    assert identity.version == "9.9.9"
    assert identity.description == "from zip"
    assert identity.model == "claude-x"
    assert identity.tools == ("t1", "t2")
    assert identity.max_tool_rounds == 11
    assert identity.reasoning_strategy == "direct"
    assert identity.memory_config == {"enabled": True}
    # Imported agents are always pinned to t4 regardless of manifest content.
    assert identity.trust_tier == "t4"
    assert identity.soul_prompt_name == "agent.imported-agent.soul"
    assert store._souls["imported-agent"] == "the soul"
    assert store._rules["imported-agent"] == "the rules"


@pytest.mark.asyncio
async def test_import_gitagent_defaults_when_manifest_fields_missing() -> None:
    store = _store()
    zip_bytes = _make_gitagent_zip(manifest={"name": "minimal"}, soul=None, rules=None)

    name = await store.import_gitagent(zip_bytes)

    created = store._agents["minimal"]
    identity = created.identity
    assert identity.version == "1.0.0"
    assert identity.description == ""
    assert identity.model == "auto"
    assert identity.tools == ()
    assert identity.max_tool_rounds == 3
    assert identity.reasoning_strategy == "direct"
    assert identity.memory_config == {}
    assert store._souls["minimal"] == ""
    assert store._rules["minimal"] == ""
    assert name == "minimal"


@pytest.mark.asyncio
async def test_import_gitagent_ignores_missing_soul_and_rules_files() -> None:
    store = _store()
    zip_bytes = _make_gitagent_zip(soul=None, rules=None, manifest={"name": "bare"})
    name = await store.import_gitagent(zip_bytes)
    assert name == "bare"
    assert store._souls["bare"] == ""
    assert store._rules["bare"] == ""
