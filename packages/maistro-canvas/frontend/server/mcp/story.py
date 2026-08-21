from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Literal

import httpx

from .character import POSES, CharacterFeatures

logger = logging.getLogger(__name__)

LITELLM_URL = "http://localhost:4000"
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")
STORY_MODEL = "google-gemini-2.5-flash"

AgeGroup = Literal["toddler", "early_reader", "reader"]


def _age_to_group(age: int) -> AgeGroup:
    if age <= 4:
        return "toddler"
    if age <= 7:
        return "early_reader"
    return "reader"


def _words_per_page(age_group: AgeGroup) -> tuple[int, int]:
    if age_group == "toddler":
        return (20, 60)
    if age_group == "early_reader":
        return (50, 100)
    return (100, 150)


@dataclass(frozen=True)
class StoryPage:
    page_number: int
    scene_type: str
    text: str
    illustration_prompt: str
    character_pose: str
    mood: str
    setting: str


@dataclass
class Story:
    title: str
    subtitle: str
    child_name: str
    age_group: AgeGroup
    pages: list[StoryPage] = field(default_factory=list)
    theme: str = ""
    dedication: str = ""

    @property
    def story_pages(self) -> list[StoryPage]:
        return [p for p in self.pages if p.page_number >= 3]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _system_prompt(age_group: AgeGroup, word_range: tuple[int, int]) -> str:
    return (
        "You are a children's book author writing a personalized picture book where "
        "the reader's child is the main character. You write age-appropriate, engaging, "
        "original stories with vivid imagery.\n\n"
        f"Target age group: {age_group}\n"
        f"Words per story page: {word_range[0]}-{word_range[1]}\n\n"
        "You MUST return ONLY valid JSON (no markdown fences, no extra text). "
        "The JSON structure:\n"
        '{"title":"string","subtitle":"string","dedication":"string",'
        '"theme":"string","pages":[{'
        '"page_number":int,"scene_type":"title|copyright|story_beat|action_beat|'
        'emotional_beat|ending","text":"string","illustration_prompt":"string",'
        '"character_pose":"one of the allowed poses","mood":"string","setting":"string"}]}\n\n'
        "STORY STRUCTURE (32 pages total):\n"
        "- Page 1: title page (scene_type='title', text is the book title and child name)\n"
        "- Page 2: copyright/dedication "
        "(scene_type='copyright', text has copyright and dedication)\n"
        "- Pages 3-8: Introduction and setup (establish world, character, normal life)\n"
        "- Pages 9-14: Rising action (adventure begins, challenges appear)\n"
        "- Pages 15-20: Middle adventure (exciting events, character grows)\n"
        "- Pages 21-26: Climax and resolution\n"
        "- Pages 27-28: Winding down and happy ending (scene_type='ending')\n"
        "- Pages 29-32: Back matter (final spread, end papers)\n\n"
        "POSE NAMES (use EXACTLY one of these for character_pose):\n" + ", ".join(POSES) + "\n\n"
        "RULES:\n"
        "- The child's name appears in the story text\n"
        "- Every story page has an illustration_prompt describing the scene\n"
        "- illustration_prompt should describe the setting, action, mood, and lighting\n"
        "- character_pose should match the action described\n"
        "- No copyrighted characters or plots\n"
        "- Positive, empowering themes\n"
        "- Age-appropriate vocabulary\n"
        "- Each page should advance the story\n"
        "- Vary the moods: warm, exciting, dreamy, playful, calm\n"
    )


def generate_story(
    child_name: str,
    child_age: int,
    features: CharacterFeatures,
    interests: list[str] | None = None,
    theme_hint: str = "",
    model: str = STORY_MODEL,
) -> Story:
    age_group = _age_to_group(child_age)
    word_range = _words_per_page(age_group)

    interests_text = ", ".join(interests) if interests else "a surprise adventure"
    theme_text = theme_hint or "discovery and imagination"

    user_prompt = (
        f"Write a 32-page personalized picture book for {child_name} (age {child_age}).\n"
        f"Character appearance: {features.hair} hair, {features.skin_tone} skin, "
        f"{features.eye_color} eyes, {features.face_shape} face. "
        f"{', '.join(features.signature_features)}.\n"
        f"Interests/themes to incorporate: {interests_text}\n"
        f"Overall theme: {theme_text}\n"
        f"Make the story feel personal — {child_name} should be the hero who solves problems "
        f"through creativity, kindness, or courage.\n"
    )

    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _system_prompt(age_group, word_range)},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 8000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(text)
    pages = []
    for p in parsed.get("pages", []):
        pose = p.get("character_pose", "front_standing")
        if pose not in POSES:
            pose = "front_standing"
        pages.append(
            StoryPage(
                page_number=p["page_number"],
                scene_type=p.get("scene_type", "story_beat"),
                text=p.get("text", ""),
                illustration_prompt=p.get("illustration_prompt", ""),
                character_pose=pose,
                mood=p.get("mood", "warm"),
                setting=p.get("setting", ""),
            )
        )

    while len(pages) < 32:
        pages.append(
            StoryPage(
                page_number=len(pages) + 1,
                scene_type="story_beat",
                text="",
                illustration_prompt="A gentle scene with soft colors",
                character_pose="front_standing",
                mood="calm",
                setting="peaceful landscape",
            )
        )

    pages = pages[:32]

    return Story(
        title=parsed.get("title", f"{child_name}'s Adventure"),
        subtitle=parsed.get("subtitle", "A personalized story"),
        child_name=child_name,
        age_group=age_group,
        pages=pages,
        theme=parsed.get("theme", theme_text),
        dedication=parsed.get("dedication", f"For {child_name}, with love"),
    )


