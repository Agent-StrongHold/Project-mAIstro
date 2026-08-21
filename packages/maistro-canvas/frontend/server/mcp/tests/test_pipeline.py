import pytest
from PIL import Image
from server.mcp.character import (
    CELL_LABELS_TOP,
    GRID_COLS,
    GRID_ROWS,
    POSE_BODY,
    POSE_FACING,
    POSE_LABELS,
    POSES,
    CharacterFeatures,
    build_character_design_text,
    build_character_prompt,
    extract_poses,
    generate_reference_image,
)
from server.mcp.golden import has_golden, load_golden_features, load_golden_story
from server.mcp.illustration import (
    _generate_coloring_scenes,
    _post_process_coloring,
    build_coloring_page_prompt,
    build_picture_book_prompt,
)
from server.mcp.pipeline import OrderSpec, run_pipeline
from server.mcp.products import get_product
from server.mcp.story import Story, StoryPage, _age_to_group, _words_per_page, validate_story


def _sample_features() -> CharacterFeatures:
    return CharacterFeatures(
        hair="brown wavy shoulder-length",
        skin_tone="warm medium",
        eye_color="brown",
        face_shape="round",
        age_style="5 years old",
        body_type="average height for age",
        signature_features=("bright smile", "dimples"),
        typical_expression="cheerful and curious",
    )


def _sample_story(child_name: str = "Emma") -> Story:
    pages = [
        StoryPage(
            1,
            "title",
            f"{child_name}'s Big Adventure",
            "title page",
            "front_standing",
            "warm",
            "title",
        ),
        StoryPage(
            2,
            "copyright",
            f"Copyright 2026 Main Character Press. For {child_name}.",
            "decorative",
            "front_standing",
            "calm",
            "copyright",
        ),
    ]
    for i in range(3, 33):
        pages.append(
            StoryPage(
                i,
                "story_beat" if i < 31 else "ending",
                (
                    f"Page {i} story text for {child_name} with enough words "
                    "to be a proper sentence about something interesting."
                ),
                f"A scene showing {child_name} in a magical place",
                "front_standing" if i % 3 == 0 else "front_waving" if i % 3 == 1 else "looking_up",
                "warm" if i % 2 == 0 else "playful",
                "garden" if i < 15 else "forest",
            )
        )
    return Story(
        title=f"{child_name}'s Big Adventure",
        subtitle="A personalized story",
        child_name=child_name,
        age_group="early_reader",
        pages=pages,
        dedication=f"For {child_name}, with love",
    )


# --- Character Module Tests ---


def test_poses_defined():
    assert len(POSES) == 13
    for pose in POSES:
        assert pose in POSE_BODY
        assert pose in POSE_FACING
        assert pose in POSE_LABELS


def test_grid_layout_consistency():
    assert len(CELL_LABELS_TOP) == GRID_COLS * GRID_ROWS
    pose_cells = [v for v in CELL_LABELS_TOP.values() if "(empty)" not in v]
    assert len(pose_cells) >= 13


def test_reference_image_generates():
    ref = generate_reference_image(512, 512)
    assert ref.size == (512, 512)
    assert ref.mode == "RGB"


def test_reference_image_full_size():
    ref = generate_reference_image(2048, 2048)
    assert ref.size == (2048, 2048)


def test_character_prompt_builds():
    features = _sample_features()
    prompt = build_character_prompt(features, "warm watercolor")
    assert "brown wavy shoulder-length" in prompt
    assert "warm medium" in prompt
    assert "brown" in prompt
    assert "13 different poses" in prompt
    assert "4x4 grid" in prompt


def test_character_design_text():
    features = _sample_features()
    text = build_character_design_text(features, "Emma")
    assert "Emma" in text
    assert "brown wavy shoulder-length" in text
    assert "bright smile" in text


