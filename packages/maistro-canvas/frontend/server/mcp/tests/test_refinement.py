import pytest
from PIL import Image, ImageDraw
from server.mcp.character_normalizer import HeadRegion, Point, Region
from server.mcp.refinement import (
    RefinementResult,
    StyleToken,
    apply_edge_soften,
    apply_face_protection,
    apply_palette_unification,
    build_edge_mask,
    build_refinement_prompt,
    extract_dominant_color,
    refine_scene,
)


def _make_composite(size: tuple[int, int] = (200, 200)) -> Image.Image:
    img = Image.new("RGBA", size, (100, 150, 200, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 30, 160, 180], fill=(200, 100, 50, 255))
    return img


class TestBuildEdgeMask:
    def test_with_character_slot(self):
        slot = Region(x=0.3, y=0.2, w=0.4, h=0.7)
        mask = build_edge_mask(slot, 200, 200)
        assert mask.size == (200, 200)
        border_val = mask.getpixel((58, 38))
        assert border_val == 255

    def test_no_slot_returns_black(self):
        mask = build_edge_mask(None, 200, 200)
        corner = mask.getpixel((0, 0))
        assert corner == 0

    def test_border_only(self):
        slot = Region(x=0.4, y=0.3, w=0.2, h=0.4)
        mask = build_edge_mask(slot, 100, 100)
        inside_x = int(0.5 * 100)
        inside_y = int(0.5 * 100)
        outside_x = int(0.1 * 100)
        outside_y = int(0.1 * 100)
        assert mask.getpixel((inside_x, inside_y)) == 0
        assert mask.getpixel((outside_x, outside_y)) == 0


class TestExtractDominantColor:
    def test_uniform_color(self):
        img = Image.new("RGBA", (50, 50), (200, 100, 50, 255))
        r, g, b = extract_dominant_color(img)
        assert r == pytest.approx(200, abs=5)
        assert g == pytest.approx(100, abs=5)
        assert b == pytest.approx(50, abs=5)

    def test_two_color_image(self):
        img = Image.new("RGBA", (100, 100), (100, 100, 100, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 50, 100], fill=(200, 200, 200, 255))
        r, _g, _b = extract_dominant_color(img)
        assert 100 < r < 200

    def test_transparent_image(self):
        img = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        r, g, b = extract_dominant_color(img)
        assert (r, g, b) == (128, 128, 128)


class TestApplyEdgeSoften:
    def test_does_not_crash(self):
        composite = _make_composite()
        edge_mask = build_edge_mask(Region(0.3, 0.2, 0.4, 0.7), 200, 200)
        result = apply_edge_soften(composite, edge_mask, strength=0.7)
        assert result.size == composite.size

    def test_preserves_size(self):
        composite = _make_composite((300, 300))
        edge_mask = Image.new("L", (300, 300), 0)
        result = apply_edge_soften(composite, edge_mask, strength=0.5)
        assert result.size == (300, 300)


class TestApplyPaletteUnification:
    def test_shifts_toward_dominant(self):
        img = Image.new("RGBA", (100, 100), (50, 200, 100, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 80, 100], fill=(200, 100, 50, 255))
        result = apply_palette_unification(img, strength=1.0)
        r, g, b, _ = result.getpixel((10, 50))
        assert r != 200 or g != 100 or b != 50

    def test_low_strength_minimal_change(self):
        img = Image.new("RGBA", (100, 100), (200, 100, 50, 255))
        result = apply_palette_unification(img, strength=0.01)
        r, g, b, _ = result.getpixel((50, 50))
        assert abs(r - 200) < 5
        assert abs(g - 100) < 5
        assert abs(b - 50) < 5


class TestApplyFaceProtection:
    def test_preserves_original_face_area(self):
        original = Image.new("RGBA", (100, 100), (100, 50, 200, 255))
        refined = Image.new("RGBA", (100, 100), (200, 100, 50, 255))
        face_mask = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(face_mask)
        draw.ellipse([40, 20, 60, 40], fill=255)

        result = apply_face_protection(refined, original, face_mask)
        center = result.getpixel((50, 30))
        assert center[0] < 200

    def test_outside_face_uses_refined(self):
        original = Image.new("RGBA", (100, 100), (100, 50, 200, 255))
        refined = Image.new("RGBA", (100, 100), (200, 100, 50, 255))
        face_mask = Image.new("L", (100, 100), 0)

        result = apply_face_protection(refined, original, face_mask)
        corner = result.getpixel((5, 5))
        assert corner[0] == 200


class TestBuildRefinementPrompt:
    def test_default_style(self):
        prompt = build_refinement_prompt()
        assert "watercolor" in prompt.lower()
        assert "face" in prompt.lower()
        assert "EXACTLY" in prompt

    def test_custom_style(self):
        token = StyleToken(technique="oil painting", contrast="high")
        prompt = build_refinement_prompt(token)
        assert "oil painting" in prompt
        assert "bold" in prompt.lower()

    def test_sharp_edges_style(self):
        token = StyleToken(edge_softness=0.3)
        prompt = build_refinement_prompt(token)
        assert "clean, defined edges" in prompt.lower()


class TestRefineScene:
    def test_pillow_fallback(self):
        composite = _make_composite()
        result = refine_scene(composite)
        assert isinstance(result, RefinementResult)
        assert result.refined
        assert result.refinement_method == "pillow_fallback"
        assert result.composite.size == composite.size

    def test_with_character_slot(self):
        composite = _make_composite()
        slot = Region(0.3, 0.2, 0.4, 0.7)
        result = refine_scene(composite, character_slot=slot)
        assert result.refined

    def test_with_face_protection(self):
        composite = _make_composite()
        head = HeadRegion(
            bounds=Region(0.4, 0.1, 0.2, 0.15),
            center=Point(0.5, 0.175),
            radius=0.1,
        )
        result = refine_scene(composite, head_region=head)
        assert result.refined

    def test_custom_style_token(self):
        composite = _make_composite()
        token = StyleToken(contrast="high", edge_softness=0.3)
        result = refine_scene(composite, style_token=token)
        assert result.refined

    def test_preserves_original(self):
        composite = _make_composite()
        original_data = composite.get_flattened_data()
        _ = refine_scene(composite)
        after_data = composite.get_flattened_data()
        assert original_data == after_data
