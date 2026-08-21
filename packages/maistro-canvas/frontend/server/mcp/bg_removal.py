"""Background removal — BFS flood fill from edges with luminance threshold.

Ported from renderingPipeline.js removeBackground(). Uses Pillow instead
of browser canvas API. Removes near-white/grey backgrounds from generated
images so character/prop layers composite properly on top of backgrounds.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BgRemovalConfig:
    threshold: int = 240
    feather: int = 4
    max_saturation_delta: int = 50


def _luminance(r: int, g: int, b: int) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def _is_bg_color(pixel: tuple[int, int, int, int], threshold: int, max_delta: int) -> bool:
    r, g, b, a = pixel
    if a < 128:
        return True
    lum = _luminance(r, g, b)
    if lum < threshold:
        return False
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    return not max_c - min_c > max_delta


def _seed_edge_mask(
    pixels: list[tuple[int, int, int, int]],
    w: int,
    h: int,
    threshold: int,
    max_delta: int,
) -> tuple[list[int], deque[int]]:
    """Mark all background-coloured edge pixels and return (mask, BFS queue)."""
    mask = [0] * (w * h)
    queue: deque[int] = deque()

    def _seed(idx: int) -> None:
        if _is_bg_color(pixels[idx], threshold, max_delta):
            mask[idx] = 1
            queue.append(idx)

    for x in range(w):
        _seed(x)
        _seed((h - 1) * w + x)
    for y in range(h):
        _seed(y * w)
        _seed(y * w + w - 1)
    return mask, queue


def _flood_fill(
    pixels: list[tuple[int, int, int, int]],
    mask: list[int],
    queue: deque[int],
    w: int,
    h: int,
    threshold: int,
    max_delta: int,
) -> None:
    """BFS flood-fill of contiguous background regions from seeded edges."""
    while queue:
        idx = queue.popleft()
        if mask[idx] != 1:
            continue
        x = idx % w
        y = (idx - x) // w
        neighbours: list[int] = []
        if x > 0:
            neighbours.append(idx - 1)
        if x < w - 1:
            neighbours.append(idx + 1)
        if y > 0:
            neighbours.append(idx - w)
        if y < h - 1:
            neighbours.append(idx + w)
        for ni in neighbours:
            if mask[ni] == 0 and _is_bg_color(pixels[ni], threshold, max_delta):
                mask[ni] = 1
                queue.append(ni)


def _feather_distance(mask: list[int], x: int, y: int, w: int, h: int, feather: int) -> float:
    """Distance from (x, y) to the nearest masked background pixel within feather."""
    min_dist: float = feather + 1
    for fy in range(-feather, feather + 1):
        for fx in range(-feather, feather + 1):
            nx = x + fx
            ny = y + fy
            if nx < 0 or nx >= w or ny < 0 or ny >= h:
                continue
            if mask[ny * w + nx] == 1:
                d = (fx * fx + fy * fy) ** 0.5
                if d < min_dist:
                    min_dist = d
    return min_dist


def _apply_mask(
    pixels: list[tuple[int, int, int, int]],
    mask: list[int],
    w: int,
    h: int,
    feather: int,
) -> list[tuple[int, int, int, int]]:
    """Produce the output pixel list with background cleared and edges feathered."""
    new_pixels = list(pixels)
    if feather <= 0:
        for i in range(len(mask)):
            if mask[i] == 1:
                new_pixels[i] = (0, 0, 0, 0)
        return new_pixels

    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if mask[idx] == 1:
                new_pixels[idx] = (0, 0, 0, 0)
            elif mask[idx] == 2:
                min_dist = _feather_distance(mask, x, y, w, h, feather)
                if min_dist <= feather:
                    alpha = round(255 * (min_dist / feather))
                    r, g, b, _ = new_pixels[idx]
                    new_pixels[idx] = (r, g, b, alpha)
    return new_pixels


def remove_background(
    image: Image.Image,
    threshold: int = 240,
    feather: int = 4,
    max_saturation_delta: int = 50,
) -> Image.Image:
    img = image.convert("RGBA")
    w, h = img.size
    pixels = img.get_flattened_data()

    mask, queue = _seed_edge_mask(pixels, w, h, threshold, max_saturation_delta)
    _flood_fill(pixels, mask, queue, w, h, threshold, max_saturation_delta)

    # Unreached background-coloured pixels (interior) are marked as 2.
    for i in range(len(mask)):
        if mask[i] == 0:
            mask[i] = 2

    new_pixels = _apply_mask(pixels, mask, w, h, feather)

    result = Image.new("RGBA", (w, h))
    result.putdata(new_pixels)
    return result
