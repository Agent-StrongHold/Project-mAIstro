"""The canonical extension-attribution carrier (M9-I1, issue #976).

One extension-mediated effect — an adapter-mediated model call, an installed
extension's activation, a delegated hop that carries extension work — must be
traceable to the exact extension identity that caused it: **name, version,
publisher, and the package/manifest digests**, next to the canonical caller
identity (Workspace, Run, NodeRun, Attempt, Invocation) the rest of the
system already records.

This module owns that carrier, and it owns it *here* — inside the
capabilities layer — for a containment reason that is not negotiable:
``maistro.capabilities`` sits on the promotion-path import closure (the RSI
candidate walks it), and the promotion-surface gate requires every module
that closure reaches to be a protected path. ``maistro.extensions`` is not
one: its package initializer pulls ``isolation → sandbox → runs → graph``,
so a single ``maistro.capabilities → maistro.extensions`` import drags the
whole extension runtime (and 300+ modules) onto the promotion path. The
carrier therefore lives below the extension layer and
:mod:`maistro.extensions.attribution` re-exports it, so the extension-facing
public surface is unchanged and the dependency runs the way the layering
already runs (extensions use capabilities, never the reverse).

What this module deliberately is not:

- **Not a correlation ID.** Attribution rides beside the canonical
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

The payload format is versioned (:data:`ATTRIBUTION_FORMAT`) and parsed
fail-closed: a payload that does not match the format this build understands
is a loud error, never a silent guess — the same posture
:func:`maistro.extensions.types.canonical_install_payload` takes for signed
identity payloads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

#: Version tag of the JSON payload :meth:`ExtensionAttribution.to_payload`
#: writes and :func:`attribution_from_payload` reads. Bumped only when the
#: field set changes incompatibly; decoders refuse formats they do not pin.
ATTRIBUTION_FORMAT = "extension-attribution:v1"

#: The closed payload key set, in decode order. The set is closed in both
#: directions: an unknown key in a stored payload means the payload was
#: written by a different (likely newer) format and must not be silently
#: narrowed into this one, and a missing key means a truncated row that
#: cannot be read as an identity.
ATTRIBUTION_KEYS: tuple[str, ...] = (
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

#: Strict ``MAJOR.MINOR.PATCH`` with semver.org's no-leading-zeros rule — the
#: version form the extension contract pins. It is mirrored here rather than
#: imported from :mod:`maistro.extensions.semver` for the containment reason
#: in the module docstring: the capabilities layer may not import the
#: extensions package. ``tests/extensions/test_attribution.py`` pins the two
#: implementations to the same accept/reject decisions, so they cannot drift.
_STRICT_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

#: Digests are stored in the sha256-hex form install records use.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InvalidAttribution(ValueError):
    """An attribution value or stored payload is not a well-formed identity.

    Raised on construction with an empty identity field, a digest that is not
    SHA-256 hex, a version that is not strict ``MAJOR.MINOR.PATCH``, or a
    stored payload with a foreign format version, a missing or unknown key,
    or a non-string value. Nothing is coerced: evidence that must be guessed
    at is not evidence.
    """


def is_strict_version(text: str) -> bool:
    """Whether ``text`` is a strict ``MAJOR.MINOR.PATCH`` version.

    The same rule :meth:`maistro.extensions.semver.SemVer.parse` enforces,
    mirrored here so the capabilities layer can validate a declared package
    version without importing the extensions package.
    """
    return isinstance(text, str) and _STRICT_VERSION_RE.fullmatch(text.strip()) is not None


def is_sha256_digest(text: str) -> bool:
    """Whether ``text`` is a lowercase sha256 hex digest."""
    return isinstance(text, str) and _SHA256_RE.fullmatch(text) is not None


def _require_digest(value: str, what: str) -> str:
    if not is_sha256_digest(value):
        raise InvalidAttribution(f"attribution {what} must be sha256 hex, got {value!r}")
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
        if not is_strict_version(self.version):
            raise InvalidAttribution(
                f"attribution version {self.version!r} is not strict MAJOR.MINOR.PATCH "
                "(the extension contract allows no pre-release, build metadata, "
                "'v' prefix, or partial forms)"
            )
        _require_text(self.publisher, "publisher")
        _require_digest(self.package_sha256, "package_sha256")
        _require_digest(self.manifest_sha256, "manifest_sha256")

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
            **{key: getattr(self, key) for key in ATTRIBUTION_KEYS[1:]},
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
    unknown = sorted(set(payload) - set(ATTRIBUTION_KEYS))
    if unknown:
        raise InvalidAttribution(f"attribution payload has unknown keys: {unknown}")
    missing = sorted(set(ATTRIBUTION_KEYS) - set(payload))
    if missing:
        raise InvalidAttribution(f"attribution payload is missing keys: {missing}")
    if payload["format"] != ATTRIBUTION_FORMAT:
        raise InvalidAttribution(
            f"attribution payload format {payload['format']!r} is not "
            f"{ATTRIBUTION_FORMAT!r}; this build cannot interpret it"
        )
    for key in ATTRIBUTION_KEYS[1:]:
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

    The same tuple :func:`maestro.extensions.types.identity_key` builds from
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
    "ATTRIBUTION_KEYS",
    "ExtensionAttribution",
    "InvalidAttribution",
    "attribution_from_payload",
    "attribution_identity_key",
    "is_sha256_digest",
    "is_strict_version",
]
