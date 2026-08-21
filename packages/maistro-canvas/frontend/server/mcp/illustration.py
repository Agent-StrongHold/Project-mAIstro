from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from .character import POSE_BODY, CharacterFeatures, CharacterSheet
from .image_provider import generate_image as _provider_generate

if TYPE_CHECKING:
    from .products import ProductSpec
    from .story import Story, StoryPage

logger = logging.getLogger(__name__)

IMAGE_MODEL = "google-gemini-2.5-flash-image"

PICTURE_BOOK_DPI = 300
COLORING_BOOK_DPI = 300

STYLE_PROMPTS = {
    "warm watercolor": (
        "warm watercolor children's book illustration with soft edges, "
        "visible paper texture, gentle pastel palette, warm tones"
    ),
    "bold_simple": (
        "bold simple children's coloring book line art, thick clean outlines, "
        "large clear shapes, suitable for crayons, ages 3-6, NO shading, NO fill, "
        "pure black outlines on white background"
    ),
    "detailed_ornate": (
        "detailed ornate coloring book line art for older children, fine detailed lines, "
        "intricate patterns and textures, suitable for colored pencils, ages 7+, "
        "NO shading, NO fill, pure black outlines on white background"
    ),
}


@dataclass
class IllustrationResult:
    page_number: int
    image: Image.Image
    image_bytes: bytes
    prompt_used: str
    model_used: str
    is_color: bool = True


def _pil_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _bytes_to_pil(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _target_resolution(product: ProductSpec, is_color: bool = True) -> tuple[int, int]:
    w_px = int(product.trim_width_in * PICTURE_BOOK_DPI)
    h_px = int(product.trim_height_in * PICTURE_BOOK_DPI)
    return (w_px, h_px)


def build_picture_book_prompt(
    page: StoryPage,
    features: CharacterFeatures,
    child_name: str,
    style: str = "warm watercolor",
) -> str:
    style_text = STYLE_PROMPTS.get(style, STYLE_PROMPTS["warm watercolor"])
    pose_desc = POSE_BODY.get(page.character_pose, "standing naturally")

    parts = [
        f"Full-bleed children's book illustration, {style_text}.",
        f"Scene: {page.illustration_prompt}",
        f"The main character ({child_name}) is {pose_desc}.",
        f"Character: {features.hair} hair, {features.skin_tone} skin, "
        f"{features.eye_color} eyes, {features.face_shape} face. "
        f"{', '.join(features.signature_features)}.",
        f"Mood: {page.mood}. Setting: {page.setting}.",
        "Fill the entire frame, no white borders, full bleed.",
        "High detail, professional children's book quality.",
        "NO TEXT, NO WORDS, NO LETTERS in the illustration.",
    ]
    return " ".join(parts)


def build_coloring_page_prompt(
    scene_description: str,
    features: CharacterFeatures,
    child_name: str,
    pose_name: str = "front_standing",
    style: str = "bold_simple",
) -> str:
    style_text = STYLE_PROMPTS.get(style, STYLE_PROMPTS["bold_simple"])
    pose_desc = POSE_BODY.get(pose_name, "standing naturally")

    parts = [
        f"Full-page coloring book illustration, {style_text}.",
        f"Scene: {scene_description}",
        f"The child ({child_name}) is {pose_desc}.",
        f"Character: {features.hair} hair texture, {features.face_shape} face shape. "
        f"{', '.join(features.signature_features)}.",
        "PURE BLACK outlines on PURE WHITE background ONLY.",
        "NO shading, NO gray tones, NO filled areas, NO color.",
        "Clean lines suitable for coloring with crayons or colored pencils.",
        "Fill the entire page, no borders.",
        "NO TEXT, NO WORDS, NO LETTERS.",
    ]
    return " ".join(parts)


def _call_image_generation(
    prompt: str,
    reference_image: Image.Image | None = None,
    model: str = IMAGE_MODEL,
    timeout: int = 180,
) -> Image.Image:
    return _provider_generate(
        prompt=prompt,
        reference_image=reference_image,
        timeout=timeout,
    )


def _post_process_coloring(img: Image.Image) -> Image.Image:
    gray = img.convert("L")
    bw = gray.point([255 if i > 200 else 0 for i in range(256)])
    return bw.convert("RGB")


def generate_picture_book_page(
    page: StoryPage,
    features: CharacterFeatures,
    child_name: str,
    product: ProductSpec,
    character_sheet: CharacterSheet | None = None,
    style: str = "warm watercolor",
) -> IllustrationResult:
    prompt = build_picture_book_prompt(page, features, child_name, style)

    ref_image = None
    if character_sheet and page.character_pose in character_sheet.pose_crops:
        ref_image = character_sheet.pose_crops[page.character_pose]

    logger.info("Generating illustration for page %d: %s", page.page_number, page.scene_type)
    image = _call_image_generation(prompt, reference_image=ref_image)

    target_w, target_h = _target_resolution(product, is_color=True)
    image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)

    return IllustrationResult(
        page_number=page.page_number,
        image=image,
        image_bytes=_pil_to_bytes(image),
        prompt_used=prompt,
        model_used=IMAGE_MODEL,
        is_color=True,
    )


