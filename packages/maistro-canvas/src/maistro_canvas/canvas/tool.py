"""Canvas tool: layer-based image compositing engine for the Da Vinci agent.

Manages a session-scoped canvas with independently transformable layers.
Image generation is delegated to LiteLLM (which routes to the cheapest
available model per tier). Compositing and text rendering use Pillow.

Per ADR-K8S-025, this is an in-process tool (calls HTTP APIs, no OS-level
isolation needed). Per the canvas.md tool spec, it exposes 5 actions:
generate, refine, reference, composite, text.
"""

from __future__ import annotations

import base64
import io
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger("maistro_canvas.canvas.tool")

# ---------------------------------------------------------------------------
# Layer model
# ---------------------------------------------------------------------------


@dataclass
class Layer:
    """A single compositable layer on the canvas."""

    id: str
    name: str
    layer_type: str  # background | character | object | text
    image_data: bytes | None = None  # PNG bytes
    width: int = 0
    height: int = 0
    x: int = 0
    y: int = 0
    scale: float = 1.0
    rotation: float = 0.0  # degrees
    z_index: int = 0
    visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Canvas:
    """Session-scoped canvas holding ordered layers."""

    id: str
    width: int = 1024
    height: int = 1024
    layers: dict[str, Layer] = field(default_factory=dict)
    background_color: str = "#000000"

    def add_layer(self, layer: Layer) -> None:
        self.layers[layer.id] = layer

    def get_layer(self, layer_id: str) -> Layer | None:
        return self.layers.get(layer_id)

    def remove_layer(self, layer_id: str) -> bool:
        return self.layers.pop(layer_id, None) is not None

    def sorted_layers(self) -> list[Layer]:
        """Return layers sorted by z_index (back-to-front)."""
        return sorted(self.layers.values(), key=lambda layer: layer.z_index)


# ---------------------------------------------------------------------------
# Session store (in-memory, per Stronghold-API process)
# ---------------------------------------------------------------------------

_canvases: dict[str, Canvas] = {}


def get_or_create_canvas(
    session_id: str,
    width: int = 1024,
    height: int = 1024,
) -> Canvas:
    """Get existing canvas for session or create a new one."""
    if session_id not in _canvases:
        _canvases[session_id] = Canvas(id=session_id, width=width, height=height)
    return _canvases[session_id]


def destroy_canvas(session_id: str) -> None:
    """Clean up canvas state when session ends."""
    _canvases.pop(session_id, None)


# ---------------------------------------------------------------------------
# Draft / Proof model priority lists (from canvas.md)
# ---------------------------------------------------------------------------

DRAFT_MODELS = [
    "google-gemini-2.5-flash-image",
    "together-black-forest-labs/flux.1-schnell",
    "together-rundiffusion/juggernaut-lightning-flux",
    "together-stabilityai/stable-diffusion-xl",
    "imagen-4-fast",
]

PROOF_MODELS = [
    "google-gemini-3-pro-image",
    "imagen-4-ultra",
    "together-black-forest-labs/flux.2-pro",
    "together-black-forest-labs/flux.1.1-pro",
    "together-ideogram-ai/ideogram-3.0",
]

REFINE_MODEL = "together-black-forest-labs/flux.1-kontext-pro"

# Aspect ratio → (width, height) at 1024-base
ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
    "3:2": (1216, 832),
    "2:3": (832, 1216),
    "4:3": (1152, 896),
    "3:4": (896, 1152),
}


# ---------------------------------------------------------------------------
# Image generation (delegates to LiteLLM via Stronghold's model proxy)
# ---------------------------------------------------------------------------


