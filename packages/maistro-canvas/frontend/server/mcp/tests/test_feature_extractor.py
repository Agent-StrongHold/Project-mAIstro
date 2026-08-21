import pytest
from PIL import Image, ImageDraw
from server.mcp.feature_extractor import (
    ExtractedFeatures,
    _classify_eye_color,
    _classify_hair_color,
    _classify_skin_tone,
    _rgb_to_hsl,
    _sample_region,
    build_photo_derived_design,
    extract_features,
)


def _make_face_image(
    hair_color: tuple[int, int, int] = (60, 40, 30),
    skin_color: tuple[int, int, int] = (200, 160, 130),
    eye_color: tuple[int, int, int] = (80, 60, 40),
) -> Image.Image:
    img = Image.new("RGBA", (200, 300), (240, 240, 240, 255))
    draw = ImageDraw.Draw(img)

    draw.rectangle([50, 0, 150, 60], fill=(*hair_color, 255))
    draw.ellipse([60, 40, 140, 150], fill=(*skin_color, 255))
    draw.ellipse([80, 80, 95, 95], fill=(*eye_color, 255))
    draw.ellipse([105, 80, 120, 95], fill=(*eye_color, 255))

    return img


class TestRgbToHsl:
    def test_red(self):
        h, s, lum = _rgb_to_hsl(255, 0, 0)
        assert h == pytest.approx(0.0, abs=1)
        assert s == pytest.approx(100.0, abs=1)
        assert lum == pytest.approx(50.0, abs=1)

    def test_white(self):
        _h, s, lum = _rgb_to_hsl(255, 255, 255)
        assert s == pytest.approx(0.0, abs=1)
        assert lum == pytest.approx(100.0, abs=1)

    def test_black(self):
        _h, s, lum = _rgb_to_hsl(0, 0, 0)
        assert s == pytest.approx(0.0, abs=1)
        assert lum == pytest.approx(0.0, abs=1)

    def test_pure_green(self):
        h, s, _lum = _rgb_to_hsl(0, 255, 0)
        assert h == pytest.approx(120.0, abs=1)
        assert s == pytest.approx(100.0, abs=1)


class TestClassifyHairColor:
    def test_black(self):
        assert "black" in _classify_hair_color(0, 0, 10)

    def test_brown(self):
        result = _classify_hair_color(25, 30, 35)
        assert "brown" in result.lower()

    def test_blonde(self):
        result = _classify_hair_color(35, 20, 70)
        assert "blonde" in result.lower()

    def test_red(self):
        result = _classify_hair_color(10, 60, 45)
        assert "red" in result.lower() or "ginger" in result.lower() or "auburn" in result.lower()

    def test_grey(self):
        result = _classify_hair_color(0, 5, 50)
        assert "grey" in result.lower() or "silver" in result.lower() or "ash" in result.lower()


class TestClassifySkinTone:
    def test_dark(self):
        result = _classify_skin_tone(25, 30, 25)
        assert "dark" in result.lower() or "brown" in result.lower()

    def test_medium(self):
        result = _classify_skin_tone(30, 35, 50)
        assert "medium" in result.lower() or "olive" in result.lower() or "brown" in result.lower()

    def test_fair(self):
        result = _classify_skin_tone(20, 15, 80)
        assert "fair" in result.lower() or "pale" in result.lower()


class TestClassifyEyeColor:
    def test_brown(self):
        result = _classify_eye_color(80, 60, 40)
        assert "brown" in result.lower()

    def test_blue(self):
        result = _classify_eye_color(60, 100, 200)
        assert "blue" in result.lower()

    def test_green(self):
        result = _classify_eye_color(60, 150, 80)
        assert "green" in result.lower()

    def test_dark(self):
        result = _classify_eye_color(20, 20, 20)
        assert "dark" in result.lower()


class TestSampleRegion:
    def test_samples_center(self):
        img = Image.new("RGBA", (100, 100), (200, 100, 50, 255))
        pixels = img.get_flattened_data()
        result = _sample_region(pixels, 100, 50, 50, 5)
        assert result is not None
        assert result == (200, 100, 50)

    def test_empty_region(self):
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        pixels = img.get_flattened_data()
        result = _sample_region(pixels, 100, 50, 50, 5)
        assert result is None


class TestExtractFeatures:
    def test_extracts_from_face_image(self):
        img = _make_face_image()
        features = extract_features(img)
        assert isinstance(features, ExtractedFeatures)
        assert features.hair_color is not None
        assert features.skin_tone is not None
        assert features.eye_color is not None
        assert features.description != ""

    def test_description_format(self):
        img = _make_face_image()
        features = extract_features(img)
        assert "hair" in features.description
        assert "skin" in features.description
        assert "eyes" in features.description

    def test_downscales_large_image(self):
        large = _make_face_image()
        large = large.resize((2000, 3000), Image.Resampling.LANCZOS)
        features = extract_features(large)
        assert features.description != ""

    def test_blonde_hair(self):
        img = _make_face_image(hair_color=(220, 200, 150))
        features = extract_features(img)
        assert features.hair_color is not None
        assert "blonde" in features.hair_color.lower()


class TestBuildPhotoDerivedDesign:
    def test_with_features(self):
        features = ExtractedFeatures(
            hair_color="blonde",
            skin_tone="fair",
            eye_color="blue",
            description="blonde hair, fair skin, blue eyes",
        )
        result = build_photo_derived_design(features, "a child character")
        assert "blonde" in result
        assert "fair" in result
        assert "blue" in result

    def test_empty_features(self):
        features = ExtractedFeatures()
        result = build_photo_derived_design(features, "a child")
        assert "child" in result

    def test_no_base_design(self):
        features = ExtractedFeatures(
            hair_color="brown",
            skin_tone="medium",
            eye_color="brown",
            description="brown hair, medium skin, brown eyes",
        )
        result = build_photo_derived_design(features)
        assert "brown" in result
