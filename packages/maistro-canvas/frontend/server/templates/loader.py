from __future__ import annotations

from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent


def load_template(yaml_path: str | Path) -> dict:
    path = Path(yaml_path)
    if not path.is_absolute():
        path = TEMPLATES_DIR / path
    with open(path) as f:
        return yaml.safe_load(f)


def load_all_templates() -> list[dict]:
    templates = []
    for p in sorted(TEMPLATES_DIR.glob("*.yaml")):
        templates.append(load_template(p))
    return templates


def yaml_to_story_template(data: dict) -> dict:
    fields = {
        "slug": data["slug"],
        "display_title": data["display_title"],
        "title_pattern": data["title_pattern"],
        "age_range": data.get("age_range", []),
        "page_count": data.get("page_count", 32),
        "illustration_style": data.get("illustration_style", "full_color"),
        "compatible_products": data.get("compatible_products", []),
        "required_variables": data.get("required_variables", []),
        "optional_variables": data.get("optional_variables", []),
        "wizard_steps": data.get("wizard_steps", []),
        "story_prompt": data.get("story_prompt", ""),
        "scene_structure": data.get("scene_structure", []),
        "description": data.get("description", ""),
        "themes": data.get("themes", []),
        "etsy_tags": data.get("etsy_tags", []),
        "max_characters": data.get("max_characters", 1),
    }
    return fields
