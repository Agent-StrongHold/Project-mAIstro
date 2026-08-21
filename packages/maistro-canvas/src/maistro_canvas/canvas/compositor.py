"""Canvas compositor — assembles layer images into a single PIL image.

All PIL operations are CPU-bound and run via asyncio.to_thread so the
event loop stays unblocked.  The compositor is stateless: given the
same inputs it always produces byte-identical output (determinism
invariant from spec 1189).
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from maistro_canvas.types import CanvasRecord, CompositeResult, LayerRecord, TextConfig

logger = logging.getLogger("maistro_canvas.canvas.compositor")

# Pillow is a required runtime dependency (added to pyproject.toml)
try:
    from PIL import Image, ImageDraw, ImageFont

    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PIL_AVAILABLE = False

_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
_BICUBIC = getattr(Image, "Resampling", Image).BICUBIC


# ─────────────────────────────────────────────────────────────────────
# Image store protocol (fetch a URL → PIL Image)
# ─────────────────────────────────────────────────────────────────────


class ImageStore(Protocol):
    async def fetch(self, url: str) -> Image.Image: ...


# ─────────────────────────────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────────────────────────────


def _parse_hex_color(hex_color: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RGB to (R, G, B, 255)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (255, 255, 255, 255)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, 255)


# ─────────────────────────────────────────────────────────────────────
# Synchronous (CPU-bound) PIL operations — called via asyncio.to_thread
# ─────────────────────────────────────────────────────────────────────


def _transform_layer_image(
    src: Image.Image,
    *,
    canvas_w: int,
    canvas_h: int,
    x: float,
    y: float,
    scale: float,
    rotation: float,
    opacity: float,
) -> Image.Image:
    """Apply scale, rotation, opacity, and position to a layer image.

    Returns a new RGBA image the size of the canvas with the transformed
    layer pasted at the correct position.  Areas outside the canvas are
    clipped.
    """
    img = src.convert("RGBA")

    # Scale
    if scale != 1.0 and scale > 0:
        new_w = max(1, round(img.width * scale))
        new_h = max(1, round(img.height * scale))
        img = img.resize((new_w, new_h), _LANCZOS)

    # Rotation — expand=True keeps the full rotated image
    if rotation != 0.0:
        img = img.rotate(-rotation, expand=True, resample=_BICUBIC)

    # Apply opacity by scaling the alpha channel
    if opacity < 1.0:
        r, g, b, a = img.split()
        a = a.point(lambda v: round(v * opacity))
        img = Image.merge("RGBA", (r, g, b, a))

    # Paste onto a transparent canvas-sized frame
    frame = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    paste_x = round(x)
    paste_y = round(y)
    # Center the rotated image on the intended position
    cx = paste_x - img.width // 2 + (round(src.width * scale) if scale > 0 else src.width) // 2
    cy = paste_y - img.height // 2 + (round(src.height * scale) if scale > 0 else src.height) // 2
    frame.paste(img, (cx, cy), img)
    return frame


def _render_text_layer(
    text_config: TextConfig,
    canvas_w: int,
    canvas_h: int,
) -> Image.Image:
    """Render text onto a transparent canvas-sized image."""
    frame = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)

    # Attempt to load a system font; fall back to default
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", text_config.size)
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", text_config.size
            )
        except OSError:
            font = ImageFont.load_default()

    # Parse color
    color_hex = text_config.color.lstrip("#")
    if len(color_hex) == 6:
        color = (int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16), 255)
    else:
        color = (255, 255, 255, 255)

    # Get text bounding box for alignment
    bbox = draw.textbbox((0, 0), text_config.content, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    if text_config.alignment == "center":
        text_x = (canvas_w - text_w) // 2
    elif text_config.alignment == "right":
        text_x = canvas_w - text_w - 20
    else:
        text_x = 20
    text_y = (canvas_h - text_h) // 2

    # Optional shadow
    if text_config.shadow_color:
        shadow_hex = text_config.shadow_color.lstrip("#")
        if len(shadow_hex) == 6:
            shadow = (
                int(shadow_hex[0:2], 16),
                int(shadow_hex[2:4], 16),
                int(shadow_hex[4:6], 16),
                180,
            )
        else:
            shadow = (0, 0, 0, 180)
        ox, oy = text_config.shadow_offset
        draw.text((text_x + ox, text_y + oy), text_config.content, font=font, fill=shadow)

    draw.text((text_x, text_y), text_config.content, font=font, fill=color)
    return frame


def _alpha_composite_frame(
    base: Image.Image,
    layer_frame: Image.Image,
    blend_mode: str,
) -> Image.Image:
    """Composite layer_frame over base with the given blend mode."""
    if blend_mode == "normal":
        return Image.alpha_composite(base, layer_frame)

    # For non-normal blend modes: compose the RGB channels, keep alpha from layer_frame
    base_rgb = base.convert("RGB")
    layer_rgb = layer_frame.convert("RGB")

    if blend_mode == "multiply":
        from PIL import ImageChops

        blended_rgb = ImageChops.multiply(base_rgb, layer_rgb)
    elif blend_mode == "screen":
        from PIL import ImageChops

        blended_rgb = ImageChops.screen(base_rgb, layer_rgb)
    elif blend_mode == "overlay":
        from PIL import ImageChops

        blended_rgb = ImageChops.overlay(base_rgb, layer_rgb)
    elif blend_mode == "darken":
        from PIL import ImageChops

        blended_rgb = ImageChops.darker(base_rgb, layer_rgb)
    elif blend_mode == "lighten":
        from PIL import ImageChops

        blended_rgb = ImageChops.lighter(base_rgb, layer_rgb)
    else:
        blended_rgb = layer_rgb  # unknown mode → treat as normal

    # Re-attach original alpha
    blended = blended_rgb.convert("RGBA")
    _, _, _, layer_a = layer_frame.split()
    blended.putalpha(layer_a)
    return Image.alpha_composite(base, blended)


def _encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _encode_webp(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def _encode_jpg(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────
# PilCompositorService
# ─────────────────────────────────────────────────────────────────────


class PilCompositorService:
    """CompositorService implementation using Pillow."""

    def __init__(self, image_store: ImageStore) -> None:
        if not _PIL_AVAILABLE:  # pragma: no cover
            msg = "Pillow is required for PilCompositorService (pip install Pillow)"
            raise RuntimeError(msg)
        self._image_store = image_store

    async def composite(
        self,
        canvas: CanvasRecord,
        layers: list[LayerRecord],
    ) -> CompositeResult:
        from maistro_canvas.types import CompositeResult

        canvas_w, canvas_h = canvas.width, canvas.height
        bg_color = _parse_hex_color(canvas.background_color)

        # Sort visible layers back-to-front (z_index ascending)
        visible = sorted(
            (lyr for lyr in layers if lyr.visible),
            key=lambda lyr: lyr.z_index,
        )

        # Build the base (background colour)
        output: Image.Image = await asyncio.to_thread(
            Image.new, "RGBA", (canvas_w, canvas_h), bg_color
        )

        for lyr in visible:
            frame: Image.Image | None = None

            if lyr.layer_type == "text" and lyr.text_config is not None:
                frame = await asyncio.to_thread(
                    _render_text_layer, lyr.text_config, canvas_w, canvas_h
                )
            elif lyr.image_path:
                try:
                    src = await self._image_store.fetch(lyr.image_path)
                except Exception:
                    logger.warning("Could not fetch image for layer %s; skipping", lyr.id)
                    continue
                frame = await asyncio.to_thread(
                    _transform_layer_image,
                    src,
                    canvas_w=canvas_w,
                    canvas_h=canvas_h,
                    x=lyr.x,
                    y=lyr.y,
                    scale=lyr.scale,
                    rotation=lyr.rotation,
                    opacity=lyr.opacity,
                )
            # else: no image and not a text layer → transparent gap, skip

            if frame is not None:
                output = await asyncio.to_thread(
                    _alpha_composite_frame, output, frame, lyr.blend_mode
                )

        image_bytes: bytes = await asyncio.to_thread(_encode_png, output)

        # Build a minimal snapshot (id + z_index only) for the composite record.
        # Full serialisation is the persistence layer's responsibility.
        snapshot = [
            {"id": lyr.id, "z_index": lyr.z_index, "visible": lyr.visible} for lyr in layers
        ]
        return CompositeResult(
            canvas_id=canvas.id,
            image_bytes=image_bytes,
            width=canvas_w,
            height=canvas_h,
            layer_snapshot=snapshot,
        )

    # Alias used by tests and injection code
    @classmethod
    def create(cls, image_store: ImageStore) -> PilCompositorService:
        return cls(image_store)

    async def encode(
        self,
        image_bytes: bytes,
        *,
        fmt: str = "png",
        quality: int = 90,
    ) -> bytes:
        """Re-encode existing PNG bytes into the requested format."""
        img: Image.Image = await asyncio.to_thread(
            lambda b: Image.open(io.BytesIO(b)).convert("RGBA"), image_bytes
        )
        target = fmt.lower()
        if target == "png":
            return await asyncio.to_thread(_encode_png, img)
        if target in ("webp",):
            return await asyncio.to_thread(_encode_webp, img, quality)
        if target in ("jpg", "jpeg"):
            return await asyncio.to_thread(_encode_jpg, img, quality)
        from maistro_canvas.types import UnsupportedFormatError

        raise UnsupportedFormatError(f"unsupported format: {fmt!r}")


# Convenience alias: tests import CompositorService from this module
CompositorService = PilCompositorService
