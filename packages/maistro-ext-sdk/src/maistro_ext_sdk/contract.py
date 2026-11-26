"""The versioned extension contract (M9-A1, #949).

The contract version is the version of THIS schema — the manifest fields, the
authority vocabulary, and the validation behavior an extension author codes
against. It is deliberately a literal in this module, not derived from the
package version, the lockstep workspace VERSION file, or any installed
distribution:

- The *package* (`maistro-ext-sdk`) versions in lockstep with the monorepo per
  ADR-073126-c4e1 — that is what ``__version__`` carries.
- The *contract* versions independently, exactly as the issue requires, so a
  manifest written against contract 1.x keeps validating no matter how many
  application releases ship in between.

Reconciliation note: ADR-073126-c4e1 ("Versioning is lockstep across the
monorepo") governs published package versions, not contract semantics. This
module adds a second, semantic axis — the manifest contract — which the same
ADR does not speak to. A host that rejects a manifest names the contract
version it enforces, so an author can tell "your manifest is malformed" from
"your manifest predates this host".
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CONTRACT_VERSION",
    "EXTENSION_CONTRACT_VERSION",
    "ContractVersion",
    "contract_version",
    "parse_contract_version",
]

#: The extension manifest contract this SDK publishes. Bump only for a
#: breaking change to the manifest schema or the authority vocabulary; add
#: fields with defaults without bumping. Independently versioned from the
#: maistro application version (which is what ``maistro_ext_sdk.__version__``
#: reflects, in lockstep with the repo's VERSION file).
EXTENSION_CONTRACT_VERSION = "1.0.0"

#: Alias under the shorter name; one value, two spellings on purpose — the
#: constant is the storage, the function is the queryable surface the issue
#: asks for ("contract version is queryable").
CONTRACT_VERSION = EXTENSION_CONTRACT_VERSION

#: Every contract version this SDK can validate. v1 SDKs validate v1
#: manifests; a future 2.x schema lands behind this gate, not by silently
#: reinterpreting 1.x documents.
SUPPORTED_CONTRACT_MAJORS = (1,)


@dataclass(frozen=True, order=True)
class ContractVersion:
    """A parsed contract version (semver-shaped, ordered by parts).

    A small explicit type rather than a tuple so error messages and
    compatibility reports can carry it whole. ``order=True`` gives the
    lexicographic (major, minor, patch) ordering the range parser needs.
    """

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def supported(self) -> bool:
        """Whether this SDK validates manifests written against this version."""
        return self.major in SUPPORTED_CONTRACT_MAJORS


def contract_version() -> str:
    """The extension contract version this SDK publishes (queryable surface)."""
    return EXTENSION_CONTRACT_VERSION


def parse_contract_version(value: str) -> ContractVersion:
    """Parse a ``MAJOR.MINOR.PATCH`` contract version string.

    Raises ``ValueError`` on anything else — an explicit failure, per the
    issue's "malformed ... declarations fail explicitly" bar.
    """
    parts = value.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"contract version must be MAJOR.MINOR.PATCH, got {value!r} "
            f"(this SDK publishes {EXTENSION_CONTRACT_VERSION})"
        )
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"contract version components must be integers, got {value!r}") from exc
    if major < 0 or minor < 0 or patch < 0:
        raise ValueError(f"contract version components must be non-negative, got {value!r}")
    return ContractVersion(major=major, minor=minor, patch=patch)
