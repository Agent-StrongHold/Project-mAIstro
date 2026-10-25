"""Cross-family governed install of external-style packages (M9-E, #942).

The family suites (#961 providers, #963 connectors, #964 tools/Skills) prove
each family's SDK seams in isolation. This module pins the epic's own
acceptance criterion: **one external-style provider, connector and tool
package can be installed independently** — meaning each package travels the
one governed install path (``ExtensionInstallService`` inspect → authorize →
install) as artifact bytes, is loaded only from the installed artifact, and
registers through its family's canonical seam without any core edit:

* the provider package registers models into the canonical registry through
  ``register_adapter_models`` — the shared registration/conformance seam;
* the connector package passes the shared connector conformance suite and
  ingests through the host ``SyncEngine`` with full provenance;
* the tool package's contract is parsed from the *installed* bytes and its
  state-changing handler executes through the canonical Invocation seam.

Independence is pinned both ways: each package installs standalone with its
own install id, and one family's registration refusal (a conformance-failing
adapter) leaves the other families' installs intact and registering.

The artifact/manifest split mirrors production: the governed install envelope
(``manifest_version: 1``) authorizes exact artifact bytes; family authority
declarations (the contract document for the tool) travel *inside* the
digest-pinned artifact, so what the host classifies is exactly what was
authorized. Nothing here imports extension code from the source tree.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.provider_adapters import (
    AdapterRegistrationError,
    ProviderAdapterCatalog,
    ProviderAdapterSpec,
    ReferenceChatAdapter,
    reference_adapter_spec,
    register_adapter_models,
    run_adapter_conformance,
)
from maistro.connectors import (
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorInstance,
    ConnectorScopeError,
    ConnectorSession,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SourceItem,
    StaticSecretAuthority,
    SyncContext,
    SyncEngine,
    SyncPage,
    run_connector_conformance,
)
from maistro.extensions import (
    ExtensionInstallService,
    ExtensionLifecycleError,
    ExtensionPackage,
    ExtensionScope,
)
from maistro.extensions.service import LoadedExtension
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.tool_skill import (
    ExtensionContract,
    ExtensionToolCatalog,
    PermissionBeyondGrant,
    invoke_extension_tool,
)
from maistro.extensions.trust import TrustPolicy
from maistro.extensions.types import (
    ExtensionInstallRecord,
    ExtensionState,
    TrustClaim,
    sha256_hex,
)
from maistro.policy.types import Decision, PolicyVerdict
from maistro.providers.registry import InMemoryProviderRegistry

PUBLISHER_ID = "acme-labs"
ORG = "org-acme"
WORKSPACE = "ws-7"
OPERATOR = "operator:alice"

RUN_ID = "run-1"
NODE_RUN_ID = "node-1"
ATTEMPT_ID = "attempt-1"


async def _allow(binding: object, request: object, context: object) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(Decision.ALLOW, reason="epic proof allows", rule="epic.allow")


# ---------------------------------------------------------------------------
# The three external-style packages, as artifact bytes
# ---------------------------------------------------------------------------

PROVIDER_PLUGIN = '''"""acme.inference 1.0.0 entrypoint (installed artifact)."""

PLUGIN = {
    "kind": "capability-provider",
    "name": "acme.inference",
    "version": "1.0.0",
}


def build_adapter():
    """Build the adapter exactly as an out-of-tree provider package would."""
    from maistro.capabilities.provider_adapters import (
        ProviderAdapterSpec,
        ReferenceChatAdapter,
    )

    spec = ProviderAdapterSpec.model_validate(
        {
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
    )
    return ReferenceChatAdapter(spec)
'''

CONNECTOR_PLUGIN = '''"""acme.repo-feed 1.0.0 entrypoint (installed artifact)."""

from maistro.connectors import (
    ConnectorCapability,
    ConnectorDescriptor,
    SecretRef,
    SourceItem,
    SyncContext,
    SyncPage,
)

PLUGIN = {
    "kind": "connector",
    "name": "acme.repo_feed",
    "version": "1.0.0",
}

_DOCUMENTS = (
    ("doc-1", "installed connector document one"),
    ("doc-2", "installed connector document two"),
)


class RepoFeedConnector:
    """A LIST source that resolves its declared secret during listing."""

    def __init__(self) -> None:
        self._descriptor = ConnectorDescriptor(
            # Connector ids are the source-identity namespace ('vendor.feed');
            # the install envelope's extension id spells it repo_feed because
            # install ids allow underscores, not hyphens.
            connector_id="acme.repo-feed",
            version="1.0.0",
            capabilities=frozenset({ConnectorCapability.LIST}),
            secret_refs=(SecretRef(name="ACME_TOKEN", description="Acme feed token"),),
        )

    @property
    def descriptor(self) -> ConnectorDescriptor:
        return self._descriptor

    async def list_items(self, ctx: SyncContext) -> SyncPage:
        await ctx.session.resolve_secret("ACME_TOKEN")
        items = tuple(
            SourceItem(
                source_id="acme",
                external_id=external_id,
                content=content,
                version="v1",
            )
            for external_id, content in _DOCUMENTS
        )
        return SyncPage(items=items, next_cursor=None)


def build_connector():
    return RepoFeedConnector()
'''

TOOL_PLUGIN = '''"""acme-labs.notary 1.0.0 entrypoint (installed artifact)."""

PLUGIN = {
    "kind": "tool",
    "name": "acme-labs.notary",
    "version": "1.0.0",
    "capabilities": ["workspace.write"],
    "handler": "notarize",
}

_notarized: list[str] = []


async def notarize(document_id: str) -> dict:
    """A state-changing handler: records the document, reports the ledger."""
    _notarized.append(document_id)
    return {"notarized": list(_notarized), "count": len(_notarized)}
'''

#: The tool family's authority declaration, carried inside the artifact. The
#: host classifies from these exact bytes (pinned by the artifact digest).
TOOL_CONTRACT: dict[str, Any] = {
    "id": "acme-labs.notary",
    "publisher": "acme-labs",
    "version": "1.0.0",
    "title": "Acme notary",
    "description": "Records documents into an install-scoped notary ledger.",
    "contract": ">=1.0.0,<2.0.0",
    "family": "tool",
    "capabilities": ["workspace.write"],
    "effects": ["mutating"],
    "data": {"scopes": ["workspace"]},
    "entrypoint": {"module": "acme_notary.plugin", "object": "PLUGIN"},
}


@dataclass(frozen=True)
class FamilyPackageSpec:
    """One external-style package the scratch publisher offers."""

    extension_id: str
    version: str
    module_name: str
    plugin_source: str
    extra_entries: tuple[tuple[str, str], ...] = ()
    #: Authority the install envelope presents at inspect/authorize, derived
    #: from the family contract so the grant can never lag the declaration.
    permissions: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.extension_id}@{self.version}"


def _family_package_specs() -> dict[str, FamilyPackageSpec]:
    """The three family packages, keyed by ``id@version``."""
    specs = (
        FamilyPackageSpec(
            extension_id="acme.inference",
            version="1.0.0",
            module_name="acme_inference.plugin",
            plugin_source=PROVIDER_PLUGIN,
        ),
        FamilyPackageSpec(
            extension_id="acme.repo_feed",
            version="1.0.0",
            module_name="acme_repofeed.plugin",
            plugin_source=CONNECTOR_PLUGIN,
        ),
        FamilyPackageSpec(
            extension_id="acme.notary",
            version="1.0.0",
            module_name="acme_notary.plugin",
            plugin_source=TOOL_PLUGIN,
            extra_entries=(("extension.json", json.dumps(TOOL_CONTRACT, sort_keys=True)),),
            permissions=tuple(TOOL_CONTRACT["capabilities"]),
        ),
    )
    return {spec.key: spec for spec in specs}


def _artifact_zip(spec: FamilyPackageSpec) -> bytes:
    """The payload artifact: a zip carrying the module tree (+ contract doc)."""
    buffer = io.BytesIO()
    entries = [
        (spec.module_name.replace(".", "/") + ".py", spec.plugin_source),
        *spec.extra_entries,
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, text in entries:
            entry = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o600 << 16
            archive.writestr(entry, text)
    return buffer.getvalue()


def _install_envelope(spec: FamilyPackageSpec, artifact: bytes) -> bytes:
    """The governed install manifest pinning the artifact bytes."""
    document = {
        "manifest_version": 1,
        "id": spec.extension_id,
        "name": spec.extension_id,
        "version": spec.version,
        "publisher": PUBLISHER_ID,
        "api_version": "1.0.0",
        "permissions": list(spec.permissions),
        "entry_points": [{"name": "plugin", "module": spec.module_name, "attribute": "PLUGIN"}],
        "artifact": {"sha256": sha256_hex(artifact), "size": len(artifact)},
    }
    return json.dumps(document, sort_keys=True, indent=2).encode("utf-8")


def build_family_packages() -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Build every artifact and install envelope once, keyed by ``spec.key``."""
    artifacts: dict[str, bytes] = {}
    manifests: dict[str, bytes] = {}
    for key, spec in _family_package_specs().items():
        artifact = _artifact_zip(spec)
        artifacts[key] = artifact
        manifests[key] = _install_envelope(spec, artifact)
    return artifacts, manifests


