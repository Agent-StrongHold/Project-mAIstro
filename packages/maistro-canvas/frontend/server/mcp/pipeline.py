from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .character import CharacterSheet, create_character_sheet_from_photo
from .golden import has_golden, load_golden_features, load_golden_story
from .illustration import (
    IllustrationResult,
    generate_coloring_book_illustrations,
    generate_picture_book_illustrations,
)
from .pdf_composer import compose_cover, compose_interior
from .products import ProductSpec, get_product
from .story import Story, generate_story, validate_story

logger = logging.getLogger(__name__)

BookType = Literal["picture", "coloring-standard", "coloring-premium"]
ArtStyle = Literal["warm watercolor", "bold_simple", "detailed_ornate"]

PRODUCT_MAP: dict[BookType, str] = {
    "picture": "picture-book-7.5",
    "coloring-standard": "coloring-standard",
    "coloring-premium": "coloring-premium",
}


@dataclass
class OrderSpec:
    child_photo_path: str
    child_name: str
    child_age: int
    book_type: BookType
    art_style: ArtStyle = "warm watercolor"
    interests: list[str] = field(default_factory=list)
    theme_hint: str = ""
    shipping_address: dict = field(default_factory=dict)
    product_id: str | None = None

    @property
    def product(self) -> ProductSpec:
        pid = self.product_id or PRODUCT_MAP[self.book_type]
        return get_product(pid)


@dataclass
class PipelineResult:
    order: OrderSpec
    character_sheet: CharacterSheet
    story: Story | None
    illustrations: list[IllustrationResult]
    interior_pdf_path: Path
    cover_pdf_path: Path
    product: ProductSpec
    stages_completed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def run_pipeline(
    order: OrderSpec,
    output_dir: str | Path,
    skip_ai: bool = False,
    fallback_to_golden: bool = False,
    max_retries: int = 3,
) -> PipelineResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    product = order.product
    stages: list[str] = []
    errors: list[str] = []

    logger.info(
        "=== Pipeline Start: %s for %s (age %d) ===",
        product.name,
        order.child_name,
        order.child_age,
    )

    character_sheet = _stage_character_sheet(
        order, output_dir, stages, errors, skip_ai, fallback_to_golden
    )
    story = _stage_story(
        order, character_sheet.features, stages, errors, skip_ai, fallback_to_golden
    )
    illustrations = _stage_illustrations(
        order, character_sheet, story, product, stages, errors, skip_ai
    )
    interior_path, cover_path = _stage_pdf(
        order, product, story, illustrations, output_dir, stages, errors, skip_ai
    )

    result = PipelineResult(
        order=order,
        character_sheet=character_sheet,
        story=story,
        illustrations=illustrations,
        interior_pdf_path=interior_path,
        cover_pdf_path=cover_path,
        product=product,
        stages_completed=stages,
        errors=errors,
    )

    logger.info(
        "=== Pipeline %s: %d stages, %d errors, %d illustrations ===",
        "COMPLETE" if result.success else "FAILED",
        len(stages),
        len(errors),
        len(illustrations),
    )
    return result


