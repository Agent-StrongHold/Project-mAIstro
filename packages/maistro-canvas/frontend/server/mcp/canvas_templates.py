from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Geometry:
    bounds: dict[str, float]
    head_center: dict[str, float]
    head_radius: float
    face_box: dict[str, float]
    shoulder_center: dict[str, float]
    hip_center: dict[str, float]
    ground_y: float
    anchor_offset: dict[str, float] = field(default_factory=lambda: {"x": 0, "y": 0})
    skeleton: str = "neutral_stand"


STANDING_GEO = Geometry(
    bounds={"x": 0.25, "y": 0.05, "w": 0.50, "h": 0.90},
    head_center={"x": 0.50, "y": 0.15},
    head_radius=0.10,
    face_box={"x": 0.38, "y": 0.06, "w": 0.24, "h": 0.18},
    shoulder_center={"x": 0.50, "y": 0.30},
    hip_center={"x": 0.50, "y": 0.55},
    ground_y=0.95,
)

SITTING_GEO = Geometry(
    bounds={"x": 0.20, "y": 0.10, "w": 0.60, "h": 0.75},
    head_center={"x": 0.50, "y": 0.18},
    head_radius=0.10,
    face_box={"x": 0.38, "y": 0.09, "w": 0.24, "h": 0.18},
    shoulder_center={"x": 0.50, "y": 0.33},
    hip_center={"x": 0.50, "y": 0.55},
    ground_y=0.85,
    anchor_offset={"x": 0, "y": -0.10},
)

CROUCH_GEO = Geometry(
    bounds={"x": 0.20, "y": 0.15, "w": 0.60, "h": 0.70},
    head_center={"x": 0.48, "y": 0.22},
    head_radius=0.10,
    face_box={"x": 0.36, "y": 0.13, "w": 0.24, "h": 0.18},
    shoulder_center={"x": 0.48, "y": 0.37},
    hip_center={"x": 0.50, "y": 0.60},
    ground_y=0.85,
    anchor_offset={"x": 0, "y": -0.05},
)


@dataclass(frozen=True)
class Pose:
    id: str
    label: str
    body: str
    facing: str
    angle: int
    anchor: str
    scale: str
    arm_position: str
    geo: Geometry


