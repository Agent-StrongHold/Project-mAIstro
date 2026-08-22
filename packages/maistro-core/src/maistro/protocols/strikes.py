"""The strike-ladder boundary (#134).

`Gate` was typed against the concrete `InMemoryStrikeTracker`, and that is how
`security.pg_strikes.PgStrikeTracker` came to describe itself as a replacement
while being unsubstitutable: its `get()` returned a dict where `Gate` does
attribute access on a `StrikeRecord`, and its `record_violation()` returned
three keys where `Gate` reads six. Nothing caught it, because there was no
protocol for either to fail to satisfy.

That is exactly what `packages/maistro-core/CLAUDE.md` means by "business logic
depends on protocols, never concrete implementations" — the convention is not
style, it is the thing that would have made this a type error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.security.strikes import StrikeRecord


@runtime_checkable
class StrikeTracker(Protocol):
    """Per-user violation escalation: warn, lock, disable.

    Every method returns `StrikeRecord` or None — never a dict. The caller reads
    `strike_count`, `scrutiny_level`, `locked_until`, `disabled` and `is_locked`
    off the result, and a mapping that happens to carry those as keys is not the
    same thing.
    """

    async def get(self, user_id: str) -> StrikeRecord | None:
        """The user's current standing, or None if they have never offended."""
        ...

    async def record_violation(
        self,
        *,
        user_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        """Record a violation and return the standing it escalated to.

        The full record, not a summary: the caller turns it straight into the
        response a blocked user sees, which names the strike number, the
        scrutiny level and when the lockout lifts.
        """
        ...

    async def submit_appeal(self, user_id: str, appeal_text: str) -> bool:
        """Attach an appeal. False when there is nothing to appeal against."""
        ...

    async def remove_strikes(self, user_id: str, count: int | None = None) -> StrikeRecord | None:
        """Administratively forgive strikes; None clears all of them."""
        ...

    async def unlock(self, user_id: str) -> StrikeRecord | None:
        """Lift a timed lockout without clearing the strikes that caused it."""
        ...

    async def enable(self, user_id: str) -> StrikeRecord | None:
        """Re-enable a disabled account."""
        ...


__all__ = ["StrikeTracker"]
