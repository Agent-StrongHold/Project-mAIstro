"""Tests for the tool reversibility taxonomy registry (SPEC-252 / ADR-050)."""

from __future__ import annotations

import pytest

from maistro.tools.reversibility import (
    ToolRegistration,
    ToolRegistrationError,
    ToolReversibility,
    default_for_external,
)
from maistro.tools.reversibility_registry import ReversibilityRegistry


class TestRegistration:
    def test_internal_tool_no_compensator_succeeds(self) -> None:
        registry = ReversibilityRegistry()
        registry.register(
            ToolRegistration(name="read_file", reversibility=ToolReversibility.INTERNAL)
        )
        assert registry.reversibility_of("read_file") == ToolReversibility.INTERNAL

    def test_irreversible_tool_no_compensator_succeeds(self) -> None:
        registry = ReversibilityRegistry()
        registry.register(
            ToolRegistration(name="send_email", reversibility=ToolReversibility.IRREVERSIBLE)
        )
        assert registry.reversibility_of("send_email") == ToolReversibility.IRREVERSIBLE

    def test_reversible_without_compensator_raises(self) -> None:
        registry = ReversibilityRegistry()
        with pytest.raises(ToolRegistrationError):
            registry.register(
                ToolRegistration(name="create_file", reversibility=ToolReversibility.REVERSIBLE)
            )

    def test_reversible_with_irreversible_compensator_raises(self) -> None:
        registry = ReversibilityRegistry()
        with pytest.raises(ToolRegistrationError):
            registry.register(
                ToolRegistration(
                    name="create_file",
                    reversibility=ToolReversibility.REVERSIBLE,
                    compensator="delete_file",
                ),
                compensator_reversibility=ToolReversibility.IRREVERSIBLE,
            )

    def test_reversible_with_valid_compensator_succeeds(self) -> None:
        registry = ReversibilityRegistry()
        registry.register(
            ToolRegistration(
                name="create_file",
                reversibility=ToolReversibility.REVERSIBLE,
                compensator="delete_file",
            ),
            compensator_reversibility=ToolReversibility.REVERSIBLE,
        )
        assert registry.compensator_for("create_file") == "delete_file"

    def test_reregistering_overwrites(self) -> None:
        registry = ReversibilityRegistry()
        registry.register(ToolRegistration(name="tool", reversibility=ToolReversibility.INTERNAL))
        registry.register(
            ToolRegistration(name="tool", reversibility=ToolReversibility.IRREVERSIBLE)
        )
        assert registry.reversibility_of("tool") == ToolReversibility.IRREVERSIBLE


class TestLookupErrors:
    def test_reversibility_of_unknown_raises_key_error(self) -> None:
        registry = ReversibilityRegistry()
        with pytest.raises(KeyError):
            registry.reversibility_of("nope")

    def test_compensator_for_unknown_raises_key_error(self) -> None:
        registry = ReversibilityRegistry()
        with pytest.raises(KeyError):
            registry.compensator_for("nope")


class TestExternalDefault:
    def test_default_for_external_is_irreversible(self) -> None:
        assert default_for_external() == ToolReversibility.IRREVERSIBLE