POSES: dict[str, Pose] = {
    "standing_front": Pose(
        "standing_front",
        "Standing, facing viewer",
        "standing upright, feet shoulder-width apart",
        "front",
        0,
        "ground_contact",
        "child_midground",
        "arms at sides, slightly away from body",
        Geometry(**{**vars(STANDING_GEO), "skeleton": "neutral_stand"}),
    ),
    "standing_3q_left": Pose(
        "standing_3q_left",
        "Standing, 3/4 view left",
        "standing, weight on right leg, left leg slightly forward",
        "three_quarter_left",
        -30,
        "ground_contact",
        "child_midground",
        "arms relaxed at sides",
        Geometry(
            bounds=STANDING_GEO.bounds,
            head_center={"x": 0.47, "y": 0.15},
            head_radius=0.10,
            face_box={"x": 0.35, "y": 0.06, "w": 0.22, "h": 0.18},
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="weight_right",
        ),
    ),
    "standing_3q_right": Pose(
        "standing_3q_right",
        "Standing, 3/4 view right",
        "standing, weight on left leg, right leg slightly forward",
        "three_quarter_right",
        30,
        "ground_contact",
        "child_midground",
        "arms relaxed at sides",
        Geometry(
            bounds=STANDING_GEO.bounds,
            head_center={"x": 0.53, "y": 0.15},
            head_radius=0.10,
            face_box={"x": 0.43, "y": 0.06, "w": 0.22, "h": 0.18},
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="weight_left",
        ),
    ),
    "sitting_cross_legged": Pose(
        "sitting_cross_legged",
        "Sitting cross-legged",
        "sitting cross-legged on the ground",
        "front",
        0,
        "seat_contact",
        "child_midground",
        "hands resting on knees",
        Geometry(**{**vars(SITTING_GEO), "skeleton": "cross_legged"}),
    ),
    "walking_left": Pose(
        "walking_left",
        "Walking left",
        "mid-stride walking, left foot forward",
        "profile_left",
        -90,
        "ground_contact",
        "child_midground",
        "arms in natural walking swing",
        Geometry(
            bounds={"x": 0.20, "y": 0.05, "w": 0.60, "h": 0.90},
            head_center=STANDING_GEO.head_center,
            head_radius=0.10,
            face_box=STANDING_GEO.face_box,
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="walk_left",
        ),
    ),
    "walking_right": Pose(
        "walking_right",
        "Walking right",
        "mid-stride walking, right foot forward",
        "profile_right",
        90,
        "ground_contact",
        "child_midground",
        "arms in natural walking swing",
        Geometry(
            bounds={"x": 0.20, "y": 0.05, "w": 0.60, "h": 0.90},
            head_center=STANDING_GEO.head_center,
            head_radius=0.10,
            face_box=STANDING_GEO.face_box,
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="walk_right",
        ),
    ),
    "running_left": Pose(
        "running_left",
        "Running left",
        "running, leaning slightly forward, dynamic pose",
        "three_quarter_left",
        -45,
        "ground_contact",
        "child_midground",
        "arms pumping, one forward one back",
        Geometry(
            bounds={"x": 0.18, "y": 0.08, "w": 0.64, "h": 0.87},
            head_center=STANDING_GEO.head_center,
            head_radius=0.10,
            face_box=STANDING_GEO.face_box,
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.93,
            skeleton="run_left",
        ),
    ),
    "running_right": Pose(
        "running_right",
        "Running right",
        "running, leaning slightly forward, dynamic pose",
        "three_quarter_right",
        45,
        "ground_contact",
        "child_midground",
        "arms pumping, one forward one back",
        Geometry(
            bounds={"x": 0.18, "y": 0.08, "w": 0.64, "h": 0.87},
            head_center=STANDING_GEO.head_center,
            head_radius=0.10,
            face_box=STANDING_GEO.face_box,
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.93,
            skeleton="run_right",
        ),
    ),
    "looking_up": Pose(
        "looking_up",
        "Looking up in wonder",
        "standing, head tilted back looking up",
        "front",
        0,
        "ground_contact",
        "child_midground",
        "arms slightly out from sides",
        Geometry(
            bounds=STANDING_GEO.bounds,
            head_center={"x": 0.50, "y": 0.12},
            head_radius=0.10,
            face_box={"x": 0.38, "y": 0.04, "w": 0.24, "h": 0.16},
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="look_up",
        ),
    ),
    "crouching": Pose(
        "crouching",
        "Crouching / examining",
        "crouching down, knees bent, leaning forward slightly",
        "three_quarter_left",
        -30,
        "ground_contact",
        "child_foreground",
        "one hand reaching toward ground",
        Geometry(**{**vars(CROUCH_GEO), "skeleton": "crouch_left"}),
    ),
    "arms_raised": Pose(
        "arms_raised",
        "Arms raised (joy/surprise)",
        "standing, both arms raised above head",
        "front",
        0,
        "ground_contact",
        "child_midground",
        "both arms raised high, hands open",
        Geometry(
            bounds={"x": 0.18, "y": 0.02, "w": 0.64, "h": 0.93},
            head_center=STANDING_GEO.head_center,
            head_radius=0.10,
            face_box=STANDING_GEO.face_box,
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="arms_up",
        ),
    ),
    "hugging": Pose(
        "hugging",
        "Hugging something",
        "standing, arms wrapped around an object",
        "three_quarter_right",
        30,
        "ground_contact",
        "child_midground",
        "arms wrapped around, holding close",
        Geometry(
            bounds=STANDING_GEO.bounds,
            head_center={"x": 0.53, "y": 0.15},
            head_radius=0.10,
            face_box={"x": 0.43, "y": 0.06, "w": 0.22, "h": 0.18},
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="hug_right",
        ),
    ),
    "sitting_edge": Pose(
        "sitting_edge",
        "Sitting on edge (rock/log/bed)",
        "sitting on edge of something, legs dangling",
        "three_quarter_left",
        -30,
        "seat_contact",
        "child_midground",
        "hands gripping edge or resting on lap",
        Geometry(
            bounds=SITTING_GEO.bounds,
            head_center={"x": 0.47, "y": 0.18},
            head_radius=0.10,
            face_box=SITTING_GEO.face_box,
            shoulder_center=SITTING_GEO.shoulder_center,
            hip_center=SITTING_GEO.hip_center,
            ground_y=0.85,
            anchor_offset=SITTING_GEO.anchor_offset,
            skeleton="edge_sit_left",
        ),
    ),
    "pointing": Pose(
        "pointing",
        "Pointing at something",
        "standing, one arm extended pointing",
        "three_quarter_right",
        30,
        "ground_contact",
        "child_midground",
        "right arm extended pointing, left arm at side",
        Geometry(
            bounds={"x": 0.15, "y": 0.05, "w": 0.70, "h": 0.90},
            head_center={"x": 0.53, "y": 0.15},
            head_radius=0.10,
            face_box={"x": 0.43, "y": 0.06, "w": 0.22, "h": 0.18},
            shoulder_center=STANDING_GEO.shoulder_center,
            hip_center=STANDING_GEO.hip_center,
            ground_y=0.95,
            skeleton="point_right",
        ),
    ),
}