def _stage_character_sheet(
    order: OrderSpec,
    output_dir: Path,
    stages: list[str],
    errors: list[str],
    skip_ai: bool,
    fallback_to_golden: bool = False,
) -> CharacterSheet:
    stage = "character_sheet"
    logger.info("[%s] Starting...", stage)

    if skip_ai:
        from .character import CharacterFeatures

        features = CharacterFeatures(
            hair="brown wavy",
            skin_tone="warm medium",
            eye_color="brown",
            face_shape="round",
            age_style=f"{order.child_age} years old",
            body_type="average build for age",
            signature_features=("bright smile",),
            typical_expression="cheerful",
        )
        sheet = CharacterSheet(features=features, quality_score=0.5)
        stages.append(stage)
        return sheet

    try:
        sheet = create_character_sheet_from_photo(
            photo_path=order.child_photo_path,
            child_name=order.child_name,
            child_age=order.child_age,
            art_style=order.art_style,
        )
        if sheet.sheet_image is not None:
            sheet_path = output_dir / "character_sheet.png"
            sheet.sheet_image.save(sheet_path)
            logger.info("[%s] Saved to %s", stage, sheet_path)
        stages.append(stage)
        return sheet
    except Exception as e:
        logger.error("[%s] Failed: %s", stage, e)
        errors.append(f"{stage}: {e}")

        if fallback_to_golden and has_golden("features"):
            from .character import CharacterFeatures

            try:
                features = load_golden_features()
                logger.warning("[%s] Falling back to golden features", stage)
                errors.append(f"{stage}_golden_fallback: using saved golden features")
                return CharacterSheet(features=features, quality_score=0.0)
            except Exception as ge:
                logger.error("[%s] Golden fallback also failed: %s", stage, ge)

        from .character import CharacterFeatures

        features = CharacterFeatures(
            hair="brown",
            skin_tone="medium",
            eye_color="brown",
            face_shape="round",
            age_style=f"{order.child_age} years old",
            body_type="average",
            signature_features=("smile",),
            typical_expression="happy",
        )
        return CharacterSheet(features=features, quality_score=0.0)


def _stage_story(
    order: OrderSpec,
    features,
    stages: list[str],
    errors: list[str],
    skip_ai: bool,
    fallback_to_golden: bool = False,
) -> Story | None:
    stage = "story"
    logger.info("[%s] Starting...", stage)

    if order.book_type != "picture":
        logger.info("[%s] Skipping (not a picture book)", stage)
        return None

    if skip_ai:
        story = _placeholder_story(order)
        stages.append(stage)
        return story

    try:
        story = generate_story(
            child_name=order.child_name,
            child_age=order.child_age,
            features=features,
            interests=order.interests,
            theme_hint=order.theme_hint,
        )
        issues = validate_story(story, order.child_age)
        if issues:
            logger.warning("[%s] Validation issues: %s", stage, issues)
            for issue in issues:
                errors.append(f"{stage}_validation: {issue}")

        stages.append(stage)
        return story
    except Exception as e:
        logger.error("[%s] Failed: %s", stage, e)
        errors.append(f"{stage}: {e}")

        if fallback_to_golden and has_golden("story"):
            try:
                story = load_golden_story()
                logger.warning("[%s] Falling back to golden story", stage)
                errors.append(f"{stage}_golden_fallback: using saved golden story")
                stages.append(stage)
                return story
            except Exception as ge:
                logger.error("[%s] Golden fallback also failed: %s", stage, ge)

        return _placeholder_story(order)


def _stage_illustrations(
    order: OrderSpec,
    sheet: CharacterSheet,
    story: Story | None,
    product: ProductSpec,
    stages: list[str],
    errors: list[str],
    skip_ai: bool,
) -> list[IllustrationResult]:
    stage = "illustrations"
    logger.info("[%s] Starting...", stage)

    if skip_ai:
        from PIL import Image as PILImage

        results = []
        w = int(product.trim_width_in * 300)
        h = int(product.trim_height_in * 300)
        for i in range(product.page_count):
            img = PILImage.new("RGB", (w, h), (220 + i % 20, 225 + i % 15, 235))
            from .illustration import _pil_to_bytes

            results.append(
                IllustrationResult(
                    page_number=i + 1,
                    image=img,
                    image_bytes=_pil_to_bytes(img),
                    prompt_used="placeholder",
                    model_used="pillow",
                    is_color="Full Color" in product.interior_color,
                )
            )
        stages.append(stage)
        return results

    try:
        if order.book_type == "picture" and story is not None:
            results = generate_picture_book_illustrations(
                story=story,
                features=sheet.features,
                product=product,
                character_sheet=sheet,
                style=order.art_style,
            )
        else:
            results = generate_coloring_book_illustrations(
                features=sheet.features,
                child_name=order.child_name,
                product=product,
                art_style=order.art_style,
                interests=order.interests,
                character_sheet=sheet,
            )

        for r in results:
            img_path = Path(f"page_{r.page_number:03d}.png")
            logger.debug("[%s] Page %d: %s", stage, r.page_number, img_path)

        stages.append(stage)
        return results
    except Exception as e:
        logger.error("[%s] Failed: %s", stage, e)
        errors.append(f"{stage}: {e}")
        return []


