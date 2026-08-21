// Template Book Engine — deterministic scene definitions, pose templates, layout constraints
// The AI plugs INTO this structure, not the other way around.

// ── Pose Templates ──────────────────────────────────────────────────────────
// Each pose defines a canonical character slot that both default + child must match.

// All ratios are relative to a 1024x1024 generation canvas (0.0 - 1.0).
// Character is expected to be centered with white background.

function p(id, label, body, facing, angle, anchor, scale, arm_position, geo) {
  return { id, label, body, facing, angle, anchor, scale, arm_position, geo };
}

const STANDING_GEO = {
  bounds: { x: 0.25, y: 0.05, w: 0.50, h: 0.90 },
  head_center: { x: 0.50, y: 0.15 },
  head_radius: 0.10,
  face_box: { x: 0.38, y: 0.06, w: 0.24, h: 0.18 },
  shoulder_center: { x: 0.50, y: 0.30 },
  hip_center: { x: 0.50, y: 0.55 },
  ground_y: 0.95,
  anchor_offset: { x: 0, y: 0 },
};

const SITTING_GEO = {
  bounds: { x: 0.20, y: 0.10, w: 0.60, h: 0.75 },
  head_center: { x: 0.50, y: 0.18 },
  head_radius: 0.10,
  face_box: { x: 0.38, y: 0.09, w: 0.24, h: 0.18 },
  shoulder_center: { x: 0.50, y: 0.33 },
  hip_center: { x: 0.50, y: 0.55 },
  ground_y: 0.85,
  anchor_offset: { x: 0, y: -0.10 },
};

const CROUCH_GEO = {
  bounds: { x: 0.20, y: 0.15, w: 0.60, h: 0.70 },
  head_center: { x: 0.48, y: 0.22 },
  head_radius: 0.10,
  face_box: { x: 0.36, y: 0.13, w: 0.24, h: 0.18 },
  shoulder_center: { x: 0.48, y: 0.37 },
  hip_center: { x: 0.50, y: 0.60 },
  ground_y: 0.85,
  anchor_offset: { x: 0, y: -0.05 },
};