@dataclass(frozen=True)
class CompositionZone:
    id: str
    label: str
    character_slot: dict[str, float]
    text_safe: dict[str, float]
    focus_area: str


COMPOSITION_ZONES: dict[str, CompositionZone] = {
    "center_focus": CompositionZone(
        "center_focus",
        "Character centered",
        {"x": 0.35, "y": 0.25, "w": 0.3, "h": 0.65},
        {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.2},
        "center",
    ),
    "left_focus": CompositionZone(
        "left_focus",
        "Character left, space right",
        {"x": 0.05, "y": 0.2, "w": 0.35, "h": 0.7},
        {"x": 0.45, "y": 0.05, "w": 0.5, "h": 0.25},
        "left",
    ),
    "right_focus": CompositionZone(
        "right_focus",
        "Character right, space left",
        {"x": 0.6, "y": 0.2, "w": 0.35, "h": 0.7},
        {"x": 0.05, "y": 0.05, "w": 0.5, "h": 0.25},
        "right",
    ),
    "wide_establishing": CompositionZone(
        "wide_establishing",
        "Wide shot, character small",
        {"x": 0.25, "y": 0.5, "w": 0.2, "h": 0.4},
        {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.15},
        "center_bottom",
    ),
    "close_up": CompositionZone(
        "close_up",
        "Close-up, head and shoulders",
        {"x": 0.2, "y": 0.1, "w": 0.6, "h": 0.7},
        {"x": 0.05, "y": 0.8, "w": 0.9, "h": 0.15},
        "center",
    ),
    "bottom_center": CompositionZone(
        "bottom_center",
        "Character bottom, sky above",
        {"x": 0.3, "y": 0.45, "w": 0.4, "h": 0.5},
        {"x": 0.05, "y": 0.02, "w": 0.9, "h": 0.15},
        "bottom_center",
    ),
    "top_text_wide": CompositionZone(
        "top_text_wide",
        "Text top, wide scene below",
        {"x": 0.35, "y": 0.3, "w": 0.3, "h": 0.6},
        {"x": 0.08, "y": 0.03, "w": 0.84, "h": 0.22},
        "center",
    ),
}


@dataclass(frozen=True)
class StyleToken:
    line_weight: int
    edge_softness: float
    palette: str
    contrast: str
    detail_level: str
    technique: str
    bg_complexity: str


