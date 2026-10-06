"""The out-of-tree reference gallery proves the external extension lifecycle (#980, M9-J2).

These tests are the repository-side half of the issue's acceptance. The
gallery (``extensions/reference-gallery/``) is a third-party-shaped,
multi-family extension repository; here it is driven through the platform's
real machinery end to end:

1. **publish** — ``tools/publish.py`` builds every package, binds each
   manifest to its built artifact, and signs the canonical install payload
   with the publisher's Ed25519 key (byte-deterministically);
2. **resolve** — ``maistro.extensions.resolve_lock`` turns root requests
   against the published catalog into a reproducible lock, pulling the
   connector in through the skill's declared dependency;
3. **materialize** — ``materialize_lock`` records every locked identity
   through the durable install store, with digest + signature verification
   and minted trust evidence;
4. **activate** — ``ExtensionInstallService`` runs inspect → authorize →
   install per family, the loader (the only code-execution seam) importing
   the entrypoint from the installed *wheel bytes*, never an editable path;
5. **execute** — the provider-adapter family registers through
   ``register_adapter_models`` and passes ``run_adapter_conformance``, the
   canonical ADR-104 seams; the other families' loaded handlers are invoked.

Nothing here imports the gallery's packages from their source trees: the
code that runs is loaded from the published wheels, which is the property
"packages install through the catalog/registry lifecycle rather than
editable source paths" demands.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from maistro.capabilities.provider_adapters import (
    ProviderAdapterCatalog,
    ProviderAdapterSpec,
    register_adapter_models,
    run_adapter_conformance,
)
from maistro.extensions import (
    ExtensionManifest,
    InMemoryExtensionStore,
    PackageDigestMismatch,
    TrustPolicy,
    inspect_manifest,
    resolve_lock,
)
from maistro.extensions.resolution import (
    CatalogEntry,
    ExtensionCatalog,
    ExtensionDependency,
    LockArtifacts,
    LockState,
    MissingLockArtifacts,
    RootRequest,
    materialize_lock,
)
from maistro.extensions.service import (
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.types import (
    ExtensionPackage,
    ExtensionScope,
    PackageIdentity,
    PublisherIdentity,
    TrustClaim,
    canonical_install_payload,
    identity_key,
    sha256_hex,
)
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import RoutingTask

ROOT = Path(__file__).resolve().parent.parent
GALLERY = ROOT / "extensions" / "reference-gallery"
PUBLISH_TOOL = GALLERY / "tools" / "publish.py"
GALLERY_POLICY = GALLERY / "namespace-policy.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

PUBLISHER_ID = "gallery"
SCOPE = ExtensionScope(org_id="org-reference", workspace_id="ws-gallery")
EXPECTED_FAMILIES = (
    "gallery.weather_connector",
    "gallery.unit_skill",
    "gallery.model_adapter",
    "gallery.renderer_pack",
)


def _load_publish_tool() -> Any:
    """Import the gallery's publish tool as a module, for its canonical
    serialization helpers. The test digests exactly what the tool digests."""
    spec = importlib.util.spec_from_file_location("gallery_publish_tool", PUBLISH_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLISH = _load_publish_tool()


@dataclass(frozen=True)
class PublishedEntry:
    """One catalog entry plus its artifact bytes, ready for the platform."""

    identity: PackageIdentity
    publisher_id: str
    signature: str
    manifest_bytes: bytes
    package_bytes: bytes
    manifest: ExtensionManifest
    dependencies: tuple[ExtensionDependency, ...]


@dataclass(frozen=True)
class PublishedGallery:
    """The output of one publish run: the catalog snapshot and its bytes."""

    out_dir: Path
    catalog: dict[str, Any]
    snapshot_sha256: str
    entries: dict[str, PublishedEntry]

    @property
    def signing_public_key(self) -> str:
        return str(self.catalog["signing_public_key"])


def _parse_catalog(out_dir: Path) -> PublishedGallery:
    catalog = json.loads((out_dir / "catalog.json").read_text(encoding="utf-8"))
    snapshot = {key: value for key, value in catalog.items() if key != "catalog_snapshot_sha256"}
    snapshot_sha256 = sha256_hex(PUBLISH.canonical_json(snapshot))
    assert snapshot_sha256 == catalog["catalog_snapshot_sha256"], (
        "the catalog's snapshot digest must cover exactly the entries it ships"
    )
    entries: dict[str, PublishedEntry] = {}
    for raw in catalog["entries"]:
        manifest_bytes = str(raw["manifest_bytes"]).encode("utf-8")
        identity = PackageIdentity(
            extension_name=str(raw["identity"]["extension_name"]),
            semantic_version=str(raw["identity"]["semantic_version"]),
            package_sha256=str(raw["identity"]["package_sha256"]),
            manifest_sha256=str(raw["identity"]["manifest_sha256"]),
        )
        entries[identity.extension_name] = PublishedEntry(
            identity=identity,
            publisher_id=str(raw["publisher_id"]),
            signature=str(raw["signature"]),
            manifest_bytes=manifest_bytes,
            package_bytes=(out_dir / str(raw["artifact_file"])).read_bytes(),
            manifest=inspect_manifest(manifest_bytes),
            dependencies=tuple(
                ExtensionDependency(
                    target=str(dep["target"]),
                    range_text=str(dep["range_text"]),
                    required=bool(dep["required"]),
                )
                for dep in raw["dependencies"]
            ),
        )
    return PublishedGallery(
        out_dir=out_dir,
        catalog=catalog,
        snapshot_sha256=snapshot_sha256,
        entries=entries,
    )


@pytest.fixture(scope="module")
def gallery(tmp_path_factory: pytest.TempPathFactory) -> PublishedGallery:
    """One real publish run over the gallery sources."""
    out_dir = tmp_path_factory.mktemp("gallery-publish")
    result = subprocess.run(
        (sys.executable, str(PUBLISH_TOOL), "--out-dir", str(out_dir)),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, f"publish failed:\n{result.stdout}\n{result.stderr}"
    return _parse_catalog(out_dir)


def _gallery_publisher(key_hex: str, registered_at: Any) -> PublisherIdentity:
    """The registered publisher identity the install verification trusts."""
    return PublisherIdentity(
        publisher_id=PUBLISHER_ID,
        display_name="Reference gallery publisher (fixture)",
        signing_key_fingerprint=hashlib.sha256(bytes.fromhex(key_hex)).hexdigest(),
        signing_public_key=key_hex,
        registered_at=registered_at,
    )


# ---------------------------------------------------------------------------
# The publish workflow: artifact binding, signing, determinism
# ---------------------------------------------------------------------------


def test_publish_is_byte_deterministic(gallery: PublishedGallery, tmp_path: Path) -> None:
    """Same sources, byte-identical catalog: a publisher (and this repo's CI)
    can reproduce the snapshot exactly, which is what makes the lock and the
    audit trail comparable across runs."""
    second = tmp_path / "again"
    result = subprocess.run(
        (sys.executable, str(PUBLISH_TOOL), "--out-dir", str(second)),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (second / "catalog.json").read_bytes() == (gallery.out_dir / "catalog.json").read_bytes()


def test_the_gallery_spans_the_extension_families(gallery: PublishedGallery) -> None:
    """The issue's family coverage: a provider adapter, a connector/tool, a
    skill, and a UI pack — each an independently installable package, each
    with the authority posture its family needs and no more."""
    assert sorted(gallery.entries) == sorted(EXPECTED_FAMILIES)
    posture = {
        "gallery.weather_connector": (
            {"network.outbound", "tool.invoke"},
            [],
        ),
        "gallery.unit_skill": (
            {"workspace.read"},
            ["gallery.weather_connector"],
        ),
        "gallery.model_adapter": (
            {"network.outbound"},
            [],
        ),
        "gallery.renderer_pack": (
            {"workspace.read"},
            [],
        ),
    }
    for name, (permissions, dependency_targets) in posture.items():
        entry = gallery.entries[name]
        assert set(entry.manifest.permissions) == permissions, name
        assert sorted(dep.target for dep in entry.dependencies) == dependency_targets, name


def test_catalog_artifact_claims_describe_the_built_wheels(
    gallery: PublishedGallery,
) -> None:
    """Every manifest's artifact claim names its wheel's exact bytes — the
    binding the platform verifies before anything else."""
    for entry in gallery.entries.values():
        digest = sha256_hex(entry.package_bytes)
        assert digest == entry.identity.package_sha256
        assert entry.manifest.artifact_sha256 == digest
        assert entry.manifest.artifact_size == len(entry.package_bytes)
        # The signature covers the exact manifest bytes the catalog serves.
        assert sha256_hex(entry.manifest_bytes) == entry.identity.manifest_sha256


def test_signatures_verify_against_the_registered_publisher_key(
    gallery: PublishedGallery,
) -> None:
    """The Ed25519 signature over the canonical install payload verifies with
    the committed publisher key — the same check the install store runs."""
    committed_key = (
        (GALLERY / "keys" / "reference-publisher.pub").read_text(encoding="utf-8").strip()
    )
    assert gallery.signing_public_key == committed_key, (
        "the catalog must be signed by the key the repository publishes"
    )
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(committed_key))
    for entry in gallery.entries.values():
        payload = canonical_install_payload(entry.identity)
        public_key.verify(bytes.fromhex(entry.signature), payload)


def test_catalog_manifests_pass_the_platform_inspector(
    gallery: PublishedGallery,
) -> None:
    """The published documents are the platform envelope, executable proof —
    every field ``inspect_manifest`` validates, validated."""
    for name, entry in gallery.entries.items():
        manifest = inspect_manifest(entry.manifest_bytes)
        assert manifest.extension_id == name
        assert manifest.publisher == PUBLISHER_ID
        assert manifest.api_version == "1.0.0"
        assert manifest.entry_points, "a catalog manifest must name its entry point"


# ---------------------------------------------------------------------------
# Resolution: the reproducible lock over the catalog snapshot
# ---------------------------------------------------------------------------


def _catalog_snapshot(gallery: PublishedGallery) -> ExtensionCatalog:
    """The published catalog, as the platform's resolution consumes it."""
    return ExtensionCatalog(
        entries=tuple(
            CatalogEntry(
                identity=entry.identity,
                source="reference-gallery:catalog",
                catalog_snapshot_sha256=gallery.snapshot_sha256,
                publisher_id=entry.publisher_id,
                signature=entry.signature,
                dependencies=entry.dependencies,
            )
            for entry in gallery.entries.values()
        )
    )


def test_resolution_locks_the_whole_gallery_deterministically(
    gallery: PublishedGallery,
) -> None:
    """One lock over four root requests: byte-identical across runs, stable
    digest, every family pinned with its full identity."""
    snapshot = _catalog_snapshot(gallery)
    requests = [RootRequest(extension_name=name) for name in EXPECTED_FAMILIES]
    first = resolve_lock(requests, snapshot)
    second = resolve_lock(requests, snapshot)
    assert isinstance(first, LockState)
    assert first.to_json() == second.to_json()
    assert first.lock_digest() == second.lock_digest()
    assert sorted(entry.extension_name for entry in first.entries) == sorted(EXPECTED_FAMILIES)
    for entry in first.entries:
        assert entry.catalog_snapshot_sha256 == gallery.snapshot_sha256
        assert entry.package_sha256 == gallery.entries[entry.extension_name].identity.package_sha256


def test_dependency_resolution_pulls_the_connector_in_for_the_skill(
    gallery: PublishedGallery,
) -> None:
    """Requesting only the skill yields two locked extensions: the skill and
    the connector its manifest depends on — with the connector's `required_by`
    naming the skill, not just the root request."""
    lock = resolve_lock(
        [RootRequest(extension_name="gallery.unit_skill")],
        _catalog_snapshot(gallery),
    )
    assert sorted(entry.extension_name for entry in lock.entries) == [
        "gallery.unit_skill",
        "gallery.weather_connector",
    ]
    connector = lock.get("gallery.weather_connector")
    assert connector is not None
    assert "gallery.unit_skill" in connector.required_by


# ---------------------------------------------------------------------------
# Materialization: durable, verified install records through the real store
# ---------------------------------------------------------------------------


class GalleryFetcher:
    """Serves each locked entry's bytes from the published snapshot."""

    def __init__(self, gallery: PublishedGallery) -> None:
        self._artifacts = {
            entry.identity: LockArtifacts(
                package_bytes=entry.package_bytes,
                manifest_body=entry.manifest_bytes.decode("utf-8"),
            )
            for entry in gallery.entries.values()
        }

    async def fetch_lock_artifact(self, entry: Any) -> LockArtifacts | None:
        return self._artifacts.get(entry.identity)


async def test_materialize_lock_records_durable_verified_installs(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """The lock recreates the exact extension set through the durable store:
    digest, signature, and publisher all verified, evidence minted per
    record, provenance naming this catalog snapshot."""
    lock = resolve_lock(
        [RootRequest(extension_name=name) for name in EXPECTED_FAMILIES],
        _catalog_snapshot(gallery),
    )
    db_path = tmp_path / "installs.sqlite"
    async with aiosqlite.connect(db_path) as conn:
        store = SqliteExtensionInstallStore(conn)
        await store.ensure_schema()
        await store.register_publisher(
            _gallery_publisher(gallery.signing_public_key, _utc(2026, 10, 6))
        )
        records = await materialize_lock(lock, store, GalleryFetcher(gallery))
        assert len(records) == len(EXPECTED_FAMILIES)
        for record in records:
            assert record.evidence.verified is True
            assert record.publisher.publisher_id == PUBLISHER_ID
            assert record.provenance.catalog_snapshot_sha256 == gallery.snapshot_sha256
        # Re-materializing the same lock is an idempotent re-record: the same
        # identities, no duplicates, nothing re-verified into new rows.
        again = await materialize_lock(lock, store, GalleryFetcher(gallery))
        assert {identity_key(r.identity) for r in again} == {
            identity_key(r.identity) for r in records
        }
        stored = [
            record for name in EXPECTED_FAMILIES for record in await store.install_history(name)
        ]
        assert len(stored) == len(EXPECTED_FAMILIES)


async def test_a_tampered_artifact_fails_closed_before_any_record(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """One flipped byte in one wheel: the batch install refuses, nothing is
    recorded, nothing is activated — a corrupt artifact never happened."""
    lock = resolve_lock(
        [RootRequest(extension_name=name) for name in EXPECTED_FAMILIES],
        _catalog_snapshot(gallery),
    )

    class TamperedFetcher(GalleryFetcher):
        async def fetch_lock_artifact(self, entry: Any) -> LockArtifacts | None:
            artifacts = await super().fetch_lock_artifact(entry)
            assert artifacts is not None
            if entry.extension_name == "gallery.unit_skill":
                flipped = bytes(artifacts.package_bytes[:-1]) + bytes(
                    [artifacts.package_bytes[-1] ^ 0x01]
                )
                artifacts = LockArtifacts(
                    package_bytes=flipped, manifest_body=artifacts.manifest_body
                )
            return artifacts

    db_path = tmp_path / "installs.sqlite"
    async with aiosqlite.connect(db_path) as conn:
        store = SqliteExtensionInstallStore(conn)
        await store.ensure_schema()
        await store.register_publisher(
            _gallery_publisher(gallery.signing_public_key, _utc(2026, 10, 6))
        )
        with pytest.raises((PackageDigestMismatch, MissingLockArtifacts)):
            await materialize_lock(lock, store, TamperedFetcher(gallery))
        stored = [
            record for name in EXPECTED_FAMILIES for record in await store.install_history(name)
        ]
        assert stored == []


# ---------------------------------------------------------------------------
# Activation: inspect -> authorize -> install, code only after authorization
# ---------------------------------------------------------------------------


class WheelEntrypointLoader:
    """The host loader: unpacks the installed wheel and imports its
    entrypoint — the platform's only code-execution seam, reachable only
    after authorization. Every module it loads is remembered so the
    families' handlers can be invoked from the *installed* code."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, str]] = []
        self.modules: dict[str, Any] = {}

    async def load(self, record: Any, payload: bytes) -> LoadedExtension:
        self.calls.append((record.extension_id, record.version))
        target = self.root / f"{record.extension_id}-{record.version}"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as wheel:
            wheel.extractall(target)
        (entry_point,) = json.loads(record.manifest.raw)["entry_points"]
        module_name = str(entry_point["module"])
        sys.path.insert(0, str(target))
        try:
            sys.modules.pop(module_name, None)
            module = import_module(module_name)
        finally:
            sys.path.remove(str(target))
        plugin = getattr(module, str(entry_point["attribute"]))
        assert plugin["name"] == record.extension_id, (
            "the loaded entrypoint must identify as the record's extension"
        )
        assert plugin["version"] == record.version
        self.modules[record.extension_id] = module
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


def _utc(year: int, month: int, day: int) -> Any:
    from datetime import UTC, datetime

    return datetime(year, month, day, tzinfo=UTC)


def _maistro_modules_imported(before: frozenset[str]) -> set[str]:
    """Product modules that appeared in ``sys.modules`` since ``before``."""
    return {m for m in set(sys.modules) - before if m == "maistro" or m.startswith("maistro.")}


async def _activate(
    gallery: PublishedGallery,
    loader: WheelEntrypointLoader,
    root_modules_before: frozenset[str],
) -> dict[str, Any]:
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=loader,
        trust_policy=TrustPolicy(
            trusted_publishers=frozenset({PUBLISHER_ID}),
            require_signature=True,
            allowed_signer_keys=frozenset(
                {hashlib.sha256(bytes.fromhex(gallery.signing_public_key)).hexdigest()}
            ),
        ),
        platform_api_version="1.0.0",
    )
    records: dict[str, Any] = {}
    for name in EXPECTED_FAMILIES:
        entry = gallery.entries[name]
        inspected = await service.inspect(
            actor="operator:reference",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=entry.manifest_bytes, payload=entry.package_bytes
            ),
            trust_evidence=TrustClaim(
                publisher_id=PUBLISHER_ID,
                signature_present=True,
                signer_key_id=hashlib.sha256(bytes.fromhex(gallery.signing_public_key)).hexdigest(),
                package_sha256=entry.identity.package_sha256,
            ),
        )
        # No code has run for this extension yet: inspection and
        # authorization are pure evaluation over bytes, and no product
        # module has been imported by anyone.
        assert loader.modules.get(name) is None
        assert not _maistro_modules_imported(root_modules_before)
        assert inspected.state.value == "awaiting_authorization"
        authorized = await service.authorize(
            inspected.install_id,
            actor="operator:reference",
            scope=SCOPE,
            approve=True,
            reason=f"reference gallery acceptance ({name})",
        )
        assert authorized.granted_permissions == authorized.requested_permissions
        active = await service.install(
            inspected.install_id,
            actor="operator:reference",
            scope=SCOPE,
            payload=entry.package_bytes,
        )
        assert active.state.value == "active"
        assert await service.active(SCOPE, name) is not None
        records[name] = active
    return records


async def test_activation_runs_each_family_through_the_governed_lifecycle(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """All four families inspect → authorize → install → ACTIVE, and no
    product-private module is ever imported: the only new modules the
    activation introduces are the gallery's own."""
    loader = WheelEntrypointLoader(tmp_path / "installs")
    before = frozenset(sys.modules)
    records = await _activate(gallery, loader, before)
    assert sorted(records) == sorted(EXPECTED_FAMILIES)
    imported = _maistro_modules_imported(before)
    assert imported == set(), f"activation imported product modules: {sorted(imported)}"
    # The loaded code is the installed artifact's, invoked through the
    # canonical seam: each family's handler runs from the loader's module.
    connector = loader.modules["gallery.weather_connector"]
    assert (
        connector.HANDLERS["current_forecast_brief"](
            "Lisbon", {"summary": "sunny", "high_c": 28, "low_c": 17}
        )
        == "Lisbon: sunny, high 28°C, low 17°C"
    )
    skill = loader.modules["gallery.unit_skill"]
    assert skill.convert_report_units({"high_c": 28}) == {"high_f": 82.4}
    renderer = loader.modules["gallery.renderer_pack"]
    assert renderer.render_run_summary({"name": "r", "state": "succeeded"}) == (
        "Run 'r' — succeeded"
    )


async def test_inspection_rejects_a_tampered_payload_before_any_code_runs(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """A wheel that does not digest to its manifest's artifact claim is
    rejected at inspection; the loader is never reached."""
    loader = WheelEntrypointLoader(tmp_path / "tampered")
    entry = gallery.entries["gallery.renderer_pack"]
    tampered = bytes(entry.package_bytes[:-1]) + bytes([entry.package_bytes[-1] ^ 0xFF])
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=loader,
        trust_policy=TrustPolicy(trusted_publishers=frozenset({PUBLISHER_ID})),
        platform_api_version="1.0.0",
    )
    record = await service.inspect(
        actor="operator:reference",
        scope=SCOPE,
        package=ExtensionPackage(manifest_bytes=entry.manifest_bytes, payload=tampered),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER_ID,
            signature_present=True,
            signer_key_id=hashlib.sha256(bytes.fromhex(gallery.signing_public_key)).hexdigest(),
            package_sha256=sha256_hex(tampered),
        ),
    )
    assert record.state.value == "rejected"
    assert "artifact digest mismatch" in (record.failure_reason or "")
    assert loader.calls == [], "no extension code may run for a tampered artifact"


# ---------------------------------------------------------------------------
# Execution: the provider-adapter family through the canonical ADR-104 seams
# ---------------------------------------------------------------------------


class GalleryAdapter:
    """Host-side wrapper binding the installed adapter module to the
    ``ProviderAdapter`` protocol. The adapter's code is the wheel's; the
    spec is the adapter's own declaration, validated by the SDK here."""

    def __init__(self, spec: ProviderAdapterSpec, module: Any) -> None:
        self._spec = spec
        self._module = module

    @property
    def spec(self) -> ProviderAdapterSpec:
        return self._spec

    def normalize_request(self, model: str, request: Any) -> dict[str, object]:
        return self._module.normalize_request(model, request)

    def normalize_response(self, payload: Any) -> dict[str, object]:
        return self._module.normalize_response(payload)

    def usage_from(self, payload: Any) -> tuple[int, int] | None:
        return self._module.usage_from(payload)

    def error_kind_for(self, status: int) -> str:
        return self._module.error_kind_for(status)

    def health_from(self, payload: Any) -> bool:
        return self._module.health_from(payload)


def _installed_adapter_module(gallery: PublishedGallery, tmp_path: Path) -> Any:
    """Import the adapter's entrypoint from the published wheel — never from
    the source tree."""
    entry = gallery.entries["gallery.model_adapter"]
    target = tmp_path / "adapter-wheel"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(entry.package_bytes)) as wheel:
        wheel.extractall(target)
    sys.path.insert(0, str(target))
    try:
        sys.modules.pop("gallery_model_adapter.plugin", None)
        sys.modules.pop("gallery_model_adapter", None)
        return import_module("gallery_model_adapter.plugin")
    finally:
        sys.path.remove(str(target))


async def test_provider_adapter_registers_through_the_canonical_seam(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """The installed adapter passes the shared conformance suite and
    registers through ``register_adapter_models``: its models join canonical
    routing and the cost-aware router selects them like built-in ones."""
    from maistro.capabilities.provider_adapters import AdapterCapabilities, AdapterModelSpec

    module = _installed_adapter_module(gallery, tmp_path)
    spec = ProviderAdapterSpec(**module.SPEC)
    adapter = GalleryAdapter(spec, module)

    report = run_adapter_conformance(adapter)
    failures = [check for check in report.checks if not check.passed]
    assert failures == [], f"conformance failures: {failures}"

    registry = InMemoryProviderRegistry()
    catalog = ProviderAdapterCatalog()
    metadata = await register_adapter_models(catalog, registry, adapter)
    assert {m.name for m in metadata} == {"gallery-chat-fast", "gallery-chat-balanced"}
    for model in metadata:
        stored = await registry.get_model(model.name)
        assert stored.provider == "gallery-model-adapter"

    router = CostAwareRouter(registry)
    selected = await router.select(RoutingTask(task_type="general"))
    assert selected.name == "gallery-chat-fast", (
        "the router must select adapter models under the canonical policy"
    )
    # The registered catalog resolves the model to the adapter for transport.
    assert catalog.resolve_provider("gallery-chat-fast", None) is not None
    assert catalog.registered_ids() == ("gallery-model-adapter",)

    # Model-level capability flags narrow the adapter's declaration.
    assert spec.capabilities == AdapterCapabilities(tools=True)
    assert spec.models[0].capabilities.tools is True
    assert isinstance(spec.models[1], AdapterModelSpec)


async def test_a_lying_adapter_is_refused_at_registration(
    gallery: PublishedGallery, tmp_path: Path
) -> None:
    """Reclassifying HTTP 500 as permanent would contradict canonical retry
    policy: conformance must fail the check and registration must refuse."""
    from maistro.capabilities.provider_adapters import AdapterRegistrationError

    module = _installed_adapter_module(gallery, tmp_path)
    spec = ProviderAdapterSpec(**module.SPEC)

    class LyingAdapter(GalleryAdapter):
        def error_kind_for(self, status: int) -> str:
            if status >= 500:
                return "permanent"
            return super().error_kind_for(status)

    adapter = LyingAdapter(spec, module)
    report = run_adapter_conformance(adapter)
    failing = [check.name for check in report.checks if not check.passed]
    assert "error_taxonomy" in failing
    catalog = ProviderAdapterCatalog()
    with pytest.raises(AdapterRegistrationError):
        catalog.register(adapter)


# ---------------------------------------------------------------------------
# CI + gates: the reusable M9 conformance tooling runs against the gallery
# ---------------------------------------------------------------------------


def test_ci_runs_the_reusable_gates_against_the_gallery_policy() -> None:
    """CI's lint-and-type-check job runs both extension gates with the
    gallery's own policy — the same reusable tooling, one more repository."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["lint-and-type-check"]["steps"]
    runs = [str(step.get("run", "")) for step in steps if isinstance(step, dict)]
    policy = "extensions/reference-gallery/namespace-policy.json"
    assert any("check-extension-imports.py" in run and policy in run for run in runs), (
        "CI must run the import gate against the gallery policy"
    )
    assert any("check-reference-extension.py" in run and policy in run for run in runs), (
        "CI must run the isolation fixture against the gallery policy"
    )


def test_the_import_gate_passes_over_the_real_gallery_tree() -> None:
    """The gate, run exactly as CI runs it, accepts every gallery package."""
    result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts" / "check-extension-imports.py"),
            "--policy",
            str(GALLERY_POLICY),
        ),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 extension package(s)" in result.stdout
