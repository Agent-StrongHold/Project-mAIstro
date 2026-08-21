from __future__ import annotations

import json
import logging
from pathlib import Path

from PIL import Image

from ..character import CharacterFeatures
from ..story import Story, StoryPage

logger = logging.getLogger(__name__)

GOLDEN_DIR = Path(__file__).parent


def _golden_path(name: str) -> Path:
    return GOLDEN_DIR / name


def has_golden(stage: str) -> bool:
    mapping = {
        "features": "features.json",
        "story": "story.json",
        "reference": "reference.png",
    }
    if stage not in mapping:
        return False
    return _golden_path(mapping[stage]).exists()


def load_golden_features() -> CharacterFeatures:
    path = _golden_path("features.json")
    if not path.exists():
        raise FileNotFoundError(f"Golden features not found: {path}")
    data = json.loads(path.read_text())
    return CharacterFeatures(
        hair=data["hair"],
        skin_tone=data["skin_tone"],
        eye_color=data["eye_color"],
        face_shape=data["face_shape"],
        age_style=data["age_style"],
        body_type=data["body_type"],
        signature_features=tuple(data.get("signature_features", [])),
        typical_expression=data.get("typical_expression", "bright smile"),
    )


def save_golden_features(features: CharacterFeatures) -> None:
    path = _golden_path("features.json")
    data = {
        "hair": features.hair,
        "skin_tone": features.skin_tone,
        "eye_color": features.eye_color,
        "face_shape": features.face_shape,
        "age_style": features.age_style,
        "body_type": features.body_type,
        "signature_features": list(features.signature_features),
        "typical_expression": features.typical_expression,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("Saved golden features to %s", path)


def load_golden_story() -> Story:
    path = _golden_path("story.json")
    if not path.exists():
        raise FileNotFoundError(f"Golden story not found: {path}")
    data = json.loads(path.read_text())
    pages = []
    for p in data.get("pages", []):
        pages.append(
            StoryPage(
                page_number=p["page_number"],
                scene_type=p.get("scene_type", "story_beat"),
                text=p.get("text", ""),
                illustration_prompt=p.get("illustration_prompt", ""),
                character_pose=p.get("character_pose", "front_standing"),
                mood=p.get("mood", "warm"),
                setting=p.get("setting", ""),
            )
        )
    return Story(
        title=data.get("title", "Golden Story"),
        subtitle=data.get("subtitle", ""),
        child_name=data.get("child_name", "Emma"),
        age_group=data.get("age_group", "early_reader"),
        pages=pages,
        theme=data.get("theme", ""),
        dedication=data.get("dedication", ""),
    )


def save_golden_story(story: Story) -> None:
    path = _golden_path("story.json")
    data = {
        "title": story.title,
        "subtitle": story.subtitle,
        "child_name": story.child_name,
        "age_group": story.age_group,
        "theme": story.theme,
        "dedication": story.dedication,
        "pages": [
            {
                "page_number": p.page_number,
                "scene_type": p.scene_type,
                "text": p.text,
                "illustration_prompt": p.illustration_prompt,
                "character_pose": p.character_pose,
                "mood": p.mood,
                "setting": p.setting,
            }
            for p in story.pages
        ],
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("Saved golden story to %s (%d pages)", path, len(story.pages))


def load_golden_reference() -> Image.Image:
    path = _golden_path("reference.png")
    if not path.exists():
        raise FileNotFoundError(f"Golden reference not found: {path}")
    return Image.open(path)


def save_golden_reference(img: Image.Image) -> None:
    path = _golden_path("reference.png")
    img.save(path, format="PNG")
    logger.info("Saved golden reference to %s (%dx%d)", path, img.width, img.height)