export const POSES = {
  standing_front: p(
    "standing_front", "Standing, facing viewer",
    "standing upright, feet shoulder-width apart", "front", 0,
    "ground_contact", "child_midground",
    "arms at sides, slightly away from body",
    { ...STANDING_GEO, skeleton: "neutral_stand" }
  ),
  standing_3q_left: p(
    "standing_3q_left", "Standing, 3/4 view left",
    "standing, weight on right leg, left leg slightly forward", "three_quarter_left", -30,
    "ground_contact", "child_midground",
    "arms relaxed at sides",
    { ...STANDING_GEO, skeleton: "weight_right", head_center: { x: 0.47, y: 0.15 }, face_box: { x: 0.35, y: 0.06, w: 0.22, h: 0.18 } }
  ),
  standing_3q_right: p(
    "standing_3q_right", "Standing, 3/4 view right",
    "standing, weight on left leg, right leg slightly forward", "three_quarter_right", 30,
    "ground_contact", "child_midground",
    "arms relaxed at sides",
    { ...STANDING_GEO, skeleton: "weight_left", head_center: { x: 0.53, y: 0.15 }, face_box: { x: 0.43, y: 0.06, w: 0.22, h: 0.18 } }
  ),
  sitting_cross_legged: p(
    "sitting_cross_legged", "Sitting cross-legged",
    "sitting cross-legged on the ground", "front", 0,
    "seat_contact", "child_midground",
    "hands resting on knees",
    { ...SITTING_GEO, skeleton: "cross_legged" }
  ),
  walking_left: p(
    "walking_left", "Walking left",
    "mid-stride walking, left foot forward", "profile_left", -90,
    "ground_contact", "child_midground",
    "arms in natural walking swing",
    { ...STANDING_GEO, skeleton: "walk_left", bounds: { x: 0.20, y: 0.05, w: 0.60, h: 0.90 } }
  ),
  walking_right: p(
    "walking_right", "Walking right",
    "mid-stride walking, right foot forward", "profile_right", 90,
    "ground_contact", "child_midground",
    "arms in natural walking swing",
    { ...STANDING_GEO, skeleton: "walk_right", bounds: { x: 0.20, y: 0.05, w: 0.60, h: 0.90 } }
  ),
  running_left: p(
    "running_left", "Running left",
    "running, leaning slightly forward, dynamic pose", "three_quarter_left", -45,
    "ground_contact", "child_midground",
    "arms pumping, one forward one back",
    { ...STANDING_GEO, skeleton: "run_left", bounds: { x: 0.18, y: 0.08, w: 0.64, h: 0.87 }, ground_y: 0.93 }
  ),
  running_right: p(
    "running_right", "Running right",
    "running, leaning slightly forward, dynamic pose", "three_quarter_right", 45,
    "ground_contact", "child_midground",
    "arms pumping, one forward one back",
    { ...STANDING_GEO, skeleton: "run_right", bounds: { x: 0.18, y: 0.08, w: 0.64, h: 0.87 }, ground_y: 0.93 }
  ),
  looking_up: p(
    "looking_up", "Looking up in wonder",
    "standing, head tilted back looking up", "front", 0,
    "ground_contact", "child_midground",
    "arms slightly out from sides",
    { ...STANDING_GEO, skeleton: "look_up", head_center: { x: 0.50, y: 0.12 }, face_box: { x: 0.38, y: 0.04, w: 0.24, h: 0.16 } }
  ),
  crouching: p(
    "crouching", "Crouching / examining",
    "crouching down, knees bent, leaning forward slightly", "three_quarter_left", -30,
    "ground_contact", "child_foreground",
    "one hand reaching toward ground",
    { ...CROUCH_GEO, skeleton: "crouch_left" }
  ),
  arms_raised: p(
    "arms_raised", "Arms raised (joy/surprise)",
    "standing, both arms raised above head", "front", 0,
    "ground_contact", "child_midground",
    "both arms raised high, hands open",
    { ...STANDING_GEO, skeleton: "arms_up", bounds: { x: 0.18, y: 0.02, w: 0.64, h: 0.93 } }
  ),
  hugging: p(
    "hugging", "Hugging something",
    "standing, arms wrapped around an object", "three_quarter_right", 30,
    "ground_contact", "child_midground",
    "arms wrapped around, holding close",
    { ...STANDING_GEO, skeleton: "hug_right", head_center: { x: 0.53, y: 0.15 }, face_box: { x: 0.43, y: 0.06, w: 0.22, h: 0.18 } }
  ),
  sitting_edge: p(
    "sitting_edge", "Sitting on edge (rock/log/bed)",
    "sitting on edge of something, legs dangling", "three_quarter_left", -30,
    "seat_contact", "child_midground",
    "hands gripping edge or resting on lap",
    { ...SITTING_GEO, skeleton: "edge_sit_left", head_center: { x: 0.47, y: 0.18 } }
  ),
  pointing: p(
    "pointing", "Pointing at something",
    "standing, one arm extended pointing", "three_quarter_right", 30,
    "ground_contact", "child_midground",
    "right arm extended pointing, left arm at side",
    { ...STANDING_GEO, skeleton: "point_right", bounds: { x: 0.15, y: 0.05, w: 0.70, h: 0.90 }, head_center: { x: 0.53, y: 0.15 }, face_box: { x: 0.43, y: 0.06, w: 0.22, h: 0.18 } }
  ),
};

// ── Composition Zones ────────────────────────────────────────────────────────
// Define where elements go on a page. All values are ratios (0-1) of page dims.

export const COMPOSITION_ZONES = {
  center_focus: {
    id: "center_focus",
    label: "Character centered",
    character_slot: { x: 0.35, y: 0.25, w: 0.3, h: 0.65 },
    text_safe: { x: 0.05, y: 0.02, w: 0.9, h: 0.2 },
    focus_area: "center",
  },
  left_focus: {
    id: "left_focus",
    label: "Character left, space right",
    character_slot: { x: 0.05, y: 0.2, w: 0.35, h: 0.7 },
    text_safe: { x: 0.45, y: 0.05, w: 0.5, h: 0.25 },
    focus_area: "left",
  },
  right_focus: {
    id: "right_focus",
    label: "Character right, space left",
    character_slot: { x: 0.6, y: 0.2, w: 0.35, h: 0.7 },
    text_safe: { x: 0.05, y: 0.05, w: 0.5, h: 0.25 },
    focus_area: "right",
  },
  wide_establishing: {
    id: "wide_establishing",
    label: "Wide shot, character small",
    character_slot: { x: 0.25, y: 0.5, w: 0.2, h: 0.4 },
    text_safe: { x: 0.05, y: 0.02, w: 0.9, h: 0.15 },
    focus_area: "center_bottom",
  },
  close_up: {
    id: "close_up",
    label: "Close-up, head and shoulders",
    character_slot: { x: 0.2, y: 0.1, w: 0.6, h: 0.7 },
    text_safe: { x: 0.05, y: 0.8, w: 0.9, h: 0.15 },
    focus_area: "center",
  },
  bottom_center: {
    id: "bottom_center",
    label: "Character bottom, sky above",
    character_slot: { x: 0.3, y: 0.45, w: 0.4, h: 0.5 },
    text_safe: { x: 0.05, y: 0.02, w: 0.9, h: 0.15 },
    focus_area: "bottom_center",
  },
  top_text_wide: {
    id: "top_text_wide",
    label: "Text top, wide scene below",
    character_slot: { x: 0.35, y: 0.3, w: 0.3, h: 0.6 },
    text_safe: { x: 0.08, y: 0.03, w: 0.84, h: 0.22 },
    focus_area: "center",
  },
};

