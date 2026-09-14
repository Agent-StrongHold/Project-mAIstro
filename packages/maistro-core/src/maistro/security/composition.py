"""Canonical application security dependencies.

Application composition roots share these dependencies instead of constructing
product-local Warden or audit authorities. The default composition is suitable
for an ephemeral process; durable application roots replace only the audit sink
with their configured canonical store.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.security._types import AuditLog
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.warden.detector import Warden


@dataclass(frozen=True)
class CanonicalSecurityDependencies:
    """The canonical detector and decision-audit sink for one application."""

    warden: Warden
    audit_log: AuditLog


def build_canonical_security_dependencies() -> CanonicalSecurityDependencies:
    """Build the shared ephemeral security composition.

    Durable application composition roots should construct the same dataclass
    with their canonical persistent audit sink. Keeping this fallback here,
    rather than in a product package, prevents consumers from creating a
    second Warden or audit vocabulary.
    """

    return CanonicalSecurityDependencies(warden=Warden(), audit_log=InMemoryAuditLog())