@dataclass(frozen=True)
class StyleContract:
    art_style: str = "warm watercolor children's book illustration"
    color_palette: tuple[str, ...] = ("#F4E8C1", "#D4A574", "#8FB996", "#6B8F71", "#E8D5B7")
    lighting: str = "soft warm light"
    mood: str = "whimsical wonder"
    recurring_elements: tuple[str, ...] = ()
    negative_prompts: str = "no text in images, no watermarks, no photorealism, no scary imagery"


VALID_SCENE_TYPES = (
    "title_page",
    "dedication",
    "story_beat",
    "emotional_beat",
    "action_beat",
    "ending",
)

VALID_COMPOSITIONS = (
    "center_focus",
    "left_focus",
    "right_focus",
    "wide_establishing",
    "close_up",
    "bottom_center",
    "top_text_wide",
)


@dataclass(frozen=True)
class PropSpec:
    name: str
    description: str
    scale: str = "handheld"
    placement: str = "right"


@dataclass(frozen=True)
class ScenePlan:
    id: int
    title: str
    scene_type: str
    page_text: str
    description: str
    pose: str = "standing_front"
    composition: str = "center_focus"
    character_action: str = ""
    props: tuple[PropSpec, ...] = ()


@dataclass
class BookDecomposition:
    title: str
    dedication: str
    style_contract: StyleContract
    scenes: list[ScenePlan] = field(default_factory=list)
    page_dims: tuple[int, int] = (1536, 1024)
    orientation: str = "landscape (wide)"