// ── Style Tokens ─────────────────────────────────────────────────────────────
// Map UI presets to deterministic generation parameters.

export const STYLE_TOKENS = {
  "Warm watercolor childrens book": {
    line_weight: 0,
    edge_softness: 0.9,
    palette: "warm_pastel_low_sat",
    contrast: "low",
    detail_level: "minimal",
    technique: "wet-on-wet watercolor with soft edges and visible paper texture",
    bg_complexity: "simple_wash",
  },
  "Soft pastel digital illustration": {
    line_weight: 1,
    edge_softness: 0.7,
    palette: "soft_pastel_balanced",
    contrast: "low",
    detail_level: "moderate",
    technique: "digital painting with soft pastel brush strokes and gentle gradients",
    bg_complexity: "layered_gradient",
  },
  "Bold gouache with visible brushstrokes": {
    line_weight: 2,
    edge_softness: 0.3,
    palette: "bold_saturated",
    contrast: "medium_high",
    detail_level: "moderate",
    technique: "gouache paint with thick visible brushstrokes, opaque matte finish",
    bg_complexity: "textured_blocks",
  },
  "Gentle colored pencil sketch": {
    line_weight: 1,
    edge_softness: 0.5,
    palette: "natural_earth_toned",
    contrast: "low",
    detail_level: "high",
    technique: "colored pencil on off-white paper with visible cross-hatching and soft shading",
    bg_complexity: "lightly_sketched",
  },
  "Clean flat vector illustration": {
    line_weight: 3,
    edge_softness: 0.0,
    palette: "bright_primary",
    contrast: "high",
    detail_level: "minimal",
    technique: "flat vector shapes with clean edges, no shading, solid color fills",
    bg_complexity: "geometric_shapes",
  },
  "Whimsical ink and wash": {
    line_weight: 2,
    edge_softness: 0.6,
    palette: "muted_warm",
    contrast: "medium",
    detail_level: "moderate",
    technique: "black ink outlines with watercolor wash fill, slightly loose and playful lines",
    bg_complexity: "ink_splatter_wash",
  },
  "Dreamy airbrushed fantasy": {
    line_weight: 0,
    edge_softness: 0.95,
    palette: "cool_fantasy",
    contrast: "medium_low",
    detail_level: "high",
    technique: "airbrushed soft gradients with ethereal glow effects and no hard edges",
    bg_complexity: "atmospheric_layers",
  },
};

export const MOOD_TOKENS = {
  "warm and cozy": { saturation: 0.6, brightness: 0.7, warmth: 0.8, tension: 0.1 },
  "bright and adventurous": { saturation: 0.8, brightness: 0.9, warmth: 0.5, tension: 0.3 },
  "dreamy and magical": { saturation: 0.5, brightness: 0.6, warmth: 0.3, tension: 0.1 },
  "playful and silly": { saturation: 0.7, brightness: 0.8, warmth: 0.6, tension: 0.2 },
  "calm and gentle": { saturation: 0.4, brightness: 0.7, warmth: 0.5, tension: 0.0 },
  "exciting and energetic": { saturation: 0.9, brightness: 0.85, warmth: 0.4, tension: 0.5 },
};

