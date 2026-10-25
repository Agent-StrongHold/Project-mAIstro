"""Tests for the canvas compositor (#171).

`canvas/compositor.py` had **0% coverage** — not "reported at zero", but absent
from `coverage.xml` entirely, because `canvas/` has no `__init__.py` and
coverage.py skips namespace-package directories when it walks for files that
were never imported. Two gates were green over it for the same reason: the
aggregate floor, because the statements were not in the denominator, and the
diff gate, because a PR touching these files would find no record to compare
against.

It is live code: `canvas/routes.py` and `canvas/runner.py` both import it.

The module's docstring makes a falsifiable claim — *"the compositor is
stateless: given the same inputs it always produces byte-identical output
(determinism invariant from spec 1189)"* — so that is what these assert,
alongside the layer-ordering and blend-mode behaviour the compositing actually
turns on. Where a test would only restate the implementation (that
`_encode_png` calls `img.save`), it asserts the observable property instead
(that the bytes decode to an image of the right size and mode).
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from maistro_canvas.canvas.compositor import (
    CompositorService,
    PilCompositorService,
    _alpha_composite_frame,
    _parse_hex_color,
    _render_text_layer,
    _transform_layer_image,
)
from maistro_canvas.types import CanvasRecord, LayerRecord, TextConfig, UnsupportedFormatError

RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)


class DictImageStore:
    """An `ImageStore` over a dict. Deliberately not a mock.

    The compositor's contract with the store is one method returning a PIL
    image; a `Mock` would let a signature change pass, and the whole point of
    this file is that something passed while proving nothing.
    """

    def __init__(self, images: dict[str, Image.Image] | None = None) -> None:
        self.images = images or {}
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> Image.Image:
        self.fetched.append(url)
        if url not in self.images:
            raise FileNotFoundError(url)
        return self.images[url]


def solid(size: tuple[int, int], color: tuple[int, int, int, int]) -> Image.Image:
    return Image.new("RGBA", size, color)


def canvas(width: int = 40, height: int = 30, background: str = "#000000") -> CanvasRecord:
    return CanvasRecord(id="c1", name="c", width=width, height=height, background_color=background)


def layer(**kwargs) -> LayerRecord:
    base = {"id": "l1", "canvas_id": "c1", "name": "l"}
    return LayerRecord(**{**base, **kwargs})


def decode(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert("RGBA")


class TestParseHexColor:
    def test_six_digit_hex(self):
        assert _parse_hex_color("#FF8000") == (255, 128, 0, 255)

    def test_three_digit_hex_expands_each_nibble(self):
        assert _parse_hex_color("#F80") == _parse_hex_color("#FF8800")

    def test_the_leading_hash_is_optional(self):
        assert _parse_hex_color("00FF00") == (0, 255, 0, 255)

    @pytest.mark.parametrize("bad", ["#12345", "#GGGGGG_", "", "#1234567"])
    def test_an_unparseable_colour_falls_back_to_opaque_white(self, bad):
        """The compositor never raises on a bad background — a malformed colour
        in a stored record would otherwise make the canvas unrenderable rather
        than merely wrong."""
        assert _parse_hex_color(bad) == (255, 255, 255, 255)


class TestTransformLayerImage:
    def test_the_result_is_always_canvas_sized(self):
        """Every frame is composited onto the canvas, so a transform that
        returned the source size would misalign every later layer."""
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=40,
            canvas_h=30,
            x=0,
            y=0,
            scale=3.0,
            rotation=45.0,
            opacity=0.5,
        )
        assert out.size == (40, 30)
        assert out.mode == "RGBA"

    def test_opacity_scales_the_alpha_channel(self):
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=20,
            canvas_h=20,
            x=10,
            y=10,
            scale=1.0,
            rotation=0.0,
            opacity=0.5,
        )
        assert out.getpixel((10, 10))[3] == pytest.approx(128, abs=2)

    def test_opacity_does_not_darken_the_colour(self):
        """The other half of the same bug, and the half a pixel-alpha check
        misses. `paste(img, pos, img)` blended RGB against the transparent-black
        frame as well as alpha, so a half-opacity pure red arrived as
        (128, 0, 0, 64) — too faint *and* too dark. Alpha carries the fade;
        the colour must survive it intact."""
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=20,
            canvas_h=20,
            x=10,
            y=10,
            scale=1.0,
            rotation=0.0,
            opacity=0.5,
        )
        assert out.getpixel((10, 10))[:3] == (255, 0, 0)

    def test_full_opacity_leaves_alpha_untouched(self):
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=20,
            canvas_h=20,
            x=10,
            y=10,
            scale=1.0,
            rotation=0.0,
            opacity=1.0,
        )
        assert out.getpixel((10, 10))[3] == 255

    def test_scaling_up_covers_more_of_the_canvas(self):
        def opaque_pixels(scale: float) -> int:
            out = _transform_layer_image(
                solid((4, 4), RED),
                canvas_w=40,
                canvas_h=40,
                x=20,
                y=20,
                scale=scale,
                rotation=0.0,
                opacity=1.0,
            )
            return sum(1 for px in out.getdata() if px[3] > 0)

        assert opaque_pixels(4.0) > opaque_pixels(1.0)

    def test_a_layer_positioned_off_canvas_is_clipped_not_an_error(self):
        """Clipping is the documented behaviour. Raising here would let one
        badly-placed layer fail a whole composite."""
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=20,
            canvas_h=20,
            x=500,
            y=500,
            scale=1.0,
            rotation=0.0,
            opacity=1.0,
        )
        assert out.size == (20, 20)
        assert all(px[3] == 0 for px in out.getdata())

    def test_a_non_positive_scale_does_not_divide_by_zero_or_raise(self):
        """`scale` reaches this from a stored record, so zero is reachable."""
        out = _transform_layer_image(
            solid((10, 10), RED),
            canvas_w=20,
            canvas_h=20,
            x=10,
            y=10,
            scale=0.0,
            rotation=0.0,
            opacity=1.0,
        )
        assert out.size == (20, 20)


class TestAlphaCompositeFrame:
    def _frames(self):
        return solid((8, 8), RED), solid((8, 8), BLUE)

    def test_normal_puts_the_layer_over_the_base(self):
        base, over = self._frames()
        assert _alpha_composite_frame(base, over, "normal").getpixel((4, 4)) == BLUE

    def test_multiply_of_two_opaque_primaries_is_black(self):
        base, over = self._frames()
        r, g, b, _ = _alpha_composite_frame(base, over, "multiply").getpixel((4, 4))
        assert (r, g, b) == (0, 0, 0)

    def test_screen_of_red_over_blue_is_magenta(self):
        base, over = self._frames()
        r, g, b, _ = _alpha_composite_frame(base, over, "screen").getpixel((4, 4))
        assert (r, g, b) == (255, 0, 255)

    def test_darken_and_lighten_pick_per_channel_extremes(self):
        base, over = self._frames()
        assert _alpha_composite_frame(base, over, "darken").getpixel((4, 4))[:3] == (0, 0, 0)
        assert _alpha_composite_frame(base, over, "lighten").getpixel((4, 4))[:3] == (255, 0, 255)

    def test_overlay_is_accepted_and_produces_an_rgba_frame(self):
        base, over = self._frames()
        out = _alpha_composite_frame(base, over, "overlay")
        assert out.mode == "RGBA"
        assert out.size == (8, 8)

    def test_an_unknown_blend_mode_degrades_to_normal_rather_than_raising(self):
        """`blend_mode` is a stored string. A KeyError here would make one bad
        record poison every composite of that canvas."""
        base, over = self._frames()
        unknown = _alpha_composite_frame(base, over, "no-such-mode")
        assert unknown.getpixel((4, 4)) == _alpha_composite_frame(base, over, "normal").getpixel(
            (4, 4)
        )

    def test_a_transparent_layer_leaves_the_base_visible(self):
        base = solid((8, 8), RED)
        clear = Image.new("RGBA", (8, 8), (0, 0, 255, 0))
        assert _alpha_composite_frame(base, clear, "normal").getpixel((4, 4)) == RED


class TestRenderTextLayer:
    def test_text_is_drawn_onto_a_transparent_canvas_sized_frame(self):
        frame = _render_text_layer(TextConfig(content="hello"), 200, 80)
        assert frame.size == (200, 80)
        assert any(px[3] > 0 for px in frame.getdata()), "nothing was drawn"

    def test_empty_text_draws_nothing_and_does_not_raise(self):
        frame = _render_text_layer(TextConfig(content=""), 60, 40)
        assert all(px[3] == 0 for px in frame.getdata())

    @pytest.mark.parametrize("alignment", ["left", "center", "right"])
    def test_each_alignment_places_ink_somewhere_on_the_frame(self, alignment):
        frame = _render_text_layer(TextConfig(content="iii", size=20, alignment=alignment), 300, 60)
        assert any(px[3] > 0 for px in frame.getdata())

    def test_alignment_actually_moves_the_text(self):
        """Three code paths that all draw *something* would pass the test above
        while ignoring the setting entirely."""

        def centre_of_mass(alignment: str) -> float:
            frame = _render_text_layer(
                TextConfig(content="iii", size=20, alignment=alignment), 300, 60
            )
            xs = [i % 300 for i, px in enumerate(frame.getdata()) if px[3] > 0]
            return sum(xs) / len(xs)

        assert centre_of_mass("left") < centre_of_mass("center") < centre_of_mass("right")

    def test_a_shadow_adds_ink_beyond_the_glyphs(self):
        def ink(**kwargs) -> int:
            frame = _render_text_layer(TextConfig(content="X", size=40, **kwargs), 120, 80)
            return sum(1 for px in frame.getdata() if px[3] > 0)

        assert ink(shadow_color="#000000", shadow_offset=(6, 6)) > ink()

    def test_a_malformed_shadow_colour_still_renders(self):
        frame = _render_text_layer(TextConfig(content="X", size=30, shadow_color="#nope"), 100, 60)
        assert any(px[3] > 0 for px in frame.getdata())

    def test_the_absolute_font_path_is_tried_when_the_bare_name_is_not_found(self, monkeypatch):
        """The fallback chain is not decoration: a slim container image has no
        font cache, so `truetype("DejaVuSans.ttf")` raises and the absolute
        Debian path is what actually renders. Untested, a typo in that path
        would only surface as blank text in production."""
        import maistro_canvas.canvas.compositor as mod

        tried: list[str] = []
        real = mod.ImageFont.truetype

        def only_absolute(path, size, *a, **kw):
            tried.append(path)
            if not str(path).startswith("/"):
                raise OSError("cannot open resource")
            return real(path, size, *a, **kw)

        monkeypatch.setattr(mod.ImageFont, "truetype", only_absolute)
        frame = _render_text_layer(TextConfig(content="X", size=24), 100, 60)
        assert tried == ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        assert any(px[3] > 0 for px in frame.getdata())

    def test_text_still_renders_when_neither_system_font_exists(self, monkeypatch):
        """Both system lookups failing must degrade to PIL's default font, not
        raise — otherwise one missing font package turns every text layer into
        a failed composite.

        The patch refuses only the two paths the module asks for. A blanket
        `truetype` stub also breaks `load_default()`, which since Pillow 10
        loads a *bundled* face through the same function — so it would have
        tested an unreachable state and reported the fallback as broken when it
        is not.
        """
        import maistro_canvas.canvas.compositor as mod

        real = mod.ImageFont.truetype
        refused = {"DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"}

        def no_system_fonts(path, *a, **kw):
            if isinstance(path, str) and path in refused:
                raise OSError("cannot open resource")
            return real(path, *a, **kw)

        monkeypatch.setattr(mod.ImageFont, "truetype", no_system_fonts)
        frame = _render_text_layer(TextConfig(content="X", size=24), 100, 60)
        assert any(px[3] > 0 for px in frame.getdata()), "the default font drew nothing"

    def test_a_malformed_text_colour_falls_back_rather_than_raising(self):
        frame = _render_text_layer(TextConfig(content="X", size=30, color="#12345"), 100, 60)
        assert any(px[3] > 0 for px in frame.getdata())


class TestComposite:
    async def test_an_empty_canvas_is_the_background_colour(self):
        service = PilCompositorService(DictImageStore())
        result = await service.composite(canvas(background="#FF0000"), [])
        assert (result.width, result.height) == (40, 30)
        assert decode(result.image_bytes).getpixel((0, 0)) == RED

    async def test_layers_are_composited_back_to_front_by_z_index(self):
        """The list order must not decide what is on top — z_index does. Passing
        them in reverse is what distinguishes the two."""
        store = DictImageStore({"red": solid((40, 30), RED), "blue": solid((40, 30), BLUE)})
        service = PilCompositorService(store)
        result = await service.composite(
            canvas(),
            [
                layer(id="top", z_index=5, image_path="blue"),
                layer(id="bottom", z_index=1, image_path="red"),
            ],
        )
        assert decode(result.image_bytes).getpixel((20, 15)) == BLUE

    async def test_an_invisible_layer_is_not_drawn(self):
        store = DictImageStore({"blue": solid((40, 30), BLUE)})
        service = PilCompositorService(store)
        result = await service.composite(
            canvas(background="#FF0000"),
            [layer(image_path="blue", visible=False)],
        )
        assert decode(result.image_bytes).getpixel((20, 15)) == RED
        assert store.fetched == [], "an invisible layer was still fetched"

    async def test_a_layer_whose_image_cannot_be_fetched_is_skipped(self):
        """A missing asset must degrade to a gap, not a failed composite — the
        alternative is one dead URL making a whole canvas unrenderable."""
        store = DictImageStore({"ok": solid((40, 30), BLUE)})
        service = PilCompositorService(store)
        result = await service.composite(
            canvas(background="#FF0000"),
            [layer(id="missing", z_index=1, image_path="gone")],
        )
        assert decode(result.image_bytes).getpixel((20, 15)) == RED

    async def test_a_layer_with_neither_image_nor_text_is_a_transparent_gap(self):
        service = PilCompositorService(DictImageStore())
        result = await service.composite(
            canvas(background="#FF0000"), [layer(layer_type="image", image_path=None)]
        )
        assert decode(result.image_bytes).getpixel((20, 15)) == RED

    async def test_a_text_layer_without_a_config_is_skipped(self):
        service = PilCompositorService(DictImageStore())
        result = await service.composite(
            canvas(background="#FF0000"), [layer(layer_type="text", text_config=None)]
        )
        assert decode(result.image_bytes).getpixel((20, 15)) == RED

    async def test_a_text_layer_is_rendered(self):
        service = PilCompositorService(DictImageStore())
        result = await service.composite(
            canvas(width=200, height=80, background="#000000"),
            [layer(layer_type="text", text_config=TextConfig(content="hello", size=30))],
        )
        composited = decode(result.image_bytes)
        assert any(px[:3] != (0, 0, 0) for px in composited.getdata()), "no text was drawn"

    async def test_the_snapshot_records_every_layer_including_hidden_ones(self):
        """It is a record of what the canvas held at composite time, not of what
        was drawn — dropping hidden layers would make it unable to explain a
        later change."""
        service = PilCompositorService(DictImageStore())
        result = await service.composite(
            canvas(),
            [layer(id="a", z_index=1), layer(id="b", z_index=2, visible=False)],
        )
        assert result.layer_snapshot == [
            {"id": "a", "z_index": 1, "visible": True},
            {"id": "b", "z_index": 2, "visible": False},
        ]

    async def test_the_result_carries_the_canvas_id_and_dimensions(self):
        service = PilCompositorService(DictImageStore())
        result = await service.composite(canvas(width=64, height=48), [])
        assert result.canvas_id == "c1"
        assert (result.width, result.height) == (64, 48)
        assert decode(result.image_bytes).size == (64, 48)

    async def test_output_is_byte_identical_across_runs(self):
        """The determinism invariant the module docstring claims (spec 1189).

        Worth asserting on bytes rather than on pixels: PNG encoding carries
        metadata, and a timestamp written into the header would break
        reproducibility while every pixel comparison still passed.
        """
        store = DictImageStore({"red": solid((20, 20), RED)})
        layers = [
            layer(id="a", z_index=1, image_path="red", scale=1.5, rotation=30.0, opacity=0.7),
            layer(
                id="b",
                z_index=2,
                layer_type="text",
                text_config=TextConfig(content="determinism", size=18),
            ),
        ]
        first = await PilCompositorService(store).composite(canvas(), layers)
        second = await PilCompositorService(store).composite(canvas(), layers)
        assert first.image_bytes == second.image_bytes


class TestEncode:
    async def _png(self) -> bytes:
        service = PilCompositorService(DictImageStore())
        return (await service.composite(canvas(width=16, height=16), [])).image_bytes

    async def test_png_round_trips(self):
        service = PilCompositorService(DictImageStore())
        out = await service.encode(await self._png(), fmt="png")
        assert Image.open(io.BytesIO(out)).format == "PNG"

    @pytest.mark.parametrize(
        ("fmt", "expected"), [("webp", "WEBP"), ("jpg", "JPEG"), ("jpeg", "JPEG")]
    )
    async def test_other_formats_are_produced_and_are_that_format(self, fmt, expected):
        service = PilCompositorService(DictImageStore())
        out = await service.encode(await self._png(), fmt=fmt)
        assert Image.open(io.BytesIO(out)).format == expected

    async def test_the_format_name_is_case_insensitive(self):
        service = PilCompositorService(DictImageStore())
        out = await service.encode(await self._png(), fmt="PNG")
        assert Image.open(io.BytesIO(out)).format == "PNG"

    async def test_jpeg_flattens_alpha_rather_than_failing_to_save(self):
        """JPEG has no alpha channel; saving RGBA directly raises in Pillow."""
        service = PilCompositorService(DictImageStore())
        out = await service.encode(await self._png(), fmt="jpg")
        assert Image.open(io.BytesIO(out)).mode == "RGB"

    async def test_an_unsupported_format_raises_the_domain_error(self):
        service = PilCompositorService(DictImageStore())
        with pytest.raises(UnsupportedFormatError, match="tiff"):
            await service.encode(await self._png(), fmt="tiff")

    async def test_encoding_preserves_the_dimensions(self):
        service = PilCompositorService(DictImageStore())
        out = await service.encode(await self._png(), fmt="webp")
        assert Image.open(io.BytesIO(out)).size == (16, 16)


class TestConstruction:
    def test_create_returns_a_service_bound_to_the_store(self):
        store = DictImageStore()
        assert isinstance(PilCompositorService.create(store), PilCompositorService)

    def test_the_module_alias_is_the_same_class(self):
        """`routes.py` imports `PilCompositorService`; other code imports
        `CompositorService`. If they ever diverge, one caller silently gets a
        different implementation."""
        assert CompositorService is PilCompositorService
