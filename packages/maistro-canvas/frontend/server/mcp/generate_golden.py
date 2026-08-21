#!/usr/bin/env python3
"""Generate golden sample fixtures for each pipeline stage.

Run this script to create/refresh the golden files used by tests as AI fallbacks.
Uses a Pillow-drawn test face (no real photos needed) + real LLM calls.

Usage:
    python3 -m server.mcp.generate_golden
    python3 canvas-studio-poc/server/mcp/generate_golden.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def _make_test_face(size: int = 512) -> Image.Image:
    img = Image.new("RGB", (size, size), (200, 170, 140))
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 3
    head_r = size // 6
    draw.ellipse([cx - head_r, cy - head_r, cx + head_r, cy + head_r], fill=(220, 190, 160))
    eye_y = cy - head_r // 4
    eye_dx = head_r // 3
    eye_r = head_r // 8
    draw.ellipse(
        [cx - eye_dx - eye_r, eye_y - eye_r, cx - eye_dx + eye_r, eye_y + eye_r], fill=(80, 60, 40)
    )
    draw.ellipse(
        [cx + eye_dx - eye_r, eye_y - eye_r, cx + eye_dx + eye_r, eye_y + eye_r], fill=(80, 60, 40)
    )
    mouth_y = cy + head_r // 3
    draw.arc(
        [cx - head_r // 3, mouth_y - head_r // 8, cx + head_r // 3, mouth_y + head_r // 4],
        0,
        180,
        fill=(180, 80, 80),
        width=2,
    )
    hair_y = cy - head_r - head_r // 6
    draw.rectangle(
        [cx - head_r - 2, hair_y, cx + head_r + 2, cy - head_r + head_r // 4], fill=(90, 60, 30)
    )
    body_top = cy + head_r + head_r // 4
    body_bottom = size - size // 10
    draw.rectangle(
        [cx - head_r // 2, body_top, cx + head_r // 2, body_bottom], fill=(100, 140, 180)
    )
    return img


def main() -> int:
    mcp_dir = Path(__file__).parent
    sys.path.insert(0, str(mcp_dir.parent.parent))

    from server.mcp.character import analyze_photo, generate_reference_image
    from server.mcp.golden import save_golden_features, save_golden_reference, save_golden_story
    from server.mcp.story import generate_story

    results: list[str] = []

    print("1/3 Generating reference image (deterministic)...")
    try:
        ref = generate_reference_image(2048, 2048)
        save_golden_reference(ref)
        results.append("reference: OK")
    except Exception as e:
        results.append(f"reference: FAILED ({e})")

    print("2/3 Analyzing test face (vision LLM)...")
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            face = _make_test_face()
            face.save(f.name, format="PNG")
            photo_path = f.name

        features = analyze_photo(photo_path=photo_path, child_name="Emma", child_age=5)
        save_golden_features(features)
        results.append(
            f"features: OK (hair={features.hair}, "
            f"skin={features.skin_tone}, eyes={features.eye_color})"
        )
        Path(photo_path).unlink(missing_ok=True)
    except Exception as e:
        results.append(f"features: FAILED ({e})")
        print(f"  Error: {e}")
        features = None

    print("3/3 Generating story (LLM)...")
    try:
        if features is None:
            from server.mcp.character import CharacterFeatures

            features = CharacterFeatures(
                hair="brown wavy",
                skin_tone="warm medium",
                eye_color="brown",
                face_shape="round",
                age_style="5 years old",
                body_type="average",
                signature_features=("bright smile",),
                typical_expression="cheerful",
            )
        story = generate_story(
            child_name="Emma",
            child_age=5,
            features=features,
            interests=["Dinosaurs", "Ocean Life"],
            theme_hint="discovery and imagination",
        )
        save_golden_story(story)
        results.append(f"story: OK ({len(story.pages)} pages, title='{story.title}')")
    except Exception as e:
        results.append(f"story: FAILED ({e})")

    print("\n=== Golden Generation Results ===")
    for r in results:
        print(f"  {r}")

    all_ok = all("OK" in r for r in results)
    print(f"\n{'All golden samples saved.' if all_ok else 'Some stages failed.'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
