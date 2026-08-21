"""Tests for maistro.agents.recipes.RecipeRegistry / AgentRecipe."""

from __future__ import annotations

from pathlib import Path

import yaml

from maistro.agents.recipes import AgentRecipe, RecipeRegistry
from maistro.agents.spec.agent_spec import AgentRole


def _make_recipe(name: str = "scout") -> AgentRecipe:
    return AgentRecipe(name=name, role=AgentRole.SCOUT, prompt_name="agent.scout.prompt")


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
        registry = RecipeRegistry(recipes_dir=tmp_path)
        recipe = _make_recipe("agent.scout")
        registry.save(recipe)

        fresh = RecipeRegistry(recipes_dir=tmp_path)
        loaded = fresh.get("agent.scout")
        assert loaded is not None
        assert loaded.name == "agent.scout"

    def test_falls_back_to_glob_scan_when_filename_does_not_match(self, tmp_path: Path) -> None:
        recipe = _make_recipe("scout")
        data = recipe.model_dump(exclude_defaults=True)
        data["role"] = recipe.role.value
        (tmp_path / "weirdly_named.yaml").write_text(yaml.dump(data), encoding="utf-8")

        registry = RecipeRegistry(recipes_dir=tmp_path)
        loaded = registry.get("scout")
        assert loaded is not None
        assert loaded.name == "scout"

    def test_no_matching_file_returns_none(self, tmp_path: Path) -> None:
        recipe = _make_recipe("scout")
        data = recipe.model_dump(exclude_defaults=True)
        data["role"] = recipe.role.value
        (tmp_path / "other.yaml").write_text(yaml.dump(data), encoding="utf-8")

        registry = RecipeRegistry(recipes_dir=tmp_path)
        assert registry.get("nobody") is None


class TestListRecipes:
    def test_missing_dir_returns_empty_list(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path / "nope")
        assert registry.list_recipes() == []

    def test_loads_all_yaml_files_in_dir(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path)
        registry.save(_make_recipe("scout"))
        registry.save(_make_recipe("coder"))

        fresh = RecipeRegistry(recipes_dir=tmp_path)
        names = sorted(r.name for r in fresh.list_recipes())
        assert names == ["coder", "scout"]


class TestRegister:
    def test_register_overwrites_cache_entry(self, tmp_path: Path) -> None:
        registry = RecipeRegistry(recipes_dir=tmp_path)
        first = _make_recipe("scout")
        second = AgentRecipe(name="scout", role=AgentRole.CODER, prompt_name="other")

        registry.register(first)
        registry.register(second)

        assert registry.get("scout") is second


class TestSave:
    def test_creates_dir_and_writes_yaml_file(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "nested" / "yaml"
        registry = RecipeRegistry(recipes_dir=target_dir)
        recipe = _make_recipe("agent.with.dots")

        path = registry.save(recipe)

        assert path == target_dir / "agent_with_dots.yaml"
        assert path.exists()
        on_disk = yaml.safe_load(path.read_text())
        assert on_disk["role"] == "scout"
        assert registry.get("agent.with.dots") is recipe


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
