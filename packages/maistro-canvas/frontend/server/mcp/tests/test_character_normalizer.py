import pytest
from PIL import Image, ImageDraw
from server.mcp.character_normalizer import (
    HeadRegion,
    Point,
    Region,
    Silhouette,
    build_face_mask,
    compute_normalization,
    detect_head_region,
    detect_silhouette,
    normalize_character,
)


def _make_char_on_white(
    img_size: tuple[int, int] = (200, 200),
    fg_region: tuple[int, int, int, int] = (60, 30, 140, 180),
    fg_color: tuple[int, int, int] = (100, 50, 200),
) -> Image.Image:
    img = Image.new("RGBA", img_size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle(fg_region, fill=(*fg_color, 255))
    return img


class TestDetectSilhouette:
    def test_finds_foreground(self):
        img = _make_char_on_white()
        sil = detect_silhouette(img)
        assert sil is not None
        assert sil.width_px > 0
        assert sil.height_px > 0
        assert sil.pixel_ratio > 0

    def test_all_white_returns_none(self):
        img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        assert detect_silhouette(img) is None

    def test_small_foreground_below_threshold(self):
        img = Image.new("RGBA", (1000, 1000), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 2, 2], fill=(100, 50, 200, 255))
        assert detect_silhouette(img) is None

    def test_bounds_correct(self):
        img = _make_char_on_white((200, 200), (60, 30, 140, 180))
        sil = detect_silhouette(img)
        assert sil is not None
        assert sil.bounds.x == pytest.approx(60 / 200, abs=0.01)
        assert sil.bounds.y == pytest.approx(30 / 200, abs=0.01)


class TestDetectHeadRegion:
    def test_detects_head_in_top_portion(self):
        img = Image.new("RGBA", (200, 300), (255, 255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([50, 30, 150, 200], fill=(100, 50, 200, 255))
        draw.ellipse([70, 10, 130, 60], fill=(100, 50, 200, 255))
        sil = detect_silhouette(img)
        assert sil is not None
        head = detect_head_region(img, sil)
        assert head is not None
        assert head.bounds.w > 0
        assert head.bounds.h > 0

    def test_no_head_if_silhouette_none(self):
        img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        sil = Silhouette(
            bounds=Region(0.1, 0.1, 0.8, 0.8),
            center=Point(0.5, 0.5),
            pixel_ratio=0.5,
            width_px=80,
            height_px=80,
        )
        head = detect_head_region(img, sil)
        assert head is None


class TestComputeNormalization:
    def test_correct_scale_returns_no_correction(self):
        sil = Silhouette(
            bounds=Region(0.2, 0.1, 0.6, 0.8),
            center=Point(0.5, 0.5),
            pixel_ratio=0.4,
            width_px=600,
            height_px=800,
        )
        pose = Region(0.2, 0.1, 0.6, 0.8)
        norm = compute_normalization(sil, None, pose, 1024)
        assert norm is not None
        assert not norm.needs_correction

    def test_too_large_needs_correction(self):
        sil = Silhouette(
            bounds=Region(0.05, 0.02, 0.9, 0.95),
            center=Point(0.5, 0.5),
            pixel_ratio=0.7,
            width_px=920,
            height_px=970,
        )
        pose = Region(0.2, 0.1, 0.6, 0.8)
        norm = compute_normalization(sil, None, pose, 1024)
        assert norm is not None
        assert norm.needs_correction

    def test_none_returns_none(self):
        assert compute_normalization(None, None, None) is None


class TestNormalizeCharacter:
    def test_returns_correct_size(self):
        img = _make_char_on_white((200, 200))
        result, _sil, _head, _norm = normalize_character(img, target_width=512, target_height=512)
        assert result.size == (512, 512)

    def test_all_white_image(self):
        img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        _result, sil, head, norm = normalize_character(img)
        assert sil is None
        assert head is None
        assert norm is None

    def test_with_pose_bounds(self):
        img = _make_char_on_white((200, 200), (40, 20, 160, 180))
        pose = Region(0.2, 0.1, 0.6, 0.8)
        result, sil, _head, _norm = normalize_character(img, pose_bounds=pose)
        assert result.size == (1024, 1024)
        assert sil is not None


class TestBuildFaceMask:
    def test_creates_ellipse_mask(self):
        head = HeadRegion(
            bounds=Region(0.4, 0.1, 0.2, 0.15),
            center=Point(0.5, 0.175),
            radius=0.1,
        )
        mask = build_face_mask(head, 256)
        assert mask is not None
        assert mask.size == (256, 256)
        center = mask.getpixel((128, 45))
        assert center == 255
        corner = mask.getpixel((0, 0))
        assert corner == 0

    def test_none_head_returns_none(self):
        assert build_face_mask(None) is None
