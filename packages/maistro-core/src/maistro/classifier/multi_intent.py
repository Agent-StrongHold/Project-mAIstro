"""Multi-intent detection for compound requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.classifier.keyword import STRONG_INDICATORS

if TYPE_CHECKING:
    from maistro.types.config import TaskTypeConfig


def _split_into_parts(text_lower: str) -> list[str]:
    """Split lowercased text on conjunctions into meaningful (>5 char) parts."""
    splitters = [" and then ", " and also ", " and ", " also ", ". also ", ". then "]
    parts = [text_lower]
    for splitter in splitters:
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(p.split(splitter))
        parts = new_parts
    return [p.strip() for p in parts if len(p.strip()) > 5]


def _match_strong_indicator(part: str) -> str | None:
    """Return the task type whose strong indicator phrase appears in ``part``."""
    for task_name, phrases in STRONG_INDICATORS.items():
        for phrase in phrases:
            padded = " " + phrase + " "
            if padded in " " + part + " ":
                return task_name
    return None


def _match_config_keyword(
    part: str,
    task_types: dict[str, TaskTypeConfig],
    seen_types: list[str],
) -> str | None:
    """Return the first config task type whose keyword appears in ``part`` and
    has not already been seen."""
    for task_name, task_cfg in task_types.items():
        for kw in task_cfg.keywords:
            if kw in part and task_name not in seen_types:
                return task_name
    return None


def detect_multi_intent(
    user_text: str,
    task_types: dict[str, TaskTypeConfig],
) -> list[str]:
    """Detect if a message contains multiple distinct intents.

    Returns list of task_type strings if compound, else empty.
    """
    parts = _split_into_parts(user_text.lower())
    if len(parts) < 2:
        return []

    seen_types: list[str] = []
    for part in parts:
        best_type = _match_strong_indicator(part)
        if best_type is None:
            best_type = _match_config_keyword(part, task_types, seen_types)

        if best_type and best_type not in seen_types:
            seen_types.append(best_type)

    return seen_types if len(seen_types) >= 2 else []