async def _generate_image(
    prompt: str,
    *,
    tier: str = "draft",
    negative_prompt: str = "no text, no watermark, no signature",
    aspect_ratio: str = "1:1",
    count: int = 1,
    source_image: str | None = None,
    strength: float = 0.6,
    litellm_url: str = "http://litellm:4000",
    litellm_key: str = "",
) -> list[bytes]:
    """Generate images via LiteLLM's /v1/images/generations endpoint.

    Returns a list of PNG byte buffers.
    """

    models = DRAFT_MODELS if tier == "draft" else PROOF_MODELS
    if source_image:
        models = [REFINE_MODEL]

    width, height = ASPECT_RATIOS.get(aspect_ratio, (1024, 1024))

    body: dict[str, Any] = {
        "prompt": prompt,
        "n": count,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    if source_image:
        body["image"] = source_image
        body["strength"] = strength

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if litellm_key:
        headers["Authorization"] = f"Bearer {litellm_key}"

    last_error: Exception | None = None
    async with shared_client(timeout=120.0) as client:
        for model in models:
            body["model"] = model
            try:
                resp = await client.post(
                    f"{litellm_url}/v1/images/generations",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                results: list[bytes] = []
                for item in data.get("data", []):
                    b64 = item.get("b64_json", "")
                    if b64:
                        results.append(base64.b64decode(b64))
                if results:
                    logger.info("Generated %d image(s) via %s", len(results), model)
                    return results
            except Exception as e:
                logger.warning("Model %s failed: %s, trying next", model, e)
                last_error = e
                continue

    msg = f"All models failed for tier={tier}"
    raise RuntimeError(msg) from last_error


# ---------------------------------------------------------------------------
# Compositing engine (Pillow)
# ---------------------------------------------------------------------------


def _composite_layers(canvas: Canvas) -> bytes:
    """Composite all visible layers into a single PNG."""
    from PIL import Image

    base = Image.new("RGBA", (canvas.width, canvas.height), canvas.background_color)

    for layer in canvas.sorted_layers():
        if not layer.visible or layer.image_data is None:
            continue

        img = Image.open(io.BytesIO(layer.image_data)).convert("RGBA")

        # Scale
        if layer.scale != 1.0:
            new_w = max(1, int(img.width * layer.scale))
            new_h = max(1, int(img.height * layer.scale))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Rotate (expand=True keeps the full image after rotation)
        if layer.rotation != 0:
            img = img.rotate(-layer.rotation, expand=True, resample=Image.Resampling.BICUBIC)

        # Paste at position (using alpha channel as mask)
        base.paste(img, (layer.x, layer.y), img)

    buf = io.BytesIO()
    base.save(buf, format="PNG")
    return buf.getvalue()


def _render_text(
    text: str,
    style: dict[str, Any],
    canvas_width: int,
    canvas_height: int,
) -> bytes:
    """Render text to a transparent PNG layer using Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = style.get("size", 48)
    color = style.get("color", "#FFFFFF")
    alignment = style.get("alignment", "center")

    # Try to load a font; fall back to default
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font_name = style.get("font", "sans-serif")
        weight = style.get("weight", "normal")
        # Map common names to system fonts
        font_map = {
            "sans-serif": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "monospace": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        }
        if weight == "bold":
            font_map["sans-serif"] = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            font_map["serif"] = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
            font_map["monospace"] = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

        font_path = font_map.get(font_name, font_name)
        font = ImageFont.truetype(font_path, font_size)
    except OSError:
        font = ImageFont.load_default()

    # Calculate text bounding box for alignment
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]

    if alignment == "center":
        x = (canvas_width - text_width) // 2
    elif alignment == "right":
        x = canvas_width - text_width - 20
    else:
        x = 20

    y = style.get("y", canvas_height // 2 - font_size // 2)

    # Shadow
    shadow = style.get("shadow")
    if shadow:
        shadow_offset = shadow.get("offset", 2)
        shadow_color = shadow.get("color", "#000000")
        draw.text((x + shadow_offset, y + shadow_offset), text, fill=shadow_color, font=font)

    draw.text((x, y), text, fill=color, font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Canvas tool executor (the 5 actions)
# ---------------------------------------------------------------------------


async def execute_canvas(  # noqa: C901
    session_id: str,
    action: str,
    *,
    # generate params
    layer_type: str = "background",
    tier: str = "draft",
    prompt: str = "",
    aspect_ratio: str = "1:1",
    negative_prompt: str = "no text, no watermark, no signature",
    count: int = 2,
    lighting: str = "",
    perspective: str = "",
    # refine params
    source_image: str = "",
    region: str = "full",
    strength: float = 0.6,
    reference_images: list[str] | None = None,
    # composite params
    layers: list[dict[str, Any]] | None = None,
    canvas_width: int = 1024,
    canvas_height: int = 1024,
    # text params
    text_content: str = "",
    text_style: dict[str, Any] | None = None,
    # infra
    litellm_url: str = "http://litellm:4000",
    litellm_key: str = "",
) -> dict[str, Any]:
    """Execute a canvas action. Returns structured result with layer IDs and images."""

    canvas = get_or_create_canvas(session_id, canvas_width, canvas_height)

    if action == "generate":
        # Build prompt with isolation instructions per layer type
        full_prompt = prompt
        if layer_type == "background":
            full_prompt = f"{prompt}. Full environment scene, no people or characters, no objects in foreground."
        elif layer_type in ("character", "object"):
            full_prompt = (
                f"{prompt}. Isolated on pure white background, clean edges, full body visible."
            )

        if lighting:
            full_prompt += f" Lighting: {lighting}."
        if perspective:
            full_prompt += f" Camera: {perspective}."

        images = await _generate_image(
            full_prompt,
            tier=tier,
            negative_prompt=negative_prompt,
            aspect_ratio=aspect_ratio,
            count=count,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
        )

        created_layers: list[dict[str, Any]] = []
        for i, img_bytes in enumerate(images):
            from PIL import Image

            img = Image.open(io.BytesIO(img_bytes))
            layer_id = f"{layer_type}-{uuid.uuid4().hex[:8]}"
            layer = Layer(
                id=layer_id,
                name=f"{layer_type} variant {i + 1}",
                layer_type=layer_type,
                image_data=img_bytes,
                width=img.width,
                height=img.height,
                z_index=0 if layer_type == "background" else 10 + len(canvas.layers),
            )
            canvas.add_layer(layer)
            created_layers.append(
                {
                    "layer_id": layer_id,
                    "name": layer.name,
                    "width": img.width,
                    "height": img.height,
                    "z_index": layer.z_index,
                    "image_b64": base64.b64encode(img_bytes).decode(),
                }
            )

        return {
            "action": "generate",
            "tier": tier,
            "layer_type": layer_type,
            "count": len(created_layers),
            "layers": created_layers,
            "canvas_id": canvas.id,
        }

    if action == "refine":
        images = await _generate_image(
            prompt,
            tier="proof",
            source_image=source_image,
            strength=strength,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
        )

        layer_id = f"refined-{uuid.uuid4().hex[:8]}"
        img_bytes = images[0]
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        layer = Layer(
            id=layer_id,
            name=f"refined ({region})",
            layer_type="character",
            image_data=img_bytes,
            width=img.width,
            height=img.height,
        )
        canvas.add_layer(layer)

        return {
            "action": "refine",
            "region": region,
            "strength": strength,
            "layer_id": layer_id,
            "width": img.width,
            "height": img.height,
            "image_b64": base64.b64encode(img_bytes).decode(),
        }

    if action == "reference":
        # Generate hero image, then turnaround views
        hero_images = await _generate_image(
            f"{prompt}. Character reference sheet, front view, clean isolated on white background.",
            tier="draft",
            aspect_ratio="1:1",
            count=1,
            litellm_url=litellm_url,
            litellm_key=litellm_key,
        )

        views = ["front view", "side view (left)", "back view", "three-quarter view"]
        all_images: list[dict[str, Any]] = []

        for view in views:
            view_images = await _generate_image(
                f"{prompt}. {view}, character reference sheet, clean isolated on white background.",
                tier="draft",
                count=1,
                litellm_url=litellm_url,
                litellm_key=litellm_key,
            )
            all_images.append(
                {
                    "view": view,
                    "image_b64": base64.b64encode(view_images[0]).decode(),
                }
            )

        return {
            "action": "reference",
            "views": all_images,
            "hero_b64": base64.b64encode(hero_images[0]).decode(),
        }

    if action == "composite":
        # Update layer transforms from the provided layer specs
        if layers:
            for spec in layers:
                target = canvas.get_layer(spec.get("layer_id", spec.get("image", "")))
                if target is None:
                    continue
                if "x" in spec:
                    target.x = spec["x"]
                if "y" in spec:
                    target.y = spec["y"]
                if "scale" in spec:
                    target.scale = spec["scale"]
                if "rotation" in spec:
                    target.rotation = spec["rotation"]
                if "z_index" in spec:
                    target.z_index = spec["z_index"]
                if "visible" in spec:
                    target.visible = spec["visible"]

        result_bytes = _composite_layers(canvas)

        return {
            "action": "composite",
            "canvas_id": canvas.id,
            "width": canvas.width,
            "height": canvas.height,
            "layer_count": len([layer for layer in canvas.layers.values() if layer.visible]),
            "image_b64": base64.b64encode(result_bytes).decode(),
        }

    if action == "text":
        style = text_style or {}
        text_bytes = _render_text(text_content, style, canvas.width, canvas.height)

        layer_id = f"text-{uuid.uuid4().hex[:8]}"
        from PIL import Image

        img = Image.open(io.BytesIO(text_bytes))
        layer = Layer(
            id=layer_id,
            name=f"text: {text_content[:30]}",
            layer_type="text",
            image_data=text_bytes,
            width=img.width,
            height=img.height,
            z_index=100,  # text always on top
        )
        canvas.add_layer(layer)

        return {
            "action": "text",
            "layer_id": layer_id,
            "text": text_content,
            "style": style,
            "image_b64": base64.b64encode(text_bytes).decode(),
        }

    if action == "upload":
        # Import a user-uploaded image as a canvas layer
        upload_image = source_image  # reuse source_image param for the b64 data
        if not upload_image:
            return {"error": "upload_image (via source_image param) is required"}

        img_bytes = base64.b64decode(upload_image)
        from PIL import Image

        upload_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")

        # Re-encode as PNG for consistent storage
        buf = io.BytesIO()
        upload_img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        layer_id = f"{layer_type}-upload-{uuid.uuid4().hex[:8]}"
        layer = Layer(
            id=layer_id,
            name=text_content or f"uploaded {layer_type}",  # reuse text_content as name
            layer_type=layer_type,
            image_data=png_bytes,
            width=img.width,
            height=img.height,
            z_index=10 + len(canvas.layers),
        )
        canvas.add_layer(layer)

        return {
            "action": "upload",
            "layer_id": layer_id,
            "name": layer.name,
            "width": img.width,
            "height": img.height,
            "z_index": layer.z_index,
            "image_b64": base64.b64encode(png_bytes).decode(),
        }

    if action == "list_layers":
        return {
            "action": "list_layers",
            "canvas_id": canvas.id,
            "layers": list_layers(session_id),
        }

    if action == "transform":
        layer_id_param = layers[0].get("layer_id", "") if layers else ""
        transform_spec = layers[0] if layers else {}
        result = transform_layer(
            session_id,
            layer_id_param,
            x=transform_spec.get("x"),
            y=transform_spec.get("y"),
            scale=transform_spec.get("scale"),
            rotation=transform_spec.get("rotation"),
            z_index=transform_spec.get("z_index"),
            visible=transform_spec.get("visible"),
        )
        if result is None:
            return {"error": f"Layer not found: {layer_id_param}"}
        return {"action": "transform", **result}

    if action == "delete":
        layer_id_param = layers[0].get("layer_id", "") if layers else ""
        ok = delete_layer(session_id, layer_id_param)
        return {"action": "delete", "layer_id": layer_id_param, "deleted": ok}

    if action == "duplicate":
        layer_id_param = layers[0].get("layer_id", "") if layers else ""
        result = duplicate_layer(session_id, layer_id_param)
        if result is None:
            return {"error": f"Layer not found: {layer_id_param}"}
        return {"action": "duplicate", **result}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Character reference persistence (postgres)
# ---------------------------------------------------------------------------


@dataclass
class CharacterReference:
    """A saved character reference sheet for cross-session reuse."""

    id: str
    name: str
    description: str
    tags: list[str]
    user_id: str
    tenant_id: str
    hero_image: bytes  # PNG bytes of the hero/front view
    view_images: dict[str, bytes]  # view_name -> PNG bytes
    created_at: str = ""


# SQL for the character_references table (migration managed separately)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS character_references (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT[] NOT NULL DEFAULT '{}',
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    hero_image BYTEA NOT NULL,
    view_images JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_char_ref_tenant ON character_references(tenant_id);
CREATE INDEX IF NOT EXISTS idx_char_ref_tags ON character_references USING GIN(tags);
"""


async def save_character_reference(
    *,
    name: str,
    description: str,
    tags: list[str],
    hero_image: bytes,
    view_images: dict[str, bytes],
    user_id: str,
    tenant_id: str,
    db_pool: Any = None,
) -> dict[str, Any]:
    """Save a character reference to postgres for cross-session reuse."""
    ref_id = f"ref-{uuid.uuid4().hex[:12]}"

    if db_pool is None:
        logger.warning("No database pool — saving reference to in-memory store only")
        # Fallback: in-memory store for dev/testing
        _ref_store[f"{user_id}/{name}"] = CharacterReference(
            id=ref_id,
            name=name,
            description=description,
            tags=tags,
            user_id=user_id,
            tenant_id=tenant_id,
            hero_image=hero_image,
            view_images=view_images,
        )
        return {"id": ref_id, "name": name, "stored": "memory"}

    # Encode view images as base64 JSON for JSONB column
    views_json = {k: base64.b64encode(v).decode() for k, v in view_images.items()}

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO character_references (id, name, description, tags, user_id, tenant_id, hero_image, view_images)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (user_id, name) DO UPDATE SET
                description = EXCLUDED.description,
                tags = EXCLUDED.tags,
                hero_image = EXCLUDED.hero_image,
                view_images = EXCLUDED.view_images,
                created_at = NOW()
            """,
            ref_id,
            name,
            description,
            tags,
            user_id,
            tenant_id,
            hero_image,
            __import__("json").dumps(views_json),
        )

    return {"id": ref_id, "name": name, "stored": "postgres"}


async def load_character_reference(
    *,
    name: str,
    user_id: str,
    tenant_id: str,
    db_pool: Any = None,
) -> dict[str, Any] | None:
    """Load a character reference by name. Checks user's own refs first, then tenant."""
    if db_pool is None:
        ref = _ref_store.get(f"{user_id}/{name}")
        if ref is None:
            return None
        return {
            "name": ref.name,
            "description": ref.description,
            "tags": ref.tags,
            "hero_b64": base64.b64encode(ref.hero_image).decode(),
            "views": {k: base64.b64encode(v).decode() for k, v in ref.view_images.items()},
        }

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT name, description, tags, hero_image, view_images
            FROM character_references
            WHERE name = $1 AND (user_id = $2 OR tenant_id = $3)
            ORDER BY (user_id = $2) DESC
            LIMIT 1
            """,
            name,
            user_id,
            tenant_id,
        )
        if row is None:
            return None

        views_json = __import__("json").loads(row["view_images"]) if row["view_images"] else {}
        return {
            "name": row["name"],
            "description": row["description"],
            "tags": list(row["tags"]),
            "hero_b64": base64.b64encode(row["hero_image"]).decode(),
            "views": views_json,  # already base64 strings
        }


async def list_character_references(
    *,
    user_id: str,
    tenant_id: str,
    tags: list[str] | None = None,
    db_pool: Any = None,
) -> list[dict[str, Any]]:
    """List saved character references visible to the user."""
    if db_pool is None:
        results = []
        for ref in _ref_store.values():
            if ref.user_id == user_id or ref.tenant_id == tenant_id:
                if tags and not set(tags).intersection(ref.tags):
                    continue
                results.append(
                    {
                        "name": ref.name,
                        "description": ref.description,
                        "tags": ref.tags,
                        "user_id": ref.user_id,
                    }
                )
        return results

    async with db_pool.acquire() as conn:
        if tags:
            rows = await conn.fetch(
                """
                SELECT name, description, tags, user_id, created_at
                FROM character_references
                WHERE (user_id = $1 OR tenant_id = $2) AND tags && $3
                ORDER BY created_at DESC
                """,
                user_id,
                tenant_id,
                tags,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT name, description, tags, user_id, created_at
                FROM character_references
                WHERE user_id = $1 OR tenant_id = $2
                ORDER BY created_at DESC
                """,
                user_id,
                tenant_id,
            )

    return [
        {
            "name": r["name"],
            "description": r["description"],
            "tags": list(r["tags"]),
            "user_id": r["user_id"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


# In-memory fallback store for dev/testing
_ref_store: dict[str, CharacterReference] = {}


# ---------------------------------------------------------------------------
# Layer manipulation helpers (called by LLM as sub-actions)
# ---------------------------------------------------------------------------


def list_layers(session_id: str) -> list[dict[str, Any]]:
    """List all layers on the canvas with their current transforms."""
    canvas = _canvases.get(session_id)
    if canvas is None:
        return []
    return [
        {
            "layer_id": layer.id,
            "name": layer.name,
            "type": layer.layer_type,
            "x": layer.x,
            "y": layer.y,
            "scale": layer.scale,
            "rotation": layer.rotation,
            "z_index": layer.z_index,
            "width": layer.width,
            "height": layer.height,
            "visible": layer.visible,
        }
        for layer in canvas.sorted_layers()
    ]


def transform_layer(
    session_id: str,
    layer_id: str,
    *,
    x: int | None = None,
    y: int | None = None,
    scale: float | None = None,
    rotation: float | None = None,
    z_index: int | None = None,
    visible: bool | None = None,
) -> dict[str, Any] | None:
    """Update transform properties of a single layer."""
    canvas = _canvases.get(session_id)
    if canvas is None:
        return None
    layer = canvas.get_layer(layer_id)
    if layer is None:
        return None

    if x is not None:
        layer.x = x
    if y is not None:
        layer.y = y
    if scale is not None:
        layer.scale = scale
    if rotation is not None:
        layer.rotation = rotation
    if z_index is not None:
        layer.z_index = z_index
    if visible is not None:
        layer.visible = visible

    return {
        "layer_id": layer.id,
        "x": layer.x,
        "y": layer.y,
        "scale": layer.scale,
        "rotation": layer.rotation,
        "z_index": layer.z_index,
        "visible": layer.visible,
    }


def delete_layer(session_id: str, layer_id: str) -> bool:
    """Remove a layer from the canvas."""
    canvas = _canvases.get(session_id)
    if canvas is None:
        return False
    return canvas.remove_layer(layer_id)


def duplicate_layer(session_id: str, layer_id: str) -> dict[str, Any] | None:
    """Duplicate a layer with a new ID and offset position."""
    canvas = _canvases.get(session_id)
    if canvas is None:
        return None
    source = canvas.get_layer(layer_id)
    if source is None:
        return None

    new_id = f"{source.layer_type}-{uuid.uuid4().hex[:8]}"
    new_layer = Layer(
        id=new_id,
        name=f"{source.name} (copy)",
        layer_type=source.layer_type,
        image_data=source.image_data,
        width=source.width,
        height=source.height,
        x=source.x + 20,
        y=source.y + 20,
        scale=source.scale,
        rotation=source.rotation,
        z_index=source.z_index + 1,
        visible=source.visible,
        metadata=dict(source.metadata),
    )
    canvas.add_layer(new_layer)
    return {
        "layer_id": new_id,
        "name": new_layer.name,
        "x": new_layer.x,
        "y": new_layer.y,
    }
