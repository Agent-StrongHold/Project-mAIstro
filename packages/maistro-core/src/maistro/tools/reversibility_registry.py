"""Tool reversibility registration registry (SPEC-252 / ADR-050)."""

from __future__ import annotations

from maistro.tools.reversibility import ToolRegistration, ToolRegistrationError, ToolReversibility


class ReversibilityRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ToolRegistration] = {}

    def register(
        self,
        registration: ToolRegistration,
        *,
        compensator_reversibility: ToolReversibility | None = None,
    ) -> None:
        if registration.reversibility == ToolReversibility.REVERSIBLE:
            if registration.compensator is None:
                raise ToolRegistrationError(
                    f"{registration.name}: REVERSIBLE tool requires a compensator"
                )
            if compensator_reversibility == ToolReversibility.IRREVERSIBLE:
                raise ToolRegistrationError(
                    f"{registration.name}: compensator must not be IRREVERSIBLE"
                )
        self._registrations[registration.name] = registration

    def reversibility_of(self, name: str) -> ToolReversibility:
        return self._registrations[name].reversibility

    def compensator_for(self, name: str) -> str | None:
        return self._registrations[name].compensator
