"""Trust tier model, review queue, and banish list.

Trust contamination rule: context_trust_tier can only decrease per engine session.
Admin decisions feed the RLPHD loop (Reinforcement Learning for Policy via Human Decisions).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from maistro.security.normalize import normalize_for_detection
from maistro.security.warden.heuristics import heuristic_scan
from maistro_design.scan import scan_blocking_patterns


class TrustTier(StrEnum):
    T0 = "t0"  # built-in (engine-shipped, immutable)
    T1 = "t1"  # verified (audited third-party)
    T2 = "t2"  # community (user-installed, unaudited)
    T3 = "t3"  # untrusted (runtime user input / external fetch)
    SKULL = "skull"  # dangerous / blocked (Warden-flagged or banished)

    def min(self, other: TrustTier) -> TrustTier:
        """Return the lower-trust of two tiers. Trust can only decrease."""
        _order = [TrustTier.T0, TrustTier.T1, TrustTier.T2, TrustTier.T3, TrustTier.SKULL]
        return _order[max(_order.index(self), _order.index(other))]


@dataclass
class TrustReviewRecord:
    """A Warden scan result queued for async admin review."""

    id: str
    content_fingerprint: str  # sha256 hex of scanned content
    assigned_tier: TrustTier
    warden_recommendation: str  # "keep" | "upgrade" | "banish"
    warden_flags: tuple[str, ...]  # patterns detected
    warden_confidence: float
    source: str  # "discovery_field" | "design_system" | "skill"
    source_key: str  # e.g. field key or system slug
    admin_decision: str | None = None  # None = pending; set by resolve()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_pending(self) -> bool:
        return self.admin_decision is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "assigned_tier": self.assigned_tier,
            "warden_recommendation": self.warden_recommendation,
            "warden_flags": list(self.warden_flags),
            "source": self.source,
            "source_key": self.source_key,
            "admin_decision": self.admin_decision,
            "created_at": self.created_at.isoformat(),
        }


class InMemoryTrustBanishList:
    """Pattern registry that auto-blocks future content matching banished patterns.

    Part of the RLPHD loop: admin banish decisions persist here and gate
    future Warden pre-scans before the full pipeline runs.
    """

    def __init__(self) -> None:
        self._patterns: list[str] = []
        self._lock = threading.RLock()

    def add_pattern(self, pattern: str) -> None:
        with self._lock:
            if pattern not in self._patterns:
                self._patterns.append(pattern)

    def is_banned(self, content: str) -> bool:
        with self._lock:
            content_lower = content.lower()
            return any(p.lower() in content_lower for p in self._patterns)

    def list_patterns(self) -> list[str]:
        with self._lock:
            return list(self._patterns)

    def __len__(self) -> int:
        return len(self._patterns)


class InMemoryTrustReviewQueue:
    """Async admin review queue for Warden-scanned inputs.

    Admin decisions: keep | upgrade | improve_and_upgrade | banish
    Each resolved decision feeds back into Warden's RLPHD loop.
    """

    def __init__(self) -> None:
        self._records: dict[str, TrustReviewRecord] = {}
        self._lock = threading.RLock()

    def enqueue(self, record: TrustReviewRecord) -> None:
        with self._lock:
            self._records[record.id] = record

    def pending(self) -> list[TrustReviewRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.is_pending()]

    def resolve(self, record_id: str, decision: str) -> TrustReviewRecord:
        """Record an admin decision. Raises ValueError if record not found."""
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                msg = f"TrustReviewRecord '{record_id}' not found"
                raise ValueError(msg)
            record.admin_decision = decision
            return record

    def all_records(self) -> list[TrustReviewRecord]:
        with self._lock:
            return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)


def _fingerprint(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _warden_recommendation(flags: tuple[str, ...], confidence: float) -> str:
    """Derive a Warden recommendation from scan results."""
    if not flags:
        return "upgrade"
    if confidence >= 0.85:
        return "banish"
    return "keep"


def scan_and_record(
    content: str,
    *,
    source: str,
    source_key: str,
    record_id: str,
    banish_list: InMemoryTrustBanishList | None = None,
    review_queue: InMemoryTrustReviewQueue | None = None,
) -> TrustTier:
    """Scan content with the shared Design/Warden vocabulary and enqueue review.

    The synchronous pre-scan intentionally runs the deterministic layers only;
    those are the same blocking patterns used by the final output boundary plus
    Warden's heuristic layer. A blocking match is SKULL/high-confidence, while a
    heuristic-only match remains T3 but is explicitly kept for review. No clean
    record is manufactured from content the renderer would later reject.
    """
    flags: list[str] = []
    banished = banish_list is not None and banish_list.is_banned(content)
    if banished:
        # Preserve the stable RLPHD flag while avoiding a second banish-list
        # lookup in the shared scanner.
        flags.append("banish_list_match")

    blocking_flags = scan_blocking_patterns("content", content, None)
    flags.extend(blocking_flags)
    suspicious, heuristic_flags = heuristic_scan(normalize_for_detection(content))
    if suspicious:
        flags.extend(f"content: matched heuristic pattern {flag}" for flag in heuristic_flags)

    if banished or blocking_flags:
        tier = TrustTier.SKULL
        confidence = 1.0 if banished else 0.9
    elif suspicious:
        tier = TrustTier.T3
        confidence = 0.6
    else:
        tier = TrustTier.T3
        confidence = 0.0

    flags_tuple = tuple(flags)
    if review_queue is not None:
        record = TrustReviewRecord(
            id=record_id,
            content_fingerprint=_fingerprint(content),
            assigned_tier=tier,
            warden_recommendation=_warden_recommendation(flags_tuple, confidence),
            warden_flags=flags_tuple,
            warden_confidence=confidence,
            source=source,
            source_key=source_key,
        )
        review_queue.enqueue(record)

    return tier
