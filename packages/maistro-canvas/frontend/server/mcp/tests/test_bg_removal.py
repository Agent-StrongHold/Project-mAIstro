import pytest
from PIL import Image, ImageDraw
from server.mcp.bg_removal import _is_bg_color, _luminance, remove_background


def _make_test_image(
    size: tuple[int, int] = (100, 100),
    bg_color: tuple[int, int, int] = (255, 255, 255),
    fg_center: bool = True,
    fg_color: tuple[int, int, int] = (100, 50, 200),
) -> Image.Image:
    img = Image.new("RGBA", size, (*bg_color, 255))
    if fg_center:
        draw = ImageDraw.Draw(img)
        cx, cy = size[0] // 2, size[1] // 2
        r = min(size) // 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*fg_color, 255))
    return img


class TestLuminance:
    def test_white(self):
        assert _luminance(255, 255, 255) == pytest.approx(255.0)

    def test_black(self):
        assert _luminance(0, 0, 0) == pytest.approx(0.0)

    def test_mid_gray(self):
        val = _luminance(128, 128, 128)
        assert 127 < val < 129


class TestIsBgColor:
    def test_white_pixel_is_bg(self):
        assert _is_bg_color((255, 255, 255, 255), 240, 50)

    def test_dark_pixel_is_not_bg(self):
        assert not _is_bg_color((50, 50, 50, 255), 240, 50)

    def test_transparent_is_bg(self):
        assert _is_bg_color((200, 200, 200, 0), 240, 50)

    def test_saturated_high_lum_not_bg(self):
        assert not _is_bg_color((255, 100, 100, 255), 240, 50)


class TestRemoveBackground:
    def test_removes_white_bg(self):
        img = _make_test_image((100, 100), (255, 255, 255), True, (100, 50, 200))
        result = remove_background(img)
        assert result.mode == "RGBA"

        corner = result.getpixel((0, 0))
        assert corner[3] == 0

        center = result.getpixel((50, 50))
        assert center[3] > 0

    def test_preserves_foreground_alpha(self):
        img = _make_test_image((80, 80), (250, 250, 250), True, (80, 40, 160))
        result = remove_background(img, feather=0)
        center = result.getpixel((40, 40))
        assert center[3] == 255

    def test_no_bg_removal_needed(self):
        img = Image.new("RGBA", (50, 50), (100, 50, 200, 255))
        result = remove_background(img, feather=0)
        corner = result.getpixel((0, 0))
        assert corner[3] > 0

    def test_feather_creates_soft_edges(self):
        img = _make_test_image((200, 200), (255, 255, 255), True, (80, 40, 160))
        result_feathered = remove_background(img, feather=4)
        result_sharp = remove_background(img, feather=0)
        feathered_data = result_feathered.get_flattened_data()
        sharp_data = result_sharp.get_flattened_data()
        semi_transparent_feather = sum(1 for p in feathered_data if 0 < p[3] < 255)
        semi_transparent_sharp = sum(1 for p in sharp_data if 0 < p[3] < 255)
        assert semi_transparent_feather >= semi_transparent_sharp

    def test_colored_bg_with_low_saturation(self):
        img = _make_test_image((100, 100), (245, 245, 240), True, (80, 40, 160))
        result = remove_background(img, threshold=240, feather=0)
        corner = result.getpixel((0, 0))
        assert corner[3] == 0

    def test_high_saturation_bg_preserved(self):
        img = Image.new("RGBA", (50, 50), (255, 100, 100, 255))
        result = remove_background(img, threshold=240, feather=0)
        corner = result.getpixel((0, 0))
        assert corner[3] > 0