export const LIGHTING_TOKENS = {
  "soft golden hour warmth": { direction: "low_side", intensity: 0.6, color_temp: "warm_golden", shadow_softness: 0.8 },
  "bright cheerful daylight": { direction: "overhead", intensity: 0.8, color_temp: "neutral_white", shadow_softness: 0.5 },
  "moonlit and sparkly": { direction: "overhead", intensity: 0.4, color_temp: "cool_blue", shadow_softness: 0.9 },
  "dappled forest light": { direction: "high_side", intensity: 0.6, color_temp: "warm_green", shadow_softness: 0.7 },
  "cozy lamplight glow": { direction: "low_front", intensity: 0.5, color_temp: "warm_orange", shadow_softness: 0.85 },
  "natural and neutral": { direction: "overhead", intensity: 0.65, color_temp: "neutral", shadow_softness: 0.6 },
};

// ── Scene Type Definitions ───────────────────────────────────────────────────

export const SCENE_TYPES = {
  title_page: {
    has_text: false,
    has_character: false,
    default_composition: "wide_establishing",
    prompt_hint: "title page illustration, establishing shot of the story world",
  },
  dedication: {
    has_text: true,
    has_character: false,
    default_composition: "wide_establishing",
    prompt_hint: "simple decorative illustration for dedication page",
  },
  story_beat: {
    has_text: true,
    has_character: true,
    default_composition: "center_focus",
    prompt_hint: null,
  },
  emotional_beat: {
    has_text: true,
    has_character: true,
    default_composition: "close_up",
    prompt_hint: "emotional close-up moment",
  },
  action_beat: {
    has_text: true,
    has_character: true,
    default_composition: "left_focus",
    prompt_hint: "dynamic action scene with movement",
  },
  ending: {
    has_text: true,
    has_character: true,
    default_composition: "center_focus",
    prompt_hint: "final scene, resolution, warmth",
  },
};

// ── Template Builder ─────────────────────────────────────────────────────────

export function buildSceneTemplate(sceneDef, styleToken, moodToken, lightingToken) {
  const pose = typeof sceneDef.pose === "string"
    ? POSES[sceneDef.pose] || POSES.standing_front
    : sceneDef.pose || POSES.standing_front;

  const composition = typeof sceneDef.composition === "string"
    ? COMPOSITION_ZONES[sceneDef.composition] || COMPOSITION_ZONES.center_focus
    : sceneDef.composition || COMPOSITION_ZONES.center_focus;

  const style = typeof styleToken === "string"
    ? STYLE_TOKENS[styleToken] || STYLE_TOKENS["Warm watercolor childrens book"]
    : styleToken || STYLE_TOKENS["Warm watercolor childrens book"];

  return {
    scene_type: sceneDef.type || "story_beat",
    title: sceneDef.title || "Untitled Scene",
    page_text: sceneDef.page_text || "",
    description: sceneDef.description || "",

    composition,
    character_slot: {
      pose,
      slot_bounds: composition.character_slot,
    },

    generation_params: {
      style,
      mood: moodToken || MOOD_TOKENS["warm and cozy"],
      lighting: lightingToken || LIGHTING_TOKENS["soft golden hour warmth"],
    },

    props: (sceneDef.props || []).map((p) => ({
      name: p.name,
      description: p.description,
      placement: p.placement || "right",
    })),
  };
}

// ── Prompt Builder ───────────────────────────────────────────────────────────
// Turns structured scene template into controlled generation prompts.
// NO freeform AI prompt construction — deterministic from tokens.

export function buildBackgroundPrompt(template, settingDesc) {
  const { style, mood, lighting } = template.generation_params;
  const parts = [
    style.technique,
    `${style.bg_complexity} background`,
    lighting.color_temp.replace(/_/g, " ") + " lighting",
    `shadow softness ${lighting.shadow_softness}`,
    mood.tension < 0.2 ? "peaceful atmosphere" : mood.tension > 0.4 ? "dynamic atmosphere" : "gentle atmosphere",
    "NO CHARACTERS, NO PEOPLE, NO FIGURES, NO TEXT, NO LETTERS",
    "leave open space for character placement",
    settingDesc,
  ];
  return parts.filter(Boolean).join(". ");
}

