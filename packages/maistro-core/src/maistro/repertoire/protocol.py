"""The generic Repertoire protocol (SPEC-258 / ADR-070)."""

from __future__ import annotations

from typing import Protocol, TypeVar

from maistro.repertoire.types import Verdict

InputT = TypeVar("InputT", contravariant=True)
S = TypeVar("S")
E = TypeVar("E")


class Repertoire(Protocol[InputT, S, E]):
    """A reuse-first cascade: recall a verified entry, else improvise and rehearse a new one."""

    def recall(self, input_class: str) -> E | None:
        """Best verified entry for the class (Perform), or None on a miss."""
        ...

    def nearest(self, input_class: str) -> tuple[E, ...]:
        """Entries to use as Improvise priors."""
        ...

    def improvise(self, inp: InputT, priors: tuple[E, ...]) -> S:
        """Reason from scratch, guided by priors."""
        ...

    def rehearse(self, candidate: S) -> Verdict:
        """Verify a candidate solution before it can be committed."""
        ...

    def compose(self, verified: S, input_class: str) -> E:
        """Distill a verified solution into a new entry."""
        ...

    def class_of(self, inp: InputT) -> str:
        """Map an input to its Repertoire class key."""
        ...
