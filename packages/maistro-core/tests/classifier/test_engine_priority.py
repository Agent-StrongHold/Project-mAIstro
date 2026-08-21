"""ClassifierEngine priority handling: only valid overrides are honoured.

``Intent.tier`` is typed ``Literal["P0".."P5"]``. The engine must never emit a
tier outside that alphabet, even when handed a malformed ``explicit_priority``.
Previously this was papered over with ``# type: ignore[arg-type]``.
"""

from __future__ import annotations

import asyncio
import typing

from maistro.classifier.engine import ClassifierEngine
from maistro.types.intent import Intent

_PRIORITY_VALUES = set(typing.get_args(typing.get_type_hints(Intent)["tier"]))


def _classify(text: str, explicit_priority: str | None) -> Intent:
    engine = ClassifierEngine()
    return asyncio.run(
        engine.classify(
            [{"role": "user", "content": text}],
            task_types={},
            explicit_priority=explicit_priority,
        )
    )


class TestExplicitPriority:
    def test_valid_override_is_honoured(self) -> None:
        intent = _classify("hello there", explicit_priority="P1")
        assert intent.tier == "P1"

    def test_invalid_override_falls_back_to_inference(self) -> None:
        # "high" is not a P0..P5 tier; the engine must not emit it.
        intent = _classify("this is urgent and broken", explicit_priority="high")
        assert intent.tier in _PRIORITY_VALUES
        assert intent.tier == "P0"  # inferred from "urgent"/"broken"

    def test_no_override_uses_inference(self) -> None:
        intent = _classify("important client deadline", explicit_priority=None)
        assert intent.tier == "P1"

    def test_tier_is_always_a_valid_literal(self) -> None:
        for prio in ["P0", "P3", "garbage", "", None]:
            intent = _classify("some message text", explicit_priority=prio)
            assert intent.tier in _PRIORITY_VALUES
