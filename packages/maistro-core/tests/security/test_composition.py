"""The canonical security composition is the only Warden/audit authority.

Turing (and any other application root) consumes
``build_canonical_security_dependencies`` rather than constructing a
product-local Warden or audit vocabulary (#1139). These tests pin the composed
objects to the canonical detector and audit record so a replacement composition
cannot silently introduce a second security authority.
"""

from __future__ import annotations

import asyncio

from maistro.security._types import AuditEntry, AuditLog
from maistro.security.composition import (
    CanonicalSecurityDependencies,
    build_canonical_security_dependencies,
)
from maistro.security.warden.detector import WARDEN_POLICY_VERSION, Warden


def test_composition_builds_the_canonical_warden_and_audit_sink() -> None:
    dependencies = build_canonical_security_dependencies()

    assert isinstance(dependencies, CanonicalSecurityDependencies)
    assert isinstance(dependencies.warden, Warden)
    # The audit correlation identity comes from the canonical detector, never
    # from a consumer-local policy version.
    assert dependencies.warden.policy_version == WARDEN_POLICY_VERSION
    assert isinstance(dependencies.audit_log, AuditLog)


def test_composed_audit_sink_records_correlation_without_content() -> None:
    dependencies = build_canonical_security_dependencies()

    asyncio.run(
        dependencies.audit_log.log(
            AuditEntry(
                boundary="user_input",
                user_id="user-1",
                verdict="blocked",
                route="/v1/chat",
                action="chat",
                policy_version=dependencies.warden.policy_version,
                workspace_id="ws-1",
                project_id="proj-1",
                run_id="run-1",
                content_sha256="0" * 64,
                content_length=12,
            )
        )
    )
    entries = asyncio.run(dependencies.audit_log.get_entries(user_id="user-1"))

    assert len(entries) == 1
    entry = entries[0]
    assert entry.verdict == "blocked"
    assert entry.run_id == "run-1"
    assert entry.policy_version == WARDEN_POLICY_VERSION
    # The audit record carries evidence hashes, never the scanned content.
    assert entry.detail == ""
    assert entry.content_length == 12
