"""Competitive + complementary selection over tournament candidates (SPEC-070126-9d37).

Given several candidate fixes for one file, ranked by fitness composite, combine
them greedily: apply each best-first onto an accumulating result and keep it only
if it lands cleanly. A clean land means it touched a region no kept candidate
did — complementary, so both survive. A conflict means a higher-scored candidate
already occupies that region — competitive, so the lower-scored one is dropped.

`greedy_merge` is the pure kernel (the caller supplies `apply`, which in the loop
is a `git apply` onto a merge worktree). `select_with_fallback` adds the cycle's
safety net: a genuinely combined (2+) result is only trusted if it re-passes the
gates; otherwise it falls back to the single top candidate, which is known-good.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


def _default_key(candidate: Any) -> Any:
    return candidate.composite


def greedy_merge(
    candidates: Iterable[T],
    apply: Callable[[T], bool],
    *,
    key: Callable[[T], Any] = _default_key,
) -> list[T]:
    """Keep candidates that apply cleanly, best-first.

    ``apply(candidate)`` reports whether the candidate's change lands on the
    accumulating result without conflicting with what's already kept. Returns the
    kept candidates in application (score-descending) order.
    """
    kept: list[T] = []
    for candidate in sorted(candidates, key=key, reverse=True):
        if apply(candidate):
            kept.append(candidate)
    return kept


@dataclass
class SelectionResult(Generic[T]):
    """Outcome of a cycle's selection: what to promote and how it was chosen."""

    kept: list[T] = field(default_factory=list)
    merged: bool = False  # a genuine 2+ combination that re-passed the gates
    fallback: bool = False  # a combination regressed; fell back to the top candidate


def select_with_fallback(
    candidates: Iterable[T],
    apply: Callable[[T], bool],
    rescore: Callable[[list[T]], bool],
    *,
    key: Callable[[T], Any] = _default_key,
) -> SelectionResult[T]:
    """Greedy-merge, then validate a genuine combination.

    A single surviving candidate is already validated (identical to that
    candidate), so ``rescore`` is only consulted for a 2+ combination. If that
    combination regresses (``rescore`` returns False), fall back to the single
    highest-scored candidate.
    """
    kept = greedy_merge(candidates, apply, key=key)
    if len(kept) < 2:
        return SelectionResult(kept=kept)
    if rescore(kept):
        return SelectionResult(kept=kept, merged=True)
    return SelectionResult(kept=[kept[0]], fallback=True)
