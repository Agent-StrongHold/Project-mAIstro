"""Canvas structured exporters — SPEC-070426-457b.

HTML export is pure stdlib and always runs. PPTX export needs python-pptx; those
tests skip when it is absent (graceful degradation is itself covered explicitly).
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from maistro_canvas.export import (
    ExporterDependencyError,
    ExportLayer,
    ExportPage,
    ExportText,
    export_html,
    export_pptx,
)

# a 1x1 transparent PNG
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


def _page() -> ExportPage:
    return ExportPage(
        width=1280,
        height=720,
        background_color="#0B0B0B",
        layers=[
            ExportLayer(z_index=0, x=0, y=0, width=1280, height=720, image_png=_PNG),
            ExportLayer(
                z_index=1,
                x=64,
                y=520,
                text=ExportText(
                    content="Hello & <world>", size=48, color="#FFFFFF", alignment="center"
                ),
            ),
        ],
    )


# ─── HTML ────────────────────────────────────────────────────────────────────


def test_html_is_single_file_and_fixed_size() -> None:
    out = export_html(_page())
    assert out.startswith("<!doctype html>")
    assert "width:1280px" in out and "height:720px" in out
    assert "background:#0B0B0B" in out


def test_html_escapes_text_and_keeps_it_as_text() -> None:
    out = export_html(_page())
    assert "Hello &amp; &lt;world&gt;" in out  # escaped, still selectable text (not rasterized)
    assert "text-align:center" in out
    assert "font-size:48px" in out


def test_html_image_layer_becomes_data_uri() -> None:
    out = export_html(_page())
    assert "data:image/png;base64," in out


def test_html_layers_paint_back_to_front_by_z_index() -> None:
    page = ExportPage(
        width=100,
        height=100,
        layers=[
            ExportLayer(z_index=5, text=ExportText(content="TOP")),
            ExportLayer(z_index=1, text=ExportText(content="BOTTOM")),
        ],
    )
    out = export_html(page)
    assert out.index("BOTTOM") < out.index("TOP")  # lower z rendered first (behind)


def test_html_applies_rotation_and_opacity() -> None:
    page = ExportPage(
        width=100,
        height=100,
        layers=[ExportLayer(rotation=30, opacity=0.5, text=ExportText(content="x"))],
    )
    out = export_html(page)
    assert "transform:rotate(30deg)" in out
    assert "opacity:0.5" in out


# ─── PPTX ────────────────────────────────────────────────────────────────────


def test_pptx_is_a_valid_editable_deck() -> None:
    pptx = pytest.importorskip("pptx")
    data = export_pptx([_page(), _page()])
    # a .pptx is a zip (OOXML); text stays as editable text, not a picture
    assert zipfile.is_zipfile(BytesIO(data))
    prs = pptx.Presentation(BytesIO(data))
    assert len(prs.slides) == 2
    texts = [
        run.text
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_text_frame
        for para in shape.text_frame.paragraphs
        for run in para.runs
    ]
    assert any("Hello" in t for t in texts)  # editable text box, not baked into an image


def test_pptx_requires_at_least_one_page() -> None:
    pytest.importorskip("pptx")
    with pytest.raises(ExporterDependencyError):
        export_pptx([])


def test_pptx_missing_dependency_raises_graceful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When python-pptx is absent, PPTX export raises a typed error rather than crashing."""
    import builtins

    real_import = builtins.__import__

    def _no_pptx(name: str, *args: object, **kwargs: object) -> object:
        if name == "pptx" or name.startswith("pptx."):
            raise ImportError("no pptx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pptx)
    with pytest.raises(ExporterDependencyError):
        export_pptx([_page()])
