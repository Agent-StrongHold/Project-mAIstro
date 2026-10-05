"""Install-record rules against the reference store (M9-B1, issue #952).

Each test names the acceptance criterion it pins:

* same semantic version + different digest cannot silently share identity;
* history retains publisher/digest/manifest after registry changes;
* tampered packages fail verification before the (code-import) activation
  callback ever runs;
* provenance is queryable from history;
* trust evidence is durable, not recomputed on read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from extensions.extension_fixtures import (
    CATALOG_SNAPSHOT,
    CATALOG_URL,
    MANIFEST_BODY,
    PACKAGE_BYTES,
    RETRIEVED_AT,
    install_bundle,
    key_fingerprint,
    make_identity,
    make_publisher,
    make_request,
    public_key_hex,
    reidentify,
    sign,
)
from maistro.extensions.store import InMemoryExtensionInstallStore
from maistro.extensions.types import (
    ExtensionIdentityConflict,
    PackageSignatureInvalid,
    PublisherKeyConflict,
    UnknownPublisher,
    manifest_snapshot,
    publisher_from_json,
    publisher_to_json,
)
from maistro.extensions.verify import verify_package_signature


class ActivationRecorder:
    """Stands in for the code-import/activation boundary."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    def __call__(self, record: object) -> None:
        self.calls.append(record)


async def test_install_persists_publisher_digest_manifest_and_provenance() -> None:
    """A successful install records every piece of metadata the issue names."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])

    record = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    assert record.identity == bundle["identity"]
    assert record.publisher == bundle["publisher"]
    assert record.signature == bundle["request"].signature
    assert record.manifest == manifest_snapshot(MANIFEST_BODY)
    assert record.provenance.catalog_url == CATALOG_URL
    assert record.provenance.catalog_snapshot_sha256 == CATALOG_SNAPSHOT
    assert record.provenance.retrieved_at == RETRIEVED_AT
    assert record.installed_at.tzinfo is UTC
    assert record.evidence.verified_at == record.installed_at
    assert record.evidence.verified is True
    assert record.evidence.subject_sha256 == bundle["identity"].package_sha256
    assert record.evidence.verifier_key_fingerprint == bundle["publisher"].signing_key_fingerprint


async def test_activate_runs_once_with_the_persisted_record() -> None:
    """The activation boundary sees exactly the record the store persisted."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    activate = ActivationRecorder()

    record = await store.record_install(
        bundle["request"], package_bytes=bundle["package_bytes"], activate=activate
    )

    assert activate.calls == [record]


async def test_same_semantic_version_with_different_digest_is_refused() -> None:
    """A second package cannot silently occupy an installed version identity."""
    store = InMemoryExtensionInstallStore()
    first = install_bundle()
    await store.register_publisher(first["publisher"])
    installed = await store.record_install(first["request"], package_bytes=first["package_bytes"])

    # Same publisher (same registered key), same name and version, different
    # bytes: the identity is well-signed but conflicts with the installed one.
    tampered_bytes = b"different bytes entirely\n"
    second_identity = make_identity(package_bytes=tampered_bytes)
    second_request = make_request(second_identity, sign(first["key"], second_identity))

    with pytest.raises(ExtensionIdentityConflict) as excinfo:
        await store.record_install(second_request, package_bytes=tampered_bytes)
    assert "1.0.0" in str(excinfo.value)

    history = await store.install_history("ext-tool")
    assert history == [installed]
    assert history[0].identity.package_sha256 == first["identity"].package_sha256


async def test_re_recording_the_same_identity_is_idempotent() -> None:
    """Identical re-record returns the original record and never re-activates."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    original = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
    activate = ActivationRecorder()

    again = await store.record_install(
        bundle["request"], package_bytes=bundle["package_bytes"], activate=activate
    )

    assert again == original
    assert activate.calls == []
    assert len(await store.install_history("ext-tool")) == 1


async def test_tampered_package_fails_digest_verification_before_activation() -> None:
    """Bytes that do not match the digest are refused before code import."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    activate = ActivationRecorder()
    tampered = PACKAGE_BYTES + b"inject"

    with pytest.raises(Exception, match="digest"):
        await store.record_install(bundle["request"], package_bytes=tampered, activate=activate)
    assert activate.calls == []
    assert await store.install_history("ext-tool") == []


