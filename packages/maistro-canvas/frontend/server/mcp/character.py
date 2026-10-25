from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

CONDUCTOR_URL = "http://localhost:8100"
LITELLM_URL = "http://localhost:4000"
LITELLM_KEY = os.environ.get("LITELLM_API_KEY", "")

VISION_MODEL = "google-gemini-2.5-flash"
IMAGE_MODEL = "google-gemini-2.5-flash-image"

POSES = (
    "front_standing",
    "front_waving",
    "front_running",
    "front_sitting",
    "side_walking_left",
    "side_walking_right",
    "side_running",
    "back_standing",
    "back_waving",
    "three_quarter_left",
    "three_quarter_right",
    "looking_up",
    "looking_down",
)

POSE_LABELS = {
    "front_standing": "Front Standing",
    "front_waving": "Front Waving",
    "front_running": "Front Running",
    "front_sitting": "Front Sitting",
    "side_walking_left": "Side Walk Left",
    "side_walking_right": "Side Walk Right",
    "side_running": "Side Running",
    "back_standing": "Back Standing",
    "back_waving": "Back Waving",
    "three_quarter_left": "3/4 Left",
    "three_quarter_right": "3/4 Right",
    "looking_up": "Looking Up",
    "looking_down": "Looking Down",
}

GRID_COLS = 4
GRID_ROWS = 4
HERO_CELL = (3, 0)
CELL_LABELS_TOP = {
    (0, 0): "front_standing",
    (1, 0): "front_waving",
    (2, 0): "front_running",
    (3, 0): "front_sitting",
    (0, 1): "side_walk_L",
    (1, 1): "side_walk_R",
    (2, 1): "side_running",
    (3, 1): "back_standing",
    (0, 2): "back_waving",
    (1, 2): "3/4 left",
    (2, 2): "3/4 right",
    (3, 2): "look_up",
    (0, 3): "look_down",
    (1, 3): "(empty)",
    (2, 3): "(empty)",
    (3, 3): "HERO: front_standing",
}

POSE_BODY = {
    "front_standing": (
        "standing upright facing the viewer, feet shoulder-width apart, arms relaxed at sides"
    ),
    "front_waving": "standing facing viewer, one hand raised waving enthusiastically",
    "front_running": "running toward the viewer, dynamic pose, arms pumping",
    "front_sitting": "sitting cross-legged on the ground facing the viewer, hands on knees",
    "side_walking_left": "walking to the left in profile, mid-stride, arms swinging naturally",
    "side_walking_right": "walking to the right in profile, mid-stride, arms swinging naturally",
    "side_running": "running to the right in profile, leaning forward, arms pumping",
    "back_standing": "standing upright facing away from the viewer, arms at sides",
    "back_waving": "standing facing away, one arm raised waving over shoulder",
    "three_quarter_left": "standing at 3/4 angle facing left, weight on back foot",
    "three_quarter_right": "standing at 3/4 angle facing right, weight on back foot",
    "looking_up": "standing facing viewer, head tilted back looking up in wonder",
    "looking_down": "standing facing viewer, head tilted down looking at something on the ground",
}

POSE_FACING = {
    "front_standing": "front",
    "front_waving": "front",
    "front_running": "front",
    "front_sitting": "front",
    "side_walking_left": "profile_left",
    "side_walking_right": "profile_right",
    "side_running": "profile_right",
    "back_standing": "back",
    "back_waving": "back",
    "three_quarter_left": "three_quarter_left",
    "three_quarter_right": "three_quarter_right",
    "looking_up": "front",
    "looking_down": "front",
}


@dataclass(frozen=True)
class CharacterFeatures:
    hair: str
    skin_tone: str
    eye_color: str
    face_shape: str
    age_style: str
    body_type: str
    signature_features: tuple[str, ...]
    typical_expression: str


@dataclass
class CharacterSheet:
    features: CharacterFeatures
    sheet_image: Image.Image | None = None
    sheet_image_bytes: bytes | None = None
    pose_crops: dict[str, Image.Image] = field(default_factory=dict)
    pose_image_bytes: dict[str, bytes] = field(default_factory=dict)
    quality_score: float = 0.0
    quality_notes: str = ""


def _pil_to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/{fmt.lower()};base64,{b64}"


