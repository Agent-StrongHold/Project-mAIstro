from server.mcp.canvas_templates import (
    COMPOSITION_ZONES,
    CROUCH_GEO,
    LIGHTING_TOKENS,
    MOOD_TOKENS,
    POSES,
    SCENE_TYPES,
    SITTING_GEO,
    STANDING_GEO,
    STYLE_TOKENS,
    BookPlan,
    CompositionZone,
    Geometry,
    LightingToken,
    MoodToken,
    Pose,
    PropDef,
    SceneDef,
    StyleToken,
    build_background_prompt,
    build_character_design,
    build_character_prompt,
    build_prop_prompt,
    build_scene_template,
    generate_scene_plan,
)

REQUIRED_GEO_FIELDS = (
    "bounds",
    "head_center",
    "head_radius",
    "face_box",
    "shoulder_center",
    "hip_center",
    "ground_y",
)

EXPECTED_POSE_KEYS = [
    "standing_front",
    "standing_3q_left",
    "standing_3q_right",
    "sitting_cross_legged",
    "walking_left",
    "walking_right",
    "running_left",
    "running_right",
    "looking_up",
    "crouching",
    "arms_raised",
    "hugging",
    "sitting_edge",
    "pointing",
]

POSE_REQUIRED_FIELDS = (
    "id",
    "label",
    "body",
    "facing",
    "angle",
    "anchor",
    "scale",
    "arm_position",
    "geo",
)

SLOT_KEYS = {"x", "y", "w", "h"}


class TestGeometryAndPoses:
    def test_standing_geo_fields(self):
        for field in REQUIRED_GEO_FIELDS:
            assert hasattr(STANDING_GEO, field)
        assert isinstance(STANDING_GEO.bounds, dict)
        assert isinstance(STANDING_GEO.head_center, dict)
        assert isinstance(STANDING_GEO.head_radius, float)
        assert isinstance(STANDING_GEO.ground_y, float)

    def test_sitting_geo_fields(self):
        for field in REQUIRED_GEO_FIELDS:
            assert hasattr(SITTING_GEO, field)
        assert SITTING_GEO.anchor_offset == {"x": 0, "y": -0.10}

    def test_crouch_geo_fields(self):
        for field in REQUIRED_GEO_FIELDS:
            assert hasattr(CROUCH_GEO, field)
        assert CROUCH_GEO.anchor_offset == {"x": 0, "y": -0.05}

    def test_poses_count(self):
        assert len(POSES) == 14

    def test_poses_has_expected_keys(self):
        for key in EXPECTED_POSE_KEYS:
            assert key in POSES

    def test_each_pose_has_required_fields(self):
        for key, pose in POSES.items():
            assert isinstance(pose, Pose)
            for field in POSE_REQUIRED_FIELDS:
                assert hasattr(pose, field), f"Pose {key} missing {field}"

    def test_pose_ids_match_dict_keys(self):
        for key, pose in POSES.items():
            assert pose.id == key

    def test_each_pose_has_valid_geo(self):
        for key, pose in POSES.items():
            assert isinstance(pose.geo, Geometry)
            for field in REQUIRED_GEO_FIELDS:
                assert hasattr(pose.geo, field), f"Pose {key} geo missing {field}"


class TestCompositionZones:
    def test_count(self):
        assert len(COMPOSITION_ZONES) == 7

    def test_each_zone_has_character_slot(self):
        for key, zone in COMPOSITION_ZONES.items():
            assert isinstance(zone, CompositionZone)
            assert isinstance(zone.character_slot, dict)
            assert SLOT_KEYS.issubset(zone.character_slot.keys()), (
                f"{key} character_slot missing keys"
            )

    def test_each_zone_has_text_safe(self):
        for key, zone in COMPOSITION_ZONES.items():
            assert isinstance(zone.text_safe, dict)
            assert SLOT_KEYS.issubset(zone.text_safe.keys()), f"{key} text_safe missing keys"


