from __future__ import annotations

import io
import math
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib.colors import Color, white
from reportlab.pdfgen import canvas as pdfcanvas

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .products import ProductSpec


def _word_wrap(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    if max_width <= 0 or not text:
        return []
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        if stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _render_text_bar(
    c: pdfcanvas.Canvas,
    text: str,
    bar_x: float,
    bar_y: float,
    bar_w: float,
    bar_h: float,
    font_size: float = 11,
    font_name: str = "Helvetica",
    padding: float = 8,
    alpha: float = 0.88,
) -> None:
    text_color = Color(0.12, 0.12, 0.18)
    bar_color = Color(1.0, 1.0, 1.0, alpha)

    inner_w = bar_w - 2 * padding
    lines = _word_wrap(text, font_name, font_size, inner_w)
    if not lines:
        return

    line_height = font_size * 1.45
    needed_h = len(lines) * line_height + 2 * padding
    actual_h = min(needed_h, bar_h)

    c.saveState()
    c.setFillColor(bar_color)
    c.roundRect(bar_x, bar_y, bar_w, actual_h, 4, fill=1, stroke=0)

    c.setFillColor(text_color)
    c.setFont(font_name, font_size)
    text_y = bar_y + actual_h - padding - font_size
    for line in lines:
        if text_y < bar_y:
            break
        c.drawString(bar_x + padding, text_y, line)
        text_y -= line_height
    c.restoreState()


def compose_interior(
    product: ProductSpec,
    output_path: str | Path,
    page_images: Sequence[io.BytesIO | str | Path] | None = None,
    page_texts: dict[int, str] | None = None,
    title: str = "My Book",
    author: str = "Main Character Press",
) -> Path:
    output_path = Path(output_path)

    bleed_w = product.bleed_width_pt
    bleed_h = product.bleed_height_pt
    bleed = product.bleed_in * 72
    safety = product.safety_margin_in * 72

    c = pdfcanvas.Canvas(str(output_path), pagesize=(bleed_w, bleed_h))
    c.setTitle(title)
    c.setAuthor(author)
    c.setCreator("Main Character Press Pipeline")

    is_color = "Full Color" in product.interior_color
    page_count = product.page_count
    has_text = page_texts is not None and is_color

    for page_num in range(1, page_count + 1):
        has_image = page_images is not None and page_num <= len(page_images)

        if has_image and page_images is not None:
            img = page_images[page_num - 1]
            if isinstance(img, io.BytesIO):
                img.seek(0)
                from PIL import Image as PILImage

                pil_img = PILImage.open(img)
                tmp_path = output_path.parent / f"_tmp_page_{page_num}.png"
                pil_img.save(tmp_path, format="PNG")
                c.drawImage(
                    str(tmp_path), 0, 0, width=bleed_w, height=bleed_h, preserveAspectRatio=False
                )
                tmp_path.unlink(missing_ok=True)
            else:
                c.drawImage(
                    str(img), 0, 0, width=bleed_w, height=bleed_h, preserveAspectRatio=False
                )
        else:
            if page_num == 1:
                c.setFillColor(Color(0.1, 0.1, 0.3) if is_color else Color(0.2, 0.2, 0.2))
                c.rect(0, 0, bleed_w, bleed_h, fill=1, stroke=0)
                c.setFillColor(white)
                c.setFont("Helvetica-Bold", 28)
                c.drawCentredString(bleed_w / 2, bleed_h / 2 + 30, title)
                c.setFont("Helvetica", 14)
                c.drawCentredString(bleed_w / 2, bleed_h / 2 - 10, "A personalized story")
                c.setFont("Helvetica-Oblique", 11)
                c.drawCentredString(bleed_w / 2, bleed_h / 2 - 40, f"by {author}")
            elif page_num == 2:
                c.setFillColor(white)
                c.rect(0, 0, bleed_w, bleed_h, fill=1, stroke=0)
                c.setFillColor(Color(0.3, 0.3, 0.3))
                c.setFont("Helvetica", 10)
                safety_x = bleed + safety
                safety_y = bleed + safety
                c.drawString(safety_x, bleed_h - safety_y - 12, f"{title}")
                c.drawString(safety_x, bleed_h - safety_y - 26, f"Copyright 2026 {author}")
                c.drawString(safety_x, bleed_h - safety_y - 40, "All rights reserved.")
                c.drawString(safety_x, bleed_h - safety_y - 60, f"Page count: {page_count}")
                c.drawString(
                    safety_x,
                    bleed_h - safety_y - 74,
                    f"Interior: {product.interior_color}, {product.print_quality}",
                )
                c.drawString(safety_x, bleed_h - safety_y - 88, f"Paper: {product.paper}")
            else:
                if is_color:
                    hue = ((page_num - 3) % 26) / 26.0
                    r = 0.85 + 0.1 * math.sin(hue * 2 * math.pi)
                    g = 0.88 + 0.08 * math.sin(hue * 2 * math.pi + 2)
                    b = 0.92 + 0.06 * math.sin(hue * 2 * math.pi + 4)
                    c.setFillColor(Color(r, g, b))
                else:
                    gray = 0.97
                    c.setFillColor(Color(gray, gray, gray))
                c.rect(0, 0, bleed_w, bleed_h, fill=1, stroke=0)
                c.setFillColor(Color(0.4, 0.4, 0.4))
                c.setFont("Helvetica", 12)
                c.drawCentredString(bleed_w / 2, bleed_h / 2, f"Page {page_num}")

        if has_text and page_num >= 3 and page_texts is not None and page_num in page_texts:
            text = page_texts[page_num]
            if text.strip():
                bar_margin_x = bleed + safety
                bar_margin_bottom = bleed + safety
                bar_h = bleed_h * 0.18
                bar_y = bar_margin_bottom
                bar_x = bar_margin_x
                bar_w = bleed_w - 2 * bar_margin_x

                font_size = min(11, bleed_w / 40)
                _render_text_bar(c, text, bar_x, bar_y, bar_w, bar_h, font_size=font_size)

        c.showPage()

    c.save()
    return output_path


def compose_cover(
    product: ProductSpec,
    output_path: str | Path,
    title: str = "My Book",
    author: str = "Main Character Press",
    front_image: io.BytesIO | str | Path | None = None,
    back_image: io.BytesIO | str | Path | None = None,
) -> Path:
    output_path = Path(output_path)

    cover_w = product.cover_width_pt
    cover_h = product.cover_height_pt

    bleed = product.bleed_in * 72
    spine_w = product.spine_width_pt
    trim_w = product.trim_width_pt
    trim_h = product.trim_height_pt

    back_x = bleed
    spine_x = bleed + trim_w
    front_x = bleed + trim_w + spine_w

    c = pdfcanvas.Canvas(str(output_path), pagesize=(cover_w, cover_h))
    c.setTitle(f"{title} - Cover")

    is_color = "Full Color" in product.interior_color

    if is_color:
        c.setFillColor(Color(0.15, 0.25, 0.45))
    else:
        c.setFillColor(Color(0.25, 0.25, 0.25))
    c.rect(0, 0, cover_w, cover_h, fill=1, stroke=0)

    if back_image:
        c.drawImage(
            str(back_image), back_x, bleed, width=trim_w, height=trim_h, preserveAspectRatio=False
        )
    else:
        c.setFillColor(Color(0.2, 0.3, 0.5) if is_color else Color(0.3, 0.3, 0.3))
        c.rect(back_x, bleed, trim_w, trim_h, fill=1, stroke=0)
        c.saveState()
        c.setFillColor(white)
        c.setFont("Helvetica", 11)
        c.drawCentredString(back_x + trim_w / 2, bleed + trim_h / 2, "Back Cover")
        c.restoreState()

    c.setFillColor(Color(0.1, 0.1, 0.1))
    c.rect(spine_x, bleed, spine_w, trim_h, fill=1, stroke=0)
    if spine_w > 15:
        c.saveState()
        c.setFillColor(white)
        c.setFont("Helvetica", 7)
        spine_center_x = spine_x + spine_w / 2
        spine_center_y = bleed + trim_h / 2
        c.translate(spine_center_x, spine_center_y)
        c.rotate(90)
        c.drawCentredString(0, 0, title)
        c.restoreState()

    if front_image:
        c.drawImage(
            str(front_image), front_x, bleed, width=trim_w, height=trim_h, preserveAspectRatio=False
        )
    else:
        c.setFillColor(Color(0.2, 0.35, 0.55) if is_color else Color(0.35, 0.35, 0.35))
        c.rect(front_x, bleed, trim_w, trim_h, fill=1, stroke=0)
        c.saveState()
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(front_x + trim_w / 2, bleed + trim_h / 2 + 30, title)
        c.setFont("Helvetica", 12)
        c.drawCentredString(front_x + trim_w / 2, bleed + trim_h / 2 - 5, author)
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(
            front_x + trim_w / 2, bleed + trim_h / 2 - 30, "A personalized story just for you"
        )
        c.restoreState()

    barcode_w = 72
    barcode_h = 54
    barcode_x = back_x + trim_w - barcode_w - 36
    barcode_y = bleed + 18
    c.setFillColor(white)
    c.rect(barcode_x, barcode_y, barcode_w, barcode_h, fill=1, stroke=0)
    c.setFillColor(Color(0.5, 0.5, 0.5))
    c.setFont("Helvetica", 6)
    c.drawCentredString(barcode_x + barcode_w / 2, barcode_y + barcode_h / 2, "ISBN Barcode Area")

    c.showPage()
    c.save()
    return output_path