def _pil_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _bytes_to_pil(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _resolve_image_url(
    photo_path: str | Path | None,
    photo_bytes: bytes | None,
    photo_data_url: str | None,
) -> str:
    """Resolve a data/URL string for the vision request from one of the inputs."""
    if photo_data_url:
        return photo_data_url
    if photo_bytes:
        b64 = base64.b64encode(photo_bytes).decode()
        return f"data:image/jpeg;base64,{b64}"
    if photo_path:
        path = Path(photo_path)
        img = Image.open(path)
        fmt = img.format or "PNG"
        return _pil_to_data_url(img, fmt)
    raise ValueError("Must provide one of: photo_path, photo_bytes, photo_data_url")


def _extract_json_object(text: str) -> str:
    """Strip any markdown code fence and isolate the JSON object in ``text``."""
    if text.startswith("```"):
        json_lines = []
        in_fence = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                if in_fence:
                    break
                in_fence = True
                continue
            if in_fence:
                json_lines.append(line)
        text = "\n".join(json_lines).strip()

    if not text.startswith("{"):
        import re

        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    return text


def analyze_photo(
    photo_path: str | Path | None = None,
    photo_bytes: bytes | None = None,
    photo_data_url: str | None = None,
    child_name: str = "the child",
    child_age: int = 5,
) -> CharacterFeatures:
    image_url = _resolve_image_url(photo_path, photo_bytes, photo_data_url)

    system_prompt = (
        "You are a character analysis engine. Given a photo of a child, "
        "extract physical traits for a children's book character specification. "
        "Be specific and factual. If unclear, estimate.\n\n"
        "Return ONLY valid JSON with these keys:\n"
        "hair, skin_tone, eye_color, face_shape, age_style, body_type, "
        "signature_features (list of strings), typical_expression"
    )

    user_content = [
        {
            "type": "text",
            "text": (
                f"Analyze this photo of {child_name} (age {child_age}) "
                "and extract the character specification."
            ),
        },
        {"type": "image_url", "image_url": {"url": image_url}},
    ]

    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": VISION_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    text = _extract_json_object(text)

    parsed = json.loads(text)
    return CharacterFeatures(
        hair=parsed["hair"],
        skin_tone=parsed["skin_tone"],
        eye_color=parsed["eye_color"],
        face_shape=parsed["face_shape"],
        age_style=parsed.get("age_style", f"{child_age} years old"),
        body_type=parsed.get("body_type", "average build for age"),
        signature_features=tuple(parsed.get("signature_features", [])),
        typical_expression=parsed.get("typical_expression", "bright smile"),
    )


def generate_reference_image(
    width: int = 2048,
    height: int = 2048,
) -> Image.Image:
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    cell_w = width // GRID_COLS
    cell_h = height // GRID_ROWS

    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            x1 = col * cell_w
            y1 = row * cell_h
            x2 = x1 + cell_w
            y2 = y1 + cell_h

            draw.rectangle(
                [x1 + 1, y1 + 1, x2 - 1, y2 - 1], fill=None, outline=(180, 180, 180, 100), width=1
            )

            pose_name = CELL_LABELS_TOP.get((col, row), "")
            if pose_name and "(empty)" not in pose_name:
                _draw_skeleton(draw, x1, y1, cell_w, cell_h, pose_name, opacity=64)
                _draw_mannequin(draw, x1, y1, cell_w, cell_h, pose_name, opacity=38)

                label = POSE_LABELS.get(pose_name, pose_name) or pose_name
                if (col, row) == HERO_CELL:
                    label = f"HERO: {label}"
                draw.text((x1 + 6, y1 + 4), label, fill=(100, 100, 100, 200))

    draw.text((width // 2 - 180, 6), "CHARACTER SHEET REFERENCE", fill=(60, 60, 60, 220))

    return img.convert("RGB")


def _draw_skeleton(
    draw: ImageDraw.ImageDraw,
    cell_x: int,
    cell_y: int,
    cell_w: int,
    cell_h: int,
    pose_name: str,
    opacity: int = 64,
) -> None:
    color = (80, 80, 80, opacity)
    cx = cell_x + cell_w // 2
    ground_y = cell_y + int(cell_h * 0.92)
    head_cy = cell_y + int(cell_h * 0.15)
    head_r = int(cell_h * 0.06)
    shoulder_y = cell_y + int(cell_h * 0.28)
    hip_y = cell_y + int(cell_h * 0.58)
    line_w = 2

    draw.ellipse(
        [cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
        outline=color,
        width=line_w,
    )

    draw.line([(cx, head_cy + head_r), (cx, shoulder_y)], fill=color, width=line_w)
    draw.line([(cx, shoulder_y), (cx, hip_y)], fill=color, width=line_w)

    arm_dx = int(cell_w * 0.18)
    arm_dy = int(cell_h * 0.12)

    if "waving" in pose_name and "back" not in pose_name:
        draw.line(
            [(cx, shoulder_y), (cx + arm_dx, shoulder_y - arm_dy * 2)], fill=color, width=line_w
        )
        draw.line(
            [(cx, shoulder_y), (cx - arm_dx * 0.5, shoulder_y + arm_dy)], fill=color, width=line_w
        )
    elif "running" in pose_name:
        draw.line(
            [(cx, shoulder_y), (cx + arm_dx, shoulder_y + arm_dy * 1.5)], fill=color, width=line_w
        )
        draw.line(
            [(cx, shoulder_y), (cx - arm_dx, shoulder_y - arm_dy * 0.5)], fill=color, width=line_w
        )
    else:
        draw.line([(cx, shoulder_y), (cx + arm_dx, shoulder_y + arm_dy)], fill=color, width=line_w)
        draw.line([(cx, shoulder_y), (cx - arm_dx, shoulder_y + arm_dy)], fill=color, width=line_w)

    leg_dx = int(cell_w * 0.08)
    if "running" in pose_name:
        draw.line([(cx, hip_y), (cx + leg_dx * 3, ground_y)], fill=color, width=line_w)
        draw.line([(cx, hip_y), (cx - leg_dx * 2, ground_y)], fill=color, width=line_w)
    elif "sitting" in pose_name:
        draw.line([(cx, hip_y), (cx + leg_dx * 3, hip_y + leg_dx * 2)], fill=color, width=line_w)
        draw.line([(cx, hip_y), (cx - leg_dx * 3, hip_y + leg_dx * 2)], fill=color, width=line_w)
    else:
        draw.line([(cx, hip_y), (cx + leg_dx, ground_y)], fill=color, width=line_w)
        draw.line([(cx, hip_y), (cx - leg_dx, ground_y)], fill=color, width=line_w)


def _draw_mannequin(
    draw: ImageDraw.ImageDraw,
    cell_x: int,
    cell_y: int,
    cell_w: int,
    cell_h: int,
    pose_name: str = "",
    opacity: int = 38,
) -> None:
    color = (160, 160, 160, opacity)
    cx = cell_x + cell_w // 2
    ground_y = cell_y + int(cell_h * 0.92)
    head_cy = cell_y + int(cell_h * 0.15)
    head_r = int(cell_h * 0.065)
    shoulder_y = cell_y + int(cell_h * 0.28)
    hip_y = cell_y + int(cell_h * 0.58)
    torso_w = int(cell_w * 0.22)
    hip_w = int(cell_w * 0.16)

    draw.ellipse(
        [cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
        fill=color,
    )

    torso_pts = [
        (cx - torso_w, shoulder_y),
        (cx + torso_w, shoulder_y),
        (cx + hip_w, hip_y),
        (cx - hip_w, hip_y),
    ]
    draw.polygon(torso_pts, fill=color)

    leg_dx = int(cell_w * 0.08)
    leg_w = int(cell_w * 0.07)
    if "sitting" not in pose_name:
        for sign in (-1, 1):
            lx = cx + sign * leg_dx
            draw.rectangle(
                [lx - leg_w, hip_y, lx + leg_w, ground_y],
                fill=color,
            )


def build_character_prompt(features: CharacterFeatures, art_style: str = "warm watercolor") -> str:
    parts = [
        "Children's book character reference sheet showing a single child "
        "in 13 different poses arranged in a 4x4 grid.",
        (
            f"Character description: {features.hair} hair, {features.skin_tone} skin, "
            f"{features.eye_color} eyes, {features.face_shape} face."
        ),
        f" {', '.join(features.signature_features)}." if features.signature_features else "",
        f"Age: {features.age_style}. Build: {features.body_type}.",
        f"Default expression: {features.typical_expression}.",
        "",
        "Art style: " + art_style + " children's book illustration.",
        "",
        "Grid layout (left to right, top to bottom):",
        "Row 1: front standing, front waving, front running, front sitting",
        "Row 2: side walking left, side walking right, side running, back standing",
        "Row 3: back waving, 3/4 angle left, 3/4 angle right, looking up",
        "Row 4: looking down, (empty), (empty), HERO large front standing",
        "",
        "CRITICAL RULES:",
        "- The SAME child appears in ALL 13 poses — identical hair, skin, eyes, face, build",
        "- Each cell shows a full-body pose on white background",
        "- Match the structural layout, pose facing, and proportions "
        "from the reference image exactly",
        "- Character features come from THIS PROMPT ONLY, not from any reference image",
        "- The HERO cell (bottom-right) shows the character larger, front standing, full detail",
        "- No text, no labels, no borders in the final image",
        "- Clean white background between all cells",
        "- Each pose must be clearly distinguishable and match the described body position",
    ]
    return "\n".join(p for p in parts if p is not None)


def _image_from_content(content: object) -> Image.Image | None:
    """Extract the first inline data-URL image from a chat message ``content``."""
    if not isinstance(content, list):
        return None
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            url = part["image_url"]["url"]
            if url.startswith("data:"):
                b64 = url.split(",", 1)[1]
                return _bytes_to_pil(base64.b64decode(b64))
    return None


def generate_character_sheet(
    features: CharacterFeatures,
    art_style: str = "warm watercolor",
    reference_image: Image.Image | None = None,
    image_model: str = IMAGE_MODEL,
) -> tuple[Image.Image, dict[str, Image.Image]]:
    ref_img = reference_image or generate_reference_image()

    prompt = build_character_prompt(features, art_style)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": _pil_to_data_url(ref_img)},
                },
            ],
        },
    ]

    resp = httpx.post(
        f"{LITELLM_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": image_model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 4096,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()

    content = data["choices"][0]["message"]["content"]

    sheet_image = _image_from_content(content)
    if sheet_image is None:
        for choice in data.get("choices", []):
            inner = choice.get("message", {}).get("content")
            sheet_image = _image_from_content(inner)
            if sheet_image is not None:
                break

    if sheet_image is None:
        raise RuntimeError(
            "Image generation did not return an image. Model response: " + str(data)[:500]
        )

    pose_crops = extract_poses(sheet_image)
    return sheet_image, pose_crops


def extract_poses(
    sheet_image: Image.Image,
    grid_cols: int = GRID_COLS,
    grid_rows: int = GRID_ROWS,
) -> dict[str, Image.Image]:
    w, h = sheet_image.size
    cell_w = w // grid_cols
    cell_h = h // grid_rows

    grid_order = [
        "front_standing",
        "front_waving",
        "front_running",
        "front_sitting",
        "side_walking_left",
        "side_walking_right",
        "side_running",
        "back_standing",
        "back_waving",
        "three_quarter_left",
        "three_quarter_right",
        "looking_up",
        "looking_down",
        "_empty_1",
        "_empty_2",
        "front_standing_hero",
    ]

    crops: dict[str, Image.Image] = {}
    for idx, pose_name in enumerate(grid_order):
        if pose_name.startswith("_empty_"):
            continue
        col = idx % grid_cols
        row = idx // grid_cols
        x1 = col * cell_w
        y1 = row * cell_h
        x2 = x1 + cell_w
        y2 = y1 + cell_h
        crop = sheet_image.crop((x1, y1, x2, y2))
        crops[pose_name] = crop

    return crops


def build_character_design_text(features: CharacterFeatures, child_name: str = "the child") -> str:
    sig = ", ".join(features.signature_features) if features.signature_features else "bright smile"
    return (
        f"A child named {child_name} ({features.age_style}), "
        f"{features.hair} hair, {features.skin_tone} skin, {features.eye_color} eyes, "
        f"{features.face_shape} face, {sig}, {features.body_type}, "
        f"wearing simple comfortable clothes appropriate for a children's book character"
    )


def create_character_sheet_from_photo(
    photo_path: str | Path,
    child_name: str = "the child",
    child_age: int = 5,
    art_style: str = "warm watercolor",
) -> CharacterSheet:
    logger.info("Analyzing photo for %s (age %d)...", child_name, child_age)
    features = analyze_photo(photo_path=photo_path, child_name=child_name, child_age=child_age)
    logger.info(
        "Features: hair=%s, skin=%s, eyes=%s", features.hair, features.skin_tone, features.eye_color
    )

    logger.info("Generating reference image...")
    ref_img = generate_reference_image()

    logger.info("Generating character sheet (13 poses, single AI call)...")
    sheet_image, pose_crops = generate_character_sheet(
        features, art_style=art_style, reference_image=ref_img
    )

    sheet = CharacterSheet(
        features=features,
        sheet_image=sheet_image,
        sheet_image_bytes=_pil_to_bytes(sheet_image),
        pose_crops=pose_crops,
        pose_image_bytes={name: _pil_to_bytes(crop) for name, crop in pose_crops.items()},
        quality_score=1.0,
    )

    logger.info(
        "Character sheet created: %d poses extracted, image size: %s",
        len(pose_crops),
        f"{sheet_image.width}x{sheet_image.height}",
    )
    return sheet