def _archive_pages(output_dir: Path) -> None:
    archive_dir = output_dir / "archive" / "pages"
    page_files = sorted(output_dir.glob("_page_*.png"))
    if not page_files:
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    for pf in page_files:
        dest = archive_dir / pf.name
        shutil.move(str(pf), str(dest))
    logger.info("Archived %d page images to %s", len(page_files), archive_dir)


def _stage_pdf(
    order: OrderSpec,
    product: ProductSpec,
    story: Story | None,
    illustrations: list[IllustrationResult],
    output_dir: Path,
    stages: list[str],
    errors: list[str],
    skip_ai: bool,
) -> tuple[Path, Path]:
    stage = "pdf"
    logger.info("[%s] Starting...", stage)

    title = story.title if story else f"{order.child_name}'s Book"
    author = "Main Character Press"

    page_texts: dict[int, str] | None = None
    if story and order.book_type == "picture":
        page_texts = {p.page_number: p.text for p in story.pages if p.text}

    page_images: list[str | Path] = []
    if illustrations:
        sorted_ills = sorted(illustrations, key=lambda x: x.page_number)
        for ill in sorted_ills:
            tmp_img = output_dir / f"_page_{ill.page_number:03d}.png"
            ill.image.save(tmp_img, format="PNG")
            page_images.append(str(tmp_img))

    interior_path = output_dir / "interior.pdf"
    cover_path = output_dir / "cover.pdf"

    try:
        compose_interior(
            product,
            interior_path,
            page_images=page_images if page_images else None,
            page_texts=page_texts,
            title=title,
            author=author,
        )
        logger.info(
            "[%s] Interior: %s (%d bytes)", stage, interior_path, interior_path.stat().st_size
        )

        compose_cover(product, cover_path, title=title, author=author)
        logger.info("[%s] Cover: %s (%d bytes)", stage, cover_path, cover_path.stat().st_size)

        _archive_pages(output_dir)

        stages.append(stage)
    except Exception as e:
        logger.error("[%s] Failed: %s", stage, e)
        errors.append(f"{stage}: {e}")
        _archive_pages(output_dir)
        compose_interior(product, interior_path, title=title, author=author)
        compose_cover(product, cover_path, title=title, author=author)

    return interior_path, cover_path


def _placeholder_story(order: OrderSpec) -> Story:
    from .story import StoryPage

    pages = [
        StoryPage(
            page_number=1,
            scene_type="title",
            text=f"{order.child_name}'s Adventure",
            illustration_prompt="Title page with child's name in decorative letters",
            character_pose="front_standing",
            mood="warm",
            setting="title page",
        ),
        StoryPage(
            page_number=2,
            scene_type="copyright",
            text=f"Copyright 2026 Main Character Press. For {order.child_name} with love.",
            illustration_prompt="Simple decorative border",
            character_pose="front_standing",
            mood="calm",
            setting="copyright page",
        ),
    ]

    for i in range(3, 33):
        scene = "story_beat" if i < 31 else "ending"
        pages.append(
            StoryPage(
                page_number=i,
                scene_type=scene,
                text=f"[Page {i} placeholder text for {order.child_name}]",
                illustration_prompt=f"A gentle scene with {order.child_name} exploring",
                character_pose="front_standing",
                mood="warm",
                setting="gentle landscape",
            )
        )

    return Story(
        title=f"{order.child_name}'s Adventure",
        subtitle="A personalized story",
        child_name=order.child_name,
        age_group="early_reader",
        pages=pages,
        dedication=f"For {order.child_name}, with love",
    )
