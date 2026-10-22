"""`Settings.circuit_breaker_max_domains` bound (#1203).

The cardinality bound caps the LLM circuit bank's failure-domain bookkeeping
for dynamically discovered providers. It is validated at the Settings
boundary — the path `domain_bank_from_settings` actually reads — so a bad
value fails at config load, before any breaker exists.
"""

from __future__ import annotations

import pytest

from maistro.config.settings import Settings, validate_circuit_max_domains
from maistro.security.resource_policy import MAX_CIRCUIT_DOMAINS


class TestLivePath:
    """`Settings.circuit_breaker_max_domains` is what `domain_bank_from_settings`
    hands to `DomainCircuitBank(max_domains=...)`, so the bound is asserted on
    the field, not merely on the validator function somewhere."""

    @pytest.mark.parametrize(
        "bad",
        [
            0,  # no domains at all would disable breaker bookkeeping
            -3,
            MAX_CIRCUIT_DOMAINS + 1,  # one past the reviewed hard ceiling
        ],
    )
    def test_out_of_bound_values_are_refused(self, bad: int) -> None:
        with pytest.raises(ValueError, match="circuit_breaker_max_domains"):
            Settings(circuit_breaker_max_domains=bad)

    def test_both_bounds_are_accepted(self) -> None:
        assert Settings(circuit_breaker_max_domains=1).circuit_breaker_max_domains == 1
        top = Settings(circuit_breaker_max_domains=MAX_CIRCUIT_DOMAINS)
        assert top.circuit_breaker_max_domains == MAX_CIRCUIT_DOMAINS

    def test_shipped_default_is_accepted(self) -> None:
        """The validator must not reject the shipped default (64 domains)."""
        assert Settings().circuit_breaker_max_domains == 64


class TestSharedImplementation:
    def test_bool_is_refused_even_though_python_coerces_it(self) -> None:
        """`True` is an `int` subclass and pydantic coerces it to 1 at the
        field boundary; the validator itself still refuses it, matching
        `DomainCircuitBank`'s own guard."""
        with pytest.raises(ValueError, match="circuit_breaker_max_domains"):
            validate_circuit_max_domains(True)

    def test_the_error_names_the_field_and_ceiling(self) -> None:
        with pytest.raises(ValueError, match=f"<= {MAX_CIRCUIT_DOMAINS}"):
            validate_circuit_max_domains(0)
