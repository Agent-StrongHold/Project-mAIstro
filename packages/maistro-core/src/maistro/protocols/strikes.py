"""Strike-tracking protocol — the lockout ladder's DI seam (#134).

`Gate` holds the strike ladder: it reads a record before admitting input and
writes one after a violation, then reads `strike_count`, `scrutiny_level`,
`locked_until`, `disabled` and `is_locked` off whatever comes back.

Both `Gate.__init__` and `Container.strike_tracker` were typed against the
**concrete** `InMemoryStrikeTracker`, against this repository's own stated
convention — *"Protocol-driven DI: business logic depends on protocols, never
concrete implementations"* (`packages/maistro-core/CLAUDE.md`). The cost was not
theoretical. `PgStrikeTracker` advertised itself as a replacement while
returning `dict` from both methods, so wiring the durable tracker raised
`AttributeError` on the **first security violation** — the one moment the path
exists for. With the seam typed, that is a type error at the boundary instead of
a runtime failure under attack.

`StrikeRecord` is the return type rather than a mapping deliberately: `is_locked`
is a *computed* property (disabled, or `locked_until` still in the future), and a
dict makes every caller recompute it — which is how two implementations end up
disagreeing about whether an account is locked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro.security.strikes import StrikeRecord


@runtime_checkable
class StrikeTracker(Protocol):
    """Read and escalate a user's strike record.

    Only what `Gate` actually calls. `submit_appeal`, `remove_strikes`, `unlock`
    and `enable` exist on the in-memory implementation and are admin surface
    reached through other paths; putting them here would oblige every tracker to
    implement an operator console before it could serve the security path.
    """

    async def get(self, user_id: str) -> StrikeRecord | None:
        """The current record, or None if this user has never had a violation.

        Never a partial record: `Gate` reads `is_locked` off the result and
        admits input when it is falsy, so a record missing `disabled` or
        `locked_until` would silently unlock a locked account.
        """
        ...

    async def record_violation(
        self,
        *,
        user_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        """Record a violation, escalate the ladder, and return the **full** record.

        The escalated state, not a summary of it. `Gate` reports
        `strike_count`, `scrutiny_level`, `locked_until` and `disabled` to the
        caller straight from this return value, so a tracker that returns only
        what it changed leaves the response describing a state the account is
        no longer in.
        """
        ...