export function buildCharacterPrompt(template, characterDesign, sceneAction, handheldProps) {
  const { style, mood, lighting } = template.generation_params;
  const { pose } = template.character_slot;
  const propNames = (handheldProps || []).map((p) => p.name).filter(Boolean);
  const propDescs = (handheldProps || []).map((p) => p.description).filter(Boolean);
  const propInstruction = propNames.length > 0
    ? `The child is HOLDING and INTERACTING WITH ${propNames.join(" and ")}: ${propDescs.join("; ")}. Show the props IN the child's hands or arms, child-sized.`
    : "";
  const parts = [
    style.technique,
    "children's book illustration on PURE WHITE background for compositing",
    characterDesign,
    sceneAction || pose.body,
    propInstruction,
    pose.arm_position !== "arms at sides" ? pose.arm_position : "",
    `facing ${pose.facing.replace(/_/g, " ")}`,
    "child-sized proportions — this is a young child, NOT an adult, everything should be proportionally small",
    lighting.color_temp.replace(/_/g, " ") + " lighting",
    `detail level: ${style.detail_level}`,
    mood.tension < 0.2 ? "gentle expression" : mood.tension > 0.4 ? "excited expression" : "curious expression",
    "consistent character design, same child as reference sheet",
    "The pose and action MUST look natural and active — the child is doing something specific, not standing still",
    "If holding items, show them gripped in hands or tucked under arms at CHILD scale (smaller than you think)",
    "NO background scenery, NO environment, clean white only",
  ];
  return parts.filter(Boolean).join(". ");
}

export function buildCombinedCharacterPrompt(template, characterDesigns, charactersPresent, bookSpec, sceneAction, handheldProps) {
  const { style, mood, lighting } = template.generation_params;
  const { pose } = template.character_slot;
  const propNames = (handheldProps || []).map((p) => p.name).filter(Boolean);
  const propDescs = (handheldProps || []).map((p) => p.description).filter(Boolean);
  const propInstruction = propNames.length > 0
    ? `Characters are HOLDING and INTERACTING WITH ${propNames.join(" and ")}: ${propDescs.join("; ")}. Show props IN hands, child-sized.`
    : "";
  const chars = bookSpec?.characters || [];
  const names = (charactersPresent || []).map((n) => n.toLowerCase().trim());
  const presentDesigns = characterDesigns.filter((_, i) => {
    if (names.length === 0) return i === 0;
    return names.includes((chars[i]?.name || "").toLowerCase().trim());
  });
  const designText = presentDesigns.length > 0
    ? presentDesigns.join(". ALSO PRESENT: ")
    : characterDesigns[0];
  const charCount = presentDesigns.length || 1;
  const countNote = charCount > 1
    ? `${charCount} children together in the scene, interacting naturally with each other`
    : "single child in the scene";
  const parts = [
    style.technique,
    "children's book illustration on PURE WHITE background for compositing",
    designText,
    countNote,
    sceneAction || pose.body,
    propInstruction,
    pose.arm_position !== "arms at sides" ? pose.arm_position : "",
    `facing ${pose.facing.replace(/_/g, " ")}`,
    "child-sized proportions — all characters are young children, NOT adults",
    lighting.color_temp.replace(/_/g, " ") + " lighting",
    `detail level: ${style.detail_level}`,
    mood.tension < 0.2 ? "gentle expressions" : mood.tension > 0.4 ? "excited expressions" : "curious expressions",
    "consistent character designs matching their reference sheets",
    "Poses and actions MUST look natural and active",
    "NO background scenery, NO environment, clean white only",
  ];
  return parts.filter(Boolean).join(". ");
}

export function buildPropPrompt(template, prop, sceneAction) {
  const { style, lighting } = template.generation_params;
  const parts = [
    style.technique,
    "children's book illustration — large scene element (building, vehicle, tree, furniture, etc.)",
    prop.description,
    sceneAction ? `as seen in scene: "${sceneAction}"` : "",
    "This is a LARGE environment element that a child character would stand NEXT TO or INSIDE",
    "Rendered at the correct scale relative to a child — not miniature, not gigantic",
    "on PURE WHITE background for compositing",
    lighting.color_temp.replace(/_/g, " ") + " lighting",
    `detail level: ${style.detail_level}`,
    "NO characters, NO people, isolated object only",
  ];
  return parts.filter(Boolean).join(". ");
}

// ── Default Character Design ─────────────────────────────────────────────────
// Generic character used when no photos are uploaded.

