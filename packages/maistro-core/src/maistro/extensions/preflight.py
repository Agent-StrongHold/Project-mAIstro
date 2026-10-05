"""Version-change preflights for the post-install lifecycle (#954, M9-B3).

Upgrades and rollbacks move an extension between versions *after* it has been
authorized once. Each preflight is a pure evaluation over immutable records,
the scope's pin, and the versions currently active in the scope — no I/O, no
imports, no loader access. It answers one question: may this version change
proceed at all, and what exactly would it do to the scope's authority?

The service turns a failed preflight into a ``PreflightError`` raised before
any state changes; a passed preflight's report travels with the operation so
the operator sees — and the audit trail records — precisely which authority
the change carries.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.extensions.authority import (
    AuthorityBaseline,
    AuthorityDelta,
    compute_authority_delta,
)
from maistro.extensions.compatibility import CompatibilityPolicy, evaluate_compatibility
from maistro.extensions.manifest import SEMVER_RE
from maistro.extensions.types import ExtensionInstallRecord, ExtensionManifest, PinRecord


def _semver_tuple(version: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


@dataclass(frozen=True)
class PreflightCheck:
    """One named preflight assertion and its outcome."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    """What a version change would do, and whether it may proceed.

    ``allowed`` is the single answer the service acts on; ``checks`` and
    ``authority`` are the evidence an operator (and the audit trail) is
    shown. A report never mutates anything.
    """

    operation: str
    extension_id: str
    from_version: str | None
    to_version: str
    checks: tuple[PreflightCheck, ...]
    #: The change's permission delta against the currently granted authority
    #: (plus platform pre-approvals). Non-empty ``new`` is the explicit
    #: re-authorization signal.
    authority: AuthorityDelta

    @property
    def allowed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(f"{check.name}: {check.detail}" for check in self.checks if not check.passed)

    @property
    def broadens_authority(self) -> bool:
        return self.authority.requires_authorization


def _pin_check(pin: PinRecord | None, target_version: str) -> PreflightCheck:
    if pin is None:
        return PreflightCheck("pin", True, "no pin holds this extension")
    if pin.version == target_version:
        return PreflightCheck("pin", True, f"pinned version {pin.version} matches the target")
    return PreflightCheck(
        "pin",
        False,
        f"pinned at {pin.version}; moving to {target_version} requires an explicit unpin",
    )


def _compatibility_check(
    manifest: ExtensionManifest,
    installed_versions: dict[str, str],
    platform_api_version: str,
) -> PreflightCheck:
    report = evaluate_compatibility(
        manifest,
        CompatibilityPolicy(
            platform_api_version=platform_api_version,
            installed_versions=installed_versions,
        ),
    )
    if report.compatible:
        return PreflightCheck(
            "compatibility", True, "platform api and declared dependencies are satisfied"
        )
    return PreflightCheck("compatibility", False, "; ".join(report.failures))


def _scope_versions_without(
    installed_versions: dict[str, str], extension_id: str
) -> dict[str, str]:
    """Versions that stay active across the swap; the extension's own entry is
    excluded because the candidate is precisely what replaces it."""
    return {key: version for key, version in installed_versions.items() if key != extension_id}


def upgrade_preflight(
    *,
    active: ExtensionInstallRecord,
    candidate_version: str,
    candidate_source_sha256: str,
    candidate_permissions: tuple[str, ...],
    pin: PinRecord | None,
    installed_versions: dict[str, str],
    platform_api_version: str,
    pre_approved: frozenset[str],
) -> PreflightReport:
    """May ``candidate`` replace the active version of this extension?

    Checks, in the order the service applies them:

    - ``identity`` — the candidate is a *change*: a byte-identical manifest is
      an idempotent no-op (reported as allowed; the service returns the active
      record untouched), while the same version with different bytes is
      refused outright — one version may never have two contents.
    - ``direction`` — an upgrade moves forward (strictly greater semver).
      Moving to an older version is rollback's operation, with rollback's
      checks; the two paths must not blur.
    - ``pin`` — a pin holding another version requires an explicit unpin.
    - ``compatibility`` — platform api version and declared dependencies,
      evaluated against the versions that will still be active after the swap.

    The authority delta compares the candidate's declared permissions with the
    active grant plus platform pre-approvals; a non-empty ``authority.new`` is
    exactly the "requires explicit re-authorization" signal, and the service
    enforces it by routing every upgrade through the inspect → authorize flow.
    """
    checks: list[PreflightCheck] = []

    same_version = active.version == candidate_version
    byte_identical = active.manifest.source_sha256 == candidate_source_sha256
    if same_version and byte_identical:
        return PreflightReport(
            operation="upgrade",
            extension_id=active.extension_id,
            from_version=active.version,
            to_version=candidate_version,
            checks=(
                PreflightCheck(
                    "identity",
                    True,
                    f"{candidate_version} is already the active version, byte-identical",
                ),
            ),
            authority=compute_authority_delta(
                candidate_permissions,
                AuthorityBaseline(
                    previously_granted=frozenset(active.granted_permissions),
                    pre_approved=pre_approved,
                ),
            ),
        )

    candidate = _semver_tuple(candidate_version)
    current = _semver_tuple(active.version)
    if candidate is None or current is None:
        checks.append(
            PreflightCheck(
                "identity",
                False,
                f"non-semver version: active={active.version!r} candidate={candidate_version!r}",
            )
        )
    elif same_version:
        checks.append(
            PreflightCheck(
                "identity",
                False,
                f"version {candidate_version} is active with different manifest bytes; "
                "one version may never have two contents",
            )
        )
    elif candidate < current:
        checks.append(
            PreflightCheck(
                "identity",
                False,
                f"{candidate_version} is older than the active {active.version}; "
                "moving backward is a rollback, not an upgrade",
            )
        )
    else:
        checks.append(PreflightCheck("identity", True, f"{active.version} -> {candidate_version}"))

    checks.append(_pin_check(pin, candidate_version))
    checks.append(
        _compatibility_check(
            active.manifest,
            _scope_versions_without(installed_versions, active.extension_id),
            platform_api_version,
        )
    )

    return PreflightReport(
        operation="upgrade",
        extension_id=active.extension_id,
        from_version=active.version,
        to_version=candidate_version,
        checks=tuple(checks),
        authority=compute_authority_delta(
            candidate_permissions,
            AuthorityBaseline(
                previously_granted=frozenset(active.granted_permissions),
                pre_approved=pre_approved,
            ),
        ),
    )


def rollback_preflight(
    *,
    target: ExtensionInstallRecord,
    current: ExtensionInstallRecord | None,
    pin: PinRecord | None,
    installed_versions: dict[str, str],
    platform_api_version: str,
    pre_approved: frozenset[str],
) -> PreflightReport:
    """May the superseded ``target`` become active again?

    - ``state`` — only SUPERSEDED records roll back: they are versions this
      scope actually ran and authorized before.
    - ``grant`` — the target's frozen grant must exist; a rollback restores a
      previously authorized authority, it never invents one.
    - ``pin`` — a pin holding another version requires an explicit unpin.
    - ``compatibility`` — platform api and declared dependencies against the
      scope minus the extension itself (its current version is what the
      rollback replaces).
    - ``authority`` — what the restored grant adds *today*. Restoring
      permissions the current version had already dropped is a real authority
      change; the service refuses it unless the operator acknowledges the
      broadening explicitly, so "rollback" can never silently resurrect
      authority the scope no longer grants.
    """
    checks: list[PreflightCheck] = []

    if target.state.value == "superseded":
        checks.append(
            PreflightCheck("state", True, f"{target.version} is SUPERSEDED and rollback-eligible")
        )
    else:
        checks.append(
            PreflightCheck(
                "state",
                False,
                f"{target.version} is {target.state}; only SUPERSEDED versions roll back",
            )
        )

    if target.granted_permissions:
        checks.append(
            PreflightCheck(
                "grant",
                True,
                f"restores the frozen grant: {', '.join(target.granted_permissions)}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                "grant",
                False,
                "the record carries no frozen grant; there is no previously "
                "authorized authority to restore",
            )
        )

    checks.append(_pin_check(pin, target.version))
    checks.append(
        _compatibility_check(
            target.manifest,
            _scope_versions_without(installed_versions, target.extension_id),
            platform_api_version,
        )
    )

    current_granted = tuple(current.granted_permissions) if current else ()
    authority = compute_authority_delta(
        target.granted_permissions,
        AuthorityBaseline(
            previously_granted=frozenset(current_granted),
            pre_approved=pre_approved,
        ),
    )

    return PreflightReport(
        operation="rollback",
        extension_id=target.extension_id,
        from_version=current.version if current else None,
        to_version=target.version,
        checks=tuple(checks),
        authority=authority,
    )
