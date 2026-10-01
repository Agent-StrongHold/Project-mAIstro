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
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class ObservationModality:
    """The two modalities an observation can arrive as."""

    TEXT = "text"
    IMAGE = "image"


#: Observation payload keys that carry an image MIME type.
_IMAGE_MIME_KEYS = ("mime_type", "mimetype", "content_type")
#: Observation payload keys that carry an image reference directly.
_IMAGE_REFERENCE_KEYS = ("image_url", "image", "inline_data", "b64_json")


class ObservationRoute(BaseModel):
    """Where one observation goes: its modality and the model alias chosen for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    modality: str
    model: str

    @field_validator("modality")
    @classmethod
    def _validate_modality(cls, value: str) -> str:
        if value not in (ObservationModality.TEXT, ObservationModality.IMAGE):
            raise ValueError(
                f"modality must be {ObservationModality.TEXT!r} or {ObservationModality.IMAGE!r}"
            )
        return value

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must be a non-empty string")
        return value


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
    if isinstance(payload, Mapping):
        record: Mapping[str, Any] = payload
        part_type = record.get("type")
        if part_type == "image_url" or part_type == "input_image":
            return ObservationModality.IMAGE
        for key in _IMAGE_MIME_KEYS:
            mime = record.get(key)
            if isinstance(mime, str) and mime.strip().lower().startswith("image/"):
                return ObservationModality.IMAGE
        for key in _IMAGE_REFERENCE_KEYS:
            if record.get(key) is not None:
                return ObservationModality.IMAGE
        # A content-parts list under any common key: an image part inside makes the payload image-bearing.
        for value in record.values():
            if isinstance(value, (list, tuple)) and any(
                classify_observation(item) == ObservationModality.IMAGE for item in value
            ):
                return ObservationModality.IMAGE
    return ObservationModality.TEXT


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
        for key in ("url", "image_url"):
            nested = payload.get(key)
            if isinstance(nested, str):
                return nested
            if isinstance(nested, Mapping) and isinstance(nested.get("url"), str):
                return str(nested["url"])
        inline = payload.get("inline_data")
        if isinstance(inline, Mapping) and isinstance(inline.get("data"), str):
            mime = inline.get("mime_type") or inline.get("mimetype") or "image/png"
            return f"data:{mime};base64,{inline['data']}"
        data = payload.get("data") or payload.get("b64_json")
        if isinstance(data, str):
            mime = payload.get("mime_type") or payload.get("mimetype") or "image/png"
            return f"data:{mime};base64,{data}"
    return ""


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