STYLE_TOKENS: dict[str, StyleToken] = {
    "Warm watercolor childrens book": StyleToken(
        0,
        0.9,
        "warm_pastel_low_sat",
        "low",
        "minimal",
        "wet-on-wet watercolor with soft edges and visible paper texture",
        "simple_wash",
    ),
    "Soft pastel digital illustration": StyleToken(
        1,
        0.7,
        "soft_pastel_balanced",
        "low",
        "moderate",
        "digital painting with soft pastel brush strokes and gentle gradients",
        "layered_gradient",
    ),
    "Bold gouache with visible brushstrokes": StyleToken(
        2,
        0.3,
        "bold_saturated",
        "medium_high",
        "moderate",
        "gouache paint with thick visible brushstrokes, opaque matte finish",
        "textured_blocks",
    ),
    "Gentle colored pencil sketch": StyleToken(
        1,
        0.5,
        "natural_earth_toned",
        "low",
        "high",
        "colored pencil on off-white paper with visible cross-hatching and soft shading",
        "lightly_sketched",
    ),
    "Clean flat vector illustration": StyleToken(
        3,
        0.0,
        "bright_primary",
        "high",
        "minimal",
        "flat vector shapes with clean edges, no shading, solid color fills",
        "geometric_shapes",
    ),
    "Whimsical ink and wash": StyleToken(
        2,
        0.6,
        "muted_warm",
        "medium",
        "moderate",
        "black ink outlines with watercolor wash fill, slightly loose and playful lines",
        "ink_splatter_wash",
    ),
    "Dreamy airbrushed fantasy": StyleToken(
        0,
        0.95,
        "cool_fantasy",
        "medium_low",
        "high",
        "airbrushed soft gradients with ethereal glow effects and no hard edges",
        "atmospheric_layers",
    ),
}


@dataclass(frozen=True)
class MoodToken:
    saturation: float
    brightness: float
    warmth: float
    tension: float


MOOD_TOKENS: dict[str, MoodToken] = {
    "warm and cozy": MoodToken(0.6, 0.7, 0.8, 0.1),
    "bright and adventurous": MoodToken(0.8, 0.9, 0.5, 0.3),
    "dreamy and magical": MoodToken(0.5, 0.6, 0.3, 0.1),
    "playful and silly": MoodToken(0.7, 0.8, 0.6, 0.2),
    "calm and gentle": MoodToken(0.4, 0.7, 0.5, 0.0),
    "exciting and energetic": MoodToken(0.9, 0.85, 0.4, 0.5),
}


@dataclass(frozen=True)
class LightingToken:
    direction: str
    intensity: float
    color_temp: str
    shadow_softness: float


LIGHTING_TOKENS: dict[str, LightingToken] = {
    "soft golden hour warmth": LightingToken("low_side", 0.6, "warm golden", 0.8),
    "bright cheerful daylight": LightingToken("overhead", 0.8, "neutral white", 0.5),
    "moonlit and sparkly": LightingToken("overhead", 0.4, "cool blue", 0.9),
    "dappled forest light": LightingToken("high_side", 0.6, "warm green", 0.7),
    "cozy lamplight glow": LightingToken("low_front", 0.5, "warm orange", 0.85),
    "natural and neutral": LightingToken("overhead", 0.65, "neutral", 0.6),
}


@dataclass(frozen=True)
class SceneType:
    has_text: bool
    has_character: bool
    default_composition: str
    prompt_hint: str | None


SCENE_TYPES: dict[str, SceneType] = {
    "title_page": SceneType(
        False,
        False,
        "wide_establishing",
        "title page illustration, establishing shot of the story world",
    ),
    "dedication": SceneType(
        True, False, "wide_establishing", "simple decorative illustration for dedication page"
    ),
    "story_beat": SceneType(True, True, "center_focus", None),
    "emotional_beat": SceneType(True, True, "close_up", "emotional close-up moment"),
    "action_beat": SceneType(True, True, "left_focus", "dynamic action scene with movement"),
    "ending": SceneType(True, True, "center_focus", "final scene, resolution, warmth"),
}


@dataclass
class PropDef:
    name: str
    description: str
    placement: str = "right"
    scale: str = "handheld"


