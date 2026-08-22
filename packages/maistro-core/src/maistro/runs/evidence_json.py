"""Keeping non-finite evidence intact through a JSON payload (#132 review).

`Attempt.result`, `NodeRun.result` and the accepted-outcome projections are
`Any`: whatever the executor returned. That includes non-finite floats, and the
domain deliberately supports them — `evidence_values_equal` special-cases
NaN so a NaN result compares equal to itself, and
`test_nan_result_can_be_accepted_without_stranding_node_run` exists precisely
so a NaN cannot strand a NodeRun.

The durable stores serialise the whole model to JSON, and pydantic's default
`ser_json_inf_nan="null"` turns NaN, Infinity and -Infinity into `null` on the
way out. So on PostgreSQL and SQLite a NaN result came back as `None`: not an
error, not a stranded NodeRun — a silently different number. The in-memory
store kept it, so the three backends disagreed about what had been recorded,
which is the one thing the system of record may not do.

Switching pydantic to `ser_json_inf_nan="constants"` is not the fix either: it
emits the bare tokens `NaN` and `Infinity`, which are not JSON, and PostgreSQL
rejects them in a `jsonb` column. So non-finite values are encoded as an
explicit tagged object on the way in and decoded on the way out. The tag is
verbose on purpose — a payload a human reads should say what it holds.
"""

from __future__ import annotations

import json
import math
from typing import Any

#: Key marking an encoded non-finite float. Long and specific so it cannot
#: collide with a domain result that happens to be a one-key dict.
NON_FINITE_TAG = "__maistro_non_finite__"

_ENCODE = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}


def _token(value: float) -> str:
    if math.isnan(value):
        return "nan"
    return "inf" if value > 0 else "-inf"


def encode_evidence(value: Any) -> Any:
    """Replace non-finite floats with a tagged object, recursively.

    Applied to an already-JSON-shaped payload, so the only containers left are
    dicts and lists and the only scalars are JSON scalars.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return {NON_FINITE_TAG: _token(value)}
    if isinstance(value, dict):
        return {key: encode_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_evidence(item) for item in value]
    return value


def decode_evidence(value: Any) -> Any:
    """Restore tagged non-finite floats, recursively. Inverse of `encode_evidence`."""
    if isinstance(value, dict):
        if len(value) == 1:
            token = value.get(NON_FINITE_TAG)
            if isinstance(token, str) and token in _ENCODE:
                return _ENCODE[token]
        return {key: decode_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_evidence(item) for item in value]
    return value


def payload_of(model: Any) -> Any:
    """A model as a JSON-shaped payload with non-finite evidence preserved."""
    return encode_evidence(model.model_dump(mode="json"))


def json_of(model: Any) -> str:
    """A model as JSON text with non-finite evidence preserved.

    `model_dump_json()` cannot be used: with `ser_json_inf_nan="constants"` it
    emits the bare `NaN` token, which is not JSON and which the reader would
    have to be configured to accept.
    """
    return json.dumps(payload_of(model))


def model_of(cls: Any, payload: Any) -> Any:
    """Validate a stored payload back into its model, restoring non-finites."""
    return cls.model_validate(decode_evidence(payload))


def model_of_json(cls: Any, text: str | bytes) -> Any:
    """Validate stored JSON text back into its model, restoring non-finites."""
    return model_of(cls, json.loads(text))


__all__ = [
    "NON_FINITE_TAG",
    "decode_evidence",
    "encode_evidence",
    "json_of",
    "model_of",
    "model_of_json",
    "payload_of",
]
