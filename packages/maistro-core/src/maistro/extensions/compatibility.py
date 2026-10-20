"""Compatibility resolution for candidate extensions (#953, M9-B2).

Pure evaluation over the manifest snapshot: platform API compatibility and
declared-dependency resolution against the extensions already active in the
target scope. No I/O, no imports, no side effects — a compatibility failure is
a plain data answer the service turns into a REJECTED record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from maistro.extensions.manifest import SEMVER_RE
from maistro.extensions.types import ExtensionManifest


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.match(version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _range_satisfied(range_spec: str, installed_version: str) -> bool:
    """Whether ``installed_version`` satisfies the declared dependency range.

    Supported range grammar: an exact semver, ``^X.Y.Z`` (same major, at or
    above the floor), or ``*``. Anything else is unsatisfiable — an unknown
    range must fail closed, not match leniently.
    """
    installed = _parse_semver(installed_version)
    if installed is None:
        return False
    if range_spec == "*":
        return True
    if range_spec.startswith("^"):
        floor = _parse_semver(range_spec[1:])
        if floor is None:
            return False
        return installed >= floor and installed[0] == floor[0]
    exact = _parse_semver(range_spec)
    if exact is None:
        return False
    return installed == exact


@dataclass(frozen=True)
class CompatibilityPolicy:
    """What the platform requires of a candidate extension."""

    #: The platform's own extension API version; candidates must share its
    #: major version (the compatibility rule the code registry already uses).
    platform_api_version: str
    #: Versions of extensions currently ACTIVE in the target scope, by id.
    installed_versions: Mapping[str, str]


@dataclass(frozen=True)
class CompatibilityReport:
    """The answer to "can this platform run this extension here"."""

    compatible: bool
    failures: tuple[str, ...] = ()


def evaluate_platform_compatibility(
    manifest: ExtensionManifest, platform_api_version: str
) -> CompatibilityReport:
    """The platform-API half of the evaluation, standalone.

    Install-time evaluation and runtime health projections (#978) must agree
    on what "incompatible" means, so both call this one check: the platform's
    API major version against the manifest's declared one. Dependency
    resolution is deliberately NOT part of it — runtime dependency state has
    its own readiness gate and its own, transient, summary state.
    """
    failures: list[str] = []
    platform = _parse_semver(platform_api_version)
    candidate = _parse_semver(manifest.api_version)
    if platform is None or candidate is None:
        failures.append(
            f"api_version comparison failed: platform={platform_api_version!r} "
            f"candidate={manifest.api_version!r}"
        )
    elif candidate[0] != platform[0]:
        failures.append(
            f"api_version major mismatch: platform is {platform[0]}, "
            f"{manifest.extension_id} {manifest.version} requires {manifest.api_version}"
        )
    return CompatibilityReport(compatible=not failures, failures=tuple(failures))


def evaluate_compatibility(
    manifest: ExtensionManifest, policy: CompatibilityPolicy
) -> CompatibilityReport:
    """Check platform API compatibility and resolve declared dependencies."""
    failures: list[str] = [
        *evaluate_platform_compatibility(manifest, policy.platform_api_version).failures
    ]

    for dependency in manifest.dependencies:
        installed_version = policy.installed_versions.get(dependency.extension_id)
        if installed_version is None:
            failures.append(
                f"missing dependency: {dependency.extension_id} "
                f"(range {dependency.range_spec}) is not active in this scope"
            )
        elif not _range_satisfied(dependency.range_spec, installed_version):
            failures.append(
                f"dependency conflict: {dependency.extension_id} is active at "
                f"{installed_version}, which does not satisfy {dependency.range_spec}"
            )

    return CompatibilityReport(compatible=not failures, failures=tuple(failures))