# ---------------------------------------------------------------------------
# Host seams: the artifact loader and the install service
# ---------------------------------------------------------------------------


def _extract_artifact(install_root: Path, record: ExtensionInstallRecord, payload: bytes) -> Path:
    target = (
        install_root / record.extension_id / f"{record.version}-{str(record.artifact_sha256)[:12]}"
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts or "\\\\" in name:
                raise ValueError(f"unsafe artifact entry: {name!r}")
        archive.extractall(target)
    return target


def _import_from(target: Path, module_name: str, artifact_sha256: str) -> Any:
    module_path = target.joinpath(*module_name.split(".")).with_suffix(".py")
    if not module_path.is_file():
        raise ImportError(f"artifact does not contain module {module_name!r}")
    qualified = f"m9e_family_{artifact_sha256[:12]}.{module_name}"
    spec = importlib.util.spec_from_file_location(qualified, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build a loader for {module_name!r} from the artifact")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


class InstalledFamilyLoader:
    """Load the entrypoint from installed artifact bytes, never the source."""

    def __init__(self, install_root: Path) -> None:
        self._install_root = install_root
        #: The activation each governed install produced, keyed by install id.
        #: Hosts register the object the install-time load built — never a
        #: re-load of the presented bytes — so every use below is driven from
        #: this capture, and an install that never produced a usable activation
        #: has nothing to hand out.
        self.activations: dict[str, LoadedFamily] = {}

    def activation(self, install_id: str) -> LoadedFamily | None:
        """The object this loader built during the governed install, if any."""
        return self.activations.get(install_id)

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedFamily:
        assert record.artifact_sha256 is not None
        target = _extract_artifact(self._install_root, record, payload)
        point = record.manifest.entry_points[0]
        module = _import_from(target, point.module, record.artifact_sha256)
        plugin = getattr(module, point.attribute)
        # Entrypoint identity is pinned to the embedded contract id when the
        # artifact carries one — contract ids are '<publisher>.<name>' and may
        # use hyphens, which install envelope ids (_ID_RE) cannot — else to
        # the install id itself.
        contract_doc = target / "extension.json"
        identity_id = (
            json.loads(contract_doc.read_text())["id"]
            if contract_doc.is_file()
            else record.extension_id
        )
        if plugin["name"] != identity_id or plugin["version"] != record.version:
            raise ValueError(
                f"plugin identity {plugin['name']} {plugin['version']} does not match "
                f"the embedded contract {identity_id} {record.version}"
            )
        loaded = LoadedFamily(record, plugin, module, target)
        self.activations[record.install_id] = loaded
        return loaded


class LoadedFamily(LoadedExtension):
    """A loaded family package: the plugin object, module, and install dir."""

    def __init__(
        self,
        record: ExtensionInstallRecord,
        plugin: dict[str, Any],
        module: Any,
        install_dir: Path,
    ) -> None:
        super().__init__(extension_id=record.extension_id, version=record.version)
        self.plugin = plugin
        self.module = module
        self.install_dir = install_dir


def _install_service(
    install_root: Path,
) -> tuple[ExtensionInstallService, InstalledFamilyLoader]:
    loader = InstalledFamilyLoader(install_root)
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=loader,
        trust_policy=TrustPolicy(trusted_publishers=frozenset({PUBLISHER_ID})),
    )
    return service, loader


async def _install_package(
    service: ExtensionInstallService,
    scope: ExtensionScope,
    manifest_bytes: bytes,
    artifact_bytes: bytes,
) -> ExtensionInstallRecord:
    """Walk one package through the full governed path: inspect→authorize→install."""
    inspected = await service.inspect(
        actor=OPERATOR,
        scope=scope,
        package=ExtensionPackage(manifest_bytes=manifest_bytes, payload=artifact_bytes),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER_ID,
            signature_present=True,
            signer_key_id="acme-labs-key",
            package_sha256=sha256_hex(artifact_bytes),
        ),
    )
    assert inspected.state is ExtensionState.AWAITING_AUTHORIZATION, inspected.state
    authorized = await service.authorize(
        inspected.install_id, actor=OPERATOR, scope=scope, approve=True, reason="epic proof"
    )
    assert authorized.state is ExtensionState.AUTHORIZED, authorized.state
    installed = await service.install(
        inspected.install_id, actor=OPERATOR, scope=scope, payload=artifact_bytes
    )
    assert installed.state is ExtensionState.ACTIVE, installed.state
    return installed


