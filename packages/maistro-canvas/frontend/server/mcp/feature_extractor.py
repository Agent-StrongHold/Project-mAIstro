"""Feature extractor — local pixel-based hair/skin/eye classification from photos.

Ported from featureExtractor.js. Analyzes uploaded reference photos using
pixel sampling (no AI) to extract hair color, skin tone, and eye color.
Used as fallback when AI vision analysis is unavailable or blocked.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFeatures:
    hair_color: str | None = None
    skin_tone: str | None = None
    eye_color: str | None = None
    description: str = ""


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    r_f, g_f, b_f = r / 255, g / 255, b / 255
    mx = max(r_f, g_f, b_f)
    mn = min(r_f, g_f, b_f)
    lum = (mx + mn) / 2

    if mx == mn:
        return (0.0, 0.0, lum * 100)

    d = mx - mn
    s = d / (2 - mx - mn) if lum > 0.5 else d / (mx + mn)

    if mx == r_f:
        h = ((g_f - b_f) / d + (6 if g_f < b_f else 0)) / 6
    elif mx == g_f:
        h = ((b_f - r_f) / d + 2) / 6
    else:
        h = ((r_f - g_f) / d + 4) / 6

    return (h * 360, s * 100, lum * 100)


# Ordered (predicate, label) rules for HSL-based classification. The first
# matching rule wins, preserving the original sequential if-ladder semantics.
_HslRule = tuple[Callable[[float, float, float], bool], str]

_HAIR_COLOR_RULES: list[_HslRule] = [
    (lambda h, s, lum: lum < 15, "very dark black"),
    (lambda h, s, lum: lum < 25 and s < 30, "black"),
    (lambda h, s, lum: lum < 30 and 15 < h < 40, "very dark brown"),
    (lambda h, s, lum: lum < 40 and 10 < h < 45 and s > 20, "dark brown"),
    (lambda h, s, lum: lum < 50 and 10 < h < 45, "brown"),
    (lambda h, s, lum: lum < 50 and 5 < h < 20 and s < 25, "dark ash brown"),
    (lambda h, s, lum: lum < 55 and 15 < h < 40 and s > 30, "medium brown"),
    (lambda h, s, lum: 40 <= lum < 55 and 20 < h < 50 and s > 40, "auburn"),
    (lambda h, s, lum: 35 <= lum < 55 and 5 < h < 25 and s > 50, "reddish brown"),
    (lambda h, s, lum: 40 <= lum < 55 and 10 < h < 30 and s < 25, "ash blonde"),
    (lambda h, s, lum: 50 <= lum < 70 and 15 < h < 45 and s > 25, "light brown or dark blonde"),
    (lambda h, s, lum: 55 <= lum < 75 and 20 < h < 50, "dirty blonde"),
    (lambda h, s, lum: 60 <= lum < 80 and s < 25, "blonde"),
    (lambda h, s, lum: 60 <= lum < 80 and 20 < h < 50 and s > 30, "golden blonde"),
    (lambda h, s, lum: 70 <= lum < 90 and s < 20, "light blonde"),
    (lambda h, s, lum: lum >= 75, "very light blonde or white"),
    (lambda h, s, lum: 0 < h < 15 and s > 40, "red"),
    (lambda h, s, lum: 5 < h < 30 and s > 30 and lum < 50, "ginger"),
    (lambda h, s, lum: s < 15 and lum > 40, "grey or silver"),
]

_SKIN_TONE_RULES: list[_HslRule] = [
    (lambda h, s, lum: lum < 30, "deep dark brown"),
    (lambda h, s, lum: lum < 40 and 15 < h < 35, "dark brown"),
    (lambda h, s, lum: lum < 50 and 15 < h < 40, "warm medium brown"),
    (lambda h, s, lum: lum < 55 and 10 < h < 35, "medium olive or tan"),
    (lambda h, s, lum: lum < 60 and 15 < h < 40 and s > 30, "warm light brown"),
    (lambda h, s, lum: lum < 65 and 10 < h < 35, "light tan or olive"),
    (lambda h, s, lum: lum < 70 and 15 < h < 40, "warm fair with golden undertones"),
    (lambda h, s, lum: lum < 75 and s > 20, "fair with warm undertones"),
    (lambda h, s, lum: lum < 75, "fair with cool undertones"),
    (lambda h, s, lum: lum < 80, "very fair or porcelain"),
]

_EYE_COLOR_RULES: list[_HslRule] = [
    (lambda h, s, lum: lum < 20, "very dark brown, almost black"),
    (lambda h, s, lum: lum < 30 and s < 40, "dark brown"),
    (lambda h, s, lum: lum < 40 and s < 50, "brown"),
    (lambda h, s, lum: lum < 45 and 20 < h < 50 and s > 30, "warm brown with amber flecks"),
    (lambda h, s, lum: 25 < h < 50 and s > 40 and 35 < lum < 55, "hazel"),
    (lambda h, s, lum: 20 < h < 45 and s > 50 and lum > 40, "amber"),
    (lambda h, s, lum: 50 < h < 170 and s > 20 and 25 < lum < 55, "green"),
    (lambda h, s, lum: 170 < h < 260 and s > 15 and 20 < lum < 50, "blue"),
    (lambda h, s, lum: 170 < h < 260 and s > 15 and lum >= 50, "light blue"),
    (lambda h, s, lum: 170 < h < 260 and s < 15, "grey-blue"),
    (lambda h, s, lum: s < 15 and lum < 40, "dark grey"),
    (lambda h, s, lum: s < 20 and lum >= 40, "grey"),
]


def _first_match(rules: list[_HslRule], h: float, s: float, lum: float, default: str) -> str:
    """Return the label of the first rule whose predicate matches, else default."""
    for predicate, label in rules:
        if predicate(h, s, lum):
            return label
    return default


def _classify_hair_color(h: float, s: float, lum: float) -> str:
    return _first_match(_HAIR_COLOR_RULES, h, s, lum, "brown")


def _classify_skin_tone(h: float, s: float, lum: float) -> str:
    return _first_match(_SKIN_TONE_RULES, h, s, lum, "very fair or pale")


def _classify_eye_color(r: int, g: int, b: int) -> str:
    h, s, lum = _rgb_to_hsl(r, g, b)
    return _first_match(_EYE_COLOR_RULES, h, s, lum, "brown")


def _sample_region(
    pixels: list[tuple[int, int, int, int]],
    img_w: int,
    cx: int,
    cy: int,
    radius: int,
) -> tuple[int, int, int] | None:
    r_sum = g_sum = b_sum = 0
    count = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            x = cx + dx
            y = cy + dy
            if x < 0 or x >= img_w or y < 0 or y >= len(pixels) // img_w:
                continue
            idx = y * img_w + x
            if idx >= len(pixels):
                continue
            a = pixels[idx][3]
            if a < 128:
                continue
            r_sum += pixels[idx][0]
            g_sum += pixels[idx][1]
            b_sum += pixels[idx][2]
            count += 1
    if count == 0:
        return None
    return (round(r_sum / count), round(g_sum / count), round(b_sum / count))


def extract_features(image: Image.Image) -> ExtractedFeatures:
    img = image.convert("RGBA")
    max_dim = 512
    scale = min(max_dim / img.width, max_dim / img.height, 1.0)
    if scale < 1.0:
        new_w = round(img.width * scale)
        new_h = round(img.height * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    w, h = img.size
    pixels = img.get_flattened_data()

    features = ExtractedFeatures()

    head_top_y = round(h * 0.05)
    head_cy = round(h * 0.18)
    head_cx = round(w * 0.5)
    head_r = round(min(w, h) * 0.06)

    hair_sample = _sample_region(pixels, w, head_cx, head_top_y, head_r)
    if hair_sample:
        hsl = _rgb_to_hsl(*hair_sample)
        features.hair_color = _classify_hair_color(*hsl)

    forehead_r = round(head_r * 0.5)
    forehead_y = round(head_cy - head_r * 0.3)
    forehead_sample = _sample_region(pixels, w, head_cx, forehead_y, forehead_r)
    if forehead_sample:
        hsl = _rgb_to_hsl(*forehead_sample)
        features.skin_tone = _classify_skin_tone(*hsl)

    eye_y = round(head_cy + head_r * 0.15)
    left_eye_x = round(head_cx - head_r * 0.5)
    right_eye_x = round(head_cx + head_r * 0.5)
    eye_r = max(round(head_r * 0.2), 1)
    left_eye = _sample_region(pixels, w, left_eye_x, eye_y, eye_r)
    right_eye = _sample_region(pixels, w, right_eye_x, eye_y, eye_r)
    eye_sample = left_eye or right_eye
    if eye_sample:
        features.eye_color = _classify_eye_color(*eye_sample)

    parts = []
    if features.hair_color:
        parts.append(f"{features.hair_color} hair")
    if features.skin_tone:
        parts.append(f"{features.skin_tone} skin")
    if features.eye_color:
        parts.append(f"{features.eye_color} eyes")
    features.description = ", ".join(parts)

    return features


def build_photo_derived_design(features: ExtractedFeatures, base_design: str = "") -> str:
    if not features.description:
        return base_design or ""

    design = base_design or "a child character"

    if features.hair_color:
        design = f"{features.hair_color} hair, {design}"

    if features.skin_tone:
        design = f"{features.skin_tone} skin, {design}"

    if features.eye_color:
        design = f"{features.eye_color} eyes, {design}"

    return f"Based on reference photos: {features.description}. {design}"
