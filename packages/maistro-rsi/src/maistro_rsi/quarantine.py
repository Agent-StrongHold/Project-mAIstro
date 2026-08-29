"""Quarantine gate: scan and (when warranted) escalate every self-modification
before it's allowed out of the sandbox.

`maistro-rsi` deliberately does **not** carve out "files the agent may never
touch" — an RSI loop that can't propose changes to its own harness, sandbox
control, or security wiring isn't recursive, it's just a code-fixing bot with
extra steps. The actual safety property we want is narrower and stronger:
nothing self-modified reaches the outside world (a PR, a promoted genome)
without being scanned by Warden — the same content scanner that runs at every
other trust boundary in this codebase — and, when the diff touches the agent's
own cage, an additional adversarial review pass on top of the full test suite.

This is the seam where Sentinel/RedTeam-style adversarial review plugs in:
`AdversarialReview` is a protocol so the actual reviewer (an LLM judge, a
RedTeam agent persona, a human-in-the-loop queue) is swappable without
touching the gate logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from maistro.security.warden.detector import Warden
from maistro_rsi.sensitive_paths import SENSITIVE_PATH_PATTERNS, matches_sensitive_pattern

# The containment-surface classifier lives in `sensitive_paths` (#303): it is
# pure string work with no dependencies, and both this gate and
# `scripts/check-promotion-surface.py` must consult the same matcher rather
# than two that agree until they don't. Re-exported here because callers --
# including `scripts/check_enumerations.py` -- import both names from this
# module.
__all__ = [
    "SENSITIVE_PATH_PATTERNS",
    "AdversarialReview",
    "QuarantineVerdict",
    "matches_sensitive_pattern",
    "quarantine_scan",
]


class AdversarialReview(Protocol):
    """A reviewer that judges whether a sensitive-surface diff is safe to promote.

    Implementations might be an LLM judge prompted adversarially, a dedicated
    RedTeam agent persona (see `hive-conductor` "RedTeam" guard role), or a
    human-in-the-loop approval queue — the gate doesn't care which, only that
    one ran and rendered a verdict.
    """

    async def review(self, diff: str, touched_paths: list[str]) -> bool:
        """Return True if the diff is cleared to proceed."""
        ...


@dataclass
class QuarantineVerdict:
    cleared: bool
    requires_adversarial_review: bool
    flags: tuple[str, ...]
    reason: str | None = None


def _touches_sensitive_surface(touched_paths: list[str]) -> list[str]:
    return [path for path in touched_paths if matches_sensitive_pattern(path)]


async def quarantine_scan(
    diff: str,
    touched_paths: list[str],
    warden: Warden,
    *,
    adversarial_review: AdversarialReview | None = None,
) -> QuarantineVerdict:
    """Scan a self-modification diff and decide whether it may leave the sandbox.

    Order of checks mirrors severity: a Warden-flagged diff never clears
    regardless of which files it touches (quarantine-1). A clean diff that
    only touches ordinary application surface clears immediately
    (quarantine-2). A clean diff that touches the agent's own containment
    surface is escalated — it clears only once an adversarial review has run
    and passed (quarantine-3, quarantine-4). Warden's flags are always
    surfaced verbatim; quarantine is an audit trail, not a summary
    (quarantine-5).
    """
    verdict = await warden.scan(diff, boundary="self_modification")
    sensitive = _touches_sensitive_surface(touched_paths)
    requires_review = bool(sensitive)

    if not verdict.clean:
        return QuarantineVerdict(
            cleared=False,
            requires_adversarial_review=requires_review,
            flags=verdict.flags,
            reason="warden_flagged_diff",
        )

    if not requires_review:
        return QuarantineVerdict(
            cleared=True,
            requires_adversarial_review=False,
            flags=verdict.flags,
        )

    if adversarial_review is None:
        return QuarantineVerdict(
            cleared=False,
            requires_adversarial_review=True,
            flags=verdict.flags,
            reason=f"sensitive_surface_pending_review:{','.join(sensitive)}",
        )

    approved = await adversarial_review.review(diff, touched_paths)
    return QuarantineVerdict(
        cleared=approved,
        requires_adversarial_review=True,
        flags=verdict.flags,
        reason=None if approved else "adversarial_review_rejected",
    )