def _scope() -> ExtensionScope:
    return ExtensionScope(org_id=ORG, workspace_id=WORKSPACE)


def _acme_secrets() -> StaticSecretAuthority:
    return StaticSecretAuthority({(WORKSPACE, "ACME_TOKEN"): "token-value"})


def _acme_spec_values() -> dict[str, Any]:
    return {
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


# ---------------------------------------------------------------------------
# AC1: each external-style family package installs — independently
# ---------------------------------------------------------------------------


@pytest.mark.contract("behavioral")
class TestFamilyPackagesInstallIndependently:
    """AC1: the governed install path is the whole integration per family."""

    async def test_provider_package_installs_and_registers_without_core_edits(
        self, tmp_path: Path
    ) -> None:
        artifacts, manifests = build_family_packages()
        service, loader = _install_service(tmp_path / "install-root")
        record = await _install_package(
            service,
            _scope(),
            manifests["acme.inference@1.0.0"],
            artifacts["acme.inference@1.0.0"],
        )
        assert record.install_id

        # Exercise the very instance the governed install activated — not a
        # re-load of the presented bytes: registration is driven from the
        # install-time activation, so ACTIVE-without-activation cannot hide.
        loaded = loader.activation(record.install_id)
        assert isinstance(loaded, LoadedFamily)
        adapter = loaded.module.build_adapter()

        # The one registration seam: models land in the canonical registry,
        # routing needs no core edit. Registration runs the shared suite.
        registry = InMemoryProviderRegistry()
        metadata = await register_adapter_models(ProviderAdapterCatalog(), registry, adapter)
        assert [model.name for model in metadata] == ["acme-mini"]
        models = await registry.list_models()
        assert [model.name for model in models] == ["acme-mini"]
        assert all(model.provider == "acme.models" for model in models)

        # Secret material never crosses the declarative surface: the spec
        # forbids extra (secret-shaped) fields outright.
        with pytest.raises(ValueError, match="api_key"):
            ProviderAdapterSpec.model_validate(
                {**_acme_spec_values(), "api_key": "sk-leaked-value"}
            )

    async def test_connector_package_installs_and_ingests_with_provenance(
        self, tmp_path: Path
    ) -> None:
        artifacts, manifests = build_family_packages()
        install_root = tmp_path / "install-root"
        service, loader = _install_service(install_root)
        record = await _install_package(
            service,
            _scope(),
            manifests["acme.repo_feed@1.0.0"],
            artifacts["acme.repo_feed@1.0.0"],
        )

        # Ingestion runs from the install-time activation itself.
        loaded = loader.activation(record.install_id)
        assert isinstance(loaded, LoadedFamily)
        source = loaded.module.build_connector()

        # The installed connector passes the same shared conformance suite a
        # built-in connector runs (AC6), its declared secret provisioned
        # through the bound authority — not package config.
        violations = await run_connector_conformance(
            source, workspace_ids=(WORKSPACE,), secrets=_acme_secrets()
        )
        assert violations == ()

        ingest = MemoryIngestStore()
        engine = SyncEngine(ingest, MemoryCheckpointStore())
        bound = ConnectorInstance(
            descriptor=source.descriptor,
            workspace_ids=frozenset({WORKSPACE}),
            secrets=_acme_secrets(),
        )
        report = await engine.run(source, bound, workspace_id=WORKSPACE, config_id="main")
        assert report.ingested == 2

        records = await ingest.records(WORKSPACE, "acme.repo-feed")
        assert {r.external_id for r in records} == {"doc-1", "doc-2"}
        for r in records:
            assert r.connector_id == "acme.repo-feed"
            assert r.connector_version == "1.0.0"
            assert r.workspace_id == WORKSPACE
            assert r.config_id == "main"
            assert r.content_hash

    async def test_tool_contract_comes_from_installed_bytes_and_executes_through_invocation(
        self, tmp_path: Path
    ) -> None:
        artifacts, manifests = build_family_packages()
        install_root = tmp_path / "install-root"
        service, loader = _install_service(install_root)
        record = await _install_package(
            service, _scope(), manifests["acme.notary@1.0.0"], artifacts["acme.notary@1.0.0"]
        )

        # The tool contract is read from the activation produced by install.
        loaded = loader.activation(record.install_id)
        assert isinstance(loaded, LoadedFamily)

        # The contract is parsed from the artifact's own bytes — the digest is
        # pinned to what was installed, not to anything in the source tree.
        contract_bytes = (loaded.install_dir / "extension.json").read_text().encode("utf-8")
        contract = ExtensionContract.from_manifest(
            json.loads(contract_bytes), digest=sha256_hex(contract_bytes)
        )
        assert contract.family == "tool"
        assert contract.manifest_sha256 == sha256_hex(contract_bytes)
        assert contract.version == record.version
        # Publisher binding: the embedded contract may only claim the publisher
        # the authenticated install record proves, and its id must be that
        # publisher's namespace — checked before registration is attempted.
        assert contract.publisher == record.manifest.publisher == PUBLISHER_ID
        assert contract.extension_id == f"{contract.publisher}.notary"
        # The governed grant covers the contract: the envelope presented the
        # family contract's capabilities at inspect/authorize, so what the
        # runtime binding carries is exactly what the operator approved.
        assert record.granted_permissions == tuple(TOOL_CONTRACT["capabilities"])

        catalog = ExtensionToolCatalog()
        # Registration reconciles the contract against the install record:
        # authority beyond the grant is refused, fail-closed, before any
        # Binding can carry it. The empty-grant attempt below proves the
        # check binds to the record, not to the contract's self-description.
        with pytest.raises(PermissionBeyondGrant):
            ExtensionToolCatalog().register(
                contract, loaded.plugin, handler=loaded.module.notarize, granted_permissions=()
            )
        tool = catalog.register(
            contract,
            loaded.plugin,
            handler=loaded.module.notarize,
            granted_permissions=record.granted_permissions,
        )
        binding = catalog.tool_binding(tool, workspace_id=WORKSPACE, project_id="pr-1")
        # Host-derived classification, not the package's self-description.
        assert binding.config["effect"] == tool.reversibility
        assert binding.config["manifest_sha256"] == sha256_hex(contract_bytes)
        assert binding.config["permissions"]["capabilities"] == list(record.granted_permissions)

        effects = new_in_memory_effect_context(policy_evaluator=_allow)
        outcome = await invoke_extension_tool(
            effects,
            tool,
            binding,
            {"document_id": "doc-9"},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
            actor_id="user-9",
        )
        assert outcome.status is InvocationStatus.COMPLETED
        assert outcome.result == {"notarized": ["doc-9"], "count": 1}
        assert outcome.invocation is not None
        assert outcome.invocation.run_id == RUN_ID
        assert outcome.invocation.node_run_id == NODE_RUN_ID
        assert outcome.invocation.attempt_id == ATTEMPT_ID
        assert outcome.invocation.workspace_id == WORKSPACE
        assert outcome.invocation.actor_id == "user-9"

    async def test_three_families_install_into_one_host_with_distinct_records(
        self, tmp_path: Path
    ) -> None:
        artifacts, manifests = build_family_packages()
        service, _loader = _install_service(tmp_path / "install-root")
        scope = _scope()

        records: dict[str, ExtensionInstallRecord] = {}
        for key in ("acme.inference@1.0.0", "acme.repo_feed@1.0.0", "acme.notary@1.0.0"):
            records[key] = await _install_package(service, scope, manifests[key], artifacts[key])

        install_ids = {record.install_id for record in records.values()}
        assert len(install_ids) == 3  # independent records, no shared identity
        assert all(record.state is ExtensionState.ACTIVE for record in records.values())
        # No package declared a dependency on another: each stands alone.
        for record in records.values():
            assert record.manifest.dependencies == ()


# ---------------------------------------------------------------------------
# Canonical security seams hold for installed (not source-tree) packages
# ---------------------------------------------------------------------------


@pytest.mark.contract("boundary")
class TestInstalledFamilySecuritySeams:
    async def test_installed_connector_cannot_leave_declared_scope(self, tmp_path: Path) -> None:
        artifacts, manifests = build_family_packages()
        install_root = tmp_path / "install-root"
        service, loader = _install_service(install_root)
        record = await _install_package(
            service,
            _scope(),
            manifests["acme.repo_feed@1.0.0"],
            artifacts["acme.repo_feed@1.0.0"],
        )
        # The out-of-scope attempts run the install-time activation, not a
        # re-load: whatever was activated is exactly what gets exercised.
        loaded = loader.activation(record.install_id)
        assert isinstance(loaded, LoadedFamily)
        source = loaded.module.build_connector()

        ingest = MemoryIngestStore()
        checkpoints = MemoryCheckpointStore()
        engine = SyncEngine(ingest, checkpoints)
        instance = ConnectorInstance(
            descriptor=source.descriptor,
            workspace_ids=frozenset({WORKSPACE}),
            secrets=_acme_secrets(),
        )

        # Undeclared Workspace: refused before connector code runs.
        with pytest.raises(ConnectorScopeError, match="ws-other"):
            await engine.run(source, instance, workspace_id="ws-other", config_id="main")
        assert await ingest.records("ws-other", "acme.repo-feed") == ()
        assert await checkpoints.load("ws-other", "acme.repo-feed", "main") is None

        # Undeclared secret name: the session refuses it; the authority bound
        # behind the session never sees the request.
        session = ConnectorSession.create(
            instance, workspace_id=WORKSPACE, config_id="main", config={}
        )
        with pytest.raises(ConnectorScopeError, match="UNDECLARED"):
            await session.resolve_secret("UNDECLARED_SECRET")

        # Declared but unprovisioned: an operator concern, not a scope leak.
        dry_instance = ConnectorInstance(
            descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE})
        )
        dry_session = ConnectorSession.create(
            dry_instance, workspace_id=WORKSPACE, config_id="main", config={}
        )
        with pytest.raises(LookupError, match="ACME_TOKEN"):
            await dry_session.resolve_secret("ACME_TOKEN")

    async def test_misdeclared_plugin_identity_is_refused_and_recorded_failed(
        self, tmp_path: Path
    ) -> None:
        """Committed teeth for the activation identity pin: an artifact whose
        entrypoint claims an id its embedded contract never declares travels
        inspect → authorize (the lifecycle authorizes bytes, not behavior)
        and is refused at activation — ``ExtensionLifecycleError``, the record
        persists ``FAILED``, and no activation survives the failure."""
        spec = _family_package_specs()["acme.notary@1.0.0"]
        # The entrypoint lies about which extension it is; the contract document
        # in the same artifact still says acme-labs.notary.
        lying_source = TOOL_PLUGIN.replace('"name": "acme-labs.notary"', '"name": "acme.evil"')
        assert lying_source != TOOL_PLUGIN, "the lie must actually change the plugin"
        artifact = _artifact_zip(replace(spec, plugin_source=lying_source))
        manifest = _install_envelope(spec, artifact)  # the envelope pins the lying bytes
        service, loader = _install_service(tmp_path / "install-root")
        scope = _scope()

        inspected = await service.inspect(
            actor=OPERATOR,
            scope=scope,
            package=ExtensionPackage(manifest_bytes=manifest, payload=artifact),
            trust_evidence=TrustClaim(
                publisher_id=PUBLISHER_ID,
                signature_present=True,
                signer_key_id="acme-labs-key",
                package_sha256=sha256_hex(artifact),
            ),
        )
        await service.authorize(
            inspected.install_id, actor=OPERATOR, scope=scope, approve=True, reason="epic proof"
        )
        with pytest.raises(ExtensionLifecycleError, match="recorded FAILED"):
            await service.install(
                inspected.install_id, actor=OPERATOR, scope=scope, payload=artifact
            )

        failed = await service.get(inspected.install_id, scope=scope)
        assert failed.state is ExtensionState.FAILED
        assert failed.failure_reason is not None and "does not match" in failed.failure_reason
        assert failed.install_attempts == 1
        # Nothing became usable: no active record, no retained activation —
        # the refused package is observable as FAILED, never silently absent.
        assert await service.active(scope, spec.extension_id) is None
        assert loader.activation(inspected.install_id) is None