def _extract_json(text: str) -> dict:
    code_block = __import__("re").search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except json.JSONDecodeError:
            pass

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidate = text[first : last + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            stack: list[str] = []
            for ch in candidate:
                if ch in "{[":
                    stack.append(ch)
                elif (ch == "}" and stack and stack[-1] == "{") or (
                    ch == "]" and stack and stack[-1] == "["
                ):
                    stack.pop()
            for s in reversed(stack):
                candidate += "}" if s == "{" else "]"
            candidate = __import__("re").sub(r",\s*\{[^}]*$", "", candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    raise ValueError("AI did not return valid JSON. Response: " + text[:200])


def decompose_book(
    child_name: str,
    child_age: int,
    features: CharacterFeatures,
    page_count: int = 12,
    orientation: str = "landscape (wide)",
    setting: str = "",
    theme: str = "",
    side_characters: str = "",
    title: str = "",
    dedication: str = "",
    model: str = STORY_MODEL,
) -> BookDecomposition:
    if "portrait" in orientation:
        dims = (1024, 1536)
    elif "square" in orientation:
        dims = (1024, 1024)
    else:
        dims = (1536, 1024)

    appearance = ", ".join(
        filter(
            None,
            [
                features.hair,
                features.skin_tone,
                features.eye_color,
                features.face_shape,
                features.build,
            ],
        )
    )

    system_msg = (
        "You are a children's book storyboarding engine. You output STRUCTURED scene "
        "definitions — not prompts. A rendering pipeline consumes your output "
        "deterministically.\n\n"
        "Return ONLY valid JSON:\n"
        '{"title":"book title","dedication":"dedication text or empty string",'
        '"style_contract":{"art_style":"exact art style name",'
        '"color_palette":["#hex","#hex","#hex","#hex","#hex"],'
        '"lighting":"lighting description","mood":"mood description",'
        '"recurring_elements":["elements across scenes"],'
        '"negative_prompts":"no text, no watermarks, no scary imagery"},'
        '"scenes":[{"id":1,"title":"Scene title","scene_type":"title_page",'
        '"page_text":"","description":"visual description of setting",'
        '"pose":"standing_front","composition":"center_focus",'
        '"character_action":"what the character is doing",'
        '"props":[{"name":"prop name","description":"visual description",'
        '"scale":"handheld|environment","placement":"right"}]}]}\n\n'
        f"VALID scene types: {', '.join(VALID_SCENE_TYPES)}\n"
        f"VALID poses: {', '.join(POSES)}\n"
        f"VALID compositions: {', '.join(VALID_COMPOSITIONS)}\n\n"
        f"RULES:\n"
        f"- Exactly {page_count} scenes\n"
        f"- Scene 1: scene_type=title_page, no page_text, no character pose needed\n"
        f"- Scene 2 (if dedication): scene_type=dedication, no page_text, no character\n"
        f"- Last scene: scene_type=ending\n"
        f"- Vary poses and compositions across scenes\n"
        f"- Page text: age-appropriate ({child_age}), 1-3 short sentences\n"
        f"- Props: 0-2 per scene, scale 'handheld' or 'environment'\n"
        f"- 'handheld' props are GENERATED AS PART OF the character image\n"
        f"- 'environment' props are SEPARATE layers\n"
        f"- character_action describes what the character does WITH any handheld props\n"
        f"- description: describe SETTING/ENVIRONMENT only\n"
        f"- Do NOT include 'prompt' fields — rendering pipeline builds prompts"
    )

    user_msg = (
        f"Create a {page_count}-scene children's book storyboard.\n\n"
        f"Main character: {child_name} ({child_age}, they/them)\n"
        f"Appearance: {appearance or 'generic child character'}\n"
        f"Story: A personalized adventure for {child_name}\n"
        f"Setting: {setting or 'not specified'}\n"
        f"Theme: {theme or 'discovery and imagination'}\n"
        f"{f'Side characters: {side_characters}' if side_characters else ''}\n"
        f"{f'Title: {title}' if title else 'Generate an appropriate title'}\n"
        f"{f'Dedication: {dedication}' if dedication else ''}\n\n"
        f"Remember: output structured scene data with type, pose, composition, props."
    )

    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.7,
            "max_tokens": 16000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()

    raw = _extract_json(text)

    sc_data = raw.get("style_contract", {})
    style_contract = StyleContract(
        art_style=sc_data.get("art_style", "warm watercolor children's book illustration"),
        color_palette=tuple(sc_data.get("color_palette", [])),
        lighting=sc_data.get("lighting", "soft warm light"),
        mood=sc_data.get("mood", "whimsical wonder"),
        recurring_elements=tuple(sc_data.get("recurring_elements", [])),
        negative_prompts=sc_data.get("negative_prompts", ""),
    )

    scenes: list[ScenePlan] = []
    for s in raw.get("scenes", []):
        pose = s.get("pose", "standing_front")
        if pose not in POSES:
            pose = "standing_front"
        comp = s.get("composition", "center_focus")
        if comp not in VALID_COMPOSITIONS:
            comp = "center_focus"
        props: list[PropSpec] = []
        for p in s.get("props", []):
            props.append(
                PropSpec(
                    name=p.get("name", ""),
                    description=p.get("description", ""),
                    scale=p.get("scale", "handheld"),
                    placement=p.get("placement", "right"),
                )
            )
        scenes.append(
            ScenePlan(
                id=s.get("id", len(scenes) + 1),
                title=s.get("title", f"Scene {len(scenes) + 1}"),
                scene_type=s.get("scene_type", "story_beat"),
                page_text=s.get("page_text", ""),
                description=s.get("description", ""),
                pose=pose,
                composition=comp,
                character_action=s.get("character_action", ""),
                props=tuple(props),
            )
        )

    return BookDecomposition(
        title=raw.get("title", f"{child_name}'s Adventure"),
        dedication=raw.get("dedication", ""),
        style_contract=style_contract,
        scenes=scenes,
        page_dims=dims,
        orientation=orientation,
    )


def validate_story(story: Story, child_age: int) -> list[str]:
    issues: list[str] = []
    age_group = _age_to_group(child_age)
    word_range = _words_per_page(age_group)

    if story.page_count != 32:
        issues.append(f"Expected 32 pages, got {story.page_count}")

    if story.pages and story.pages[0].scene_type != "title":
        issues.append("Page 1 should be title page")

    if len(story.pages) > 1 and story.pages[1].scene_type != "copyright":
        issues.append("Page 2 should be copyright page")

    for _i, page in enumerate(story.story_pages):
        word_count = len(page.text.split())
        if word_count > 0 and (word_count < word_range[0] * 0.5 or word_count > word_range[1] * 2):
            issues.append(
                f"Page {page.page_number}: {word_count} words "
                f"(expected {word_range[0]}-{word_range[1]})"
            )

        if page.character_pose not in POSES:
            issues.append(f"Page {page.page_number}: invalid pose '{page.character_pose}'")

    if (
        story.child_name
        and story.child_name.lower() not in story.title.lower()
        and not any(story.child_name.lower() in p.text.lower() for p in story.story_pages[:5])
    ):
        issues.append("Child name should appear in early story pages")

    return issues