@dataclass
class SceneDef:
    type: str = "story_beat"
    title: str = ""
    page_text: str = ""
    description: str = ""
    pose: str | Pose = "standing_front"
    composition: str | CompositionZone = "center_focus"
    props: list[PropDef] = field(default_factory=list)
    character_action: str = ""


@dataclass
class SceneTemplate:
    scene_type: str
    title: str
    page_text: str
    description: str
    composition: CompositionZone
    character_slot: dict[str, Any]
    generation_params: dict[str, Any]
    props: list[dict[str, str]]


def build_scene_template(
    scene_def: SceneDef,
    style_token: StyleToken | None = None,
    mood_token: MoodToken | None = None,
    lighting_token: LightingToken | None = None,
) -> SceneTemplate:
    pose = (
        scene_def.pose
        if isinstance(scene_def.pose, Pose)
        else POSES.get(scene_def.pose, POSES["standing_front"])
    )
    composition = (
        scene_def.composition
        if isinstance(scene_def.composition, CompositionZone)
        else COMPOSITION_ZONES.get(str(scene_def.composition), COMPOSITION_ZONES["center_focus"])
    )
    style = style_token or STYLE_TOKENS["Warm watercolor childrens book"]
    mood = mood_token or MOOD_TOKENS["warm and cozy"]
    lighting = lighting_token or LIGHTING_TOKENS["soft golden hour warmth"]

    return SceneTemplate(
        scene_type=scene_def.type,
        title=scene_def.title or "Untitled Scene",
        page_text=scene_def.page_text,
        description=scene_def.description,
        composition=composition,
        character_slot={"pose": pose, "slot_bounds": composition.character_slot},
        generation_params={"style": style, "mood": mood, "lighting": lighting},
        props=[
            {"name": p.name, "description": p.description, "placement": p.placement}
            for p in scene_def.props
        ],
    )


def build_background_prompt(template: SceneTemplate, setting_desc: str = "") -> str:
    style = template.generation_params["style"]
    mood = template.generation_params["mood"]
    lighting = template.generation_params["lighting"]

    parts = [
        style.technique,
        f"{style.bg_complexity} background",
        lighting.color_temp.replace("_", " ") + " lighting",
        f"shadow softness {lighting.shadow_softness}",
        "peaceful atmosphere"
        if mood.tension < 0.2
        else "dynamic atmosphere"
        if mood.tension > 0.4
        else "gentle atmosphere",
        "NO CHARACTERS, NO PEOPLE, NO FIGURES, NO TEXT, NO LETTERS",
        "leave open space for character placement",
    ]
    if setting_desc:
        parts.append(setting_desc)
    return ". ".join(p for p in parts if p)


def build_character_prompt(
    template: SceneTemplate,
    character_design: str,
    scene_action: str = "",
    handheld_props: list[PropDef] | None = None,
) -> str:
    style = template.generation_params["style"]
    mood = template.generation_params["mood"]
    lighting = template.generation_params["lighting"]
    pose = template.character_slot["pose"]

    prop_names = [p.name for p in (handheld_props or []) if p.name]
    prop_descs = [p.description for p in (handheld_props or []) if p.description]
    prop_instruction = ""
    if prop_names:
        prop_instruction = (
            f"The child is HOLDING and INTERACTING WITH {' and '.join(prop_names)}: "
            f"{'; '.join(prop_descs)}. Show the props IN the child's hands or arms, child-sized."
        )

    parts = [
        style.technique,
        "children's book illustration on PURE WHITE background for compositing",
        character_design,
        scene_action or pose.body,
        prop_instruction,
        pose.arm_position if pose.arm_position != "arms at sides" else "",
        f"facing {pose.facing.replace('_', ' ')}",
        "child-sized proportions — this is a young child, NOT an adult, "
        "everything should be proportionally small",
        lighting.color_temp.replace("_", " ") + " lighting",
        f"detail level: {style.detail_level}",
        "gentle expression"
        if mood.tension < 0.2
        else "excited expression"
        if mood.tension > 0.4
        else "curious expression",
        "consistent character design, same child as reference sheet",
        "The pose and action MUST look natural and active — the child is "
        "doing something specific, not standing still",
        "If holding items, show them gripped in hands or tucked under arms "
        "at CHILD scale (smaller than you think)",
        "NO background scenery, NO environment, clean white only",
    ]
    return ". ".join(p for p in parts if p)