# ---------------------------------------------------------------------------
# AC1 (isolation of refusals) and AC6 (shared suites) at epic level
# ---------------------------------------------------------------------------


class BuiltinStyleConnector:
    """The shape an in-tree connector ships: the same protocol."""

    def __init__(self) -> None:
        self._descriptor = ConnectorDescriptor(
            connector_id="builtin.reference-feed",
            version="1.0.0",
            capabilities=frozenset({ConnectorCapability.LIST}),
            secret_refs=(),
        )

    @property
    def descriptor(self) -> ConnectorDescriptor:
        return self._descriptor

    async def list_items(self, ctx: SyncContext) -> SyncPage:
        del ctx
        return SyncPage(
            items=(
                SourceItem(
                    source_id="builtin",
                    external_id="doc-1",
                    content="built-in document",
                    version="v1",
                ),
            ),
            next_cursor=None,
        )


@pytest.mark.contract("behavioral")
class TestRegistrationIsolationAndSharedConformance:
    async def test_lying_adapter_registration_is_isolated_from_other_families(
        self, tmp_path: Path
    ) -> None:
        """A conformance-failing provider package *installs* (the lifecycle
        authorizes bytes, not behavior) but its registration is refused by
        the shared suite — and the other families' installs stay ACTIVE and
        register normally."""
        artifacts, manifests = build_family_packages()
        install_root = tmp_path / "install-root"
        service, loader = _install_service(install_root)
        scope = _scope()
        provider_record = await _install_package(
            service, scope, manifests["acme.inference@1.0.0"], artifacts["acme.inference@1.0.0"]
        )
        connector_record = await _install_package(
            service, scope, manifests["acme.repo_feed@1.0.0"], artifacts["acme.repo_feed@1.0.0"]
        )

        # The lie is built from the *installed* artifact: activation returns the
        # module the install wrote, so the subclassed adapter is exactly the
        # object a registration attempt on this package would receive.
        loaded = loader.activation(provider_record.install_id)
        assert isinstance(loaded, LoadedFamily)
        installed_adapter = loaded.module.build_adapter()

        class LyingAdapter(type(installed_adapter)):
            """The installed adapter, reporting usage contradicting its body."""

            def usage_from(self, payload: dict[str, object]) -> tuple[int, int] | None:
                del payload
                return (999, 999)

        liar = LyingAdapter(ProviderAdapterSpec.model_validate(_acme_spec_values()))
        report = run_adapter_conformance(liar)
        assert report.failures, "the lying adapter must fail the shared suite"

        # Registration refusal is contained: nothing enters catalog or registry.
        registry = InMemoryProviderRegistry()
        with pytest.raises(AdapterRegistrationError, match="conformance"):
            await register_adapter_models(ProviderAdapterCatalog(), registry, liar)
        assert await registry.list_models() == []

        still_active = await service.get(connector_record.install_id, scope=scope)
        assert still_active.state is ExtensionState.ACTIVE

        # The installed connector still registers and conforms.
        connector_loaded = loader.activation(connector_record.install_id)
        assert isinstance(connector_loaded, LoadedFamily)
        violations = await run_connector_conformance(
            connector_loaded.module.build_connector(),
            workspace_ids=(WORKSPACE,),
            secrets=_acme_secrets(),
        )
        assert violations == ()

    async def test_external_and_builtin_reference_pass_the_same_suites(self) -> None:
        """AC6: where contracts overlap, one suite judges both implementations."""
        # Provider family: the built-in reference adapter and the external-style
        # one (built from the same plugin source the artifact carries) face the
        # identical conformance run.
        builtin_adapter = ReferenceChatAdapter(reference_adapter_spec())
        assert run_adapter_conformance(builtin_adapter).ok

        external_adapter = _plugin_from_source(
            "m9e_inline_provider", PROVIDER_PLUGIN
        ).build_adapter()
        assert run_adapter_conformance(external_adapter).ok

        # Connector family: a built-in-style in-tree connector and the external
        # one face the identical conformance run.
        assert await run_connector_conformance(BuiltinStyleConnector()) == ()
        external_connector = _plugin_from_source(
            "m9e_inline_connector", CONNECTOR_PLUGIN
        ).build_connector()
        assert (
            await run_connector_conformance(
                external_connector, workspace_ids=(WORKSPACE,), secrets=_acme_secrets()
            )
            == ()
        )


def _plugin_from_source(module_name: str, source: str) -> Any:
    """Exec one plugin source exactly as an artifact import would."""
    module = types.ModuleType(module_name)
    exec(compile(source, f"{module_name}.py", "exec"), module.__dict__)
    return module