async def test_manifest_tampering_fails_verification_before_activation() -> None:
    """A manifest swapped after signing fails, and nothing imports."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    activate = ActivationRecorder()
    forged_manifest = MANIFEST_BODY.replace("main.py", "evil.py")
    forged_identity = reidentify(
        bundle["identity"],
        manifest_sha256=manifest_snapshot(forged_manifest).sha256,
    )
    # The signature is the publisher's — over the *honest* identity. Only the
    # manifest digest in the presented identity was swapped, which is exactly
    # the mismatch the canonical payload makes unverifiable: the honest
    # signature no longer covers the presented (forged) identity.
    request = make_request(
        forged_identity, bundle["request"].signature, manifest_body=forged_manifest
    )

    with pytest.raises(Exception, match="signature"):
        await store.record_install(
            request, package_bytes=bundle["package_bytes"], activate=activate
        )
    assert activate.calls == []
    assert await store.install_history("ext-tool") == []


async def test_signature_by_a_different_key_fails_before_activation() -> None:
    """A signature from any key but the registered publisher's is refused."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    impostor = Ed25519PrivateKey.generate()
    identity = bundle["identity"]
    forged_request = make_request(identity, sign(impostor, identity))
    activate = ActivationRecorder()

    with pytest.raises(Exception, match="signature"):
        await store.record_install(
            forged_request, package_bytes=bundle["package_bytes"], activate=activate
        )
    assert activate.calls == []
    assert await store.install_history("ext-tool") == []


async def test_signature_verification_refuses_a_manifest_that_digests_elsewhere() -> None:
    """A presented manifest that does not digest to the identity's manifest
    digest is refused before any key material is touched.

    The store-level manifest-tampering test above reaches the *signature*
    refusal (the honest signature no longer covers the forged identity). This
    pins the earlier precondition: the signature is only ever checked over a
    manifest that digests to what the identity declares, so a mismatched
    manifest cannot steer the verifier into a shape it was not built for.
    """
    bundle = install_bundle()
    identity = bundle["identity"]
    swapped_manifest = MANIFEST_BODY.replace("main.py", "other.py")

    with pytest.raises(PackageSignatureInvalid, match="manifest does not digest"):
        verify_package_signature(
            identity,
            swapped_manifest,
            bundle["request"].signature,
            public_key_hex(bundle["key"]),
        )


async def test_signature_verification_refuses_malformed_key_or_signature_material() -> None:
    """Key/signature material that is not usable is a refusal, never a crash
    or a downgrade to unverified."""
    bundle = install_bundle()
    identity = bundle["identity"]
    real_signature = bundle["request"].signature
    real_key_hex = public_key_hex(bundle["key"])

    with pytest.raises(PackageSignatureInvalid, match="not valid hex"):
        verify_package_signature(identity, MANIFEST_BODY, "definitely-not-hex", real_key_hex)
    with pytest.raises(PackageSignatureInvalid, match="not valid hex"):
        verify_package_signature(identity, MANIFEST_BODY, real_signature, "definitely-not-hex")