class TestStyleTokens:
    def test_count(self):
        assert len(STYLE_TOKENS) == 7

    def test_each_has_technique_string(self):
        for _key, token in STYLE_TOKENS.items():
            assert isinstance(token, StyleToken)
            assert isinstance(token.technique, str)
            assert len(token.technique) > 0

    def test_edge_softness_range(self):
        for key, token in STYLE_TOKENS.items():
            assert 0.0 <= token.edge_softness <= 1.0, f"{key} edge_softness out of range"


class TestMoodTokens:
    def test_count(self):
        assert len(MOOD_TOKENS) == 6

    def test_all_values_are_floats_0_to_1(self):
        for key, token in MOOD_TOKENS.items():
            assert isinstance(token, MoodToken)
            for attr in ("saturation", "brightness", "warmth", "tension"):
                val = getattr(token, attr)
                assert isinstance(val, float), f"{key}.{attr} not float"
                assert 0.0 <= val <= 1.0, f"{key}.{attr}={val} out of range"


class TestLightingTokens:
    def test_count(self):
        assert len(LIGHTING_TOKENS) == 6

    def test_each_has_direction_and_color_temp(self):
        for _key, token in LIGHTING_TOKENS.items():
            assert isinstance(token, LightingToken)
            assert isinstance(token.direction, str)
            assert len(token.direction) > 0
            assert isinstance(token.color_temp, str)
            assert len(token.color_temp) > 0


class TestSceneTypes:
    def test_count(self):
        assert len(SCENE_TYPES) == 6

    def test_required_keys(self):
        for key in (
            "title_page",
            "dedication",
            "story_beat",
            "emotional_beat",
            "action_beat",
            "ending",
        ):
            assert key in SCENE_TYPES

    def test_title_page_no_character(self):
        assert SCENE_TYPES["title_page"].has_character is False

    def test_dedication_no_character(self):
        assert SCENE_TYPES["dedication"].has_character is False

    def test_story_beat_has_character(self):
        assert SCENE_TYPES["story_beat"].has_character is True

    def test_emotional_beat_has_character(self):
        assert SCENE_TYPES["emotional_beat"].has_character is True

    def test_action_beat_has_character(self):
        assert SCENE_TYPES["action_beat"].has_character is True

    def test_ending_has_character(self):
        assert SCENE_TYPES["ending"].has_character is True


class TestBuildSceneTemplate:
    def test_string_pose_resolves(self):
        sd = SceneDef(type="story_beat", pose="sitting_cross_legged")
        tmpl = build_scene_template(sd)
        assert tmpl.character_slot["pose"].id == "sitting_cross_legged"

    def test_pose_object_passed_through(self):
        pose_obj = POSES["running_left"]
        sd = SceneDef(type="story_beat", pose=pose_obj)
        tmpl = build_scene_template(sd)
        assert tmpl.character_slot["pose"] is pose_obj

    def test_unknown_pose_defaults_to_standing_front(self):
        sd = SceneDef(type="story_beat", pose="nonexistent_pose")
        tmpl = build_scene_template(sd)
        assert tmpl.character_slot["pose"].id == "standing_front"

    def test_string_composition_resolves(self):
        sd = SceneDef(type="story_beat", composition="left_focus")
        tmpl = build_scene_template(sd)
        assert tmpl.composition.id == "left_focus"

    def test_unknown_composition_defaults_to_center_focus(self):
        sd = SceneDef(type="story_beat", composition="bogus_zone")
        tmpl = build_scene_template(sd)
        assert tmpl.composition.id == "center_focus"

    def test_composition_zone_object_passed_through(self):
        zone = COMPOSITION_ZONES["close_up"]
        sd = SceneDef(type="story_beat", composition=zone)
        tmpl = build_scene_template(sd)
        assert tmpl.composition is zone

    def test_props_converted_to_dicts(self):
        props = [
            PropDef(name="wand", description="sparkly wand", placement="right"),
            PropDef(name="hat", description="pointy hat", placement="left"),
        ]
        sd = SceneDef(type="story_beat", props=props)
        tmpl = build_scene_template(sd)
        assert len(tmpl.props) == 2
        assert tmpl.props[0] == {
            "name": "wand",
            "description": "sparkly wand",
            "placement": "right",
        }
        assert tmpl.props[1] == {"name": "hat", "description": "pointy hat", "placement": "left"}

    def test_style_token_default(self):
        sd = SceneDef()
        tmpl = build_scene_template(sd)
        assert tmpl.generation_params["style"] is STYLE_TOKENS["Warm watercolor childrens book"]

    def test_mood_token_default(self):
        sd = SceneDef()
        tmpl = build_scene_template(sd)
        assert tmpl.generation_params["mood"] is MOOD_TOKENS["warm and cozy"]

    def test_lighting_token_default(self):
        sd = SceneDef()
        tmpl = build_scene_template(sd)
        assert tmpl.generation_params["lighting"] is LIGHTING_TOKENS["soft golden hour warmth"]

    def test_custom_tokens_passed_through(self):
        style = StyleToken(
            line_weight=5,
            edge_softness=0.5,
            palette="custom",
            contrast="high",
            detail_level="max",
            technique="custom technique",
            bg_complexity="none",
        )
        mood = MoodToken(saturation=0.1, brightness=0.2, warmth=0.3, tension=0.9)
        lighting = LightingToken(
            direction="back", intensity=1.0, color_temp="neon pink", shadow_softness=0.0
        )
        sd = SceneDef()
        tmpl = build_scene_template(sd, style_token=style, mood_token=mood, lighting_token=lighting)
        assert tmpl.generation_params["style"] is style
        assert tmpl.generation_params["mood"] is mood
        assert tmpl.generation_params["lighting"] is lighting

    def test_title_defaults_to_untitled(self):
        sd = SceneDef(type="story_beat")
        tmpl = build_scene_template(sd)
        assert tmpl.title == "Untitled Scene"

    def test_title_from_scene_def(self):
        sd = SceneDef(type="story_beat", title="My Scene")
        tmpl = build_scene_template(sd)
        assert tmpl.title == "My Scene"


