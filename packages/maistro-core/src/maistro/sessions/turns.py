"""What a turn identity is, for every store that records one (ADR-083026-5fab).

One rule, in the session domain that owns the concept, rather than three copies
in three stores that could drift apart -- a twin that is merely similar is a
twin nobody can rely on.
"""

from __future__ import annotations


def reject_blank_turn_id(turn_id: str | None) -> None:
    """A turn identity is either absent or a name; ``""`` is neither.

    An empty string reads as absent everywhere the codebase uses ``or``, so
    accepting one would mean an append that believes it is protected against a
    retry and is not -- the exact failure this change exists to remove, arrived
    at by a different road.
    """
    if turn_id is not None and not turn_id:
        raise ValueError("turn_id must be a non-empty string, or None")


__all__ = ["reject_blank_turn_id"]
