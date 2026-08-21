import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest
from server.mcp.character import CharacterFeatures
from server.mcp.story import (
    BookDecomposition,
    PropSpec,
    ScenePlan,
    StyleContract,
    _extract_json,
    decompose_book,
)


def _mock_features():
    features = MagicMock(spec=CharacterFeatures)
    features.hair = "brown wavy"
    features.skin_tone = "warm medium"
    features.eye_color = "brown"
    features.face_shape = "round"
    features.build = "average"
    return features


def _llm_response(payload: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
    return mock_resp


class TestExtractJson:
    def test_bare_json_object(self):
        data = {"title": "Hello", "scenes": []}
        result = _extract_json(json.dumps(data))
        assert result == data

    def test_json_in_markdown_fences(self):
        data = {"title": "Hello", "scenes": []}
        text = f"```json\n{json.dumps(data)}\n```"
        result = _extract_json(text)
        assert result == data

    def test_json_with_trailing_garbage(self):
        data = {"title": "Hello"}
        text = json.dumps(data) + " some trailing garbage here"
        result = _extract_json(text)
        assert result == data

    def test_invalid_input_raises_value_error(self):
        with pytest.raises(ValueError, match="AI did not return valid JSON"):
            _extract_json("not json at all")


class TestDataStructures:
    def test_style_contract_defaults(self):
        sc = StyleContract()
        assert sc.art_style == "warm watercolor children's book illustration"
        assert len(sc.color_palette) == 5
        assert sc.lighting == "soft warm light"
        assert sc.mood == "whimsical wonder"
        assert sc.recurring_elements == ()
        assert "no text" in sc.negative_prompts

    def test_style_contract_frozen(self):
        sc = StyleContract()
        with pytest.raises(FrozenInstanceError):
            sc.art_style = "oil painting"

    def test_prop_spec_defaults(self):
        ps = PropSpec(name="wand", description="sparkly wand")
        assert ps.scale == "handheld"
        assert ps.placement == "right"

    def test_prop_spec_frozen(self):
        ps = PropSpec(name="wand", description="sparkly wand")
        with pytest.raises(FrozenInstanceError):
            ps.name = "sword"

    def test_scene_plan_defaults(self):
        sp = ScenePlan(
            id=1, title="Opening", scene_type="title_page", page_text="", description="A forest"
        )
        assert sp.pose == "standing_front"
        assert sp.composition == "center_focus"
        assert sp.character_action == ""
        assert sp.props == ()

    def test_scene_plan_frozen(self):
        sp = ScenePlan(
            id=1, title="Opening", scene_type="title_page", page_text="", description="A forest"
        )
        with pytest.raises(FrozenInstanceError):
            sp.id = 99

    def test_book_decomposition_defaults(self):
        bd = BookDecomposition(title="Test", dedication="", style_contract=StyleContract())
        assert bd.page_dims == (1536, 1024)
        assert bd.orientation == "landscape (wide)"
        assert bd.scenes == []


class TestDecomposeBook:
    @patch("server.mcp.story.httpx.post")
    def test_returns_book_decomposition(self, mock_post):
        payload = {
            "title": "Emma's Adventure",
            "dedication": "For Emma, with love",
            "style_contract": {
                "art_style": "watercolor",
                "color_palette": ["#FF0000", "#00FF00"],
                "lighting": "warm golden",
                "mood": "playful",
                "recurring_elements": ["stars", "butterflies"],
                "negative_prompts": "no text",
            },
            "scenes": [
                {
                    "id": 1,
                    "title": "Title Page",
                    "scene_type": "title_page",
                    "page_text": "",
                    "description": "A magical forest entrance",
                    "pose": "front_standing",
                    "composition": "center_focus",
                    "character_action": "standing proudly",
                    "props": [
                        {
                            "name": "wand",
                            "description": "sparkly star wand",
                            "scale": "handheld",
                            "placement": "right",
                        }
                    ],
                },
                {
                    "id": 2,
                    "title": "Happy Ending",
                    "scene_type": "ending",
                    "page_text": "And they lived happily ever after.",
                    "description": "Sunset over the hills",
                    "pose": "front_waving",
                    "composition": "wide_establishing",
                    "character_action": "waving goodbye",
                    "props": [],
                },
            ],
        }
        mock_post.return_value = _llm_response(payload)
        result = decompose_book("Emma", 5, _mock_features())
        assert isinstance(result, BookDecomposition)
        assert result.title == "Emma's Adventure"
        assert result.dedication == "For Emma, with love"
        assert len(result.scenes) == 2
        assert result.scenes[0].title == "Title Page"
        assert result.scenes[1].scene_type == "ending"

    @patch("server.mcp.story.httpx.post")
    def test_invalid_pose_normalized_to_standing_front(self, mock_post):
        payload = {
            "title": "Test",
            "dedication": "",
            "scenes": [
                {
                    "id": 1,
                    "title": "Scene",
                    "scene_type": "story_beat",
                    "page_text": "text",
                    "description": "desc",
                    "pose": "yoga_pose_downward_dog",
                    "composition": "center_focus",
                },
            ],
        }
        mock_post.return_value = _llm_response(payload)
        result = decompose_book("Emma", 5, _mock_features())
        assert result.scenes[0].pose == "standing_front"

    @patch("server.mcp.story.httpx.post")
    def test_invalid_composition_normalized_to_center_focus(self, mock_post):
        payload = {
            "title": "Test",
            "dedication": "",
            "scenes": [
                {
                    "id": 1,
                    "title": "Scene",
                    "scene_type": "story_beat",
                    "page_text": "text",
                    "description": "desc",
                    "pose": "front_standing",
                    "composition": "dutch_angle_extreme",
                },
            ],
        }
        mock_post.return_value = _llm_response(payload)
        result = decompose_book("Emma", 5, _mock_features())
        assert result.scenes[0].composition == "center_focus"

    @patch("server.mcp.story.httpx.post")
    def test_orientation_landscape_dims(self, mock_post):
        mock_post.return_value = _llm_response({"title": "T", "dedication": "", "scenes": []})
        result = decompose_book("Emma", 5, _mock_features(), orientation="landscape (wide)")
        assert result.page_dims == (1536, 1024)

    @patch("server.mcp.story.httpx.post")
    def test_orientation_portrait_dims(self, mock_post):
        mock_post.return_value = _llm_response({"title": "T", "dedication": "", "scenes": []})
        result = decompose_book("Emma", 5, _mock_features(), orientation="portrait (tall)")
        assert result.page_dims == (1024, 1536)

    @patch("server.mcp.story.httpx.post")
    def test_orientation_square_dims(self, mock_post):
        mock_post.return_value = _llm_response({"title": "T", "dedication": "", "scenes": []})
        result = decompose_book("Emma", 5, _mock_features(), orientation="square")
        assert result.page_dims == (1024, 1024)

    @patch("server.mcp.story.httpx.post")
    def test_props_parsed_into_prop_spec_tuples(self, mock_post):
        payload = {
            "title": "Test",
            "dedication": "",
            "scenes": [
                {
                    "id": 1,
                    "title": "Scene",
                    "scene_type": "story_beat",
                    "page_text": "text",
                    "description": "desc",
                    "props": [
                        {
                            "name": "sword",
                            "description": "a shiny sword",
                            "scale": "handheld",
                            "placement": "left",
                        },
                        {
                            "name": "castle",
                            "description": "a tall castle",
                            "scale": "environment",
                            "placement": "center",
                        },
                    ],
                },
            ],
        }
        mock_post.return_value = _llm_response(payload)
        result = decompose_book("Emma", 5, _mock_features())
        props = result.scenes[0].props
        assert len(props) == 2
        assert isinstance(props[0], PropSpec)
        assert props[0].name == "sword"
        assert props[0].scale == "handheld"
        assert props[0].placement == "left"
        assert props[1].name == "castle"
        assert props[1].scale == "environment"

    @patch("server.mcp.story.httpx.post")
    def test_style_contract_built_from_response(self, mock_post):
        payload = {
            "title": "Test",
            "dedication": "",
            "style_contract": {
                "art_style": "gouache",
                "color_palette": ["#AABBCC", "#DDEEFF"],
                "lighting": "golden hour",
                "mood": "dreamy",
                "recurring_elements": ["moon", "stars"],
                "negative_prompts": "no scary stuff",
            },
            "scenes": [],
        }
        mock_post.return_value = _llm_response(payload)
        result = decompose_book("Emma", 5, _mock_features())
        sc = result.style_contract
        assert isinstance(sc, StyleContract)
        assert sc.art_style == "gouache"
        assert sc.color_palette == ("#AABBCC", "#DDEEFF")
        assert sc.lighting == "golden hour"
        assert sc.mood == "dreamy"
        assert sc.recurring_elements == ("moon", "stars")
        assert sc.negative_prompts == "no scary stuff"


class TestDecomposeBookEdgeCases:
    @patch("server.mcp.story.httpx.post")
    def test_empty_scenes_list(self, mock_post):
        mock_post.return_value = _llm_response({"title": "Empty", "dedication": "", "scenes": []})
        result = decompose_book("Emma", 5, _mock_features())
        assert result.scenes == []

    @patch("server.mcp.story.httpx.post")
    def test_missing_style_contract_uses_defaults(self, mock_post):
        mock_post.return_value = _llm_response({"title": "NoStyle", "dedication": "", "scenes": []})
        result = decompose_book("Emma", 5, _mock_features())
        sc = result.style_contract
        assert sc.art_style == "warm watercolor children's book illustration"
        assert sc.lighting == "soft warm light"
        assert sc.mood == "whimsical wonder"
        assert sc.color_palette == ()

    @patch("server.mcp.story.httpx.post")
    def test_all_optional_params_forwarded(self, mock_post):
        mock_post.return_value = _llm_response(
            {"title": "Custom", "dedication": "Custom ded", "scenes": []}
        )
        result = decompose_book(
            "Emma",
            5,
            _mock_features(),
            page_count=8,
            orientation="portrait (tall)",
            setting="enchanted forest",
            theme="friendship",
            side_characters="a talking fox",
            title="Custom Title",
            dedication="Custom ded",
            model="some-model",
        )
        assert result.orientation == "portrait (tall)"
        assert result.page_dims == (1024, 1536)
        call_args = mock_post.call_args
        body = call_args.kwargs.get("json", call_args[1].get("json", {}))
        user_msg = body["messages"][1]["content"]
        assert "enchanted forest" in user_msg
        assert "friendship" in user_msg
        assert "a talking fox" in user_msg