def test_extract_poses_from_blank_sheet():
    blank = Image.new("RGB", (2048, 2048), (255, 255, 255))
    crops = extract_poses(blank)
    assert len(crops) >= 13
    for name in POSES:
        assert name in crops or f"{name}_hero" in crops
    for crop in crops.values():
        assert crop.size[0] > 0
        assert crop.size[1] > 0


def test_mannequin_sitting_has_no_standing_legs():
    ref = generate_reference_image(2048, 2048)
    cell_w = 2048 // GRID_COLS
    cell_h = 2048 // GRID_ROWS
    sitting_col, sitting_row = 3, 0
    x1 = sitting_col * cell_w
    y1 = sitting_row * cell_h
    sitting_crop = ref.crop((x1, y1, x1 + cell_w, y1 + cell_h))
    standing_col, standing_row = 0, 0
    x2 = standing_col * cell_w
    y2 = standing_row * cell_h
    standing_crop = ref.crop((x2, y2, x2 + cell_w, y2 + cell_h))
    assert sitting_crop.size == standing_crop.size
    assert sitting_crop.get_flattened_data() != standing_crop.get_flattened_data()


# --- Story Module Tests ---


def test_age_group_mapping():
    assert _age_to_group(3) == "toddler"
    assert _age_to_group(5) == "early_reader"
    assert _age_to_group(8) == "reader"
    assert _age_to_group(12) == "reader"


def test_words_per_page_ranges():
    assert _words_per_page("toddler") == (20, 60)
    assert _words_per_page("early_reader") == (50, 100)
    assert _words_per_page("reader") == (100, 150)


def test_story_validation():
    story = _sample_story()
    assert len(story.pages) == 32
    assert story.pages[0].scene_type == "title"
    assert story.pages[1].scene_type == "copyright"


def test_story_validation_bad_page_count():
    bad_story = Story(
        title="Bad",
        subtitle="",
        child_name="Test",
        age_group="early_reader",
        pages=[StoryPage(1, "title", "Test", "", "front_standing", "warm", "test")],
    )
    issues = validate_story(bad_story, 5)
    assert any("32" in i for i in issues)


# --- Illustration Module Tests ---


def test_picture_book_prompt_builds():
    features = _sample_features()
    page = StoryPage(
        5,
        "story_beat",
        "Emma ran through the garden",
        "A sunny garden scene",
        "front_running",
        "exciting",
        "garden",
    )
    prompt = build_picture_book_prompt(page, features, "Emma")
    assert "Emma" in prompt
    assert "running" in prompt.lower()
    assert "watercolor" in prompt.lower()
    assert "NO TEXT" in prompt


def test_coloring_page_prompt_builds():
    features = _sample_features()
    prompt = build_coloring_page_prompt(
        "A garden with flowers", features, "Emma", "front_standing", "bold_simple"
    )
    assert "Emma" in prompt
    assert "bold" in prompt.lower()
    assert "NO shading" in prompt
    assert "black outlines" in prompt.lower()


def test_coloring_scene_generation():
    scenes = _generate_coloring_scenes("Emma", ["Dinosaurs", "Ocean Life"], 32)
    assert len(scenes) == 32
    assert any("Emma" in s for s in scenes)
    assert any("dinosaur" in s.lower() for s in scenes)


def test_coloring_scene_generation_premium():
    scenes = _generate_coloring_scenes("Emma", ["Dragons", "Space"], 150)
    assert len(scenes) == 150


def test_post_process_coloring():
    img = Image.new("RGB", (100, 100))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 80, 80], fill=(0, 0, 0))
    draw.rectangle([25, 25, 75, 75], fill=(200, 200, 200))
    result = _post_process_coloring(img)
    assert result.mode == "RGB"
    center_pixel = result.getpixel((50, 50))
    assert center_pixel[0] in (0, 255)


# --- Pipeline Tests (skip_ai=True for speed) ---


