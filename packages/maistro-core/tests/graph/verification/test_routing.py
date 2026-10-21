"""Text-vs-image observation routing and model-aware encoding."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.graph.verification import (
    ObservationRoute,
    classify_observation,
    encode_observation,
    route_observation,
    route_observations,
)


def test_plain_text_is_text() -> None:
    assert classify_observation("hello") == "text"
    assert classify_observation({"text": "hello"}) == "text"
    assert classify_observation(None) == "text"


def test_data_uri_string_is_image() -> None:
    assert classify_observation("data:image/png;base64,aGVsbG8=") == "image"
    assert classify_observation("data:text/plain;base64,aGVsbG8=") == "text"


def test_mime_typed_mapping_is_image() -> None:
    assert classify_observation({"mime_type": "image/jpeg"}) == "image"
    assert classify_observation({"content_type": "IMAGE/WEBP"}) == "image"
    assert classify_observation({"mime_type": "application/pdf"}) == "text"


def test_provider_content_parts_are_image() -> None:
    assert (
        classify_observation({"type": "image_url", "image_url": {"url": "https://x/y.png"}})
        == "image"
    )
    assert classify_observation({"type": "input_image"}) == "image"
    assert classify_observation({"type": "text", "text": "hi"}) == "text"


def test_reference_keys_are_image() -> None:
    assert classify_observation({"image_url": "https://x/y.png"}) == "image"
    assert classify_observation({"inline_data": {"data": "abc"}}) == "image"
    assert classify_observation({"b64_json": "abc"}) == "image"
    assert classify_observation({"inline_data": None}) == "text"


def test_content_part_lists_are_scanned() -> None:
    payload = {
        "role": "tool",
        "content": [{"type": "text", "text": "see attachment"}, {"type": "image_url"}],
    }
    assert classify_observation(payload) == "image"


def test_route_selects_model_by_modality() -> None:
    assert route_observation("hi", text_model="t", image_model="i") == ObservationRoute(
        modality="text", model="t"
    )
    assert route_observation(
        {"mime_type": "image/png"}, text_model="t", image_model="i"
    ) == ObservationRoute(modality="image", model="i")


def test_route_models_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        route_observation("hi", text_model=" ", image_model="i")


def test_route_observations_preserves_order() -> None:
    routes = route_observations(
        ["a", {"mime_type": "image/png"}, "b"],
        text_model="t",
        image_model="i",
    )
    assert [route.model for route in routes] == ["t", "i", "t"]
    assert [route.modality for route in routes] == ["text", "image", "text"]


def test_encode_text_observation() -> None:
    encoded = encode_observation("hi", ObservationRoute(modality="text", model="t"))
    assert encoded == {"type": "text", "text": "hi"}


def test_encode_image_observation_carries_reference_verbatim() -> None:
    encoded = encode_observation(
        {"image_url": "https://x/y.png"}, ObservationRoute(modality="image", model="i")
    )
    assert encoded == {"type": "image_url", "image_url": {"url": "https://x/y.png"}}


def test_encode_inline_data_builds_data_uri() -> None:
    encoded = encode_observation(
        {"inline_data": {"mime_type": "image/jpeg", "data": "abc"}},
        ObservationRoute(modality="image", model="i"),
    )
    assert encoded == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}}


def test_encode_empty_observation_is_visible_not_silent() -> None:
    assert encode_observation(
        {"mime_type": "image/png"}, ObservationRoute(modality="image", model="i")
    ) == {
        "type": "image_url",
        "image_url": {"url": ""},
    }


def test_encode_image_bearing_content_part_list_preserves_the_nested_reference() -> None:
    """A tool payload that carries its image as a nested provider content part
    keeps that part's URL; classification already saw the nested image, so
    encoding must not emit an empty reference."""
    payload = {
        "role": "tool",
        "content": [
            {"type": "text", "text": "see attachment"},
            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
        ],
    }
    assert classify_observation(payload) == "image"
    assert encode_observation(payload, ObservationRoute(modality="image", model="i")) == {
        "type": "image_url",
        "image_url": {"url": "https://x/y.png"},
    }
