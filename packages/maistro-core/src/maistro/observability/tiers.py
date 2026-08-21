"""PII sensitivity tiers and the unexpected-PII detector (ADR-055 / SPEC-070226-2b70).

``SensitivityTier`` tags every recorded LLM/tool event and routes its payload to a
storage regime (see ``maistro.observability.replay``). The ``PIIDetector`` runs on
``normal``-tier events only and reuses the SPEC-223 pattern catalogue from
``maistro.security.sentinel.pii_filter`` (imported read-only), plus a
``register_pattern()`` extension hook.

Behaviour on a match (ADR-055):
- dev mode: raise ``UnexpectedPIIError`` (fail loudly, block the PR).
- prod mode: redact the payload in place, emit a ``pii.unexpected_match`` event via
  the injected emitter, and increment the ``pii_unexpected_match_total`` counter.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from maistro.observability.metrics import registry
from maistro.security.sentinel.pii_filter import PIIMatch, redact, scan_for_pii

pii_unexpected_match_total = registry.counter(
    "pii_unexpected_match_total",
    "PII matches found on normal-tier observability events",
)


class SensitivityTier(StrEnum):
    """Storage/retention regime for a recorded event payload."""

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    SECRET = "secret"


class UnexpectedPIIError(Exception):
    """A normal-tier event payload contained PII (dev mode fails loudly)."""

    def __init__(self, pii_types: list[str]) -> None:
        self.pii_types = pii_types
        super().__init__(
            "PII detected in normal-tier observability event: "
            f"{sorted(set(pii_types))} — tag the tool/recipe with an explicit "
            "sensitivity tier or fix the payload"
        )


class PIIDetector:
    """Scans normal-tier payloads for PII using the SPEC-223 catalogue.

    Args:
        mode: ``"dev"`` raises :class:`UnexpectedPIIError`; ``"prod"`` redacts and
            emits a ``pii.unexpected_match`` event.
        emit: optional callback ``(event_name, attributes)`` invoked on prod-mode
            matches (e.g. wired to the event bus).
    """

    def __init__(
        self,
        mode: str = "prod",
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if mode not in ("dev", "prod"):
            raise ValueError(f"mode must be 'dev' or 'prod', got {mode!r}")
        self.mode = mode
        self._emit = emit
        self._extra_patterns: list[tuple[str, re.Pattern[str]]] = []

    def register_pattern(self, name: str, pattern: str | re.Pattern[str]) -> None:
        """Register an additional PII pattern (consumer extension hook)."""
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        self._extra_patterns.append((name, compiled))

    def scan(self, text: str) -> list[str]:
        """Return the PII types found in ``text`` (built-in + registered patterns)."""
        found: list[str] = [m.pii_type for m in scan_for_pii(text)]
        for name, pattern in self._extra_patterns:
            if pattern.search(text):
                found.append(name)
        return found

    def _redact_text(self, text: str) -> str:
        redacted = redact(text)
        for name, pattern in self._extra_patterns:
            redacted = pattern.sub(f"[REDACTED:{name}]", redacted)
        return redacted

    def inspect(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Scan a normal-tier payload; raise (dev) or redact + emit (prod).

        Returns the payload to store — unchanged when clean, redacted copy when
        PII matched in prod mode.
        """
        found = self.scan(_walk_strings(payload))
        if not found:
            return payload
        if self.mode == "dev":
            raise UnexpectedPIIError(found)
        pii_unexpected_match_total.inc()
        if self._emit is not None:
            self._emit("pii.unexpected_match", {"pii_types": sorted(set(found))})
        redacted = self._redact_obj(payload)
        assert isinstance(redacted, dict)
        return redacted

    def _redact_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self._redact_text(obj)
        if isinstance(obj, dict):
            return {k: self._redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._redact_obj(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self._redact_obj(v) for v in obj)
        return obj


def _walk_strings(obj: Any) -> str:
    """Concatenate every string value in a payload for a single scan pass."""
    parts: list[str] = []

    def _walk(o: Any) -> None:
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str):
                    parts.append(k)
                _walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                _walk(v)

    _walk(obj)
    return "\n".join(parts)


__all__ = [
    "PIIDetector",
    "PIIMatch",
    "SensitivityTier",
    "UnexpectedPIIError",
    "pii_unexpected_match_total",
]
