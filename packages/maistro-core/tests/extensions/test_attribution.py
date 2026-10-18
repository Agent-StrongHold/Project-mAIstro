"""Extension attribution evidence (M9-I1, #976).

Acceptance coverage, each test naming the criterion it pins:

- **exact identity**: an effect's attribution names extension, strict-semver
  version, publisher, and both digests, joined to the install record the
  identity came from — the same four-field identity key install records use;
- **canonical linkage**: attribution from a governed install carries the
  canonical org/Workspace scope; evidence joins the caller, it does not
  replace it;
- **survives hops**: the payload is plain JSON that round-trips through an
  asynchronous delegation's metadata and decodes equal on the other side;
- **no parallel correlation identity**: an extension identity cannot join the
  canonical correlation namespace (the context refuses it) and an Event's
  correlation fields are untouched by stamped attribution — provenance only;
- **historical readability**: a stored payload decodes with no registry, no
  store, and no extension present, including after the "active" version has
  moved on; foreign format versions refuse loudly instead of guessing;
- **no secrets**: the field set is closed — an attribution built from
  manifest bytes containing secret-shaped fields carries none of them, and
  the canonical envelope's redaction scrubs what a caller tries to smuggle
  through the provenance fragment anyway.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from maistro.extensions import (
    ATTRIBUTION_FORMAT,
    ExtensionAttribution,
    InvalidAttribution,
    attribution_from_payload,
    attribution_identity_key,
)
from maistro.extensions.types import sha256_hex

from .extension_fixtures import CATALOG_URL, MANIFEST_BODY, install_bundle


def _attribution(**overrides: object) -> ExtensionAttribution:
    values: dict[str, object] = {
        "extension_id": "acme.chart_tools",
        "version": "1.4.0",
        "publisher": "acme",
        "package_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
    }
    values.update(overrides)
    return ExtensionAttribution(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Exact identity: attribution == the install record's PackageIdentity
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
@pytest.mark.ac("#976/AC-1")
async def test_attribution_from_install_record_names_the_exact_identity() -> None:
    bundle = install_bundle(name="ext-tool", version="1.0.0")
    from maistro.extensions.store import InMemoryExtensionInstallStore

    store = InMemoryExtensionInstallStore()
    await store.register_publisher(bundle["publisher"])
    record = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    attribution = ExtensionAttribution.from_install_record(
        record, org_id="org-1", workspace_id="ws-1"
    )

    assert attribution.extension_id == "ext-tool"
    assert attribution.version == "1.0.0"
    assert attribution.publisher == "pub-1"
    # the digests are the record's digests, not re-derived from anything mutable
    assert attribution.package_sha256 == record.identity.package_sha256
    assert attribution.manifest_sha256 == record.identity.manifest_sha256
    assert attribution.install_id == record.install_id
    assert attribution.catalog_url == CATALOG_URL
    # the attribution joins the install record's identity: same identity key
    assert attribution_identity_key(attribution) == (
        record.identity.extension_name,
        record.identity.semantic_version,
        record.identity.package_sha256,
        record.identity.manifest_sha256,
    )


@pytest.mark.contract("boundary")
@pytest.mark.ac("#976/AC-1")
async def test_attribution_from_governed_install_carries_canonical_scope() -> None:
    """The B2 governed install links identity to its authorization scope."""

    from hashlib import sha256

    from maistro.extensions.types import (
        ExtensionInstallRecord,
        ExtensionManifest,
        ExtensionState,
    )

    payload = b"installed-payload"
    manifest_raw = json.dumps(
        {
            "manifest_version": 1,
            "id": "acme.chart_tools",
            "name": "Chart Tools",
            "version": "1.4.0",
            "publisher": "acme",
            "api_version": "1.0.0",
            "permissions": ["network.http"],
            "entry_points": [
                {"name": "main", "module": "acme_chart.main", "attribute": "activate"}
            ],
            "artifact": {"sha256": sha256(payload).hexdigest(), "size": len(payload)},
        }
    ).encode()
    manifest = ExtensionManifest(
        manifest_version=1,
        extension_id="acme.chart_tools",
        name="Chart Tools",
        version="1.4.0",
        publisher="acme",
        api_version="1.0.0",
        permissions=("network.http",),
        entry_points=(),
        dependencies=(),
        artifact_sha256=sha256(payload).hexdigest(),
        artifact_size=len(payload),
        source_sha256=sha256_hex(manifest_raw),
        raw=manifest_raw,
    )
    record = ExtensionInstallRecord(
        install_id="install-1",
        org_id="org-1",
        workspace_id="ws-1",
        extension_id="acme.chart_tools",
        version="1.4.0",
        manifest=manifest,
        state=ExtensionState.ACTIVE,
        requested_permissions=("network.http",),
        granted_permissions=("network.http",),
        artifact_sha256=sha256(payload).hexdigest(),
    )

    attribution = ExtensionAttribution.from_governed_install(record)

    assert attribution.extension_id == "acme.chart_tools"
    assert attribution.version == "1.4.0"
    assert attribution.publisher == "acme"
    assert attribution.package_sha256 == sha256(payload).hexdigest()
    assert attribution.manifest_sha256 == manifest.source_sha256
    # canonical caller linkage: the scope that authorized the install
    assert attribution.org_id == "org-1"
    assert attribution.workspace_id == "ws-1"


@pytest.mark.ac("#976/AC-1")
async def test_attribution_refuses_an_uninstalled_governed_record() -> None:
    """A record with no installed artifact digest names no exact package."""

    import hashlib

    from maistro.extensions.types import (
        ExtensionInstallRecord,
        ExtensionManifest,
        ExtensionState,
    )

    manifest = ExtensionManifest(
        manifest_version=1,
        extension_id="acme.chart_tools",
        name="Chart Tools",
        version="1.4.0",
        publisher="acme",
        api_version="1.0.0",
        permissions=(),
        entry_points=(),
        dependencies=(),
        artifact_sha256=hashlib.sha256(b"x").hexdigest(),
        artifact_size=1,
        source_sha256=hashlib.sha256(b"m").hexdigest(),
        raw=b"{}",
    )
    record = ExtensionInstallRecord(
        install_id="install-2",
        org_id="org-1",
        workspace_id="",
        extension_id="acme.chart_tools",
        version="1.4.0",
        manifest=manifest,
        state=ExtensionState.AWAITING_AUTHORIZATION,
        requested_permissions=(),
    )

    with pytest.raises(InvalidAttribution, match="no installed artifact digest"):
        ExtensionAttribution.from_governed_install(record)


# ---------------------------------------------------------------------------
# Identity is exact: validation refuses weak or malformed attributions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"extension_id": ""},
        {"version": ""},
        {"publisher": ""},
        {"package_sha256": ""},
        {"manifest_sha256": ""},
        {"version": "1.0"},  # strict MAJOR.MINOR.PATCH only, like install records
        {"version": "v1.0.0"},
        {"package_sha256": "not-a-digest"},
        {"manifest_sha256": "A" * 64},  # uppercase is not the digest form records use
    ],
)
def test_attribution_refuses_partial_or_malformed_identity(override: dict[str, str]) -> None:
    values = {
        "extension_id": "x.y",
        "version": "1.0.0",
        "publisher": "p",
        "package_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        **override,
    }
    with pytest.raises(InvalidAttribution):
        ExtensionAttribution(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Durable round-trip and historical readability
# ---------------------------------------------------------------------------


def test_payload_round_trips_equal() -> None:
    attribution = _attribution(install_id="install-1", org_id="org-1", workspace_id="ws-1")

    payload = attribution.to_payload()
    assert payload["format"] == ATTRIBUTION_FORMAT
    assert all(isinstance(value, str) for value in payload.values())
    assert attribution_from_payload(payload) == attribution
    assert ExtensionAttribution.from_json(attribution.to_json()) == attribution


@pytest.mark.ac("#976/AC-4")
def test_historical_payload_decodes_without_registry_store_or_extension() -> None:
    """Old evidence stays readable after the extension is gone.

    The payload below was written when ``acme.chart_tools`` 1.4.0 was active.
    Nothing in the decode path consults a store, a registry, or an installed
    package — the decode is pure validation — so the evidence of what ran
    survives removal, upgrade, and publisher key rotation alike.
    """

    historical = {
        "format": "extension-attribution:v1",
        "extension_id": "acme.chart_tools",
        "version": "1.4.0",
        "publisher": "acme",
        "package_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "install_id": "install-1",
        "org_id": "org-1",
        "workspace_id": "ws-1",
        "catalog_url": CATALOG_URL,
    }

    decoded = attribution_from_payload(historical)
    assert decoded == _attribution(
        install_id="install-1", org_id="org-1", workspace_id="ws-1", catalog_url=CATALOG_URL
    )
    # and a "newer" active version elsewhere changes nothing about old evidence
    assert decoded.version == "1.4.0"


@pytest.mark.ac("#976/AC-4")
def test_unknown_format_version_refuses_loudly() -> None:
    payload = _attribution().to_payload()
    payload["format"] = "extension-attribution:v999"

    with pytest.raises(InvalidAttribution, match="cannot interpret"):
        attribution_from_payload(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("publisher"),
        lambda p: p.pop("format"),
        lambda p: p.update(extra_key="1"),  # a future format narrowed by this decoder
        lambda p: p.update(version=1.4),  # non-string value
        lambda p: p.update(package_sha256="zz"),
    ],
)
def test_decode_fails_closed_on_corruption(mutate: Callable[[dict[str, object]], None]) -> None:
    payload = _attribution().to_payload()
    mutate(payload)
    with pytest.raises(InvalidAttribution):
        attribution_from_payload(payload)


def test_decode_refuses_non_object_payloads() -> None:
    with pytest.raises(InvalidAttribution, match="JSON object"):
        attribution_from_payload(["not", "an", "object"])
    with pytest.raises(InvalidAttribution, match="not JSON"):
        ExtensionAttribution.from_json("{nope")


# ---------------------------------------------------------------------------
# No parallel correlation identity
# ---------------------------------------------------------------------------


@pytest.mark.ac("#976/AC-3")
def test_extension_identity_cannot_join_the_correlation_namespace() -> None:
    """Canonical correlation ids are a closed vocabulary; attribution rides
    beside them, never in them."""

    from maistro.observability.correlation import FIELD_NAMES, bind_execution_context

    assert not any(name.startswith("extension") for name in FIELD_NAMES)
    with (
        pytest.raises(ValueError, match="not correlation ids"),
        bind_execution_context(extension_id="acme.chart_tools"),
    ):
        pass  # pragma: no cover - never reached


@pytest.mark.ac("#976/AC-3")
def test_stamped_event_keeps_canonical_correlation_and_uses_provenance() -> None:
    """Attribution on an Event lives in provenance; correlation is untouched."""

    from maistro.events.envelope import EventEnvelope

    attribution = _attribution()
    envelope = EventEnvelope(
        type="extension.effect.recorded",
        payload={"effect": "model.chat"},
        workspace_id="ws-1",
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="a-1",
        invocation_id="inv-1",
        provenance=attribution.provenance_payload(),
    )

    # canonical correlation fields carry the canonical ids, exactly as before
    assert envelope.run_id == "run-1"
    assert envelope.invocation_id == "inv-1"
    assert envelope.correlation_id == ""
    # the extension identity is provenance, keyed under the fixed fragment
    assert envelope.provenance["extension"] == attribution.to_payload()


# ---------------------------------------------------------------------------
# No secrets
# ---------------------------------------------------------------------------


@pytest.mark.ac("#976/AC-5")
async def test_attribution_from_record_carries_no_manifest_content_or_secrets() -> None:
    """The manifest body may contain anything; attribution copies identity only."""

    manifest_with_secret_shaped_lines = MANIFEST_BODY + "api_key: should-not-leak\n"
    bundle = install_bundle(manifest_body=manifest_with_secret_shaped_lines)
    from maistro.extensions.store import InMemoryExtensionInstallStore

    store = InMemoryExtensionInstallStore()
    await store.register_publisher(bundle["publisher"])
    record = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    attribution = ExtensionAttribution.from_install_record(record)

    assert set(attribution.to_payload()) == {
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
    }
    flat = json.dumps(attribution.to_payload()) + json.dumps(attribution.to_log_fields())
    assert "should-not-leak" not in flat


@pytest.mark.ac("#976/AC-5")
def test_provenance_fragment_is_redacted_by_the_canonical_envelope() -> None:
    """Even a hostile value in the identity fields cannot cross the envelope."""

    from maistro.events.envelope import EventEnvelope

    hostile = _attribution(publisher="Bearer sk-live-secret-token")
    envelope = EventEnvelope(
        type="extension.effect.recorded",
        workspace_id="ws-1",
        provenance=hostile.provenance_payload(),
    )

    published = envelope.provenance["extension"]["publisher"]
    assert published != "Bearer sk-live-secret-token"
    assert "sk-live-secret-token" not in json.dumps(envelope.provenance)


# ---------------------------------------------------------------------------
# Asynchronous delegation hops
# ---------------------------------------------------------------------------


@pytest.mark.ac("#976/AC-2")
async def test_attribution_survives_an_asynchronous_delegation_hop() -> None:
    """The payload rides delegation metadata and decodes equal on arrival."""

    from maistro.a2a.delegate import A2ADelegator, DelegationMode

    delegator = A2ADelegator()
    delegator.register_agent_capability("coordinator", can_delegate_to=["worker"])
    delegation_key = "hop-1"

    task_id = delegator.delegate_task(
        from_agent="coordinator",
        task="run chart tool",
        to_agent="worker",
        delegation_mode=DelegationMode.ALLOW_ALL,
        metadata={"extension": _attribution().to_payload(), "delegation_key": delegation_key},
    )

    # the hop is asynchronous: the task sits in the delegator's queue, and a
    # consumer on the other side reads the metadata cold
    stored = delegator.get_task_by_delegation_key(delegation_key)
    assert stored is not None
    assert stored.id == task_id
    decoded = attribution_from_payload(stored.metadata["extension"])
    assert decoded == _attribution()


# ---------------------------------------------------------------------------
# Adapter identity declaration (the live extension-mediated effect surface)
# ---------------------------------------------------------------------------


def _acme_spec(**overrides: object) -> object:
    from maistro.capabilities.provider_adapters import ProviderAdapterSpec

    values: dict[str, object] = {
        "adapter_id": "acme.models",
        "display_name": "Acme inference",
        "base_url": "https://api.acme.example/v1",
        "credential_provider": "acme",
        "credential_ref": "acme-primary",
        "models": (
            {
                "name": "acme-mini",
                "cost_per_1k_input": 0.1,
                "cost_per_1k_output": 0.4,
                "latency_p50_ms": 120,
                "tier": "fast",
            },
        ),
    }
    values.update(overrides)
    return ProviderAdapterSpec.model_validate(values)


@pytest.mark.ac("#976/AC-1")
def test_declared_adapter_identity_yields_canonical_attribution() -> None:
    spec = _acme_spec(
        version="2.3.1",
        publisher="acme",
        package_sha256="a" * 64,
        manifest_sha256="b" * 64,
    )
    attribution = spec.extension_attribution()  # type: ignore[attr-defined]
    assert attribution is not None
    assert attribution.describe() == (
        "acme.models 2.3.1 (publisher 'acme', package aaaaaaaaaaaa\u2026)"
    )


def test_undeclared_adapter_identity_yields_none() -> None:
    spec = _acme_spec()
    assert spec.extension_attribution() is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "override",
    [
        {"version": "2.3.1"},  # partial: version without the rest
        {"publisher": "acme"},
        {"package_sha256": "a" * 64},
        {
            "version": "not-semver",
            "publisher": "acme",
            "package_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        },
        {
            "version": "2.3.1",
            "publisher": "acme",
            "package_sha256": "short",
            "manifest_sha256": "b" * 64,
        },
    ],
)
def test_partial_or_malformed_adapter_identity_is_refused(override: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"identity|sha256|version"):
        _acme_spec(**override)


def test_declaring_adapter_passes_the_unchanged_conformance_suite() -> None:
    """A declaring adapter registers through the unchanged seam."""

    from maistro.capabilities.provider_adapters import ReferenceChatAdapter, run_adapter_conformance

    adapter = ReferenceChatAdapter(
        _acme_spec(
            version="1.0.0",
            publisher="acme",
            package_sha256="a" * 64,
            manifest_sha256="b" * 64,
        )
    )
    report = run_adapter_conformance(adapter)
    assert report.ok, report.failures


# ---------------------------------------------------------------------------
# Production emitters: activation logs and operator CLI carry the identity
# ---------------------------------------------------------------------------


@pytest.mark.ac("#976/AC-1")
async def test_governed_activation_logs_the_declared_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The one log line per activation names the exact installed package."""

    import logging

    from .test_install_lifecycle import (
        authorize_and_install,
        inspect_default,
        make_service,
    )

    service, _store, _loader, _clock = make_service()

    with caplog.at_level(logging.INFO, logger="maistro.extensions.service"):
        record = await inspect_default(service)
        installed = await authorize_and_install(service, record)

    attribution = ExtensionAttribution.from_governed_install(installed)
    records = [r for r in caplog.records if r.name == "maistro.extensions.service"]
    assert records, "activation must log one attribution line"
    line = records[-1]
    assert line.extension_id == "acme.chart_tools"  # type: ignore[attr-defined]
    assert line.extension_version == "1.4.0"  # type: ignore[attr-defined]
    assert line.extension_publisher == "acme"  # type: ignore[attr-defined]
    assert line.extension_install_id == installed.install_id  # type: ignore[attr-defined]
    assert line.extension_workspace_id == "ws-1"  # type: ignore[attr-defined]
    # identity only: no manifest body, no payload bytes in the line
    flat = line.getMessage() + str(line.__dict__)
    assert "extension-payload-v1" not in flat
    assert attribution.describe() in flat
