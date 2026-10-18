"""Canonical extension attribution evidence (M9-I1, issue #976).

One extension-mediated effect — an adapter-mediated model call, an installed
extension's activation, a delegated hop that carries extension work — must be
traceable to the exact extension identity that caused it: **name, version,
publisher, and the package/manifest digests**, next to the canonical caller
identity (Workspace, Run, NodeRun, Attempt, Invocation) the rest of the
system already records.

What this module deliberately is not:

- **Not a correlation ID.** Extension attribution rides beside the canonical
  identifiers — in ``EventEnvelope.provenance``, Binding snapshots, and
  structured log fields — and never in the correlation namespace. An
  extension cannot mint a universal correlation ID: the canonical
  execution-context and Event-envelope fields are closed vocabularies, and
  this type carries no field that could be mistaken for one.
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
:data:`maistro.extensions.types.canonical_install_payload` takes for signed
identity payloads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from maistro.extensions.semver import InvalidSemanticVersion, SemVer
from maistro.extensions.types import (
    DIGEST_ALGORITHM,
    ExtensionInstallRecord,
    ExtensionRegistryError,
    InstallRecord,
)

#: Version tag of the JSON payload :meth:`ExtensionAttribution.to_payload`
#: writes and :func:`attribution_from_payload` reads. Bumped only when the
#: field set changes incompatibly; decoders refuse formats they do not pin.
ATTRIBUTION_FORMAT = "extension-attribution:v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Payload keys in decode order. The set is closed: an unknown key in a
#: stored payload means the payload was written by a different (likely
#: newer) format and must not be silently narrowed into this one.
_PAYLOAD_KEYS: tuple[str, ...] = (
    "format",
    "extension_id",
    "version",
    "publisher",
    "package_sha256",
    "manifest_sha256",
    "install_id",
    "org_id",
    "workspace_id",
    "catalog_url",
)

_REQUIRED_KEYS = frozenset(_PAYLOAD_KEYS[:6])


class InvalidAttribution(ExtensionRegistryError):
    """An attribution value or stored payload is not a well-formed identity.

    Raised on construction with an empty identity field, a digest that is not
    SHA-256 hex, or a stored payload with a foreign format version, a missing
    or unknown key, or a non-string value. Nothing is coerced: evidence that
    must be guessed at is not evidence.
    """


def _require_digest(value: str, what: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise InvalidAttribution(
            f"attribution {what} must be {DIGEST_ALGORITHM} hex, got {value!r}"
        )
    return value


def _require_text(value: str, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAttribution(f"attribution {what} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ExtensionAttribution:
    """The exact extension identity behind one effect, plus its scope linkage.

    The identity triple plus both digests is the *exact* installed identity —
    the same four fields :class:`maistro.extensions.types.PackageIdentity`
    keys install records by, plus the publisher that signed it. A semantic
    version alone does not name a package; attribution without digests would
    let an upgraded package quietly inherit an old effect's identity.

    ``install_id``, ``org_id``, ``workspace_id`` and ``catalog_url`` are the
    linkage to the canonical install record and its authorization scope when
    the attribution was built from one. They are context, not identity: two
    attributions of the same installed package may differ in them.
    """

    extension_id: str
    version: str
    publisher: str
    package_sha256: str
    manifest_sha256: str
    install_id: str = ""
    org_id: str = ""
    workspace_id: str = ""
    catalog_url: str = ""

    def __post_init__(self) -> None:
        _require_text(self.extension_id, "extension_id")
        _require_text(self.version, "version")
        try:
            SemVer.parse(self.version)  # strict MAJOR.MINOR.PATCH, like every install record
        except InvalidSemanticVersion as exc:
            raise InvalidAttribution(
                f"attribution version {self.version!r} is not strict MAJOR.MINOR.PATCH: {exc}"
            ) from exc
        _require_text(self.publisher, "publisher")
        _require_digest(self.package_sha256, "package_sha256")
        _require_digest(self.manifest_sha256, "manifest_sha256")

    # ---- construction from canonical records -----------------------------

    @classmethod
    def from_install_record(
        cls,
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
        return cls(
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

    @classmethod
    def from_governed_install(cls, record: ExtensionInstallRecord) -> ExtensionAttribution:
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
        return cls(
            extension_id=record.extension_id,
            version=record.version,
            publisher=record.manifest.publisher,
            package_sha256=record.artifact_sha256,
            manifest_sha256=record.manifest.source_sha256,
            install_id=record.install_id,
            org_id=record.org_id,
            workspace_id=record.workspace_id,
        )

    # ---- canonical telemetry surfaces ------------------------------------

    def to_payload(self) -> dict[str, str]:
        """The version-tagged, JSON-safe payload for durable evidence.

        Every value is a string; the format tag travels inside the payload so
        a stored row is self-describing. This is the shape that rides in
        ``EventEnvelope.provenance`` (under the ``extension`` key, via
        :meth:`provenance_payload`), in Binding snapshots, and in delegation
        metadata across asynchronous hops.
        """
        return {
            "format": ATTRIBUTION_FORMAT,
            **{key: getattr(self, key) for key in _PAYLOAD_KEYS[1:]},
        }

    def provenance_payload(self) -> dict[str, dict[str, str]]:
        """The ``EventEnvelope.provenance`` fragment naming this attribution.

        Merged under the fixed ``extension`` key; the envelope redacts
        provenance values on construction, so a secret-shaped string cannot
        survive into durable evidence even if a caller passed one in a field
        (the field set here gives an extension no slot for one anyway).
        """
        return {"extension": self.to_payload()}

    def to_log_fields(self) -> dict[str, str]:
        """Flat scalar fields for structured log lines and span attributes.

        Only set linkage is emitted (blank optional fields are omitted), and
        every value is a string — the telemetry-safety boundary takes strings
        from a finite, server-owned vocabulary, and this is that vocabulary
        for extension attribution.
        """
        fields: dict[str, str] = {
            "extension_id": self.extension_id,
            "extension_version": self.version,
            "extension_publisher": self.publisher,
            "extension_package_sha256": self.package_sha256,
            "extension_manifest_sha256": self.manifest_sha256,
        }
        for optional, name in (
            ("install_id", "extension_install_id"),
            ("org_id", "extension_org_id"),
            ("workspace_id", "extension_workspace_id"),
        ):
            value = getattr(self, optional)
            if value:
                fields[name] = value
        return fields

    def describe(self) -> str:
        """One-line human form for error messages and audit lines."""
        return (
            f"{self.extension_id} {self.version} (publisher {self.publisher!r}, "
            f"package {self.package_sha256[:12]}…)"
        )

    # ---- durable round-trip ----------------------------------------------

    def to_json(self) -> str:
        """Serialize for a durable evidence column or a delegation hop."""
        return json.dumps(self.to_payload(), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> ExtensionAttribution:
        """Decode a serialized attribution, failing closed."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidAttribution(f"attribution payload is not JSON: {exc}") from exc
        return attribution_from_payload(payload)