class TestBuildBackgroundPrompt:
    def _make_template(self, mood=None, lighting=None, style=None):
        sd = SceneDef()
        return build_scene_template(sd, style_token=style, mood_token=mood, lighting_token=lighting)

    def test_returns_nonempty_string(self):
        tmpl = self._make_template()
        prompt = build_background_prompt(tmpl)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_contains_no_characters(self):
        tmpl = self._make_template()
        prompt = build_background_prompt(tmpl)
        assert "NO CHARACTERS" in prompt

    def test_with_setting_desc_included(self):
        tmpl = self._make_template()
        prompt = build_background_prompt(tmpl, setting_desc="a magical forest clearing")
        assert "a magical forest clearing" in prompt

    def test_high_tension_contains_dynamic(self):
        mood = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.8)
        tmpl = self._make_template(mood=mood)
        prompt = build_background_prompt(tmpl)
        assert "dynamic" in prompt

    def test_low_tension_contains_peaceful(self):
        mood = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.0)
        tmpl = self._make_template(mood=mood)
        prompt = build_background_prompt(tmpl)
        assert "peaceful" in prompt

    def test_mid_tension_contains_gentle(self):
        mood = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.3)
        tmpl = self._make_template(mood=mood)
        prompt = build_background_prompt(tmpl)
        assert "gentle" in prompt


