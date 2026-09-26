"""ADR-093 isolation floors for the autonomous RSI loop, mirrored locally.

Why a mirror and not an import
------------------------------
``scripts/check-promotion-surface.py`` requires every module reachable from
the promotion roots (``maistro_rsi.local_loop`` among them) to sit on the
containment surface ``maistro_rsi/sensitive_paths.py`` declares. Importing
``maistro.sandbox.policy`` looked like the DRY way to drive the ADR-093
decision-6 guard, but any ``maistro.sandbox.*`` import first executes
``maistro/sandbox/__init__.py``, which imports the execution fence and the
credential boundary and, through them, ~220 maistro-core modules that are
neither protected nor baselined — the promotion-surface ratchet failed on
exactly that regression (issue #80 repair round 5). The two facts this guard
needs are ADR-093 decisions, not code: the tier ladder's order and the
autonomous mode's floor.

Parity with the canonical ``maistro.sandbox.policy`` is pinned by
``packages/maistro-rsi/tests/test_autonomous_isolation_tier.py``, which
imports both and refuses to let the mirror drift. Tests sit outside the
promotion closure, so they may import the canonical module; the loop cannot.
"""

from __future__ import annotations

from typing import Literal

#: The isolation tiers ADR-093 names, strongest first. Mirror of
#: ``maistro.sandbox.policy.IsolationTier`` / ``_TIER_ORDER``; the parity
#: test in ``test_autonomous_isolation_tier.py`` fails if either side moves
#: without the other.
IsolationTier = Literal["vm", "gvisor", "container", "bubblewrap", "fake"]

#: ADR-093's ladder, strongest first. Lower index = stronger boundary.
TIER_ORDER: tuple[IsolationTier, ...] = (
    "vm",
    "gvisor",
    "container",
    "bubblewrap",
    "fake",
)

#: ADR-093 decision 6: an *autonomous* run — the multi-cycle ``run``/``evolve``
#: loops, nobody at the keyboard — may not execute candidate code behind a
#: Tier-3 OS container; the floor is a Tier-2 user-space kernel (gVisor or
#: better). Mirror of ``maistro.sandbox.policy.MODE_FLOORS[ExecutionMode.AUTONOMOUS]``.
#: Only the autonomous floor is mirrored: the RSI loop is unattended by
#: definition, so the interactive floor is not this package's question.
AUTONOMOUS_FLOOR: IsolationTier = "gvisor"


def tier_satisfies(available: IsolationTier, required: IsolationTier) -> bool:
    """Does the available tier meet or exceed the required tier?

    Same semantics as ``maistro.sandbox.policy.tier_satisfies``: a lower
    index in ``TIER_ORDER`` is a stronger boundary, so satisfying a floor
    means being at least as strong as it. Raises ``ValueError`` for a tier
    the mirror does not know — which is the parity test's cue that the
    canonical ladder grew and this mirror must follow it.
    """
    return TIER_ORDER.index(available) <= TIER_ORDER.index(required)
