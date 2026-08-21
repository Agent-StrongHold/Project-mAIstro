import base64
import io
import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from stronghold.tools.canvas_book import CanvasBookExecutor
from stronghold.types.tool import ToolResult


def _make_png_b64(width: int = 10, height: int = 10) -> str:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def executor() -> CanvasBookExecutor:
    return CanvasBookExecutor()


@pytest.fixture(autouse=True)
def _mock_canvas_modules():
    canvas_studio_poc = MagicMock()
    server = MagicMock()
    mcp = MagicMock()
    pipeline = MagicMock()
    character = MagicMock()
    feature_extractor = MagicMock()
    story_mod = MagicMock()
    image_provider = MagicMock()
    bg_removal = MagicMock()

    canvas_studio_poc.server = server
    server.mcp = mcp
    mcp.pipeline = pipeline
    mcp.character = character
    mcp.feature_extractor = feature_extractor
    mcp.story = story_mod
    mcp.image_provider = image_provider
    mcp.bg_removal = bg_removal

    mocks = {
        "canvas_studio_poc": canvas_studio_poc,
        "canvas_studio_poc.server": server,
        "canvas_studio_poc.server.mcp": mcp,
        "canvas_studio_poc.server.mcp.pipeline": pipeline,
        "canvas_studio_poc.server.mcp.character": character,
        "canvas_studio_poc.server.mcp.feature_extractor": feature_extractor,
        "canvas_studio_poc.server.mcp.story": story_mod,
        "canvas_studio_poc.server.mcp.image_provider": image_provider,
        "canvas_studio_poc.server.mcp.bg_removal": bg_removal,
    }
    with patch.dict(sys.modules, mocks):
        yield


async def test_unknown_action(executor):
    result = await executor.execute({"action": "nonexistent"})
    assert result == ToolResult(success=False, error="Unknown action: nonexistent")


async def test_remove_bg_missing_image(executor):
    result = await executor.execute({"action": "remove_bg"})
    assert result == ToolResult(success=False, error="image_b64 is required")


