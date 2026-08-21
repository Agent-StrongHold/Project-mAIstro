"""Refinement pass — post-compositing polish with AI or Pillow fallback.

Ported from refinementPass.js. Primary: AI-assisted edit (GPT-image edit).
Fallback: Pillow-based edge softening, palette unification, contrast
normalization, and face mask protection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from .character_normalizer import HeadRegion, Region, build_face_mask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StyleToken:
    technique: str = "warm watercolor children's book illustration"
    edge_softness: float = 0.7
    contrast: str = "low"
    lighting: str = "soft warm light"
    palette: str = ""
    detail_level: str = "moderate"


@dataclass
class RefinementResult:
    composite: Image.Image
    composite_original: Image.Image
    refined: bool = True
    refinement_method: str = "pillow_fallback"


def build_edge_mask(
    character_slot: Region | None,
    page_width: int = 1536,
    page_height: int = 1024,
) -> Image.Image:
    mask = Image.new("L", (page_width, page_height), 0)

    if not character_slot:
        return mask

    sx = int(character_slot.x * page_width)
    sy = int(character_slot.y * page_height)
    sw = int(character_slot.w * page_width)
    sh = int(character_slot.h * page_height)
    edge_w = int(max(sw, sh) * 0.12)

    draw = ImageDraw.Draw(mask)
    draw.rectangle(
        [sx - edge_w // 2, sy - edge_w // 2, sx + sw + edge_w // 2, sy + sh + edge_w // 2],
        fill=255,
    )
    draw.rectangle(
        [sx + edge_w // 2, sy + edge_w // 2, sx + sw - edge_w // 2, sy + sh - edge_w // 2],
        fill=0,
    )
    return mask


def extract_dominant_color(image: Image.Image) -> tuple[int, int, int]:
    img = image.convert("RGBA")
    pixels = img.get_flattened_data()
    r_sum = g_sum = b_sum = 0
    count = 0
    step = 16
    for i in range(0, len(pixels), step):
        r, g, b, a = pixels[i]
        if a < 128:
            continue
        r_sum += r
        g_sum += g
        b_sum += b
        count += 1
    if count == 0:
        return (128, 128, 128)
    return (round(r_sum / count), round(g_sum / count), round(b_sum / count))


def apply_edge_soften(
    composite: Image.Image,
    edge_mask: Image.Image,
    strength: float = 0.7,
) -> Image.Image:
    w, h = composite.size
    blurred = composite.filter(ImageFilter.GaussianBlur(radius=round(strength * 6)))

    orig = composite.convert("RGBA")
    blur = blurred.convert("RGBA")
    mask = edge_mask.convert("L")

    orig_pixels = orig.get_flattened_data()
    blur_pixels = blur.get_flattened_data()
    mask_pixels = mask.get_flattened_data()

    result_pixels = []
    for i in range(len(orig_pixels)):
        mask_val = mask_pixels[i] / 255.0
        if mask_val > 0:
            blend = mask_val * strength * 0.4
            r = round(orig_pixels[i][0] * (1 - blend) + blur_pixels[i][0] * blend)
            g = round(orig_pixels[i][1] * (1 - blend) + blur_pixels[i][1] * blend)
            b = round(orig_pixels[i][2] * (1 - blend) + blur_pixels[i][2] * blend)
            result_pixels.append((r, g, b, orig_pixels[i][3]))
        else:
            result_pixels.append(orig_pixels[i])

    result = Image.new("RGBA", (w, h))
    result.putdata(result_pixels)
    return result


def apply_palette_unification(
    composite: Image.Image,
    strength: float = 0.7,
) -> Image.Image:
    dominant = extract_dominant_color(composite)
    img = composite.convert("RGBA")
    pixels = img.get_flattened_data()
    shift = strength * 0.06

    result_pixels = []
    for r, g, b, a in pixels:
        if a < 128:
            result_pixels.append((r, g, b, a))
        else:
            result_pixels.append(
                (
                    round(r * (1 - shift) + dominant[0] * shift),
                    round(g * (1 - shift) + dominant[1] * shift),
                    round(b * (1 - shift) + dominant[2] * shift),
                    a,
                )
            )

    result = Image.new("RGBA", img.size)
    result.putdata(result_pixels)
    return result


def apply_face_protection(
    refined: Image.Image,
    original: Image.Image,
    face_mask: Image.Image,
) -> Image.Image:
    orig_data = original.convert("RGBA").get_flattened_data()
    refined_data = refined.convert("RGBA").get_flattened_data()
    mask_data = face_mask.convert("L").get_flattened_data()

    result_pixels = []
    for i in range(len(refined_data)):
        mask_val = mask_data[i] / 255.0
        if mask_val > 0.1:
            w = mask_val
            r = round(orig_data[i][0] * w + refined_data[i][0] * (1 - w))
            g = round(orig_data[i][1] * w + refined_data[i][1] * (1 - w))
            b = round(orig_data[i][2] * w + refined_data[i][2] * (1 - w))
            result_pixels.append((r, g, b, refined_data[i][3]))
        else:
            result_pixels.append(refined_data[i])

    result = Image.new("RGBA", refined.size)
    result.putdata(result_pixels)
    return result


def build_refinement_prompt(style_token: StyleToken | None = None) -> str:
    st = style_token or StyleToken()
    parts = [
        f"Refine this {st.technique} children's book illustration.",
        "Smooth edges between character and background so they feel painted together.",
        "Ensure consistent color palette and line style across the entire image.",
    ]
    if st.edge_softness > 0.5:
        parts.append("Use soft, blended edges — no harsh cutout borders.")
    else:
        parts.append("Use clean, defined edges with consistent line weight.")

    if st.contrast == "low":
        parts.append("Keep contrast soft and gentle.")
    elif st.contrast == "high":
        parts.append("Maintain bold, clear contrast between elements.")
    else:
        parts.append("Balance contrast naturally.")

    parts.extend(
        [
            (
                "CRITICAL: Preserve the character's face EXACTLY — "
                "do not change facial features, expression, or identity."
            ),
            "Maintain the character's pose and proportions exactly.",
            "Do not add text, watermarks, or signatures.",
            "Subtle, minimal edits only. This is a polish pass, not a redraw.",
        ]
    )
    return " ".join(parts)


def refine_scene(
    composite: Image.Image,
    character_slot: Region | None = None,
    head_region: HeadRegion | None = None,
    style_token: StyleToken | None = None,
) -> RefinementResult:
    st = style_token or StyleToken()
    original = composite.copy()

    logger.info("Starting Pillow-based refinement pass")

    refined = composite.convert("RGBA")

    if character_slot:
        logger.debug("Softening layer edges...")
        edge_mask = build_edge_mask(character_slot, refined.width, refined.height)
        refined = apply_edge_soften(refined, edge_mask, st.edge_softness)

    logger.debug("Unifying color palette...")
    refined = apply_palette_unification(refined, st.edge_softness)

    contrast_val = 1.1 if st.contrast == "high" else (0.9 if st.contrast == "low" else 1.0)
    from PIL import ImageEnhance

    enhancer = ImageEnhance.Contrast(refined)
    refined = enhancer.enhance(contrast_val)
    brightener = ImageEnhance.Brightness(refined)
    refined = brightener.enhance(1.02)

    if head_region:
        logger.debug("Protecting character identity...")
        face_mask = build_face_mask(head_region, min(refined.width, refined.height))
        if face_mask is not None:
            if face_mask.size != refined.size:
                face_mask = face_mask.resize(refined.size, Image.Resampling.LANCZOS)
            refined = apply_face_protection(refined, original.convert("RGBA"), face_mask)

    logger.info("Pillow-based refinement complete")
    return RefinementResult(
        composite=refined,
        composite_original=original,
        refined=True,
        refinement_method="pillow_fallback",
    )
