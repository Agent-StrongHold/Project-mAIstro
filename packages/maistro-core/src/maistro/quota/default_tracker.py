"""The process-wide default quota ledger registry (#718).

Lives in its own module -- not ``quota/tracker.py`` -- because the promotion
path reaches ``maistro.quota.tracker`` (``maistro_rsi.autorun``,
``maistro_rsi.quota_burn`` and ``maistro_rsi.cli`` import
``InMemoryQuotaTracker`` from it), and the registry's ``QuotaTracker``
annotation names the ``maistro.protocols`` package. Importing any
``maistro.protocols.*`` member from a promotion-reachable module would put the
whole protocols package initializer -- and everything it eagerly imports --
on the promotion surface, where each module would need its own adversarial
review disposition (``scripts/check-promotion-surface.py``). Nothing on the
promotion path reads or writes this registry: its users are the composition
root (``container.py``), the conductor's raw-gateway fallback
(``agents/conductor.py``), and tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.protocols.quota import QuotaTracker

_default_quota_tracker: QuotaTracker | None = None


def get_default_quota_tracker() -> QuotaTracker | None:
    """The process-wide shared quota ledger, when a composition registered one.

    Mirrors ``quota.usage_log.get_default_usage_log``'s module-level-singleton
    pattern for the one recording site that crosses no canonical Invocation
    authority: the conductor's raw-gateway fallback (``agents/conductor.py``)
    marks its ungoverned call here so a process that *does* carry a ledger
    never presents complete quota evidence while omitting that call class.
    ``None`` (no composition root registered a tracker) keeps the fallback on
    the usage-log-only evidence path — evidence is never fabricated where no
    ledger exists to receive it.
    """
    return _default_quota_tracker


def set_default_quota_tracker(tracker: QuotaTracker | None) -> None:
    """Register (or, with ``None``, clear) the process-wide quota ledger.

    Set once by the Container composition root (``maistro.container``), which
    is the single place every production process gets its ledger — never by
    agents or runners themselves (#718 stop condition: the canonical effect
    path owns authoritative recording; this default only receives the
    ungoverned fallback's non-Invocation evidence).
    """
    global _default_quota_tracker
    _default_quota_tracker = tracker