def build_prop_prompt(template: SceneTemplate, prop: PropDef, scene_action: str = "") -> str:
    style = template.generation_params["style"]
    lighting = template.generation_params["lighting"]

    parts = [
        style.technique,
        "children's book illustration — large scene element "
        "(building, vehicle, tree, furniture, etc.)",
        prop.description,
        f'as seen in scene: "{scene_action}"' if scene_action else "",
        "This is a LARGE environment element that a child character would stand NEXT TO or INSIDE",
        "Rendered at the correct scale relative to a child — not miniature, not gigantic",
        "on PURE WHITE background for compositing",
        lighting.color_temp.replace("_", " ") + " lighting",
        f"detail level: {style.detail_level}",
        "NO characters, NO people, isolated object only",
    ]
    return ". ".join(p for p in parts if p)


def build_character_design(
    name: str = "the child",
    pronouns: str = "they/them",
    hair: str = "brown wavy shoulder-length",
    skin_tone: str = "warm medium",
    eye_color: str = "brown",
    face_shape: str = "round",
    signature_features: str = "bright smile",
    build: str = "average height for their age",
    age: str = "5-6",
) -> str:
    return ", ".join(
        [
            f"A child named {name} ({age} years old, {pronouns})",
            f"{hair} hair",
            f"{skin_tone} skin",
            f"{eye_color} eyes",
            f"{face_shape} face shape",
            signature_features,
            build,
            "wearing simple comfortable clothes appropriate for a children's book character",
        ]
    )


@dataclass
class ScenePlan:
    id: int
    scene_type: str
    title: str
    page_text: str
    description: str
    composition: CompositionZone
    character_slot: dict[str, Any]
    generation_params: dict[str, Any]
    props: list[dict[str, str]]
    bg_prompt: str
    character_prompt: str | None
    prop_prompts: list[dict[str, str]]


@dataclass
class BookPlan:
    title: str
    dedication: str
    style_token: StyleToken
    mood_token: MoodToken
    lighting_token: LightingToken
    character_design: str
    character_designs: list[str]
    page_dims: dict[str, int]
    orientation: str
    scenes: list[ScenePlan]


def _resolve_page_dims(orientation: str) -> dict[str, int]:
    """Map an orientation string to canvas dimensions."""
    if "portrait" in orientation:
        return {"w": 1024, "h": 1536}
    if "square" in orientation:
        return {"w": 1024, "h": 1024}
    return {"w": 1536, "h": 1024}


def _classify_scene_type(idx: int, raw: dict, scenes_raw: list[dict], book_spec: dict) -> str:
    """Determine the scene type for the scene at ``idx``."""
    if idx == 0:
        return "title_page"
    if idx == 1 and book_spec.get("dedication"):
        return "dedication"
    if idx == len(scenes_raw) - 1:
        return "ending"
    return raw.get("scene_type", "story_beat")


_DEFAULT_POSES: dict[str, str] = {
    "emotional_beat": "looking_up",
    "action_beat": "running_right",
    "ending": "arms_raised",
}


def _resolve_pose_name(raw: dict, scene_type: str) -> str:
    """Resolve an explicit pose or fall back to a scene-type default."""
    pose_name = raw.get("pose")
    if pose_name:
        return str(pose_name)
    return _DEFAULT_POSES.get(scene_type, "standing_3q_left")