def generate_coloring_page(
    scene_description: str,
    features: CharacterFeatures,
    child_name: str,
    product: ProductSpec,
    pose_name: str = "front_standing",
    style: str = "bold_simple",
    character_sheet: CharacterSheet | None = None,
) -> IllustrationResult:
    prompt = build_coloring_page_prompt(scene_description, features, child_name, pose_name, style)

    ref_image = None
    if character_sheet and pose_name in character_sheet.pose_crops:
        ref_image = character_sheet.pose_crops[pose_name]

    logger.info("Generating coloring page: %s", scene_description[:60])
    image = _call_image_generation(prompt, reference_image=ref_image)

    image = _post_process_coloring(image)

    target_w, target_h = _target_resolution(product, is_color=False)
    image = image.resize((target_w, target_h), Image.Resampling.LANCZOS)

    return IllustrationResult(
        page_number=0,
        image=image,
        image_bytes=_pil_to_bytes(image),
        prompt_used=prompt,
        model_used=IMAGE_MODEL,
        is_color=False,
    )


def generate_picture_book_illustrations(
    story: Story,
    features: CharacterFeatures,
    product: ProductSpec,
    character_sheet: CharacterSheet | None = None,
    style: str = "warm watercolor",
) -> list[IllustrationResult]:
    results: list[IllustrationResult] = []

    for page in story.pages:
        if page.scene_type in ("title", "copyright"):
            title_img = Image.new("RGB", _target_resolution(product, True), (240, 235, 230))
            from PIL import ImageDraw

            draw = ImageDraw.Draw(title_img)
            draw.text(
                (title_img.width // 4, title_img.height // 3),
                f"{story.title}\n\n{story.child_name}",
                fill=(60, 50, 70),
            )
            results.append(
                IllustrationResult(
                    page_number=page.page_number,
                    image=title_img,
                    image_bytes=_pil_to_bytes(title_img),
                    prompt_used="title_page_placeholder",
                    model_used="pillow",
                    is_color=True,
                )
            )
            continue

        result = generate_picture_book_page(
            page, features, story.child_name, product, character_sheet, style
        )
        results.append(result)

    return results


def generate_coloring_book_illustrations(
    features: CharacterFeatures,
    child_name: str,
    product: ProductSpec,
    art_style: str = "bold_simple",
    interests: list[str] | None = None,
    character_sheet: CharacterSheet | None = None,
) -> list[IllustrationResult]:
    scene_descriptions = _generate_coloring_scenes(child_name, interests or [], product.page_count)

    results: list[IllustrationResult] = []
    pose_list = list(POSE_BODY.keys())

    for i, scene in enumerate(scene_descriptions):
        pose = pose_list[i % len(pose_list)]
        result = generate_coloring_page(
            scene_description=scene,
            features=features,
            child_name=child_name,
            product=product,
            pose_name=pose,
            style=art_style,
            character_sheet=character_sheet,
        )
        result.page_number = i + 1
        results.append(result)

    return results


def _generate_coloring_scenes(
    child_name: str,
    interests: list[str],
    page_count: int,
) -> list[str]:
    character_scenes = [
        f"{child_name} standing in a sunny garden with flowers and butterflies",
        f"{child_name} walking through a magical forest with tall trees",
        f"{child_name} running across a meadow with a kite flying high",
        f"{child_name} sitting by a pond watching ducks swim",
        f"{child_name} waving from the top of a small hill",
        f"{child_name} exploring a sandy beach with seashells",
        f"{child_name} climbing a tree in a park",
        f"{child_name} looking up at a rainbow in the sky",
        f"{child_name} riding a bicycle down a safe path",
        f"{child_name} playing with a friendly puppy in the grass",
        f"{child_name} standing next to a tall giraffe at the zoo",
        f"{child_name} building a sandcastle at the beach",
        f"{child_name} reaching for a star in a dreamy night sky",
    ]

    interest_scenes: list[str] = []
    for interest in interests:
        templates = [
            f"{child_name} discovering a magical {interest.lower()} scene",
            f"{child_name} surrounded by wonderful {interest.lower()} on an adventure",
            f"{child_name} playing happily in a {interest.lower()} wonderland",
        ]
        interest_scenes.extend(templates)

    all_scenes = character_scenes + interest_scenes

    while len(all_scenes) < page_count:
        idx = len(all_scenes) % len(character_scenes)
        base = character_scenes[idx]
        variant = (
            base.replace(child_name, f"{child_name}")
            + f" (variation {len(all_scenes) // len(character_scenes) + 1})"
        )
        all_scenes.append(variant)

    return all_scenes[:page_count]
