"""Where Hive's bounded recovery scans resume on their next tick (#1127, #1098).

`fair_page_scan` bounds how many rows one tick inspects, and on its own that
bound is the starvation one size up: a tick that always starts from the top
can never reach an eligible row behind more ineligible rows than it may
inspect. Each seam therefore hands the scan a `ScanContinuation` it keeps
across ticks, and this module is the one place those live.

Keyed by the store actually scanned rather than held as module globals: a
rebuilt Container (tests do this per case; a reconfigured process does it
once) brings new stores, and a position saved against a store that no longer
exists means nothing against the one that replaced it. Held weakly where the
store allows it, so the continuation dies with its store -- the explicit
restart `ScanContinuation` documents, applied without every caller having to
notice the swap. A store that cannot be weakly referenced is pinned instead:
keeping it alive is what keeps its identity from being reused for a different
store while a saved position still names it.
"""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

from maistro.graph.durable_runs import ScanContinuation

_Continuations = dict[str, ScanContinuation[tuple[str, str]]]

_WEAKLY_HELD: WeakKeyDictionary[Any, _Continuations] = WeakKeyDictionary()
_PINNED: dict[Any, _Continuations] = {}


def scan_continuation(seam: str, store: Any) -> ScanContinuation[tuple[str, str]]:
    """The continuation ``seam``'s bounded scan over ``store`` resumes from."""
    try:
        per_store = _WEAKLY_HELD.setdefault(store, {})
    except TypeError:
        per_store = _PINNED.setdefault(store, {})
    return per_store.setdefault(seam, ScanContinuation())


__all__ = ["scan_continuation"]