def test_pipeline_picture_book_placeholder(tmp_path):
    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Emma",
        child_age=5,
        book_type="picture",
        art_style="warm watercolor",
        interests=["Dinosaurs", "Ocean Life"],
    )
    result = run_pipeline(order, tmp_path, skip_ai=True)
    assert result.success
    assert "character_sheet" in result.stages_completed
    assert "story" in result.stages_completed
    assert "illustrations" in result.stages_completed
    assert "pdf" in result.stages_completed
    assert result.interior_pdf_path.exists()
    assert result.cover_pdf_path.exists()
    assert result.story is not None
    assert len(result.illustrations) == 32


def test_pipeline_coloring_standard_placeholder(tmp_path):
    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Liam",
        child_age=4,
        book_type="coloring-standard",
        art_style="bold_simple",
        interests=["Dinosaurs", "Ocean Life", "Dragons"],
    )
    result = run_pipeline(order, tmp_path, skip_ai=True)
    assert result.success
    assert result.interior_pdf_path.exists()
    assert result.cover_pdf_path.exists()
    assert result.story is None
    assert len(result.illustrations) == 32


def test_pipeline_coloring_premium_placeholder(tmp_path):
    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Sophia",
        child_age=8,
        book_type="coloring-premium",
        art_style="detailed_ornate",
        interests=["Dragons", "Space", "Fairies"],
    )
    result = run_pipeline(order, tmp_path, skip_ai=True)
    assert result.success
    assert len(result.illustrations) == 150
    assert result.interior_pdf_path.exists()
    from PyPDF2 import PdfReader

    reader = PdfReader(str(result.interior_pdf_path))
    assert len(reader.pages) == 150


def test_pipeline_pdf_dimensions(tmp_path):
    from PyPDF2 import PdfReader

    for book_type in ["picture", "coloring-standard"]:  # type: ignore[arg-type]
        order = OrderSpec(
            child_photo_path="/nonexistent/photo.jpg",
            child_name="Test",
            child_age=5,
            book_type=book_type,
        )
        result = run_pipeline(order, tmp_path / book_type, skip_ai=True)
        reader = PdfReader(str(result.interior_pdf_path))
        product = result.product
        assert len(reader.pages) == product.page_count
        page = reader.pages[0]
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        assert abs(w - product.bleed_width_pt) < 2
        assert abs(h - product.bleed_height_pt) < 2
        cover_reader = PdfReader(str(result.cover_pdf_path))
        assert len(cover_reader.pages) == 1


def test_order_spec_product_mapping():
    order = OrderSpec(child_photo_path="/x", child_name="T", child_age=5, book_type="picture")
    assert order.product.id == "picture-book-7.5"
    order2 = OrderSpec(
        child_photo_path="/x", child_name="T", child_age=5, book_type="coloring-premium"
    )
    assert order2.product.id == "coloring-premium"
    assert order2.product.page_count == 150


# --- Text Overlay Tests (Bug 1 fix) ---


def test_text_overlay_on_picture_book_pages(tmp_path):
    from PyPDF2 import PdfReader

    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Emma",
        child_age=5,
        book_type="picture",
    )
    result = run_pipeline(order, tmp_path, skip_ai=True)
    assert result.success
    assert result.story is not None

    reader = PdfReader(str(result.interior_pdf_path))
    all_text = ""
    for page in reader.pages:
        text = page.extract_text() or ""
        all_text += text + "\n"

    assert "Emma" in all_text, (
        f"Child name 'Emma' not found in PDF text. Extracted: {all_text[:300]}"
    )
    story_page = result.story.pages[2]
    assert story_page.text, "Page 3 should have story text"
    first_words = story_page.text.split()[:3]
    found = any(w in all_text for w in first_words if len(w) > 3)
    assert found, f"Story text words {first_words} not found in PDF. Got: {all_text[:500]}"


