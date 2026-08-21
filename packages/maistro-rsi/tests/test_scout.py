"""SPEC-070126-9d37 AC-9: scout_objective.

One model reads the file and names a single concrete improvement; every
competitor in the cycle then implements that same objective (a fair head-to-head).
Empty model output falls back to the generic objective so a cycle never stalls.
"""

from __future__ import annotations

import pytest

from maistro_rsi.scout import scout_objective


def _fake_llm(reply: str):
    def call(messages, **_kw):
        # Deterministic — no network. Echo a fixed reply regardless of input.
        return {"content": reply, "stop_reason": "stop"}

    return call


@pytest.mark.ac("SPEC-070126-9d37/AC-9")
def test_returns_model_objective_stripped() -> None:
    obj = scout_objective(
        "def f():\n    return 1\n",
        _fake_llm("  Add a docstring to f() describing its return value.  \n"),
        fallback="GENERIC",
    )
    assert obj == "Add a docstring to f() describing its return value."


@pytest.mark.ac("SPEC-070126-9d37/AC-9")
def test_empty_model_output_uses_fallback() -> None:
    assert scout_objective("x = 1\n", _fake_llm("   \n  "), fallback="GENERIC") == "GENERIC"


def test_source_is_sent_to_the_model() -> None:
    seen = {}

    def call(messages, **_kw):
        seen["text"] = "\n".join(str(m.get("content", "")) for m in messages)
        return {"content": "objective", "stop_reason": "stop"}

    scout_objective("MAGIC_TOKEN_123", call, fallback="G")
    assert "MAGIC_TOKEN_123" in seen["text"]
