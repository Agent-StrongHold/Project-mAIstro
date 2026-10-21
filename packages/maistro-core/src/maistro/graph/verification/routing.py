"""Model-aware observation routing and encoding (epic M4-I).

An observation — a tool result, a polled payload, a fetched document —
arrives as text or as an image, and the two need different models and
different wire encodings. Feeding an image payload to a text-only alias
fails at the provider; silently re-encoding it as text loses exactly the
information the observation existed to carry.

This module classifies an observation's modality, routes it to the
configured text or vision model alias, and encodes it into the
chat-content part shape the governed model egress accepts. Classification
is structural and deterministic: MIME types, provider content-part shapes,
and ``data:`` URIs are IMAGE; everything else is TEXT.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


class ObservationModality:
    """The two modalities an observation can arrive as."""

    TEXT = "text"
    IMAGE = "image"


#: Observation payload keys that carry an image MIME type.
_IMAGE_MIME_KEYS = ("mime_type", "mimetype", "content_type")
#: Observation payload keys that carry an image reference directly.
_IMAGE_REFERENCE_KEYS = ("image_url", "image", "inline_data", "b64_json")


class ObservationRoute(BaseModel):
    """Where one observation goes: its modality and the model alias chosen for it.

    The constraints are declarative (pydantic validates them at model
    construction): only the two modalities classify, and a route with no
    model alias is a misconfiguration, not a destination.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: Literal["text", "image"]
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def classify_observation(payload: object) -> str:
    """Classify one observation payload's modality.

    IMAGE when the payload is (or carries) an image: a MIME-typed mapping
    with an ``image/*`` type, a provider content part such as
    ``{"type": "image_url", ...}`` or an ``inline_data`` part, or a string
    ``data:image/*`` URI. TEXT otherwise — including payloads that say
    nothing about what they are, because TEXT is the only safe assumption.
    """
    if isinstance(payload, str):
        return (
            ObservationModality.IMAGE
            if payload.strip().lower().startswith("data:image/")
            else ObservationModality.TEXT
        )
    if isinstance(payload, Mapping) and _mapping_carries_image(payload):
        return ObservationModality.IMAGE
    return ObservationModality.TEXT


def _mime_declares_image(record: Mapping[str, Any]) -> bool:
    """Whether any of the payload's MIME-carrying keys names an ``image/*`` type."""
    for key in _IMAGE_MIME_KEYS:
        mime = record.get(key)
        if isinstance(mime, str) and mime.strip().lower().startswith("image/"):
            return True
    return False


def _mapping_carries_image(record: Mapping[str, Any]) -> bool:
    """Whether a mapping payload is, or contains, an image observation."""
    if record.get("type") in ("image_url", "input_image"):
        return True
    if _mime_declares_image(record):
        return True
    if any(record.get(key) is not None for key in _IMAGE_REFERENCE_KEYS):
        return True
    # A content-parts list under any common key: an image part inside makes the payload image-bearing.
    return any(
        isinstance(value, (list, tuple))
        and any(classify_observation(item) == ObservationModality.IMAGE for item in value)
        for value in record.values()
    )


def route_observation(
    payload: object,
    *,
    text_model: str,
    image_model: str,
) -> ObservationRoute:
    """Route one observation to the alias configured for its modality."""
    modality = classify_observation(payload)
    return ObservationRoute(
        modality=modality,
        model=image_model if modality == ObservationModality.IMAGE else text_model,
    )


def route_observations(
    payloads: Iterable[object],
    *,
    text_model: str,
    image_model: str,
) -> tuple[ObservationRoute, ...]:
    """Route observations independently; ordering follows the input."""
    return tuple(
        route_observation(payload, text_model=text_model, image_model=image_model)
        for payload in payloads
    )


def encode_observation(payload: object, route: ObservationRoute) -> dict[str, Any]:
    """Encode an observation into the chat content part its route's model accepts.

    Text observations become ``{"type": "text", "text": ...}``; image
    observations become ``{"type": "image_url", "image_url": {"url": ...}}``
    with the payload's own reference (data URI or URL) carried verbatim.
    Encoding never invents content: a payload with neither text nor an image
    reference encodes as an empty-text part, which the caller can see rather
    than silently dropping the observation.
    """
    if route.modality == ObservationModality.IMAGE:
        return {"type": "image_url", "image_url": {"url": _image_reference(payload)}}
    return {"type": "text", "text": payload if isinstance(payload, str) else _text_summary(payload)}


def _image_reference(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        return _reference_from_mapping(payload)
    return ""


def _reference_from_mapping(payload: Mapping[str, Any]) -> str:
    """The image URL/base64 reference a mapping payload carries, if any.

    Classification already scans content-part lists for an image; encoding
    must find that same nested reference rather than emitting an empty URL.
    Direct fields win, then the first image-bearing nested part.
    """
    return _direct_image_reference(payload) or _nested_image_reference(payload)


def _direct_image_reference(payload: Mapping[str, Any]) -> str:
    """A reference on the payload itself: URL, inline data, or bare base64."""
    for key in ("url", "image_url"):
        nested = payload.get(key)
        if isinstance(nested, str):
            return nested
        if isinstance(nested, Mapping) and isinstance(nested.get("url"), str):
            return str(nested["url"])
    inline = _inline_data_reference(payload.get("inline_data"))
    if inline is not None:
        return inline
    return _base64_reference(payload)


def _nested_image_reference(payload: Mapping[str, Any]) -> str:
    """The first reference carried by an image-bearing nested content part."""
    for value in payload.values():
        candidates = value if isinstance(value, (list, tuple)) else (value,)
        for candidate in candidates:
            if (
                isinstance(candidate, Mapping)
                and classify_observation(candidate) == ObservationModality.IMAGE
            ):
                reference = _image_reference(candidate)
                if reference:
                    return reference
    return ""


def _inline_data_reference(inline: object) -> str | None:
    """A Gemini-style ``inline_data`` part as a data URI, or ``None``."""
    if not (isinstance(inline, Mapping) and isinstance(inline.get("data"), str)):
        return None
    mime = inline.get("mime_type") or inline.get("mimetype") or "image/png"
    return f"data:{mime};base64,{inline['data']}"


def _base64_reference(payload: Mapping[str, Any]) -> str:
    """A bare base64 field as a data URI; an empty string when absent."""
    data = payload.get("data") or payload.get("b64_json")
    if not isinstance(data, str):
        return ""
    mime = payload.get("mime_type") or payload.get("mimetype") or "image/png"
    return f"data:{mime};base64,{data}"


def _text_summary(payload: object) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        return str(dict(payload))
    return str(payload)


__all__ = [
    "ObservationModality",
    "ObservationRoute",
    "classify_observation",
    "encode_observation",
    "route_observation",
    "route_observations",
]
