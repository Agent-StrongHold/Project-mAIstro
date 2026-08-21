"""Tests pinning the Literal return contracts of complexity helpers.

These helpers feed directly into ``Intent.complexity`` and ``Intent.tier``,
which are typed as Literals. The functions must return values drawn from
exactly those Literal alphabets so the classifier can assign them without an
unsound ``# type: ignore[arg-type]``.
"""

from __future__ import annotations

import typing
from typing import Literal, assert_type

from maistro.classifier.complexity import estimate_complexity, infer_priority
from maistro.types.intent import Intent

# The valid alphabets, taken from the Intent dataclass field annotations.
_COMPLEXITY_VALUES = set(typing.get_args(typing.get_type_hints(Intent)["complexity"]))
_PRIORITY_VALUES = set(typing.get_args(typing.get_type_hints(Intent)["tier"]))


class TestEstimateComplexityContract:
    def test_short_text_is_simple(self) -> None:
        assert estimate_complexity("hi", "chat") == "simple"

    def test_long_text_is_complex(self) -> None:
        assert estimate_complexity("word " * 250, "chat") == "complex"

    def test_complex_signals_bump_to_complex(self) -> None:
        text = (
            "Please refactor and optimize the module and also compare the "
            "trade-offs between the two approaches in a thorough comprehensive "
            "way across several files and functions and components here now"
        )
        assert estimate_complexity(text, "code") == "complex"

    def test_return_value_is_always_a_valid_literal(self) -> None:
        samples = [
            ("hi", "chat"),
            ("word " * 250, "chat"),
            ("word " * 90, "chat"),
            ("write me a function", "code"),
            ("just a normal sentence with some length to it here ok", "chat"),
        ]
        for text, task in samples:
            assert estimate_complexity(text, task) in _COMPLEXITY_VALUES

    def test_static_return_type_is_the_complexity_literal(self) -> None:
        # mypy --strict must see the narrowed Literal, not bare ``str``.
        assert_type(
            estimate_complexity("hi", "chat"),
            Literal["simple", "moderate", "complex"],
        )


class TestInferPriorityContract:
    def test_urgent_is_p0(self) -> None:
        assert infer_priority("this is urgent and broken") == "P0"

    def test_important_is_p1(self) -> None:
        assert infer_priority("important client deadline") == "P1"

    def test_low_urgency_is_p4(self) -> None:
        assert infer_priority("no rush, just curious") == "P4"

    def test_default_is_p2(self) -> None:
        assert infer_priority("what is the weather") == "P2"

    def test_return_value_is_always_a_valid_literal(self) -> None:
        for text in ["urgent", "important", "no rush", "hello", ""]:
            assert infer_priority(text) in _PRIORITY_VALUES

    def test_static_return_type_is_the_priority_literal(self) -> None:
        # mypy --strict must see the narrowed Literal, not bare ``str``.
        assert_type(
            infer_priority("hello"),
            Literal["P0", "P1", "P2", "P3", "P4", "P5"],
        )
