"""Server-configured resource limits for Canvas image allocation (#393).

A layer's ``scale`` used to reach ``PIL.resize`` unbounded: base canvas
dimensions were capped (``_MAX_DIM``), but ``scale=1e6`` on a 1024px layer
computed a ~1.024e9-px-wide target and attempted a ~4e18-byte allocation,
enabling memory/CPU denial of service. This module centralises the
server-configured bounds that are enforced *before* any pixel allocation:

- :func:`validate_scale` rejects string-encoded values, NaN, ±infinity,
  zero/negative scales, and scales above ``max_scale``.
- :func:`scaled_dimensions` computes the resize target with overflow-safe
  arithmetic and rejects targets above ``max_dimension`` per side or
  ``max_layer_pixels`` per image — checked before ``Image.resize`` runs.
- :class:`PixelBudget` charges each resize against a per-request cumulative
  cap so many individually modest layers cannot accumulate into an
  unbounded allocation ("cumulative multi-layer abuse").
- :func:`run_with_resize_timeout` bounds the decode/resize worker so a slow
  composite fails explicitly instead of hanging the caller.
- :func:`configure_pillow_decompression_limit` pins Pillow's decode-time
  pixel guard to the server-configured per-image cap.

Every rejection raises a typed :class:`~maistro_canvas.types.CanvasError`
whose detail names the violated limit, so the error is explicit, logged,
and observable; callers persist output only after success, so a rejected
composite never partially persists.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

from maistro_canvas.types import (
    _MAX_DIM,
    CompositeTimeoutError,
    LayerPixelBudgetError,
    LayerScaleLimitError,
)

logger = logging.getLogger("maistro_canvas.canvas.limits")

__all__ = [
    "CanvasImageLimits",
    "PixelBudget",
    "configure_pillow_decompression_limit",
    "load_image_limits",
    "run_with_resize_timeout",
    "scaled_dimensions",
    "validate_scale",
]

# ── Environment variables (server configuration) ────────────────────────

MAX_SCALE_ENV_VAR = "MAISTRO_CANVAS_MAX_SCALE"
MAX_LAYER_PIXELS_ENV_VAR = "MAISTRO_CANVAS_MAX_LAYER_PIXELS"
MAX_REQUEST_PIXELS_ENV_VAR = "MAISTRO_CANVAS_MAX_REQUEST_PIXELS"
MAX_DIMENSION_ENV_VAR = "MAISTRO_CANVAS_MAX_DIMENSION"
RESIZE_TIMEOUT_ENV_VAR = "MAISTRO_CANVAS_RESIZE_TIMEOUT_S"

#: Upper bound on any single layer's scale factor. Generative workflows
#: scale *down* (characters are generated at final size, per davinci
#: RULES.md), so a generous upscale allowance is safe and 64 covers any
#: legitimate downscale granularity.
_DEFAULT_MAX_SCALE = 64.0

#: Maximum pixels a single resized layer may occupy. Matches the area of
#: the largest legal canvas (_MAX_DIM x _MAX_DIM): one layer may occupy at
#: most a full-size canvas, never more.
_DEFAULT_MAX_LAYER_PIXELS = _MAX_DIM * _MAX_DIM

#: Cumulative resize budget for one composite request (all layers summed).
#: Four full-canvas-sized layers by default; the base canvas itself is
#: already bounded separately by ``validate_canvas_dimensions``.
_DEFAULT_MAX_REQUEST_PIXELS = 4 * _DEFAULT_MAX_LAYER_PIXELS

#: Per-side cap on computed resize targets; defaults to the canvas cap so
#: an extreme-aspect target (e.g. 500000x1) is rejected by the same bound
#: the canvas itself honours.
_DEFAULT_MAX_DIMENSION = _MAX_DIM

#: Wall-clock bound for one decode/resize worker step.
_DEFAULT_RESIZE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class CanvasImageLimits:
    """Immutable snapshot of the server-configured image resource limits."""

    max_scale: float = _DEFAULT_MAX_SCALE
    max_layer_pixels: int = _DEFAULT_MAX_LAYER_PIXELS
    max_request_pixels: int = _DEFAULT_MAX_REQUEST_PIXELS
    max_dimension: int = _DEFAULT_MAX_DIMENSION
    resize_timeout_s: float = _DEFAULT_RESIZE_TIMEOUT_S

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> CanvasImageLimits:
        """Read limits from the environment, falling back to safe defaults.

        A malformed override never disables a limit: unparsable values are
        logged and replaced with the default.
        """
        source = os.environ if env is None else env
        max_scale = _float_env(source, MAX_SCALE_ENV_VAR, _DEFAULT_MAX_SCALE)
        max_layer_pixels = _int_env(source, MAX_LAYER_PIXELS_ENV_VAR, _DEFAULT_MAX_LAYER_PIXELS)
        return cls(
            max_scale=max_scale,
            max_layer_pixels=max_layer_pixels,
            max_request_pixels=_int_env(
                source,
                MAX_REQUEST_PIXELS_ENV_VAR,
                max(_DEFAULT_MAX_REQUEST_PIXELS, max_layer_pixels),
            ),
            max_dimension=_int_env(source, MAX_DIMENSION_ENV_VAR, _DEFAULT_MAX_DIMENSION),
            resize_timeout_s=_float_env(source, RESIZE_TIMEOUT_ENV_VAR, _DEFAULT_RESIZE_TIMEOUT_S),
        )


def _float_env(source: Mapping[str, str], key: str, default: float) -> float:
    raw = source.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring malformed %s=%r; using %s", key, raw, default)
        return default
    if not isfinite(value) or value <= 0.0:
        logger.warning("Ignoring out-of-range %s=%r; using %s", key, raw, default)
        return default
    return value


def _int_env(source: Mapping[str, str], key: str, default: int) -> int:
    raw = source.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring malformed %s=%r; using %s", key, raw, default)
        return default
    if value <= 0:
        logger.warning("Ignoring out-of-range %s=%r; using %s", key, raw, default)
        return default
    return value


def load_image_limits() -> CanvasImageLimits:
    """Snapshot the current server-configured limits."""
    return CanvasImageLimits.from_env()


# ── Validation (runs before any pixel allocation) ───────────────────────


def validate_scale(scale: Any, limits: CanvasImageLimits | None = None) -> float:
    """Return ``scale`` as a finite positive float within ``max_scale``.

    Rejects, with :class:`LayerScaleLimitError`:
    - non-numeric types (str/None/objects) — string-encoded numbers such as
      ``"1e6"`` or ``"nan"`` must not parse into a scale;
    - ``bool`` (a subclass of int, but semantically not a scale);
    - NaN and ±infinity;
    - zero and negative values;
    - values above ``limits.max_scale``.
    """
    bound = limits if limits is not None else load_image_limits()
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        msg = f"scale must be a finite positive number, got {type(scale).__name__}"
        raise LayerScaleLimitError(msg)
    try:
        value = float(scale)
    except OverflowError:
        # An int whose magnitude exceeds the float range (e.g. 10**400).
        msg = f"scale overflows the float range, got {scale}"
        raise LayerScaleLimitError(msg) from None
    if not isfinite(value):
        msg = f"scale must be finite, got {value}"
        raise LayerScaleLimitError(msg)
    if value <= 0.0:
        msg = f"scale must be greater than 0, got {value}"
        raise LayerScaleLimitError(msg)
    if value > bound.max_scale:
        msg = f"scale exceeds the configured maximum of {bound.max_scale:g}, got {value}"
        raise LayerScaleLimitError(msg)
    return value


def scaled_dimensions(
    src_w: int,
    src_h: int,
    scale: float,
    limits: CanvasImageLimits | None = None,
) -> tuple[int, int]:
    """Compute the resize target for ``src_w`` x ``src_h`` at ``scale``.

    Both dimensions are validated against the configured per-image caps
    *before* the caller allocates: each side may not exceed
    ``max_dimension`` and the pixel count may not exceed
    ``max_layer_pixels``. Raises :class:`LayerPixelBudgetError` when the
    target would overflow either bound.
    """
    bound = limits if limits is not None else load_image_limits()
    value = validate_scale(scale, bound)
    new_w = max(1, round(src_w * value))
    new_h = max(1, round(src_h * value))
    if not (isfinite(new_w) and isfinite(new_h)):  # defensive; ints are always finite
        msg = "computed resize target is not finite"
        raise LayerPixelBudgetError(msg)
    if new_w > bound.max_dimension or new_h > bound.max_dimension:
        msg = f"scaled size {new_w}x{new_h} exceeds the per-side maximum of {bound.max_dimension}px"
        raise LayerPixelBudgetError(msg)
    if new_w * new_h > bound.max_layer_pixels:
        msg = (
            f"scaled size {new_w}x{new_h} ({new_w * new_h} pixels) exceeds the "
            f"per-image maximum of {bound.max_layer_pixels} pixels"
        )
        raise LayerPixelBudgetError(msg)
    return new_w, new_h


class PixelBudget:
    """Cumulative per-request budget for resized layer pixels."""

    def __init__(self, limits: CanvasImageLimits | None = None) -> None:
        bound = limits if limits is not None else load_image_limits()
        self.max_request_pixels = bound.max_request_pixels
        self.remaining = bound.max_request_pixels

    def charge(self, width: int, height: int) -> None:
        """Charge one resize target against the budget before allocation."""
        pixels = width * height
        if pixels > self.remaining:
            msg = (
                f"composite would resize {width}x{height} ({pixels} pixels) but only "
                f"{self.remaining} of the {self.max_request_pixels}-pixel per-request "
                "budget remains"
            )
            raise LayerPixelBudgetError(msg)
        self.remaining -= pixels


def configure_pillow_decompression_limit(limits: CanvasImageLimits | None = None) -> int:
    """Pin Pillow's decode-time pixel guard to the per-image cap.

    Returns the configured value so callers can log/observe it. Idempotent.
    """
    bound = limits if limits is not None else load_image_limits()
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = bound.max_layer_pixels
    return Image.MAX_IMAGE_PIXELS


async def run_with_resize_timeout(
    coro: Any,
    limits: CanvasImageLimits | None = None,
) -> Any:
    """Await a decode/resize worker step under the configured timeout.

    The worker runs off the event loop (``asyncio.to_thread`` by the
    caller); this bound converts an over-long CPU-bound step into an
    explicit :class:`CompositeTimeoutError` instead of an indefinite hang.
    """
    bound = limits if limits is not None else load_image_limits()
    try:
        return await asyncio.wait_for(coro, timeout=bound.resize_timeout_s)
    except TimeoutError as exc:
        msg = f"decode/resize worker exceeded the configured timeout of {bound.resize_timeout_s:g}s"
        raise CompositeTimeoutError(msg) from exc