async def test_install_without_a_registered_publisher_is_refused() -> None:
    """No publisher record, no install — nothing is persisted."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    activate = ActivationRecorder()

    with pytest.raises(UnknownPublisher):
        await store.record_install(
            bundle["request"], package_bytes=bundle["package_bytes"], activate=activate
        )
    assert activate.calls == []
    assert await store.install_history("ext-tool") == []


async def test_reregistering_a_publisher_under_a_new_key_is_refused() -> None:
    """The trust root a record was verified against cannot drift silently."""
    store = InMemoryExtensionInstallStore()
    publisher, _ = make_publisher(publisher_id="pub-1")
    await store.register_publisher(publisher)
    rotated = make_publisher(publisher_id="pub-1", signer=Ed25519PrivateKey.generate())[0]

    with pytest.raises(PublisherKeyConflict):
        await store.register_publisher(rotated)

    stored = await store.get_install(make_identity())  # nothing installed yet
    assert stored is None


async def test_history_retains_original_evidence_after_registry_changes() -> None:
    """Catalog churn and later installs cannot reach back into record one."""
    store = InMemoryExtensionInstallStore()
    first = install_bundle()
    await store.register_publisher(first["publisher"])
    original = await store.record_install(first["request"], package_bytes=first["package_bytes"])

    # "Registry changes": a second publisher publishes 2.0.0 through a
    # different catalog; the first publisher's catalog entry is rewritten.
    second = install_bundle(
        version="2.0.0",
        package_bytes=b"version two payload\n",
        manifest_body="name: ext-tool\nversion: 2.0.0\nentry: main.py\n",
        publisher_id="pub-2",
        catalog_url="https://other-catalog.example/index.json",
    )
    await store.register_publisher(second["publisher"])
    await store.record_install(second["request"], package_bytes=second["package_bytes"])

    history = await store.install_history("ext-tool")
    assert len(history) == 2
    retained = history[0]
    assert retained == original
    assert retained.publisher == first["publisher"]
    assert retained.publisher.signing_public_key == public_key_hex(first["key"])
    assert retained.identity.package_sha256 == hashlib.sha256(PACKAGE_BYTES).hexdigest()
    assert retained.manifest.body == MANIFEST_BODY
    assert retained.provenance.catalog_url == CATALOG_URL
    assert retained.evidence.verifier_key_fingerprint == key_fingerprint(first["key"])


async def test_provenance_is_queryable_from_history() -> None:
    """Each record carries the catalog it was fetched from, queryable per name."""
    store = InMemoryExtensionInstallStore()
    first = install_bundle(catalog_url="https://catalog-a.example/x.json")
    second = install_bundle(
        version="2.0.0",
        package_bytes=b"v2 payload\n",
        manifest_body="name: ext-tool\nversion: 2.0.0\nentry: main.py\n",
        publisher_id="pub-2",
        catalog_url="https://catalog-b.example/y.json",
    )
    await store.register_publisher(first["publisher"])
    await store.register_publisher(second["publisher"])
    await store.record_install(first["request"], package_bytes=first["package_bytes"])
    await store.record_install(second["request"], package_bytes=second["package_bytes"])

    by_catalog = {
        record.provenance.catalog_url for record in await store.install_history("ext-tool")
    }
    assert by_catalog == {
        "https://catalog-a.example/x.json",
        "https://catalog-b.example/y.json",
    }


async def test_trust_evidence_is_read_back_not_recomputed() -> None:
    """Reading evidence requires neither keys nor re-verification."""
    store = InMemoryExtensionInstallStore()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    installed = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    # A fresh store instance over the same "database" — here, the same records
    # re-read through the store API — must return the original evidence
    # without any signing key or verifier being available to it.
    identity = bundle["identity"]
    reread = await store.get_install(identity)
    assert reread is not None
    assert reread.evidence == installed.evidence
    assert reread.evidence.verified is True
    assert reread.evidence.subject_sha256 == identity.package_sha256


def test_naive_timestamps_in_durable_payloads_are_read_as_utc() -> None:
    """A durable payload written by an earlier serializer version that stored
    naive ISO-8601 timestamps round-trips to a timezone-aware UTC datetime —
    the documented reading of ``_datetime_value`` — so the restored record
    compares equal to the aware original instead of failing equality.
    """
    publisher, _signing_key = make_publisher()
    payload = json.loads(publisher_to_json(publisher))
    assert payload["registered_at"].endswith("+00:00")  # the writer is aware

    payload["registered_at"] = "2026-09-01T12:00:00"  # same instant, no offset
    restored = publisher_from_json(json.dumps(payload))

    assert restored.registered_at.tzinfo is UTC
    assert restored == publisher