export function buildCharacterDesign(char) {
  const name = char.name || "the child";
  const pronouns = char.pronouns || "they/them";
  const hair = char.hair || "brown wavy shoulder-length";
  const skin = char.skin_tone || "warm medium";
  const eyes = char.eye_color || "brown";
  const face = char.face_shape || "round";
  const features = char.signature_features || "bright smile";
  const build = char.build || "average height for their age";
  const age = char.age || "5-6";

  return [
    `A child named ${name} (${age} years old, ${pronouns})`,
    `${hair} hair`,
    `${skin} skin`,
    `${eyes} eyes`,
    `${face} face shape`,
    `${features}`,
    `${build}`,
    "wearing simple comfortable clothes appropriate for a children's book character",
  ].join(", ");
}

export function buildAllCharacterDesigns(bookSpec) {
  const chars = bookSpec.characters || [];
  if (chars.length === 0) {
    return [buildDefaultCharacterDesign(bookSpec)];
  }
  return chars.map((c) => buildCharacterDesign(c));
}

export function buildDefaultCharacterDesign(bookSpec) {
  return buildCharacterDesign(bookSpec);
}

// ── Scene Plan Generator ─────────────────────────────────────────────────────
// Produces a complete scene plan from AI decomposition + template constraints.

export function generateScenePlan(decomposition, bookSpec) {
  const styleToken = STYLE_TOKENS[bookSpec.art_style] || STYLE_TOKENS["Warm watercolor childrens book"];
  const moodToken = MOOD_TOKENS[bookSpec.mood] || MOOD_TOKENS["warm and cozy"];
  const lightingToken = LIGHTING_TOKENS[bookSpec.lighting] || LIGHTING_TOKENS["soft golden hour warmth"];
  const allDesigns = buildAllCharacterDesigns(bookSpec);
  const characterDesign = allDesigns[0];
  const characterDesigns = allDesigns;

  const orientation = bookSpec.orientation || "landscape (wide)";
  const dims = orientation.includes("portrait")
    ? { w: 1024, h: 1536 }
    : orientation.includes("square")
      ? { w: 1024, h: 1024 }
      : { w: 1536, h: 1024 };

  const scenes = (decomposition.scenes || []).map((raw, idx) => {
    const sceneType = idx === 0 ? "title_page"
      : idx === 1 && bookSpec.dedication ? "dedication"
      : idx === decomposition.scenes.length - 1 ? "ending"
      : raw.scene_type || "story_beat";

    const sceneTypeDef = SCENE_TYPES[sceneType] || SCENE_TYPES.story_beat;

    const composition = raw.composition || sceneTypeDef.default_composition;
    const pose = raw.pose || (sceneType === "emotional_beat" ? "looking_up"
      : sceneType === "action_beat" ? "running_right"
      : sceneType === "ending" ? "arms_raised"
      : "standing_3q_left");

    const template = buildSceneTemplate(
      {
        type: sceneType,
        title: raw.title,
        page_text: raw.page_text || "",
        description: raw.description || raw.title || "",
        pose,
        composition,
        props: raw.props || [],
      },
      styleToken,
      moodToken,
      lightingToken
    );

    const allProps = raw.props || [];
    const handheldProps = allProps.filter((p) => (p.scale || "handheld") === "handheld");
    const environmentProps = allProps.filter((p) => p.scale === "environment");

    return {
      id: raw.id || idx + 1,
      ...template,
      bg_prompt: buildBackgroundPrompt(template, raw.description || ""),
      character_prompt: sceneTypeDef.has_character === false
        ? null
        : buildCombinedCharacterPrompt(template, characterDesigns, raw.characters_present, bookSpec, raw.character_action, handheldProps),
      characters_present: raw.characters_present || [],
      prop_prompts: environmentProps.map((p) => ({
        name: p.name,
        prompt: buildPropPrompt(template, p, raw.character_action),
        placement: p.placement,
      })),
    };
  });

  return {
    title: decomposition.title || bookSpec.title || "My Book",
    dedication: bookSpec.dedication || "",
    style_contract: decomposition.style_contract || {},
    style_token: styleToken,
    mood_token: moodToken,
    lighting_token: lightingToken,
    character_design: characterDesign,
    character_designs: characterDesigns,
    page_dims: dims,
    orientation,
    scenes,
  };
}

export default {
  POSES,
  COMPOSITION_ZONES,
  STYLE_TOKENS,
  MOOD_TOKENS,
  LIGHTING_TOKENS,
  SCENE_TYPES,
  buildSceneTemplate,
  buildBackgroundPrompt,
  buildCharacterPrompt,
  buildPropPrompt,
  buildDefaultCharacterDesign,
  generateScenePlan,
};
