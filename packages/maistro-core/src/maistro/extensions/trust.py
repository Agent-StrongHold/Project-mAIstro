"""Publisher/package trust evaluation, fail-closed (#953, M9-B2).

Trust is a policy question over presented evidence: is this publisher allowed,
and does the evidence carry what the policy demands? Every ambiguity resolves
to *untrusted* — an empty allowlist trusts nobody, a required signature with
none presented fails, and evidence naming a different publisher than the
manifest is a tamper signal, not a formality.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.extensions.types import ExtensionManifest, TrustEvidence


@dataclass(frozen=True)
class TrustPolicy:
    """What the deployment demands before a package may be authorized."""

    #: Publisher ids allowed to ship extensions at all. An empty allowlist is
    #: valid and trusts nobody — deployments must opt in to publishers.
    trusted_publishers: frozenset[str] = frozenset()
    #: Require signature evidence for every package (default: yes).
    require_signature: bool = True
    #: When set, signatures must come from one of these key ids (B1 will
    #: replace key ids with real key material and verification).
    allowed_signer_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TrustReport:
    """The answer to "may this publisher's package be considered at all"."""

    trusted: bool
    failures: tuple[str, ...] = ()


def evaluate_trust(
    manifest: ExtensionManifest, evidence: TrustEvidence, policy: TrustPolicy
) -> TrustReport:
    """Evaluate publisher/package trust for an inspected manifest."""
    failures: list[str] = []

    if evidence.publisher_id != manifest.publisher:
        failures.append(
            f"publisher mismatch: manifest declares {manifest.publisher!r}, "
            f"evidence names {evidence.publisher_id!r}"
        )
    elif manifest.publisher not in policy.trusted_publishers:
        failures.append(f"publisher {manifest.publisher!r} is not in the trusted allowlist")

    if policy.require_signature and not evidence.signature_present:
        failures.append(
            f"no signature presented for {manifest.extension_id} {manifest.version} "
            "but policy requires one"
        )
    if policy.allowed_signer_keys:
        if evidence.signer_key_id is None:
            failures.append("signature key id missing but policy pins allowed signer keys")
        elif evidence.signer_key_id not in policy.allowed_signer_keys:
            failures.append(f"signer key {evidence.signer_key_id!r} is not an allowed signing key")

    if evidence.package_sha256 and evidence.package_sha256 != manifest.artifact_sha256:
        failures.append(
            "evidence digest does not match the manifest artifact claim "
            f"({evidence.package_sha256} != {manifest.artifact_sha256})"
        )

    return TrustReport(trusted=not failures, failures=tuple(failures))