class TestBuildCharacterPrompt:
    def _make_template(self, mood=None):
        sd = SceneDef()
        return build_scene_template(sd, mood_token=mood)

    def test_returns_nonempty_with_character_design(self):
        tmpl = self._make_template()
        prompt = build_character_prompt(tmpl, "a brave child with red hair")
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "a brave child with red hair" in prompt

    def test_contains_pure_white_background(self):
        tmpl = self._make_template()
        prompt = build_character_prompt(tmpl, "test child")
        assert "PURE WHITE background" in prompt

    def test_with_handheld_props(self):
        tmpl = self._make_template()
        props = [
            PropDef(name="lantern", description="a glowing lantern"),
            PropDef(name="map", description="a treasure map"),
        ]
        prompt = build_character_prompt(tmpl, "test child", handheld_props=props)
        assert "lantern" in prompt
        assert "map" in prompt
        assert "a glowing lantern" in prompt
        assert "a treasure map" in prompt

    def test_empty_props_no_prop_instruction(self):
        tmpl = self._make_template()
        prompt = build_character_prompt(tmpl, "test child", handheld_props=[])
        assert "HOLDING and INTERACTING WITH" not in prompt

    def test_none_props_no_prop_instruction(self):
        tmpl = self._make_template()
        prompt = build_character_prompt(tmpl, "test child", handheld_props=None)
        assert "HOLDING and INTERACTING WITH" not in prompt

    def test_contains_facing_direction(self):
        tmpl = self._make_template()
        prompt = build_character_prompt(tmpl, "test child")
        assert "facing" in prompt

    def test_expression_based_on_mood_tension(self):
        low_tension = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.0)
        tmpl_low = self._make_template(mood=low_tension)
        prompt_low = build_character_prompt(tmpl_low, "test child")
        assert "gentle expression" in prompt_low

        high_tension = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.9)
        tmpl_high = self._make_template(mood=high_tension)
        prompt_high = build_character_prompt(tmpl_high, "test child")
        assert "excited expression" in prompt_high

        mid_tension = MoodToken(saturation=0.5, brightness=0.5, warmth=0.5, tension=0.25)
        tmpl_mid = self._make_template(mood=mid_tension)
        prompt_mid = build_character_prompt(tmpl_mid, "test child")
        assert "curious expression" in prompt_mid


class TestBuildPropPrompt:
    def _make_template(self):
        sd = SceneDef()
        return build_scene_template(sd)

    def test_returns_nonempty_with_description(self):
        tmpl = self._make_template()
        prop = PropDef(
            name="castle", description="a towering stone castle with turrets", scale="environment"
        )
        prompt = build_prop_prompt(tmpl, prop)
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "a towering stone castle with turrets" in prompt

    def test_contains_pure_white_background(self):
        tmpl = self._make_template()
        prop = PropDef(name="tree", description="oak tree", scale="environment")
        prompt = build_prop_prompt(tmpl, prop)
        assert "PURE WHITE background" in prompt

    def test_contains_no_characters(self):
        tmpl = self._make_template()
        prop = PropDef(name="tree", description="oak tree", scale="environment")
        prompt = build_prop_prompt(tmpl, prop)
        assert "NO characters" in prompt

    def test_with_scene_action(self):
        tmpl = self._make_template()
        prop = PropDef(name="boat", description="wooden rowboat", scale="environment")
        prompt = build_prop_prompt(tmpl, prop, scene_action="crossing the river")
        assert "crossing the river" in prompt

    def test_without_scene_action_no_action_reference(self):
        tmpl = self._make_template()
        prop = PropDef(name="boat", description="wooden rowboat", scale="environment")
        prompt = build_prop_prompt(tmpl, prop, scene_action="")
        assert "as seen in scene" not in prompt


class TestBuildCharacterDesign:
    def test_default_values(self):
        result = build_character_design()
        assert "the child" in result
        assert "brown wavy shoulder-length" in result
        assert "warm medium" in result
        assert "brown eyes" in result
        assert "round" in result
        assert "bright smile" in result
        assert "average height for their age" in result
        assert "5-6" in result
        assert "they/them" in result

    def test_custom_values(self):
        result = build_character_design(
            name="Luna",
            pronouns="she/her",
            hair="blonde curly",
            skin_tone="light olive",
            eye_color="green",
            face_shape="oval",
            signature_features="freckles across nose",
            build="tall for her age",
            age="7",
        )
        assert "Luna" in result
        assert "she/her" in result
        assert "blonde curly" in result
        assert "light olive" in result
        assert "green eyes" in result
        assert "oval" in result
        assert "freckles across nose" in result
        assert "tall for her age" in result
        assert "7" in result