async def test_remove_bg_success(executor):
    return_img = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    with patch(
        "canvas_studio_poc.server.mcp.bg_removal.remove_background",
        return_value=return_img,
    ):
        result = await executor.execute(
            {
                "action": "remove_bg",
                "image_b64": _make_png_b64(),
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["width"] == 64
    assert data["height"] == 48
    assert data["full_size_bytes"] > 0


async def test_generate_illustration_missing_prompt(executor):
    result = await executor.execute({"action": "generate_illustration"})
    assert result == ToolResult(success=False, error="prompt is required")


async def test_generate_illustration_success(executor):
    return_img = Image.new("RGB", (512, 512), (100, 150, 200))
    with patch(
        "canvas_studio_poc.server.mcp.image_provider.generate_image",
        return_value=return_img,
    ):
        result = await executor.execute(
            {
                "action": "generate_illustration",
                "prompt": "A child in a garden",
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["width"] == 512
    assert data["height"] == 512
    assert data["full_size_bytes"] > 0
    assert "image_b64" in data


async def test_create_character_missing_photo(executor):
    result = await executor.execute({"action": "create_character"})
    assert result == ToolResult(success=False, error="photo_b64 is required")


async def test_create_character_success(executor):
    mock_features = MagicMock()
    mock_features.hair = "brown wavy"
    mock_features.skin_tone = "warm medium"
    mock_features.eye_color = "brown"
    mock_features.face_shape = "round"
    mock_features.signature_features = ("bright smile",)
    mock_features.typical_expression = "cheerful"

    mock_local = MagicMock()
    mock_local.hair_color = "brown"
    mock_local.skin_tone = "medium"
    mock_local.eye_color = "hazel"
    mock_local.description = "warm brown hair and bright eyes"

    with (
        patch(
            "canvas_studio_poc.server.mcp.character.analyze_photo",
            return_value=mock_features,
        ),
        patch(
            "canvas_studio_poc.server.mcp.feature_extractor.extract_features",
            return_value=mock_local,
        ),
    ):
        result = await executor.execute(
            {
                "action": "create_character",
                "photo_b64": _make_png_b64(),
                "child_name": "Emma",
                "child_age": 5,
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["name"] == "Emma"
    assert data["age"] == 5
    assert data["ai_features"]["hair"] == "brown wavy"
    assert data["ai_features"]["skin_tone"] == "warm medium"
    assert data["ai_features"]["eye_color"] == "brown"
    assert data["ai_features"]["face_shape"] == "round"
    assert data["ai_features"]["signature_features"] == ["bright smile"]
    assert data["ai_features"]["typical_expression"] == "cheerful"
    assert data["local_features"]["hair_color"] == "brown"
    assert data["local_features"]["skin_tone"] == "medium"
    assert data["local_features"]["eye_color"] == "hazel"
    assert data["local_features"]["description"] == "warm brown hair and bright eyes"


async def test_create_story_success(executor):
    mock_page = MagicMock()
    mock_page.page_number = 1
    mock_page.scene_type = "title"
    mock_page.text = "Emma's Big Adventure" + "x" * 100
    mock_page.illustration_prompt = "A magical scene" + "x" * 100
    mock_page.character_pose = "front_standing"
    mock_page.mood = "warm"

    mock_story = MagicMock()
    mock_story.title = "Emma's Big Adventure"
    mock_story.subtitle = "A personalized story"
    mock_story.dedication = "For Emma"
    mock_story.page_count = 32
    mock_story.pages = [mock_page]

    with (
        patch(
            "canvas_studio_poc.server.mcp.story.generate_story",
            return_value=mock_story,
        ),
        patch(
            "canvas_studio_poc.server.mcp.story.validate_story",
            return_value=[],
        ),
    ):
        result = await executor.execute(
            {
                "action": "create_story",
                "child_name": "Emma",
                "child_age": 5,
                "theme_hint": "discovery",
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["title"] == "Emma's Big Adventure"
    assert data["subtitle"] == "A personalized story"
    assert data["dedication"] == "For Emma"
    assert data["page_count"] == 32
    assert data["validation_issues"] == []
    assert len(data["pages"]) == 1
    assert data["pages"][0]["page_number"] == 1
    assert data["pages"][0]["scene_type"] == "title"
    assert data["pages"][0]["character_pose"] == "front_standing"
    assert data["pages"][0]["mood"] == "warm"


async def test_create_storyboard_success(executor):
    mock_style = MagicMock()
    mock_style.art_style = "warm watercolor"
    mock_style.color_palette = ("#FF0000", "#00FF00", "#0000FF")
    mock_style.lighting = "soft natural"
    mock_style.mood = "playful"
    mock_style.recurring_elements = ("rainbow", "stars")

    mock_scene = MagicMock()
    mock_scene.id = "scene_001"
    mock_scene.title = "Opening"
    mock_scene.scene_type = "title"
    mock_scene.page_text = "Once upon a time" + "x" * 100
    mock_scene.pose = "front_standing"
    mock_scene.composition = "center"
    mock_scene.character_action = "waving"
    mock_scene.props = ["book", "star"]

    mock_decomp = MagicMock()
    mock_decomp.title = "Emma's Story"
    mock_decomp.dedication = "For Emma"
    mock_decomp.style_contract = mock_style
    mock_decomp.scenes = [mock_scene]

    with patch(
        "canvas_studio_poc.server.mcp.story.decompose_book",
        return_value=mock_decomp,
    ):
        result = await executor.execute(
            {
                "action": "create_storyboard",
                "child_name": "Emma",
                "child_age": 5,
                "page_count": 12,
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["title"] == "Emma's Story"
    assert data["dedication"] == "For Emma"
    assert data["style_contract"]["art_style"] == "warm watercolor"
    assert data["style_contract"]["color_palette"] == ["#FF0000", "#00FF00", "#0000FF"]
    assert data["style_contract"]["lighting"] == "soft natural"
    assert data["style_contract"]["mood"] == "playful"
    assert data["style_contract"]["recurring_elements"] == ["rainbow", "stars"]
    assert data["scene_count"] == 1
    assert data["scenes"][0]["id"] == "scene_001"
    assert data["scenes"][0]["title"] == "Opening"
    assert data["scenes"][0]["scene_type"] == "title"
    assert data["scenes"][0]["pose"] == "front_standing"
    assert data["scenes"][0]["composition"] == "center"
    assert data["scenes"][0]["character_action"] == "waving"
    assert data["scenes"][0]["prop_count"] == 2


async def test_create_book_success(executor):
    mock_pdf_path = MagicMock()
    mock_pdf_path.exists.return_value = True
    mock_pdf_path.stat.return_value.st_size = 54321

    mock_cover_path = MagicMock()
    mock_cover_path.exists.return_value = True
    mock_cover_path.stat.return_value.st_size = 12345

    mock_product = MagicMock()
    mock_product.name = "Picture Book"

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.stages_completed = ["character"]
    mock_result.errors = []
    mock_result.product = mock_product
    mock_result.interior_pdf_path = mock_pdf_path
    mock_result.cover_pdf_path = mock_cover_path
    mock_result.illustrations = []

    with patch(
        "canvas_studio_poc.server.mcp.pipeline.run_pipeline",
        return_value=mock_result,
    ):
        result = await executor.execute(
            {
                "action": "create_book",
                "photo_b64": _make_png_b64(),
                "child_name": "Emma",
                "child_age": 5,
            }
        )
    assert result.success is True
    data = json.loads(result.content)
    assert data["success"] is True
    assert data["stages_completed"] == ["character"]
    assert data["errors"] == []
    assert data["product"] == "Picture Book"
    assert data["interior_pdf_size"] == 54321
    assert data["cover_pdf_size"] == 12345
    assert data["illustration_count"] == 0


async def test_exception_handling(executor):
    with patch(
        "canvas_studio_poc.server.mcp.image_provider.generate_image",
        side_effect=RuntimeError("API unavailable"),
    ):
        result = await executor.execute(
            {
                "action": "generate_illustration",
                "prompt": "A garden",
            }
        )
    assert result.success is False
    assert "API unavailable" in result.error