def test_no_text_overlay_on_coloring_book(tmp_path):
    from server.mcp.pdf_composer import compose_interior

    product = get_product("coloring-standard")
    img = Image.new("RGB", (100, 100), (220, 220, 220))
    img_path = tmp_path / "test.png"
    img.save(img_path)

    out = compose_interior(
        product,
        tmp_path / "interior.pdf",
        page_images=[str(img_path)] * 32,
        page_texts={3: "This should NOT appear"},
    )
    assert out.exists()

    from PyPDF2 import PdfReader

    reader = PdfReader(str(out))
    page3_text = reader.pages[2].extract_text() or ""
    assert "This should NOT appear" not in page3_text


# --- Archive Tests (Bug 3 fix) ---


def test_archived_pages_exist_after_pipeline(tmp_path):
    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Emma",
        child_age=5,
        book_type="picture",
    )
    result = run_pipeline(order, tmp_path, skip_ai=True)
    assert result.success

    archive_dir = tmp_path / "archive" / "pages"
    assert archive_dir.exists(), f"Archive directory not found at {archive_dir}"
    archived_files = list(archive_dir.glob("_page_*.png"))
    assert len(archived_files) == 32, f"Expected 32 archived pages, got {len(archived_files)}"


def test_archived_pages_not_in_output_root(tmp_path):
    order = OrderSpec(
        child_photo_path="/nonexistent/photo.jpg",
        child_name="Emma",
        child_age=5,
        book_type="picture",
    )
    _result = run_pipeline(order, tmp_path, skip_ai=True)
    orphaned = list(tmp_path.glob("_page_*.png"))
    assert len(orphaned) == 0, f"Found {len(orphaned)} orphaned _page_*.png files in output root"


# --- Golden Infrastructure Tests ---


def test_golden_files_exist():
    assert has_golden("features"), "Golden features.json missing. Run generate_golden.py"
    assert has_golden("story"), "Golden story.json missing. Run generate_golden.py"
    assert has_golden("reference"), "Golden reference.png missing. Run generate_golden.py"


def test_golden_features_loadable():
    if not has_golden("features"):
        pytest.skip("No golden features")
    features = load_golden_features()
    assert features.hair
    assert features.skin_tone
    assert features.eye_color
    assert features.face_shape
    assert isinstance(features.signature_features, tuple)


def test_golden_story_loadable():
    if not has_golden("story"):
        pytest.skip("No golden story")
    story = load_golden_story()
    assert story.title
    assert len(story.pages) == 32
    assert story.pages[0].scene_type == "title"
    assert story.pages[1].scene_type == "copyright"
    assert story.child_name


def test_golden_features_usable_in_story():
    if not has_golden("features"):
        pytest.skip("No golden features")
    features = load_golden_features()
    assert features.hair
    assert features.eye_color


def test_pipeline_with_golden_fallback(tmp_path):
    if not has_golden("features") or not has_golden("story"):
        pytest.skip("Need golden features + story for fallback test")

    _features = load_golden_features()
    story = load_golden_story()

    from server.mcp.pdf_composer import compose_interior

    product = get_product("picture-book-7.5")
    img = Image.new(
        "RGB",
        (int(product.trim_width_in * 300), int(product.trim_height_in * 300)),
        (230, 225, 220),
    )
    img_path = tmp_path / "test.png"
    img.save(img_path)

    page_texts = {p.page_number: p.text for p in story.pages if p.text}
    out = compose_interior(
        product,
        tmp_path / "interior.pdf",
        page_images=[str(img_path)] * 32,
        page_texts=page_texts,
        title=story.title,
    )
    assert out.exists()

    from PyPDF2 import PdfReader

    reader = PdfReader(str(out))
    assert len(reader.pages) == 32
    all_text = "".join(page.extract_text() or "" for page in reader.pages)
    assert story.child_name in all_text


