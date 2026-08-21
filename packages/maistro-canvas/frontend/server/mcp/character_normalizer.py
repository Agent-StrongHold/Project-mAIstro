"""Character normalizer — post-generation silhouette detection and normalization.

Ported from characterNormalizer.js. Detects character silhouette in
generated images, normalizes scale/position/anchor, detects head region
for face mask protection during refinement passes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)

WHITE_THRESHOLD = 240
MIN_PIXEL_RATIO = 0.005


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Silhouette:
    bounds: Region
    center: Point
    pixel_ratio: float
    width_px: int
    height_px: int


@dataclass(frozen=True)
class HeadRegion:
    bounds: Region
    center: Point
    radius: float


@dataclass(frozen=True)
class Normalization:
    scale: float
    offset_x: float
    offset_y: float
    alignment_score: float | None
    expected_bounds: Region
    actual_bounds: Region
    needs_correction: bool


def _is_white_or_near(r: int, g: int, b: int, a: int) -> bool:
    if a < 128:
        return True
    return r > WHITE_THRESHOLD and g > WHITE_THRESHOLD and b > WHITE_THRESHOLD


def detect_silhouette(image: Image.Image) -> Silhouette | None:
    img = image.convert("RGBA")
    w, h = img.size
    pixels = img.get_flattened_data()

    min_x, min_y = w, h
    max_x = max_y = 0
    pixel_count = 0

    for y in range(h):
        for x in range(w):
            i = y * w + x
            r, g, b, a = pixels[i]
            if not _is_white_or_near(r, g, b, a):
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                pixel_count += 1

    if pixel_count < w * h * MIN_PIXEL_RATIO:
        return None

    return Silhouette(
        bounds=Region(
            x=min_x / w,
            y=min_y / h,
            w=(max_x - min_x) / w,
            h=(max_y - min_y) / h,
        ),
        center=Point(
            x=(min_x + max_x) / 2 / w,
            y=(min_y + max_y) / 2 / h,
        ),
        pixel_ratio=pixel_count / (w * h),
        width_px=max_x - min_x,
        height_px=max_y - min_y,
    )


def detect_head_region(
    image: Image.Image,
    silhouette: Silhouette,
) -> HeadRegion | None:
    img = image.convert("RGBA")
    w, h = img.size
    pixels = img.get_flattened_data()

    top_y = silhouette.bounds.y * h
    center_x = silhouette.center.x * w
    search_height = silhouette.bounds.h * h * 0.3
    search_width = silhouette.bounds.w * w * 0.4

    min_x, min_y = w, h
    max_x = max_y = 0
    count = 0

    start_y = max(0, int(top_y) - 5)
    end_y = min(h, int(top_y + search_height))
    start_x = max(0, int(center_x - search_width / 2))
    end_x = min(w, int(center_x + search_width / 2))

    for y in range(start_y, end_y):
        for x in range(start_x, end_x):
            i = y * w + x
            r, g, b, a = pixels[i]
            if not _is_white_or_near(r, g, b, a):
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                count += 1

    if count < 50:
        return None

    return HeadRegion(
        bounds=Region(
            x=min_x / w,
            y=min_y / h,
            w=(max_x - min_x) / w,
            h=(max_y - min_y) / h,
        ),
        center=Point(
            x=(min_x + max_x) / 2 / w,
            y=(min_y + max_y) / 2 / h,
        ),
        radius=max(max_x - min_x, max_y - min_y) / 2 / w,
    )


def compute_normalization(
    silhouette: Silhouette,
    head_region: HeadRegion | None,
    pose_bounds: Region | None,
    canvas_size: int = 1024,
) -> Normalization | None:
    if not silhouette or not pose_bounds:
        return None

    expected_h = pose_bounds.h * canvas_size
    expected_w = pose_bounds.w * canvas_size

    actual_h = silhouette.height_px
    actual_w = silhouette.width_px

    scale_y = expected_h / actual_h
    scale_x = expected_w / actual_w
    scale = min(scale_x, scale_y)

    expected_anchor_x = pose_bounds.x * canvas_size + expected_w / 2
    expected_anchor_y = (pose_bounds.y + pose_bounds.h) * canvas_size

    actual_anchor_x = silhouette.bounds.x * canvas_size + actual_w * scale / 2
    actual_anchor_y = (silhouette.bounds.y + silhouette.bounds.h) * canvas_size * scale

    offset_x = expected_anchor_x - actual_anchor_x
    offset_y = expected_anchor_y - actual_anchor_y

    alignment_score = None
    if head_region and pose_bounds:
        alignment_score = 1 - min(
            1.0,
            abs(head_region.center.x - pose_bounds.x - pose_bounds.w / 2)
            + abs(head_region.center.y - pose_bounds.y - pose_bounds.h * 0.15),
        )

    needs_correction = (
        scale < 0.8 or scale > 1.25 or (alignment_score is not None and alignment_score < 0.7)
    )

    return Normalization(
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
        alignment_score=alignment_score,
        expected_bounds=pose_bounds,
        actual_bounds=silhouette.bounds,
        needs_correction=needs_correction,
    )


def normalize_character(
    image: Image.Image,
    pose_bounds: Region | None = None,
    target_width: int = 1024,
    target_height: int = 1024,
) -> tuple[Image.Image, Silhouette | None, HeadRegion | None, Normalization | None]:
    src = image.convert("RGBA")
    silhouette = detect_silhouette(src)
    if not silhouette:
        return (
            src.resize((target_width, target_height), Image.Resampling.LANCZOS),
            None,
            None,
            None,
        )

    head_region = detect_head_region(src, silhouette)
    norm = compute_normalization(silhouette, head_region, pose_bounds, target_width)

    out = Image.new("RGBA", (target_width, target_height), (255, 255, 255, 255))

    if norm:
        sx = int(silhouette.bounds.x * src.width)
        sy = int(silhouette.bounds.y * src.height)
        sw = silhouette.width_px
        sh = silhouette.height_px
        dw = int(sw * norm.scale)
        dh = int(sh * norm.scale)
        dx = int(norm.offset_x + silhouette.bounds.x * target_width * norm.scale)
        dy = int(norm.offset_y + silhouette.bounds.y * target_height * norm.scale)
        crop = src.crop((sx, sy, sx + sw, sy + sh))
        out.paste(crop.resize((dw, dh), Image.Resampling.LANCZOS), (dx, dy))
    else:
        scale = min(
            target_width * 0.6 / silhouette.width_px,
            target_height * 0.9 / silhouette.height_px,
        )
        dw = int(silhouette.width_px * scale)
        dh = int(silhouette.height_px * scale)
        dx = (target_width - dw) // 2
        dy = int(target_height * 0.95) - dh
        sx = int(silhouette.bounds.x * src.width)
        sy = int(silhouette.bounds.y * src.height)
        crop = src.crop((sx, sy, sx + silhouette.width_px, sy + silhouette.height_px))
        out.paste(crop.resize((dw, dh), Image.Resampling.LANCZOS), (dx, dy))

    return (out, silhouette, head_region, norm)


def build_face_mask(
    head_region: HeadRegion | None,
    canvas_size: int = 1024,
) -> Image.Image | None:
    if not head_region:
        return None

    from PIL import ImageDraw

    mask = Image.new("L", (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(mask)

    cx = head_region.center.x * canvas_size
    cy = head_region.center.y * canvas_size
    rx = (head_region.bounds.w * canvas_size) / 2 * 1.2
    ry = (head_region.bounds.h * canvas_size) / 2 * 1.1

    draw.ellipse(
        [cx - rx, cy - ry, cx + rx, cy + ry],
        fill=255,
    )
    return mask
