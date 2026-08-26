"""Tests for agent factory: filesystem seeding, manifest parsing, strategy construction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import maistro.agents.factory as factory_mod
from maistro.agents.factory import (
    _build_delegate_strategy,
    _build_identity_from_manifest,
    _build_persist_registry,
    _build_strategy,
    _instantiate,
    _load_preamble,
    _parse_agent_dir,
    _render_preamble,
    _safe_tuple,
    _strict_str_tuple,
    create_agents,
    register_strategy,
)
from maistro.agents.strategies.direct import DirectStrategy
from maistro.types.agent import AgentIdentity
from maistro.types.errors import ConfigError


class _RecordingPromptManager:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, str]] = []

    async def upsert(self, name: str, body: str, label: str = "") -> None:
        self.upserts.append((name, body))


def _write_agent_dir(
    base: Path,
    name: str,
    *,
    manifest_extra: dict[str, Any] | None = None,
    soul: str = "Soul body.",
    rules: str | None = None,
    soul_file: str | None = None,
) -> Path:
    agent_dir = base / name
    agent_dir.mkdir()
    manifest = {"name": name}
    if manifest_extra:
        manifest.update(manifest_extra)
    import yaml

    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(manifest))
    soul_filename = soul_file or "SOUL.md"
    (agent_dir / soul_filename).write_text(soul)
    if rules is not None:
        (agent_dir / "RULES.md").write_text(rules)
    return agent_dir


class TestLoadPreamble:
    def test_returns_contents_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "PREAMBLE.md").write_text("hello {{agent_name}}")
        assert _load_preamble(tmp_path) == "hello {{agent_name}}"

    def test_returns_empty_and_warns_when_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _load_preamble(tmp_path)
        assert result == ""
        assert "No PREAMBLE.md" in caplog.text


class TestRenderPreamble:
    def test_substitutes_defaults(self) -> None:
        out = _render_preamble("{{agent_name}}: {{capabilities}}", {"name": "Scribe"})
        assert out.startswith("Scribe: You are a")

    def test_manifest_description_overrides_default(self) -> None:
        out = _render_preamble(
            "{{agent_description}}", {"name": "X", "description": "a custom desc"}
        )
        assert out == "a custom desc"

    def test_manifest_string_capabilities_override(self) -> None:
        out = _render_preamble("{{capabilities}}", {"name": "X", "capabilities": "  custom caps  "})
        assert out == "custom caps"

    def test_manifest_non_string_capabilities_ignored(self) -> None:
        out = _render_preamble("{{capabilities}}", {"name": "X", "capabilities": 123})
        assert "text-based AI assistant" in out

    def test_unknown_variable_renders_empty(self) -> None:
        assert _render_preamble("{{nonsense}}", {"name": "X"}) == ""


class TestParseAgentDir:
    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "ghost"
        agent_dir.mkdir()
        assert _parse_agent_dir(agent_dir) is None

    def test_invalid_manifest_not_dict_returns_none_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        agent_dir = tmp_path / "bad"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("- just\n- a\n- list\n")
        with caplog.at_level(logging.WARNING):
            assert _parse_agent_dir(agent_dir) is None
        assert "Invalid agent.yaml" in caplog.text

    def test_manifest_missing_name_returns_none(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "noname"
        agent_dir.mkdir()
        (agent_dir / "agent.yaml").write_text("description: x\n")
        assert _parse_agent_dir(agent_dir) is None

    def test_valid_manifest_with_soul_and_rules(self, tmp_path: Path) -> None:
        agent_dir = _write_agent_dir(tmp_path, "scribe", soul="My soul", rules="My rules")
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        manifest, soul, rules = result
        assert manifest["name"] == "scribe"
        assert soul == "My soul"
        assert rules == "My rules"

    def test_missing_soul_file_returns_empty_string(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "nosoul"
        agent_dir.mkdir()
        import yaml

        (agent_dir / "agent.yaml").write_text(yaml.safe_dump({"name": "nosoul"}))
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        _, soul, rules = result
        assert soul == ""
        assert rules == ""

    def test_custom_soul_filename(self, tmp_path: Path) -> None:
        agent_dir = _write_agent_dir(
            tmp_path,
            "custom",
            manifest_extra={"soul": "CUSTOM_SOUL.md"},
            soul="custom body",
            soul_file="CUSTOM_SOUL.md",
        )
        result = _parse_agent_dir(agent_dir)
        assert result is not None
        _, soul, _ = result
        assert soul == "custom body"


class TestSafeTuple:
    def test_none_returns_empty(self) -> None:
        assert _safe_tuple(None) == ()

    def test_empty_string_returns_empty(self) -> None:
        assert _safe_tuple("") == ()

    def test_non_empty_string_returns_single_tuple(self) -> None:
        assert _safe_tuple("solo") == ("solo",)

    def test_list_of_strings(self) -> None:
        assert _safe_tuple(["a", "b"]) == ("a", "b")

    def test_list_of_dicts_extracts_name(self) -> None:
        assert _safe_tuple([{"name": "a"}, {"name": "b"}]) == ("a", "b")

    def test_other_type_returns_empty(self) -> None:
        assert _safe_tuple(42) == ()


class TestStrictStrTuple:
    def test_none_returns_empty(self) -> None:
        assert _strict_str_tuple(None, field="tools", agent_name="x") == ()

    def test_string_wraps_in_tuple(self) -> None:
        assert _strict_str_tuple("solo", field="tools", agent_name="x") == ("solo",)

    def test_list_of_strings(self) -> None:
        assert _strict_str_tuple(["a", "b"], field="tools", agent_name="x") == ("a", "b")

    def test_non_list_non_string_raises(self) -> None:
        with pytest.raises(ConfigError, match="field 'tools' has type int"):
            _strict_str_tuple(42, field="tools", agent_name="x")

    def test_list_with_non_string_entries_raises(self) -> None:
        with pytest.raises(ConfigError, match="non-string entries"):
            _strict_str_tuple(["a", 1], field="tools", agent_name="x")


class TestBuildIdentityFromManifest:
    def test_defaults(self) -> None:
        identity = _build_identity_from_manifest({"name": "scribe"})
        assert identity.name == "scribe"
        assert identity.soul_prompt_name == "agent.scribe.soul"
        assert identity.trust_tier == "t2"
        assert identity.reasoning_strategy == "direct"
        assert identity.max_tool_rounds == 3

    def test_reasoning_overrides(self) -> None:
        manifest = {
            "name": "x",
            "reasoning": {"strategy": "react", "max_rounds": 5, "phases": ["plan", "act"]},
        }
        identity = _build_identity_from_manifest(manifest)
        assert identity.reasoning_strategy == "react"
        assert identity.max_tool_rounds == 5
        assert identity.phases == ("plan", "act")

    def test_max_subtasks_takes_priority_over_max_rounds(self) -> None:
        manifest = {"name": "x", "reasoning": {"max_subtasks": 7, "max_rounds": 5}}
        identity = _build_identity_from_manifest(manifest)
        assert identity.max_tool_rounds == 7

    def test_full_manifest_fields(self) -> None:
        manifest = {
            "name": "x",
            "version": "2.0.0",
            "description": "desc",
            "model": "claude",
            "model_fallbacks": ["gpt"],
            "model_constraints": {"max_tokens": 100},
            "tools": ["read_file"],
            "skills": ["search"],
            "rules": ["no-evil"],
            "sub_agents": ["helper"],
            "trust_tier": "t1",
            "priority_tier": "P0",
            "memory": {"learnings": True},
        }
        identity = _build_identity_from_manifest(manifest)
        assert identity.version == "2.0.0"
        assert identity.model == "claude"
        assert identity.model_fallbacks == ("gpt",)
        assert identity.tools == ("read_file",)
        assert identity.skills == ("search",)
        assert identity.rules == ("no-evil",)
        assert identity.sub_agents == ("helper",)
        assert identity.trust_tier == "t1"
        assert identity.priority_tier == "P0"
        assert identity.memory_config == {"learnings": True}


class TestBuildDelegateStrategy:
    def test_no_sub_agents_raises(self) -> None:
        identity = AgentIdentity(name="x", reasoning_strategy="delegate")
        with pytest.raises(ConfigError, match="non-empty 'sub_agents'"):
            _build_delegate_strategy(identity)

    def test_builds_routing_table_from_available_agents(self) -> None:
        identity = AgentIdentity(
            name="x",
            reasoning_strategy="delegate",
            sub_agents=("artificer", "scribe"),
        )
        strategy = _build_delegate_strategy(identity)
        assert strategy._routing.get("code") == "artificer"
        assert strategy._routing.get("creative") == "scribe"
        assert strategy._default == "artificer"

    def test_uses_default_agent_when_present(self) -> None:
        identity = AgentIdentity(
            name="x",
            reasoning_strategy="delegate",
            sub_agents=("artificer", "default"),
        )
        strategy = _build_delegate_strategy(identity)
        assert strategy._default == "default"


class TestBuildStrategy:
    def test_direct_strategy(self) -> None:
        identity = AgentIdentity(name="x", reasoning_strategy="direct")
        assert isinstance(_build_strategy(identity), DirectStrategy)

    def test_unknown_strategy_falls_back_to_direct(self, caplog: pytest.LogCaptureFixture) -> None:
        identity = AgentIdentity(name="x", reasoning_strategy="nonexistent")
        with caplog.at_level(logging.WARNING):
            strategy = _build_strategy(identity)
        assert isinstance(strategy, DirectStrategy)
        assert "Unknown strategy" in caplog.text

    def test_delegate_strategy_routed(self) -> None:
        identity = AgentIdentity(name="x", reasoning_strategy="delegate", sub_agents=("artificer",))
        strategy = _build_strategy(identity)
        assert strategy._default == "artificer"

    def test_registered_strategy_construction_error_wrapped(self) -> None:
        class _BadStrategy:
            def __init__(self) -> None:
                raise TypeError("boom")

        register_strategy("bad", _BadStrategy)
        identity = AgentIdentity(name="x", reasoning_strategy="bad")
        try:
            with pytest.raises(ConfigError, match="could not be constructed"):
                _build_strategy(identity)
        finally:
            factory_mod._STRATEGY_REGISTRY.pop("bad", None)


class TestRegisterCustomStrategies:
    def test_registers_known_strategies(self) -> None:
        factory_mod._register_custom_strategies()
        assert "react" in factory_mod._STRATEGY_REGISTRY
        assert "delegate" in factory_mod._STRATEGY_REGISTRY

    def test_import_error_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__
        attempted = False

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal attempted
            if name == "maistro.agents.strategies.react":
                attempted = True
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        factory_mod._register_custom_strategies()

        assert attempted is True

    @pytest.mark.parametrize(
        "module_name",
        [
            "maistro.agents.strategies.delegate",
            "maistro.agents.strategies.builders_learning",
            "maistro.agents.strategies.plan_execute",
            "maistro.agents.artificer.strategy",
        ],
    )
    def test_import_error_swallowed_for_each_strategy(
        self, module_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__
        attempted = False

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            nonlocal attempted
            if name == module_name:
                attempted = True
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        factory_mod._register_custom_strategies()

        assert attempted is True


class TestInstantiate:
    def _base_deps(self) -> dict[str, Any]:
        return {
            "llm": object(),
            "context_builder": object(),
            "prompt_manager": object(),
            "warden": object(),
        }

    def test_tool_executor_dropped_when_no_tools_declared(self) -> None:
        identity = AgentIdentity(name="x")
        agent = _instantiate(identity, tool_executor=lambda *_a: None, **self._base_deps())
        assert agent._tool_executor is None

    def test_tool_executor_kept_when_tools_declared(self) -> None:
        identity = AgentIdentity(name="x", tools=("read_file",))
        sentinel_executor = object()
        agent = _instantiate(identity, tool_executor=sentinel_executor, **self._base_deps())
        assert agent._tool_executor is sentinel_executor


class TestBuildPersistRegistry:
    def test_no_engine_returns_none(self) -> None:
        assert _build_persist_registry(None) is None

    def test_construction_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_engine: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr("maistro.persistence.pg_agents.PgAgentRegistry", _raise)
        assert _build_persist_registry(object()) is None

    def test_construction_success_returns_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        monkeypatch.setattr(
            "maistro.persistence.pg_agents.PgAgentRegistry", lambda _engine: sentinel
        )
        assert _build_persist_registry(object()) is sentinel


def _create_agents_kwargs(agents_dir: str | Path, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agents_dir": agents_dir,
        "prompt_manager": _RecordingPromptManager(),
        "llm": None,
        "context_builder": None,
        "warden": None,
        "sentinel": None,
        "learning_store": None,
        "learning_extractor": None,
        "outcome_store": None,
        "session_store": None,
        "quota_tracker": None,
        "tracer": None,
    }
    base.update(overrides)
    return base


class TestCreateAgentsFilesystem:
    async def test_missing_agents_dir_returns_empty_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        kwargs = _create_agents_kwargs(tmp_path / "nope")
        with caplog.at_level(logging.WARNING):
            agents = await create_agents(**kwargs)
        assert agents == {}
        assert "not found" in caplog.text

    async def test_seeds_agents_from_directory(self, tmp_path: Path) -> None:
        _write_agent_dir(tmp_path, "scribe", soul="Scribe soul")
        _write_agent_dir(tmp_path, "ranger", soul="Ranger soul")
        prompt_manager = _RecordingPromptManager()
        kwargs = _create_agents_kwargs(tmp_path, prompt_manager=prompt_manager)

        agents = await create_agents(**kwargs)

        assert set(agents) == {"scribe", "ranger"}
        seeded_names = {name for name, _ in prompt_manager.upserts}
        assert "agent.scribe.soul" in seeded_names
        assert "agent.ranger.soul" in seeded_names

    async def test_non_directory_entries_skipped(self, tmp_path: Path) -> None:
        _write_agent_dir(tmp_path, "scribe")
        (tmp_path / "PREAMBLE.md").write_text("preamble")
        (tmp_path / "loose_file.txt").write_text("ignore me")
        kwargs = _create_agents_kwargs(tmp_path)

        agents = await create_agents(**kwargs)

        assert set(agents) == {"scribe"}

    async def test_dirs_without_manifest_skipped(self, tmp_path: Path) -> None:
        _write_agent_dir(tmp_path, "scribe")
        (tmp_path / "empty_dir").mkdir()
        kwargs = _create_agents_kwargs(tmp_path)

        agents = await create_agents(**kwargs)

        assert set(agents) == {"scribe"}

    async def test_no_agents_found_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        kwargs = _create_agents_kwargs(tmp_path)
        with caplog.at_level(logging.WARNING):
            agents = await create_agents(**kwargs)
        assert agents == {}
        assert "No agents loaded" in caplog.text

    async def test_resolver_can_see_earlier_agents(self, tmp_path: Path) -> None:
        _write_agent_dir(tmp_path, "alpha")
        _write_agent_dir(tmp_path, "beta")
        kwargs = _create_agents_kwargs(tmp_path)

        agents = await create_agents(**kwargs)

        assert agents["alpha"]._agent_resolver("alpha") is agents["alpha"]
        assert agents["beta"]._agent_resolver("alpha") is agents["alpha"]

    async def test_persist_registry_invoked_when_engine_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_agent_dir(tmp_path, "scribe")
        persisted: list[str] = []

        class _FakePersistRegistry:
            async def upsert(self, record: Any) -> None:
                persisted.append(record.name)

        monkeypatch.setattr(
            factory_mod, "_build_persist_registry", lambda _engine: _FakePersistRegistry()
        )

        async def _fake_persist_agent_record(
            persist_registry: Any, identity: Any, full_soul: str, rules: Any
        ) -> None:
            await persist_registry.upsert(identity)

        monkeypatch.setattr(factory_mod, "_persist_agent_record", _fake_persist_agent_record)

        kwargs = _create_agents_kwargs(tmp_path, sa_engine=object())
        await create_agents(**kwargs)

        assert persisted == ["scribe"]

    async def test_db_engine_present_but_empty_falls_back_to_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_agent_dir(tmp_path, "scribe")

        class _EmptyRegistry:
            def __init__(self, _engine: object) -> None:
                pass

            async def count(self) -> int:
                return 0

            # Neither this fake nor `_BrokenRegistry` below had an `upsert`
            # until #297. They did not need one: `_persist_agent_record` raised
            # `ModuleNotFoundError` on its import before it could call it, so an
            # incomplete double was indistinguishable from a complete one.
            async def upsert(self, record: dict[str, Any]) -> None:
                return None

        monkeypatch.setattr("maistro.persistence.pg_agents.PgAgentRegistry", _EmptyRegistry)
        kwargs = _create_agents_kwargs(tmp_path, sa_engine=object())

        agents = await create_agents(**kwargs)

        assert set(agents) == {"scribe"}

    async def test_db_load_failure_falls_back_to_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_agent_dir(tmp_path, "scribe")

        class _BrokenRegistry:
            def __init__(self, _engine: object) -> None:
                pass

            async def count(self) -> int:
                raise RuntimeError("db down")

            async def upsert(self, record: dict[str, Any]) -> None:
                return None

        monkeypatch.setattr("maistro.persistence.pg_agents.PgAgentRegistry", _BrokenRegistry)
        kwargs = _create_agents_kwargs(tmp_path, sa_engine=object())

        agents = await create_agents(**kwargs)

        assert set(agents) == {"scribe"}


class TestPersistAgentRecord:
    """The write-back that never happened (#297).

    What used to be here is worth recording, because it is why this went
    unnoticed for as long as it did. `test_success_path_builds_record_and_upserts`
    **injected `maistro.models` and `maistro.models.agent` into `sys.modules`**
    with a fake `AgentRecord`, so the "success path" it exercised was one that
    could not occur: the module does not exist in this repository, and `maistro`
    is a regular package, so nothing outside `maistro-core` can contribute it.
    The test manufactured the missing module rather than noticing it was missing.

    Its neighbour asserted the failure was swallowed and logged, which was true
    and was the whole defect: an unconditional failure logged as if it were an
    occasional one.
    """

    async def test_the_row_reaches_the_registry(self) -> None:
        upserted: list[dict[str, Any]] = []

        class _Registry:
            async def upsert(self, record: dict[str, Any]) -> None:
                upserted.append(record)

        identity = AgentIdentity(
            name="x",
            tools=("read_file",),
            skills=("search",),
            model_fallbacks=("gpt",),
        )
        await factory_mod._persist_agent_record(_Registry(), identity, "full soul text", "rules")

        assert len(upserted) == 1
        row = upserted[0]
        assert row["name"] == "x"
        assert row["soul"] == "full soul text"
        assert row["rules"] == "rules"
        assert row["tools"] == ["read_file"]
        assert row["provenance"] == "builtin"

    async def test_a_database_error_is_tolerated_and_named(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The agents still load from the filesystem; only the write-back is
        lost. The message says which of those two happened, rather than reusing
        one line for a transient outage and a permanent defect."""

        class _Down:
            async def upsert(self, record: dict[str, Any]) -> None:
                raise SQLAlchemyError("connection refused")

        identity = AgentIdentity(name="x")
        with caplog.at_level(logging.WARNING):
            await factory_mod._persist_agent_record(_Down(), identity, "soul", "")
        assert "was not written back to the registry" in caplog.text

    async def test_a_defect_in_the_row_is_raised_not_logged(self) -> None:
        """The direction that matters. `except Exception` is what let a
        permanent `ModuleNotFoundError` present as a database problem for the
        life of the function; anything that is not the database is a defect in
        this module and has to be loud."""

        class _Registry:
            async def upsert(self, record: dict[str, Any]) -> None:
                raise TypeError("row has a field the registry does not write")

        with pytest.raises(TypeError):
            await factory_mod._persist_agent_record(_Registry(), AgentIdentity(name="x"), "s", "")

    async def test_a_missing_upsert_is_raised_too(self) -> None:
        """A registry double without the method is a defect in the test, not a
        database outage. Both `_EmptyRegistry` and `_BrokenRegistry` above were
        exactly this until #297, and nothing said so."""
        with pytest.raises(AttributeError):
            await factory_mod._persist_agent_record(object(), AgentIdentity(name="x"), "s", "")


class TestTheBuiltinRow:
    """`_builtin_agent_row` is what the registry receives. The two fields the
    dead `AgentRecord(...)` call passed that are not columns are the record of
    why this is asserted rather than assumed."""

    def test_it_carries_no_org_id(self) -> None:
        """`agents` declares no such column. Not a prohibition on org scope --
        that is a soft axis maistro-core does carry (root decision 7, ADR-068,
        #386) -- and `org_id=""` was not a scope value in any case."""
        row = factory_mod._builtin_agent_row(AgentIdentity(name="x"), "soul", "rules")
        assert "org_id" not in row

    def test_it_carries_no_preamble_flag(self) -> None:
        """`preamble=True` was passed to a table with no such column. The
        rendered preamble is part of `soul`, which is where it belongs."""
        row = factory_mod._builtin_agent_row(AgentIdentity(name="x"), "PREAMBLE\nsoul", "rules")
        assert "preamble" not in row
        assert row["soul"] == "PREAMBLE\nsoul"

    def test_the_soul_is_the_rendered_text_not_the_identity_s(self) -> None:
        """`AgentIdentity` has no soul text -- it names a prompt. Passing the
        identity alone would persist an empty soul."""
        row = factory_mod._builtin_agent_row(AgentIdentity(name="x"), "rendered", "rules")
        assert row["soul"] == "rendered"
