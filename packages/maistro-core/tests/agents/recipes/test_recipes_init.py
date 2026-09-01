"""Tests for maistro.agents.recipes.RecipeRegistry / AgentRecipe."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from maistro.agents.recipes import AgentRecipe, RecipeRegistry, agent_recipe_to_node_template
from maistro.agents.spec.agent_spec import AgentRole


def _make_recipe(name: str = "scout") -> AgentRecipe:
    return AgentRecipe(name=name, role=AgentRole.SCOUT, prompt_name="agent.scout.prompt")


def _write_recipe(path: Path, recipe: AgentRecipe) -> None:
    data = recipe.model_dump(exclude_defaults=True)
    data["role"] = recipe.role.value
    path.write_text(yaml.dump(data), encoding="utf-8")


class TestGet:
    def test_returns_cached_recipe_without_disk_access(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path)
        recipe = _make_recipe()
        registry.register(recipe)

        assert registry.get("scout") is recipe

    def test_missing_dir_returns_none(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path / "does-not-exist")
        assert registry.get("scout") is None

    def test_loads_from_disk_by_exact_filename(self, tmp_path: Path) -> None:
        recipe = _make_recipe("agent.scout")
        _write_recipe(tmp_path / "agent_scout.yaml", recipe)

        registry = RecipeRegistry(recipes_dir=tmp_path)
        loaded = registry.get("agent.scout")
        assert loaded is not None
        assert loaded.name == "agent.scout"

    def test_falls_back_to_glob_scan_when_filename_does_not_match(self, tmp_path: Path) -> None:
        recipe = _make_recipe("scout")
        _write_recipe(tmp_path / "weirdly_named.yaml", recipe)

        registry = RecipeRegistry(recipes_dir=tmp_path)
        loaded = registry.get("scout")
        assert loaded is not None
        assert loaded.name == "scout"

    def test_no_matching_file_returns_none(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "other.yaml", _make_recipe("scout"))

        registry = RecipeRegistry(recipes_dir=tmp_path)
        assert registry.get("nobody") is None


class TestNodeTemplateProjection:
    def test_registry_projects_recipe_to_workspace_owned_node_template(self) -> None:
        recipe = AgentRecipe(
            name="scout",
            role=AgentRole.SCOUT,
            prompt_name="agent.scout.prompt",
            prompt_variants=["production", "experimental"],
            tools=["web_search"],
            min_tier=2,
            max_tier=4,
            temperature=0.2,
        )
        registry = RecipeRegistry()
        registry.register(recipe)

        template = registry.get_node_template(
            "scout",
            workspace_id="workspace-1",
            node_type="agent.runtime_selected_by_caller",
            parameters={"adapter": "chosen-elsewhere"},
        )

        assert template is not None
        assert template.workspace_id == "workspace-1"
        assert template.name == "scout"
        assert template.node_type == "agent.runtime_selected_by_caller"
        assert template.parameters == {"adapter": "chosen-elsewhere"}
        assert template.binding_ids == []
        assert template.permissions == {}
        assert template.policies == {}
        source = template.metadata["source_import_provenance"]
        assert source["source_format"] == "agent_recipe"
        assert source["source_definition"] == "AgentRecipe"
        assert source["source_name"] == "scout"
        assert len(source["source_hash"]) == 64
        snapshot = template.metadata["legacy_recipe_snapshot"]
        assert snapshot["prompt_name"] == "agent.scout.prompt"
        assert snapshot["prompt_variants"] == ["production", "experimental"]
        assert snapshot["tools"] == ["web_search"]
        assert snapshot["temperature"] == 0.2

    def test_recipe_tool_names_do_not_become_binding_ids(self) -> None:
        recipe = AgentRecipe(
            name="scout",
            role=AgentRole.SCOUT,
            prompt_name="agent.scout.prompt",
            tools=["web_search", "document_reader"],
        )

        template = agent_recipe_to_node_template(
            recipe,
            workspace_id="workspace-1",
            node_type="agent.explicit",
        )

        assert template.binding_ids == []
        assert template.metadata["legacy_recipe_snapshot"]["tools"] == [
            "web_search",
            "document_reader",
        ]

    def test_projected_recipe_instantiates_with_canonical_template_provenance(self) -> None:
        template = agent_recipe_to_node_template(
            _make_recipe(),
            workspace_id="workspace-1",
            node_type="agent.explicit",
        )

        node = template.instantiate()

        assert node.source_template is not None
        assert node.source_template.template_id == template.template_id
        assert node.source_template.template_version == template.version
        assert node.source_template.template_hash == template.content_hash
        assert node.metadata["source_import_provenance"]["source_format"] == "agent_recipe"

    @pytest.mark.parametrize(
        ("workspace_id", "node_type", "message"),
        [(" ", "agent.explicit", "workspace_id"), ("workspace-1", " ", "node_type")],
    )
    def test_projection_requires_explicit_scope_and_runtime_kind(
        self, workspace_id: str, node_type: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            agent_recipe_to_node_template(
                _make_recipe(),
                workspace_id=workspace_id,
                node_type=node_type,
            )


class TestListRecipes:
    def test_missing_dir_returns_empty_list(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path / "nope")
        assert registry.list_recipes() == []

    def test_loads_all_yaml_files_in_dir(self, tmp_path: Path) -> None:
        _write_recipe(tmp_path / "scout.yaml", _make_recipe("scout"))
        _write_recipe(tmp_path / "coder.yaml", _make_recipe("coder"))

        registry = RecipeRegistry(recipes_dir=tmp_path)
        names = sorted(r.name for r in registry.list_recipes())
        assert names == ["coder", "scout"]


class TestRegister:
    def test_register_overwrites_cache_entry(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path)
        first = _make_recipe("scout")
        second = AgentRecipe(name="scout", role=AgentRole.CODER, prompt_name="other")

        registry.register(first)
        registry.register(second)

        assert registry.get("scout") is second


class TestCompatibilityBoundary:
    def test_registry_has_no_durable_write_api(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path)

        assert not hasattr(registry, "save")
        assert list(tmp_path.iterdir()) == []


class TestParseYaml:
    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        registry = RecipeRegistry(recipes_dir=tmp_path)
        assert registry._parse_yaml(path) is None

    def test_non_dict_yaml_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        registry = RecipeRegistry(recipes_dir=tmp_path)
        assert registry._parse_yaml(path) is None

    def test_invalid_schema_logs_warning_and_returns_none(
        self, tmp_path: Path, caplog: object
    ) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("name: incomplete\n", encoding="utf-8")  # missing required fields
        registry = RecipeRegistry(recipes_dir=tmp_path)
        assert registry._parse_yaml(path) is None