def attribution_from_payload(payload: Any) -> ExtensionAttribution:
    """Rebuild an attribution from its payload, refusing anything foreign.

    Historical evidence decodes here and nowhere else: no store, no registry,
    no network. A payload this build does not pin (unknown ``format``), a
    payload with unknown keys (a future format narrowed by an old decoder),
    or a payload missing keys (a truncated row) raises
    :class:`InvalidAttribution` instead of decoding to a quietly different
    identity.
    """
    if not isinstance(payload, dict):
        raise InvalidAttribution(
            f"attribution payload must be a JSON object, got {type(payload).__name__}"
        )
    unknown = sorted(set(payload) - set(_PAYLOAD_KEYS))
    if unknown:
        raise InvalidAttribution(f"attribution payload has unknown keys: {unknown}")
    missing = sorted(_REQUIRED_KEYS - set(payload))
    if missing:
        raise InvalidAttribution(f"attribution payload is missing keys: {missing}")
    if payload["format"] != ATTRIBUTION_FORMAT:
        raise InvalidAttribution(
            f"attribution payload format {payload['format']!r} is not "
            f"{ATTRIBUTION_FORMAT!r}; this build cannot interpret it"
        )
    for key in _PAYLOAD_KEYS[1:]:
        value = payload[key]
        if not isinstance(value, str):
            raise InvalidAttribution(
                f"attribution payload key {key!r} must be a string, got {type(value).__name__}"
            )
    return ExtensionAttribution(
        extension_id=payload["extension_id"],
        version=payload["version"],
        publisher=payload["publisher"],
        package_sha256=payload["package_sha256"],
        manifest_sha256=payload["manifest_sha256"],
        install_id=payload["install_id"],
        org_id=payload["org_id"],
        workspace_id=payload["workspace_id"],
        catalog_url=payload["catalog_url"],
    )


def attribution_identity_key(attribution: ExtensionAttribution) -> tuple[str, str, str, str]:
    """Hashable key joining an attribution to its install-record identity.

    The same tuple :func:`maistro.extensions.types.identity_key` builds from
    a :class:`~maistro.extensions.types.PackageIdentity`, so evidence keyed
    by attribution joins evidence keyed by install record without either
    side coercing the other.
    """
    return (
        attribution.extension_id,
        attribution.version,
        attribution.package_sha256,
        attribution.manifest_sha256,
    )


__all__ = [
    "ATTRIBUTION_FORMAT",
    "ExtensionAttribution",
    "InvalidAttribution",
    "attribution_from_payload",
    "attribution_identity_key",
]