def _build_scene_plan(
    idx: int,
    raw: dict,
    scenes_raw: list[dict],
    book_spec: dict,
    character_design: object,
    style_token: object,
    mood_token: object,
    lighting_token: object,
) -> ScenePlan:
    """Build a single ScenePlan from a raw scene entry."""
    scene_type = _classify_scene_type(idx, raw, scenes_raw, book_spec)
    scene_type_def = SCENE_TYPES.get(scene_type, SCENE_TYPES["story_beat"])

    composition = raw.get("composition", scene_type_def.default_composition)
    pose_name = _resolve_pose_name(raw, scene_type)

    prop_defs = [
        PropDef(
            name=p.get("name", ""),
            description=p.get("description", ""),
            placement=p.get("placement", "right"),
            scale=p.get("scale", "handheld"),
        )
        for p in raw.get("props", [])
    ]

    scene_def = SceneDef(
        type=scene_type,
        title=raw.get("title", ""),
        page_text=raw.get("page_text", ""),
        description=raw.get("description", raw.get("title", "")),
        pose=pose_name,
        composition=composition,
        props=prop_defs,
        character_action=raw.get("character_action", ""),
    )

    template = build_scene_template(scene_def, style_token, mood_token, lighting_token)

    handheld = [p for p in prop_defs if p.scale == "handheld"]
    environment = [p for p in prop_defs if p.scale == "environment"]

    char_prompt = None
    if scene_type_def.has_character:
        char_prompt = build_character_prompt(
            template, character_design, scene_def.character_action, handheld
        )

    return ScenePlan(
        id=raw.get("id", idx + 1),
        scene_type=template.scene_type,
        title=template.title,
        page_text=template.page_text,
        description=template.description,
        composition=template.composition,
        character_slot=template.character_slot,
        generation_params=template.generation_params,
        props=template.props,
        bg_prompt=build_background_prompt(template, scene_def.description),
        character_prompt=char_prompt,
        prop_prompts=[
            {
                "name": p.name,
                "prompt": build_prop_prompt(template, p, scene_def.character_action),
                "placement": p.placement,
            }
            for p in environment
        ],
    )


def generate_scene_plan(
    scenes_raw: list[dict],
    book_spec: dict,
) -> BookPlan:
    style_token = STYLE_TOKENS.get(
        book_spec.get("art_style", ""), STYLE_TOKENS["Warm watercolor childrens book"]
    )
    mood_token = MOOD_TOKENS.get(book_spec.get("mood", ""), MOOD_TOKENS["warm and cozy"])
    lighting_token = LIGHTING_TOKENS.get(
        book_spec.get("lighting", ""), LIGHTING_TOKENS["soft golden hour warmth"]
    )

    characters = book_spec.get("characters", [])
    if characters:
        character_designs = [
            build_character_design(
                name=c.get("name", "the child"),
                pronouns=c.get("pronouns", "they/them"),
                hair=c.get("hair", "brown wavy shoulder-length"),
                skin_tone=c.get("skin_tone", "warm medium"),
                eye_color=c.get("eye_color", "brown"),
                face_shape=c.get("face_shape", "round"),
                signature_features=c.get("signature_features", "bright smile"),
                build=c.get("build", "average height for their age"),
                age=c.get("age", "5-6"),
            )
            for c in characters
        ]
    else:
        character_designs = [
            build_character_design(
                name=book_spec.get("child_name", "the child"),
                age=str(book_spec.get("child_age", "5-6")),
            )
        ]

    character_design = character_designs[0]

    orientation = book_spec.get("orientation", "landscape (wide)")
    dims = _resolve_page_dims(orientation)

    scenes = [
        _build_scene_plan(
            idx,
            raw,
            scenes_raw,
            book_spec,
            character_design,
            style_token,
            mood_token,
            lighting_token,
        )
        for idx, raw in enumerate(scenes_raw)
    ]

    return BookPlan(
        title=book_spec.get("title", "My Book"),
        dedication=book_spec.get("dedication", ""),
        style_token=style_token,
        mood_token=mood_token,
        lighting_token=lighting_token,
        character_design=character_design,
        character_designs=character_designs,
        page_dims=dims,
        orientation=orientation,
        scenes=scenes,
    )