def test_pdf_with_golden_story(tmp_path):
    if not has_golden("story"):
        pytest.skip("No golden story")
    story = load_golden_story()
    product = get_product("picture-book-7.5")
    from server.mcp.pdf_composer import compose_interior

    page_texts = {p.page_number: p.text for p in story.pages if p.text}
    img = Image.new(
        "RGB",
        (int(product.trim_width_in * 300), int(product.trim_height_in * 300)),
        (230, 225, 220),
    )
    img_path = tmp_path / "test.png"
    img.save(img_path)

    out = compose_interior(
        product,
        tmp_path / "interior.pdf",
        page_images=[str(img_path)] * 32,
        page_texts=page_texts,
        title=story.title,
    )
    assert out.exists()

    from PyPDF2 import PdfReader

    reader = PdfReader(str(out))
    all_text = ""
    for page in reader.pages:
        all_text += (page.extract_text() or "") + "\n"
    assert story.child_name in all_text, (
        f"Child name '{story.child_name}' not found in PDF with golden story"
    )


# --- Real AI Tests (gated by marker) ---


@pytest.mark.perf
def test_real_character_analysis(tmp_path):
    from server.mcp.character import analyze_photo

    img = Image.new("RGB", (512, 512), (200, 170, 140))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.ellipse([180, 100, 330, 250], fill=(220, 190, 160))
    draw.ellipse([220, 140, 250, 170], fill=(80, 60, 40))
    draw.ellipse([270, 140, 300, 170], fill=(80, 60, 40))
    draw.arc([230, 190, 290, 220], 0, 180, fill=(180, 80, 80), width=2)
    photo_path = tmp_path / "test_child.png"
    img.save(photo_path)

    features = analyze_photo(photo_path=photo_path, child_name="Emma", child_age=5)
    assert features.hair
    assert features.skin_tone
    assert features.eye_color
    assert features.face_shape


@pytest.mark.perf
def test_real_story_generation():
    from server.mcp.story import generate_story

    features = _sample_features()
    story = generate_story(
        child_name="Emma",
        child_age=5,
        features=features,
        interests=["Dinosaurs", "Ocean Life"],
        theme_hint="discovery and imagination",
    )
    assert story.title
    assert len(story.pages) == 32
    assert story.pages[0].scene_type == "title"


@pytest.mark.perf
def test_real_pipeline_picture_book(tmp_path):
    img = Image.new("RGB", (512, 512), (200, 170, 140))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.ellipse([180, 100, 330, 250], fill=(220, 190, 160))
    photo_path = tmp_path / "child.png"
    img.save(photo_path)

    order = OrderSpec(
        child_photo_path=str(photo_path),
        child_name="Emma",
        child_age=5,
        book_type="picture",
        art_style="warm watercolor",
        interests=["Dinosaurs"],
    )
    result = run_pipeline(order, tmp_path / "output", skip_ai=False, fallback_to_golden=True)
    assert "character_sheet" in result.stages_completed or any(
        "golden_fallback" in e for e in result.errors
    )
    assert result.interior_pdf_path.exists()
    assert result.cover_pdf_path.exists()


# --- Image Provider Tests ---


@pytest.mark.perf
def test_cloudflare_image_generation():
    from server.mcp.image_provider import generate_image

    img = generate_image(
        prompt="A happy child with brown hair waving hello, warm watercolor style, NO TEXT",
        timeout=60,
    )
    assert img.size[0] > 0
    assert img.size[1] > 0
    assert img.mode == "RGB"
    img.save("/tmp/test_provider_output.png")
    print(f"Generated image: {img.size}")


@pytest.mark.perf
def test_real_single_page_pipeline(tmp_path):
    if not has_golden("features"):
        pytest.skip("No golden features")
    features = load_golden_features()
    product = get_product("picture-book-7.5")
    from server.mcp.illustration import generate_picture_book_page
    from server.mcp.story import StoryPage

    page = StoryPage(
        3,
        "story_beat",
        "Emma walked into the garden and saw a butterfly.",
        "A child in a sunny garden discovering a colorful butterfly",
        "front_standing",
        "warm",
        "garden",
    )
    result = generate_picture_book_page(page, features, "Emma", product)
    assert result.image.size[0] > 0
    assert result.is_color
    result.image.save("/tmp/test_single_page_illustration.png")
    print(f"Single page illustration: {result.image.size}")
