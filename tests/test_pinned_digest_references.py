"""Digest-pinned base references outside Dockerfiles must match the registry.

`scripts/check-image-pins.py` closes the registry against the Dockerfiles only.
The tree also references pinned base images from non-Dockerfile surfaces --
notably `scripts/smoke-engine-canvas.sh`, whose canvas-less CONTROL_IMAGE is
the anti-cheat control probe for the engine canvas smoke: if its digest drifts
from the `quality/image-pins.json` row the Dockerfiles build from, the control
probe silently runs a different base than the image under test and the smoke
loses its teeth. A pin refresh that misses such a reference ships that drift.

The 2026-10-22 refresh of `python:3.13.16-slim-bookworm` (#2209) had to touch
the smoke script by hand; this suite holds that contract closed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_PATH = REPO_ROOT / "quality" / "image-pins.json"

# `name:tag@sha256:<digest>` -- same shape check-image-pins.py parses.
PINNED_REF = re.compile(r"\b([a-z0-9._/-]+):([A-Za-z0-9._-]+)@sha256:([0-9a-f]{64})")

# Non-Dockerfile tree surfaces allowed to reference pinned base images, as
# (path relative to repo root, description) pairs. A new surface goes here
# together with the refresh checklist that must keep it registered.
REFERENCE_SURFACES = (
    (Path("scripts/smoke-engine-canvas.sh"), "engine canvas smoke control image"),
)


def load_registry() -> set[str]:
    """The exact `name:tag@sha256:<digest>` strings image-pins.json registers."""
    import json

    pins = json.loads(PINS_PATH.read_text())["pins"]
    return {f"{p['image']}:{p['tag']}@{p['digest']}" for p in pins}


def unregistered_refs(text: str, registry: set[str]) -> set[str]:
    """Pinned refs in `text` that the registry does not exactly register."""
    return {match.group(0) for match in PINNED_REF.finditer(text)} - registry


def test_control_image_surface_is_pinned_to_the_registry() -> None:
    """Every digest-pinned ref in a reference surface is registered verbatim."""
    registry = load_registry()
    assert registry, "image-pins.json yielded no pins; the registry shape moved"

    for rel_path, description in REFERENCE_SURFACES:
        text = (REPO_ROOT / rel_path).read_text()
        stray = unregistered_refs(text, registry)
        assert not stray, (
            f"{rel_path} ({description}) references digest-pinned base image(s) "
            f"that quality/image-pins.json does not register: {sorted(stray)}. "
            "A base-digest refresh must update this reference in the same "
            "change, or the control probe drifts from the image under test."
        )


def test_control_image_matches_the_pin_the_dockerfiles_build_from() -> None:
    """The smoke control image equals a pin row some Dockerfile actually uses."""
    import json

    text = (REPO_ROOT / "scripts/smoke-engine-canvas.sh").read_text()
    refs = {m.group(0) for m in PINNED_REF.finditer(text)}
    assert refs, "smoke control image lost its digest pin entirely"

    pins = json.loads(PINS_PATH.read_text())["pins"]
    dockerfile_users = {
        f"{p['image']}:{p['tag']}@{p['digest']}"
        for p in pins
        if any(u.lower().endswith("dockerfile") for u in p.get("used_by", []))
    }
    unanchored = refs - dockerfile_users
    assert not unanchored, (
        f"smoke control image {sorted(unanchored)} matches no pin row that a "
        "Dockerfile uses; the probe no longer mirrors a built image"
    )


def test_a_stale_digest_of_a_registered_image_is_rejected() -> None:
    """The failure mode of the #2209 refresh: same image:tag, old digest."""
    registry = load_registry()
    some_ref = next(iter(registry))
    image = some_ref.split("@", 1)[0]
    stale = f"{image}@{'sha256:' + '0' * 64}"
    assert unregistered_refs(f"FROM {stale}\n", registry) == {stale}
    assert unregistered_refs(f"FROM {some_ref}\n", registry) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("python:3.12-slim@sha256:" + "a" * 64, 1),
        ("registry.example/base:1.2@sha256:" + "b" * 64, 1),
        ("python:3.12-slim", 0),  # unpinned: check-image-pins.py's problem
        ("sha256:" + "c" * 64, 0),  # bare digest: no name:tag
        ("python:3.12-slim@sha256:short", 0),  # malformed digest
    ],
)
def test_ref_scanner_shapes(text: str, expected: int) -> None:
    assert len(PINNED_REF.findall(text)) == expected
