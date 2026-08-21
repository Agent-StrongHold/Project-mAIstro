from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from mcp.pdf_composer import compose_cover, compose_interior
from mcp.products import ProductSpec

STANDARD_8x8 = ProductSpec(
    id="standard_8x8",
    name="Standard 8x8 Hardcover",
    description="8.5x8.5 inch square picture book",
    pod_package_id="picture_book_8x8",
    retail_price_usd=14.99,
    page_count=32,
    trim_width_in=8.25,
    trim_height_in=8.25,
    bleed_in=0.125,
    safety_margin_in=0.5,
)

LANDSCAPE_10x8 = ProductSpec(
    id="landscape_10x8",
    name="Landscape 10x8 Hardcover",
    description="10x8 inch landscape picture book",
    pod_package_id="picture_book_10x8",
    retail_price_usd=16.99,
    page_count=32,
    trim_width_in=10.0,
    trim_height_in=8.0,
    bleed_in=0.125,
    safety_margin_in=0.5,
)

COLORING_8x11 = ProductSpec(
    id="coloring_8x11",
    name="Coloring Book 8.5x11",
    description="8.5x11 inch coloring book",
    pod_package_id="coloring_8x11",
    retail_price_usd=8.99,
    page_count=32,
    trim_width_in=8.5,
    trim_height_in=11.0,
    bleed_in=0.0,
    safety_margin_in=0.5,
    interior_color="Black & White",
)

PRODUCT_MAP = {
    "standard_8x8": STANDARD_8x8,
    "landscape_10x8": LANDSCAPE_10x8,
    "coloring_8x11": COLORING_8x11,
}


def decode_base64_image(data: str) -> io.BytesIO:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return io.BytesIO(base64.b64decode(data))


def export_interior(payload: dict, output_path: str) -> str:
    product_id = payload.get("product_id", "landscape_10x8")
    product = PRODUCT_MAP.get(product_id, LANDSCAPE_10x8)
    title = payload.get("title", "My Book")
    author = payload.get("author", "Main Character Press")
    pages = payload.get("pages", [])

    page_images = []
    page_texts = {}

    for i, page in enumerate(pages):
        page_num = i + 1
        composite = page.get("composite")
        if composite:
            page_images.append(decode_base64_image(composite))
        else:
            layers = page.get("layers", [])
            bg = next((layer for layer in layers if layer.get("type") == "background"), None)
            if bg and bg.get("image_url"):
                img_data = decode_base64_image(bg["image_url"])
                page_images.append(img_data)
            else:
                blank = io.BytesIO()
                Image.new(
                    "RGB",
                    (int(product.bleed_width_pt), int(product.bleed_height_pt)),
                    (255, 255, 255),
                ).save(blank, format="PNG")
                blank.seek(0)
                page_images.append(blank)

        text_layers = [
            layer
            for layer in page.get("layers", [])
            if layer.get("type") == "text" and layer.get("text_content")
        ]
        if text_layers:
            page_texts[page_num] = " ".join(t["text_content"] for t in text_layers)

    actual_pages = max(len(page_images), product.page_count)
    while len(page_images) < actual_pages:
        blank = io.BytesIO()
        Image.new(
            "RGB", (int(product.bleed_width_pt), int(product.bleed_height_pt)), (245, 245, 248)
        ).save(blank, format="PNG")
        blank.seek(0)
        page_images.append(blank)

    spec = ProductSpec(
        id=product.id,
        name=product.name,
        description=product.description,
        pod_package_id=product.pod_package_id,
        retail_price_usd=product.retail_price_usd,
        page_count=actual_pages,
        trim_width_in=product.trim_width_in,
        trim_height_in=product.trim_height_in,
        bleed_in=product.bleed_in,
        safety_margin_in=product.safety_margin_in,
        interior_color=product.interior_color,
        print_quality=product.print_quality,
        binding=product.binding,
        paper=product.paper,
        cover_finish=product.cover_finish,
    )

    compose_interior(
        spec,
        output_path,
        page_images=page_images,
        page_texts=page_texts,
        title=title,
        author=author,
    )
    return output_path


def export_cover(payload: dict, output_path: str) -> str:
    product_id = payload.get("product_id", "landscape_10x8")
    product = PRODUCT_MAP.get(product_id, LANDSCAPE_10x8)
    title = payload.get("title", "My Book")
    author = payload.get("author", "Main Character Press")
    front_image = None
    back_image = None

    front_data = payload.get("front_cover")
    if front_data:
        front_image = decode_base64_image(front_data)

    back_data = payload.get("back_cover")
    if back_data:
        back_image = decode_base64_image(back_data)

    compose_cover(
        product,
        output_path,
        title=title,
        author=author,
        front_image=front_image,
        back_image=back_image,
    )
    return output_path


if __name__ == "__main__":
    raw = json.load(sys.stdin)
    mode = raw.get("mode", "interior")
    out_dir = raw.get("output_dir", tempfile.mkdtemp())

    if mode == "interior":
        path = export_interior(raw, str(Path(out_dir) / "interior.pdf"))
    elif mode == "cover":
        path = export_cover(raw, str(Path(out_dir) / "cover.pdf"))
    elif mode == "both":
        interior_path = export_interior(raw, str(Path(out_dir) / "interior.pdf"))
        cover_path = export_cover(raw, str(Path(out_dir) / "cover.pdf"))
        path = f"{interior_path},{cover_path}"
    else:
        print(json.dumps({"error": f"unknown mode: {mode}"}), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"ok": True, "path": path}))
