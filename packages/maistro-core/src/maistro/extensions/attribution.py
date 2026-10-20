"""Canonical extension attribution evidence (M9-I1, issue #976).

One extension-mediated effect — an adapter-mediated model call, an installed
extension's activation, a delegated hop that carries extension work — must be
traceable to the exact extension identity that caused it: **name, version,
publisher, and the package/manifest digests**, next to the canonical caller
identity (Workspace, Run, NodeRun, Attempt, Invocation) the rest of the
system already records.

This module is the *extension-facing* surface of that evidence. The carrier
itself — the closed, version-tagged payload, its decoder, and its identity
key — lives in
:mod:`maistro.capabilities.providers.extension_attribution`, because the
capabilities layer is the layer that carries attribution into canonical
telemetry (Binding snapshots, ``EventEnvelope.provenance``, structured log
fields) and that layer sits on the promotion-path import closure, from which
the extensions package may not be imported (see that module's docstring).
Here the carrier is re-exported unchanged, and the two constructors that
need the canonical install record — the only place in the codebase that knows
what an installed package *is* — are added.

What the evidence deliberately is not:

- **Not a correlation ID.** Extension attribution rides beside the canonical
  identifiers — in ``EventEnvelope.provenance``, Binding snapshots, and
  structured log fields — and never in the correlation namespace. An
  extension cannot mint a universal correlation ID: the canonical
  execution-context and Event-envelope fields are closed vocabularies, and
  the attribution payload carries no field that could be mistaken for one.
- **Not a registry read path.** Attribution payloads are self-contained and
  version-tagged, so historical evidence stays decodable after the extension
  is upgraded, disabled, or removed entirely. Decoding consults no store and
  no registry — the exact property that makes old evidence readable when the
  active installed version has since changed.
- **Not a secret carrier.** The field set is fixed. There is no free-form
  mapping an extension could tuck credential material into, and the canonical
  Event envelope redacts ``provenance`` independently on the way in.

The payload format is versioned (``ATTRIBUTION_FORMAT``) and parsed
fail-closed: a payload that does not match the format this build understands
is a loud error, never a silent guess — the same posture
:func:`maistro.extensions.types.canonical_install_payload` takes for signed
identity payloads.
"""

from __future__ import annotations

from maistro.capabilities.providers.extension_attribution import (
    ATTRIBUTION_FORMAT,
    ATTRIBUTION_KEYS,
    ExtensionAttribution,
    InvalidAttribution,
    attribution_from_payload,
    attribution_identity_key,
)
from maistro.extensions.types import ExtensionInstallRecord, InstallRecord


def attribution_from_install_record(
    record: InstallRecord,
    *,
    org_id: str = "",
    workspace_id: str = "",
) -> ExtensionAttribution:
    """Attribute one effect to a B1 install record's exact identity.

    The install record is the immutable fact of what was installed; the
    attribution is the same fact, shaped for telemetry. Nothing is joined
    from mutable registry state, so the attribution of an effect already
    past cannot be rewritten by a later install.
    """
    return ExtensionAttribution(
        extension_id=record.identity.extension_name,
        version=record.identity.semantic_version,
        publisher=record.publisher.publisher_id,
        package_sha256=record.identity.package_sha256,
        manifest_sha256=record.identity.manifest_sha256,
        install_id=record.install_id,
        org_id=org_id,
        workspace_id=workspace_id,
        catalog_url=record.provenance.catalog_url,
    )


def attribution_from_governed_install(record: ExtensionInstallRecord) -> ExtensionAttribution:
    """Attribute one effect to a governed (M9-B2) install's identity.

    Requires an installed payload: a record that has not reached a state
    with an artifact digest (still inspecting, denied, abandoned) names no
    exact package, and attributing effects to it would be fabrication.
    """
    if not record.artifact_sha256:
        raise InvalidAttribution(
            f"install {record.install_id!r} for {record.extension_id!r} "
            f"{record.version} has no installed artifact digest; "
            "only an installed package can be attributed"
        )
    return ExtensionAttribution(
        extension_id=record.extension_id,
        version=record.version,
        publisher=record.manifest.publisher,
        package_sha256=record.artifact_sha256,
        manifest_sha256=record.manifest.source_sha256,
        install_id=record.install_id,
        org_id=record.org_id,
        workspace_id=record.workspace_id,
    )


__all__ = [
    "ATTRIBUTION_FORMAT",
    "ATTRIBUTION_KEYS",
    "ExtensionAttribution",
    "InvalidAttribution",
    "attribution_from_governed_install",
    "attribution_from_install_record",
    "attribution_from_payload",
    "attribution_identity_key",
]