class TestGenerateScenePlan:
    def _base_spec(self, **overrides):
        spec = {
            "title": "Test Book",
            "child_name": "Alex",
            "child_age": "6",
            "orientation": "landscape (wide)",
        }
        spec.update(overrides)
        return spec

    def _five_scenes(self):
        return [
            {"title": "Cover", "description": "cover scene"},
            {"title": "Dedication", "description": "dedication scene"},
            {"title": "Scene 1", "description": "first story scene", "scene_type": "story_beat"},
            {"title": "Scene 2", "description": "second story scene", "scene_type": "story_beat"},
            {"title": "Finale", "description": "ending scene"},
        ]

    def test_first_scene_is_title_page(self):
        plan = generate_scene_plan(self._five_scenes(), self._base_spec(dedication="For Mom"))
        assert plan.scenes[0].scene_type == "title_page"

    def test_second_scene_is_dedication_when_dedication_set(self):
        plan = generate_scene_plan(self._five_scenes(), self._base_spec(dedication="For Mom"))
        assert plan.scenes[1].scene_type == "dedication"

    def test_last_scene_is_ending(self):
        plan = generate_scene_plan(self._five_scenes(), self._base_spec(dedication="For Mom"))
        assert plan.scenes[-1].scene_type == "ending"

    def test_middle_scenes_keep_raw_type(self):
        plan = generate_scene_plan(self._five_scenes(), self._base_spec(dedication="For Mom"))
        assert plan.scenes[2].scene_type == "story_beat"
        assert plan.scenes[3].scene_type == "story_beat"

    def test_landscape_dimensions(self):
        plan = generate_scene_plan(
            [{"title": "T"}], self._base_spec(orientation="landscape (wide)")
        )
        assert plan.page_dims == {"w": 1536, "h": 1024}

    def test_portrait_dimensions(self):
        plan = generate_scene_plan([{"title": "T"}], self._base_spec(orientation="portrait"))
        assert plan.page_dims == {"w": 1024, "h": 1536}

    def test_square_dimensions(self):
        plan = generate_scene_plan([{"title": "T"}], self._base_spec(orientation="square"))
        assert plan.page_dims == {"w": 1024, "h": 1024}

    def test_with_characters_list(self):
        spec = self._base_spec(
            characters=[
                {"name": "Alice", "hair": "blonde", "eye_color": "blue", "age": "5"},
                {"name": "Bob", "hair": "black", "eye_color": "brown", "age": "7"},
            ]
        )
        plan = generate_scene_plan([{"title": "T"}], spec)
        assert len(plan.character_designs) == 2
        assert "Alice" in plan.character_designs[0]
        assert "Bob" in plan.character_designs[1]

    def test_without_characters_uses_child_name_age(self):
        plan = generate_scene_plan(
            [{"title": "T"}], self._base_spec(child_name="Zoe", child_age="4")
        )
        assert len(plan.character_designs) == 1
        assert "Zoe" in plan.character_designs[0]
        assert "4" in plan.character_designs[0]

    def test_emotional_beat_default_pose_looking_up(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "Emo", "description": "emo scene", "scene_type": "emotional_beat"},
            {"title": "End", "description": "end"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        pose = plan.scenes[1].character_slot["pose"]
        assert pose.id == "looking_up"

    def test_action_beat_default_pose_running_right(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "Act", "description": "action scene", "scene_type": "action_beat"},
            {"title": "End", "description": "end"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        pose = plan.scenes[1].character_slot["pose"]
        assert pose.id == "running_right"

    def test_ending_default_pose_arms_raised(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "End", "description": "ending"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[-1].scene_type == "ending"
        pose = plan.scenes[-1].character_slot["pose"]
        assert pose.id == "arms_raised"

    def test_other_scene_default_pose_standing_3q_left(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "Mid", "description": "mid scene", "scene_type": "story_beat"},
            {"title": "End", "description": "end"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        pose = plan.scenes[1].character_slot["pose"]
        assert pose.id == "standing_3q_left"

    def test_environment_props_get_prop_prompts(self):
        scenes = [
            {
                "title": "Cover",
                "description": "c",
                "props": [
                    {
                        "name": "castle",
                        "description": "stone castle",
                        "scale": "environment",
                        "placement": "left",
                    },
                ],
            },
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert len(plan.scenes[0].prop_prompts) == 1
        assert plan.scenes[0].prop_prompts[0]["name"] == "castle"
        assert "stone castle" in plan.scenes[0].prop_prompts[0]["prompt"]

    def test_handheld_props_not_in_prop_prompts(self):
        scenes = [
            {
                "title": "Cover",
                "description": "c",
                "props": [
                    {
                        "name": "wand",
                        "description": "magic wand",
                        "scale": "handheld",
                        "placement": "right",
                    },
                ],
            },
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert len(plan.scenes[0].prop_prompts) == 0

    def test_title_page_no_character_prompt(self):
        scenes = [{"title": "Cover", "description": "c"}]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[0].scene_type == "title_page"
        assert plan.scenes[0].character_prompt is None

    def test_dedication_no_character_prompt(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "Ded", "description": "ded"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec(dedication="For you"))
        assert plan.scenes[1].scene_type == "dedication"
        assert plan.scenes[1].character_prompt is None

    def test_story_beat_has_character_prompt(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "S1", "description": "story", "scene_type": "story_beat"},
            {"title": "End", "description": "end"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[1].scene_type == "story_beat"
        assert plan.scenes[1].character_prompt is not None

    def test_book_plan_fields(self):
        plan = generate_scene_plan(
            self._five_scenes(), self._base_spec(dedication="For Mom", title="My Book")
        )
        assert isinstance(plan, BookPlan)
        assert plan.title == "My Book"
        assert plan.dedication == "For Mom"
        assert isinstance(plan.style_token, StyleToken)
        assert isinstance(plan.mood_token, MoodToken)
        assert isinstance(plan.lighting_token, LightingToken)
        assert isinstance(plan.character_design, str)
        assert isinstance(plan.page_dims, dict)
        assert isinstance(plan.orientation, str)
        assert len(plan.scenes) == 5

    def test_custom_art_style(self):
        style_key = "Bold gouache with visible brushstrokes"
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(art_style=style_key),
        )
        assert plan.style_token is STYLE_TOKENS[style_key]

    def test_custom_mood(self):
        mood_key = "exciting and energetic"
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(mood=mood_key),
        )
        assert plan.mood_token is MOOD_TOKENS[mood_key]

    def test_custom_lighting(self):
        light_key = "moonlit and sparkly"
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(lighting=light_key),
        )
        assert plan.lighting_token is LIGHTING_TOKENS[light_key]

    def test_unknown_art_style_defaults(self):
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(art_style="nonexistent style"),
        )
        assert plan.style_token is STYLE_TOKENS["Warm watercolor childrens book"]

    def test_unknown_mood_defaults(self):
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(mood="nonexistent mood"),
        )
        assert plan.mood_token is MOOD_TOKENS["warm and cozy"]

    def test_unknown_lighting_defaults(self):
        plan = generate_scene_plan(
            [{"title": "T"}],
            self._base_spec(lighting="nonexistent lighting"),
        )
        assert plan.lighting_token is LIGHTING_TOKENS["soft golden hour warmth"]

    def test_explicit_pose_overrides_default(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {
                "title": "S1",
                "description": "story",
                "scene_type": "story_beat",
                "pose": "crouching",
            },
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[1].character_slot["pose"].id == "crouching"

    def test_single_scene_is_title_page_and_ending(self):
        scenes = [{"title": "Only", "description": "only scene"}]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert len(plan.scenes) == 1
        assert plan.scenes[0].scene_type == "title_page"

    def test_two_scenes_without_dedication(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {"title": "End", "description": "end"},
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[0].scene_type == "title_page"
        assert plan.scenes[1].scene_type == "ending"

    def test_scene_plan_has_bg_prompt(self):
        plan = generate_scene_plan([{"title": "T", "description": "test desc"}], self._base_spec())
        assert isinstance(plan.scenes[0].bg_prompt, str)
        assert len(plan.scenes[0].bg_prompt) > 0

    def test_handheld_props_included_in_character_prompt(self):
        scenes = [
            {"title": "Cover", "description": "c"},
            {
                "title": "S1",
                "description": "story",
                "scene_type": "story_beat",
                "props": [
                    {
                        "name": "sword",
                        "description": "a wooden sword",
                        "scale": "handheld",
                        "placement": "right",
                    },
                ],
            },
        ]
        plan = generate_scene_plan(scenes, self._base_spec())
        assert plan.scenes[1].character_prompt is not None
        assert "sword" in plan.scenes[1].character_prompt
