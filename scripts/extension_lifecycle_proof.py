#!/usr/bin/env python3
"""Reproducible end-to-end extension lifecycle proof (M9-J3, issue #981).

One script runs the whole external extension lifecycle — discover → resolve →
inspect → authorize → install → invoke → observe → update → reauthorization
fence → restart durability — against the platform's real production seams, and
emits the evidence as a machine-readable ``lineage.json`` plus a
human-readable ``lineage.md`` into an output directory. Exit 0 iff every stage
check passed.

What "no source-tree modification / editable-install bypass" means here,
mechanically:

* every extension artifact is built as bytes in a scratch directory and
  consumed only through the governed path — catalog snapshot →
  ``resolve_lock`` → ``ExtensionInstallService.inspect/authorize/install`` →
  digest-pinned artifact loader. Nothing under ``packages/`` or
  ``extensions/`` is imported as extension code, and no loader path points
  into the repository's extension trees;
* the loader imports the entry point *from the extracted artifact*, under a
  module name derived from the artifact digest, so the code that runs is the
  code whose sha256 the catalog pinned and the operator authorized;
* the private catalog is proof-side data in the scratch directory, in the
  documented catalog-file format, read through the production resolution
  layer — the #979 catalog *service* is a sibling lane, and the format here
  is the minimal honest stand-in for one.

Determinism: the publisher uses a fixed test-only Ed25519 key, the install
service runs on an injectable deterministic clock with sequential install
ids, and the lock/lineage core (identities, digests, signatures, decisions,
refusals) is therefore byte-reproducible. Wall-clock stamps that production
stores record internally (the SQLite registry's ``installed_at``) are marked
as such in the lineage and excluded from the deterministic core digest.

Honesty boundary (stated, not hidden): rollback/disable/remove as durable
lifecycle operations are #954's surface and do not exist at the proof's base
commit; the proof pins every property they must preserve — append-only
records, queryable history after deactivation, denial leaves the prior
version active — and the lineage marks those stages accordingly. Canonical
Goal/Run truth is likewise untouched by construction: the proof asserts the
extension subsystem imports nothing from the canonical run/goal trees, so no
extension status path exists that could override it.

Usage::

    python scripts/extension_lifecycle_proof.py --out <dir> [--quiet]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from maistro.extensions import (
    ArtifactMismatch,
    ExtensionInstallService,
    ExtensionPackage,
    ExtensionScope,
    InvalidTransition,
    LoadedExtension,
    UnknownInstall,
    VersionPinned,
    resolve_lock,
)
from maistro.extensions.resolution import (
    CatalogEntry,
    ExtensionCatalog,
    ExtensionDependency,
    LockArtifacts,
    LockState,
    RootRequest,
    materialize_lock,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.trust import TrustPolicy
from maistro.extensions.types import (
    ExtensionInstallRecord,
    ExtensionState,
    PackageIdentity,
    PublisherIdentity,
    TrustClaim,
    canonical_install_payload,
    manifest_snapshot,
    sha256_hex,
)

PROOF_SCHEMA = "maistro-extension-lifecycle-proof:v1"

#: The fixed scratch publisher key seed. Test-only material, deterministic so
#: the signatures and digests in the lineage are reproducible; it signs
#: nothing real.
PUBLISHER_KEY_SEED = bytes(range(32))
PUBLISHER_ID = "acme-labs"

CATALOG_SOURCE = "file://proof/private-catalog.json"

#: Deterministic epoch for the service clock; each read advances one second.
EPOCH = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)

ORG = "org-acme"
WORKSPACE = "ws-7"
WORKSPACE_B = "ws-999"
OPERATOR = "operator:alice"
CALLER = "caller:carol"

STORAGE_CAPABILITY = "workspace.storage.write"

NOTARY_1_0_0 = "acme.notary@1.0.0"
NOTARY_1_1_0 = "acme.notary@1.1.0"
NOTARY_2_0_0 = "acme.notary@2.0.0"
GREETER_1_0_0 = "acme.greeter@1.0.0"


# ---------------------------------------------------------------------------
# The scratch extension families, as artifact bytes (no repo code is imported)
# ---------------------------------------------------------------------------

GREETER_PLUGIN = '''"""acme.greeter 1.0.0 entrypoint (proof artifact)."""

PLUGIN = {
    "kind": "tool",
    "name": "acme.greeter",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "greet",
}


def greet(context, target):
    """Greet ``target`` on behalf of the caller's own scope only."""
    return f"Hello, {target} from {context.workspace_id}!"


def probe_undeclared(context):
    """Deliberately reach for authority this manifest never declared."""
    context.capability("workspace.storage.write")
    return "unreachable"


HANDLERS = {"greet": greet, "probe_undeclared": probe_undeclared}
'''


def _notary_source(version: str, permissions: tuple[str, ...]) -> str:
    """The notary plugin source; 2.0.0 fences its work behind the grant."""
    if permissions:
        capability_line = f'    context.capability("{permissions[0]}")  # refuses unless granted'
        docstring_suffix = ", only after the host confirms the storage grant:"
    else:
        capability_line = "    del context  # zero-authority version: the context is unused"
        docstring_suffix = " (pure; no capability needed):"
    return f'''"""acme.notary {version} entrypoint (proof artifact)."""

import hashlib

PLUGIN = {{
    "kind": "tool",
    "name": "acme.notary",
    "version": "{version}",
    "capabilities": {list(permissions)},
    "handler": "seal",
}}


def seal(context, text):
    """Return the sha256 seal of ``text``{docstring_suffix}"""
{capability_line}
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


HANDLERS = {{"seal": seal}}
'''


@dataclass(frozen=True)
class PackageSpec:
    """One extension version the scratch catalog offers."""

    extension_id: str
    version: str
    module_name: str
    plugin_source: str
    permissions: tuple[str, ...]
    dependencies: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> str:
        return f"{self.extension_id}@{self.version}"


def proof_catalog_specs() -> list[PackageSpec]:
    """The catalog's offering: two families, four versions, one dependency.

    ``acme.notary`` 1.0.0/1.1.0 are same-authority (zero permissions); 2.0.0
    requests ``workspace.storage.write`` — the broader-authority upgrade the
    reauthorization fence must gate. ``acme.greeter`` 1.0.0 depends on
    ``acme.notary ^1.0.0``, so discovery must pull the dependency
    transitively and the activation layer must enforce install order.
    """
    return [
        PackageSpec(
            extension_id="acme.notary",
            version="1.0.0",
            module_name="acme_notary.plugin",
            plugin_source=_notary_source("1.0.0", ()),
            permissions=(),
        ),
        PackageSpec(
            extension_id="acme.notary",
            version="1.1.0",
            module_name="acme_notary.plugin",
            plugin_source=_notary_source("1.1.0", ()),
            permissions=(),
        ),
        PackageSpec(
            extension_id="acme.notary",
            version="2.0.0",
            module_name="acme_notary.plugin",
            plugin_source=_notary_source("2.0.0", (STORAGE_CAPABILITY,)),
            permissions=(STORAGE_CAPABILITY,),
        ),
        PackageSpec(
            extension_id="acme.greeter",
            version="1.0.0",
            module_name="acme_greeter.plugin",
            plugin_source=GREETER_PLUGIN,
            permissions=(),
            dependencies=(("acme.notary", "^1.0.0"),),
        ),
    ]


def _manifest_bytes(spec: PackageSpec, artifact: bytes) -> bytes:
    """The governed manifest for one package spec, pinning the artifact."""
    document: dict[str, Any] = {
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
    if spec.dependencies:
        document["dependencies"] = [
            {"id": target, "range": range_spec} for target, range_spec in spec.dependencies
        ]
    return json.dumps(document, sort_keys=True, indent=2).encode("utf-8")


def _artifact_zip(spec: PackageSpec) -> bytes:
    """The payload artifact: a zip carrying the module tree, nothing else."""
    buffer = io.BytesIO()
    module_path = spec.module_name.replace(".", "/") + ".py"
    # Fixed entry metadata. ``ZipFile.writestr`` dates a str arcname from
    # ``time.localtime()``, and ZIP (DOS) timestamps have 2-second
    # granularity — so the same plugin source hashed differently depending
    # on which bucket the build started in, and every digest downstream
    # (manifest, signature, catalog snapshot, lineage core) inherited that
    # drift. The artifact is a function of the source alone; measured
    # drift between back-to-back runs is pinned by
    # ``TestProofDeterminism``, which forces a bucket cross on the second
    # build.
    entry = zipfile.ZipInfo(module_path, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o600 << 16  # writestr's own default for files
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry, spec.plugin_source)
    return buffer.getvalue()


def build_packages(specs: list[PackageSpec]) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Build every artifact and manifest once, keyed by ``spec.key``."""
    artifacts: dict[str, bytes] = {}
    manifests: dict[str, bytes] = {}
    for spec in specs:
        artifact = _artifact_zip(spec)
        artifacts[spec.key] = artifact
        manifests[spec.key] = _manifest_bytes(spec, artifact)
    return artifacts, manifests


def public_key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def key_fingerprint(key: Ed25519PrivateKey) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex(key))).hexdigest()


# ---------------------------------------------------------------------------
# Host seams: the private catalog file, the artifact loader, the context
# ---------------------------------------------------------------------------


def _catalog_range(manifest_range: str) -> str:
    """Translate a manifest dependency range to the resolver's grammar.

    The manifest layer (``compatibility``) speaks ``^X.Y.Z``/exact/``*``; the
    resolution layer speaks comparator lists. They express the same set, so
    the catalog writer translates — and the proof's checks compare both
    representations against the same resolved identity.
    """
    if manifest_range.startswith("^"):
        floor = manifest_range[1:]
        major = int(floor.split(".")[0])
        return f">={floor},<{major + 1}.0.0"
    return manifest_range


def write_private_catalog(
    catalog_path: Path,
    key: Ed25519PrivateKey,
    specs: list[PackageSpec],
    artifacts: dict[str, bytes],
    manifests: dict[str, bytes],
) -> str:
    """Write the private organizational catalog file; return its sha256.

    Each entry's signature is over the canonical install identity — exactly
    the bytes an install verifies against the registered publisher key at
    materialization time — so a catalog built here round-trips through the
    real verification rules unchanged.
    """
    entries: list[dict[str, Any]] = []
    for spec in sorted(specs, key=lambda s: (s.extension_id, s.version)):
        manifest_body = manifests[spec.key].decode("utf-8")
        identity = PackageIdentity(
            extension_name=spec.extension_id,
            semantic_version=spec.version,
            package_sha256=sha256_hex(artifacts[spec.key]),
            manifest_sha256=manifest_snapshot(manifest_body).sha256,
        )
        signature = key.sign(canonical_install_payload(identity)).hex()
        entries.append(
            {
                "id": identity.extension_name,
                "version": identity.semantic_version,
                "package_sha256": identity.package_sha256,
                "manifest_sha256": identity.manifest_sha256,
                "publisher": PUBLISHER_ID,
                "signature": signature,
                "dependencies": [
                    {"id": target, "range": _catalog_range(range_spec)}
                    for target, range_spec in spec.dependencies
                ],
            }
        )
    document = {
        "catalog_version": 1,
        "publisher": {
            "publisher_id": PUBLISHER_ID,
            "display_name": "ACME Labs (proof)",
            "signing_key_fingerprint": key_fingerprint(key),
            "signing_public_key": public_key_hex(key),
        },
        "entries": entries,
    }
    catalog_path.write_text(json.dumps(document, sort_keys=True, indent=2), encoding="utf-8")
    return sha256_hex(catalog_path.read_bytes())


def load_private_catalog(catalog_path: Path) -> tuple[ExtensionCatalog, str]:
    """Read the catalog file into the production resolution snapshot.

    This is discovery: the host reads the catalog it can reach, digests the
    snapshot, and hands the immutable snapshot to the production resolver. No
    signature is trusted here — every entry's signature is verified by the
    install stores at materialization time.
    """
    raw = catalog_path.read_bytes()
    snapshot_sha256 = sha256_hex(raw)
    document = json.loads(raw.decode("utf-8"))
    entries: list[CatalogEntry] = []
    for entry in document["entries"]:
        entries.append(
            CatalogEntry(
                identity=PackageIdentity(
                    extension_name=str(entry["id"]),
                    semantic_version=str(entry["version"]),
                    package_sha256=str(entry["package_sha256"]),
                    manifest_sha256=str(entry["manifest_sha256"]),
                ),
                source=CATALOG_SOURCE,
                catalog_snapshot_sha256=snapshot_sha256,
                publisher_id=str(entry["publisher"]),
                signature=str(entry["signature"]),
                dependencies=tuple(
                    ExtensionDependency(target=str(dep["id"]), range_text=str(dep["range"]))
                    for dep in entry.get("dependencies", ())
                ),
            )
        )
    return ExtensionCatalog(entries=tuple(entries)), snapshot_sha256


class UndeclaredCapability(PermissionError):
    """The context refused authority the manifest never declared."""


class ProofExtensionContext:
    """The host's extension context: the only state an invocation can see.

    The context exposes the caller's own canonical scope facts and a
    capability accessor fenced to exactly the grant frozen at authorization.
    Authority flows from the manifest through the frozen grant; there is no
    accessor for any other Workspace's data and no way to name a capability
    outside the grant — both refusals are structural, not policy strings the
    extension could talk its way around.
    """

    def __init__(
        self,
        *,
        org_id: str,
        workspace_id: str,
        caller: str,
        extension_id: str,
        version: str,
        granted: tuple[str, ...],
    ) -> None:
        self.org_id = org_id
        self.workspace_id = workspace_id
        self.caller = caller
        self.extension_id = extension_id
        self.version = version
        self.granted = granted
        self.capability_requests: list[dict[str, str]] = []

    def capability(self, name: str) -> dict[str, str]:
        """Access one declared capability; refuse anything undeclared."""
        outcome = "granted" if name in self.granted else "denied"
        self.capability_requests.append({"capability": name, "outcome": outcome})
        if outcome == "denied":
            raise UndeclaredCapability(
                f"{self.extension_id} {self.version} requested capability {name!r} "
                "which its manifest never declared or its grant never froze"
            )
        return {
            "capability": name,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
        }


class LoadedPlugin(LoadedExtension):
    """A loaded entrypoint: the plugin object and its resolved handlers.

    Handlers are resolved from the loaded module — either its ``HANDLERS``
    mapping or a module attribute named by the handler string — so an
    invocation never re-imports and never resolves names outside the
    artifact's module.
    """

    def __init__(
        self,
        extension_id: str,
        version: str,
        plugin: dict[str, Any],
        module: Any,
        install_dir: Path,
    ) -> None:
        super().__init__(extension_id=extension_id, version=version)
        self.plugin = plugin
        self.module = module
        self.install_dir = install_dir
        handlers: dict[str, Any] = getattr(module, "HANDLERS", {})
        handler_name = str(plugin["handler"])
        self.handler = handlers.get(handler_name) or getattr(module, handler_name)

    def resolve(self, handler_name: str) -> Any:
        """One handler by name, from the same loaded module only."""
        handlers: dict[str, Any] = getattr(self.module, "HANDLERS", {})
        handler = handlers.get(handler_name) or getattr(self.module, handler_name, None)
        if handler is None:
            raise AttributeError(f"the artifact exposes no handler named {handler_name!r}")
        return handler


def _extract_artifact(install_root: Path, record: ExtensionInstallRecord, payload: bytes) -> Path:
    """Extract the artifact zip into the install root, refusing unsafe paths."""
    target = (
        install_root / record.extension_id / f"{record.version}-{str(record.artifact_sha256)[:12]}"
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
                raise ValueError(f"unsafe artifact entry: {name!r}")
        archive.extractall(target)
    return target


def _import_from(target: Path, module_name: str, artifact_sha256: str) -> Any:
    """Import ``module_name`` from the extracted artifact, and only from it."""
    module_path = target.joinpath(*module_name.split(".")).with_suffix(".py")
    if not module_path.is_file():
        raise ImportError(f"artifact does not contain module {module_name!r}")
    qualified = f"proof_ext_{artifact_sha256[:12]}.{module_name}"
    spec = importlib.util.spec_from_file_location(qualified, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build a loader for {module_name!r} from the artifact")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


class ArtifactZipLoader:
    """The host loader: import the entry point from the pinned artifact bytes.

    The platform's only code-execution seam, and the proof's mechanical
    answer to "no editable install bypass": the payload is a zip whose sha256
    the manifest's ``artifact`` claim pins and the operator authorized. The
    loader extracts it into the scope's install root and imports the declared
    module from those bytes under a digest-derived module name, so what
    executes is byte-identical to what the catalog offered and the grant was
    frozen for. It also refuses a plugin whose self-declared identity
    disagrees with the install record — the same check the service repeats.
    """

    def __init__(self, install_root: Path) -> None:
        self._install_root = install_root

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedPlugin:
        assert record.artifact_sha256 is not None
        target = _extract_artifact(self._install_root, record, payload)
        point = record.manifest.entry_points[0]
        module = _import_from(target, point.module, record.artifact_sha256)
        plugin = getattr(module, point.attribute)
        if plugin["name"] != record.extension_id or plugin["version"] != record.version:
            raise ValueError(
                f"plugin identity {plugin['name']} {plugin['version']} does not match "
                f"the install record {record.extension_id} {record.version}"
            )
        return LoadedPlugin(record.extension_id, record.version, plugin, module, target)


# ---------------------------------------------------------------------------
# The proof runner
# ---------------------------------------------------------------------------


class DeterministicClock:
    """Fixed-epoch clock; every read advances one second, so transition
    ordering in the audit trail is stable and reproducible."""

    def __init__(self) -> None:
        self._moment = EPOCH

    def __call__(self) -> datetime:
        self._moment = self._moment + timedelta(seconds=1)
        return self._moment


@dataclass
class Stage:
    """One lineage stage: its checks, its evidence, and any honest note."""

    name: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    #: Set when a stage documents a boundary rather than proving behavior.
    note: str | None = None

    def check(self, check_id: str, ok: bool, detail: str) -> bool:
        self.checks.append({"id": check_id, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(check["ok"] for check in self.checks)


@dataclass
class InvocationObservation:
    """One observed invocation, with its full provenance chain."""

    seq: int
    at: datetime
    caller: str
    org_id: str
    workspace_id: str
    install_id: str
    extension_id: str
    version: str
    artifact_sha256: str
    handler: str
    granted: tuple[str, ...]
    capability_requests: list[dict[str, str]]
    outcome: str
    result_repr: str

    @property
    def invocation_id(self) -> str:
        return f"invocation-{self.seq:04d}"

    def to_json(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "at": self.at.isoformat(),
            "caller": self.caller,
            "scope": {"org_id": self.org_id, "workspace_id": self.workspace_id},
            "install_id": self.install_id,
            "extension": {
                "id": self.extension_id,
                "version": self.version,
                "artifact_sha256": self.artifact_sha256,
            },
            "handler": self.handler,
            "granted": list(self.granted),
            "capability_requests": self.capability_requests,
            "outcome": self.outcome,
            "result_repr": self.result_repr[:200],
        }

    def core(self) -> dict[str, Any]:
        """The wall-clock-free view used for the deterministic core digest."""
        payload = self.to_json()
        del payload["at"]
        return payload


class PinnedArtifactFetcher:
    """Serves a lock's artifacts from the bytes the catalog originally
    offered — the stand-in for a catalog fetcher that reproduces an old
    environment from the lock alone."""

    def __init__(self, artifacts: dict[str, bytes], manifests: dict[str, bytes]) -> None:
        self._artifacts = artifacts
        self._manifests = manifests

    async def fetch_lock_artifact(self, entry: Any) -> LockArtifacts | None:
        key = f"{entry.extension_name}@{entry.semantic_version}"
        if key not in self._artifacts:
            return None
        return LockArtifacts(
            package_bytes=self._artifacts[key],
            manifest_body=self._manifests[key].decode("utf-8"),
        )


class LifecycleProof:
    """Drives the lifecycle against production seams and records lineage."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        scratch.mkdir(parents=True, exist_ok=True)
        self.clock = DeterministicClock()
        self.stages: list[Stage] = []
        self.invocations: list[InvocationObservation] = []
        self._invocation_seq = 0
        self._install_seq = 0
        self.lock: LockState | None = None
        self.snapshot_sha256 = ""
        self.artifacts: dict[str, bytes] = {}
        self.manifests: dict[str, bytes] = {}
        self.loaded: dict[str, LoadedPlugin] = {}

        self.catalog_path = scratch / "private-catalog.json"
        self.install_root = scratch / "install-root"
        self.registry_db = scratch / "extension-registry.sqlite3"
        self.publisher_key = Ed25519PrivateKey.from_private_bytes(PUBLISHER_KEY_SEED)
        self.publisher = PublisherIdentity(
            publisher_id=PUBLISHER_ID,
            display_name="ACME Labs (proof)",
            signing_key_fingerprint=key_fingerprint(self.publisher_key),
            signing_public_key=public_key_hex(self.publisher_key),
            registered_at=EPOCH,
        )
        self.store = InMemoryExtensionStore()
        self.service = ExtensionInstallService(
            self.store,
            loader=ArtifactZipLoader(self.install_root),
            trust_policy=TrustPolicy(trusted_publishers=frozenset({PUBLISHER_ID})),
            clock=self.clock,
            install_id_factory=self._next_install_id,
        )
        self.scope = ExtensionScope(org_id=ORG, workspace_id=WORKSPACE)

    # -- bookkeeping ---------------------------------------------------------

    def _next_install_id(self) -> str:
        self._install_seq += 1
        return f"install-{self._install_seq:04d}"

    def _stage(self, name: str, note: str | None = None) -> Stage:
        stage = Stage(name=name, note=note)
        self.stages.append(stage)
        return stage

    # -- shared lifecycle helpers ---------------------------------------------

    async def _inspect(self, key: str) -> ExtensionInstallRecord:
        """Run the production inspection over one catalog-offered package."""
        return await self.service.inspect(
            actor=OPERATOR,
            scope=self.scope,
            package=ExtensionPackage(
                manifest_bytes=self.manifests[key], payload=self.artifacts[key]
            ),
            trust_evidence=TrustClaim(
                publisher_id=PUBLISHER_ID,
                signature_present=True,
                signer_key_id=self.publisher.signing_key_fingerprint,
                package_sha256=sha256_hex(self.artifacts[key]),
            ),
        )

    async def _authorize(self, record: ExtensionInstallRecord, reason: str):
        return await self.service.authorize(
            record.install_id, actor=OPERATOR, scope=self.scope, approve=True, reason=reason
        )

    async def _install(self, record: ExtensionInstallRecord) -> ExtensionInstallRecord:
        return await self.service.install(
            record.install_id,
            actor=OPERATOR,
            scope=self.scope,
            payload=self.artifacts[f"{record.extension_id}@{record.version}"],
        )

    async def _load(self, record: ExtensionInstallRecord) -> LoadedPlugin:
        """Load the active artifact from the install root, as a host would
        after a restart or an outage: from installed bytes, not the catalog."""
        loader = ArtifactZipLoader(self.install_root)
        key = f"{record.extension_id}@{record.version}"
        self.loaded[key] = await loader.load(record, self.artifacts[key])
        return self.loaded[key]

    def _invoke(
        self, record: ExtensionInstallRecord, handler_name: str, *args: Any
    ) -> InvocationObservation:
        """Invoke one loaded handler through the grant-fenced context."""
        loaded = self.loaded[f"{record.extension_id}@{record.version}"]
        context = ProofExtensionContext(
            org_id=self.scope.org_id,
            workspace_id=self.scope.workspace_id,
            caller=CALLER,
            extension_id=record.extension_id,
            version=record.version,
            granted=record.granted_permissions,
        )
        try:
            value = loaded.resolve(handler_name)(context, *args)
        except UndeclaredCapability as exc:
            return self._record(
                record, context, handler_name, "denied:undeclared-capability", str(exc)
            )
        except Exception as exc:
            return self._record(
                record, context, handler_name, f"error:{type(exc).__name__}", repr(exc)
            )
        return self._record(record, context, handler_name, "ok", repr(value))

    def _record(
        self,
        record: ExtensionInstallRecord,
        context: ProofExtensionContext,
        handler_name: str,
        outcome: str,
        result_repr: str,
    ) -> InvocationObservation:
        self._invocation_seq += 1
        observation = InvocationObservation(
            seq=self._invocation_seq,
            at=self.clock(),
            caller=CALLER,
            org_id=context.org_id,
            workspace_id=context.workspace_id,
            install_id=record.install_id,
            extension_id=record.extension_id,
            version=record.version,
            artifact_sha256=str(record.artifact_sha256),
            handler=handler_name,
            granted=record.granted_permissions,
            capability_requests=list(context.capability_requests),
            outcome=outcome,
            result_repr=result_repr,
        )
        self.invocations.append(observation)
        return observation

    # -- stages ---------------------------------------------------------------

    def stage_build_catalog(self) -> Stage:
        """Build the external-style packages and the private catalog file."""
        stage = self._stage("build-catalog")
        specs = proof_catalog_specs()
        self.artifacts, self.manifests = build_packages(specs)
        self.snapshot_sha256 = write_private_catalog(
            self.catalog_path, self.publisher_key, specs, self.artifacts, self.manifests
        )
        stage.evidence["catalog_snapshot_sha256"] = self.snapshot_sha256
        stage.evidence["offering"] = sorted(self.artifacts)
        stage.evidence["publisher_fingerprint"] = self.publisher.signing_key_fingerprint
        parsed = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        stage.check(
            "catalog-parses",
            parsed["catalog_version"] == 1 and len(parsed["entries"]) == 4,
            "the private organizational catalog offers four pinned versions "
            "from one publisher identity",
        )
        stage.check(
            "artifacts-pinned-by-manifests",
            all(
                sha256_hex(self.artifacts[spec.key]).encode() in self.manifests[spec.key]
                for spec in specs
            ),
            "every manifest pins its artifact sha256 — the bytes the "
            "operator's inspection will be about",
        )
        return stage

    def stage_discover(self) -> Stage:
        """Discover + resolve: one operator ask becomes a reproducible lock."""
        stage = self._stage("discover")
        catalog, _snapshot = load_private_catalog(self.catalog_path)
        lock = resolve_lock([RootRequest("acme.greeter", "*")], catalog)
        self.lock = lock
        stage.evidence["lock"] = json.loads(lock.to_json())
        stage.evidence["catalog_snapshot_sha256"] = self.snapshot_sha256
        names = {entry.extension_name + "@" + entry.semantic_version for entry in lock.entries}
        stage.check(
            "dependency-resolved-transitively",
            names == {GREETER_1_0_0, NOTARY_1_1_0},
            "the greeter ask pulls acme.notary ^1.0.0: the resolver pins the "
            "highest range-compatible 1.1.0 and never the out-of-range 2.0.0",
        )
        notary = lock.get("acme.notary")
        assert notary is not None
        stage.check(
            "pin-carries-full-identity",
            notary.package_sha256 == sha256_hex(self.artifacts[NOTARY_1_1_0])
            and notary.source == CATALOG_SOURCE
            and notary.catalog_snapshot_sha256 == self.snapshot_sha256,
            "the pin names version, package digest, catalog source, and the "
            "exact snapshot digest that claimed them",
        )
        again = resolve_lock([RootRequest("acme.greeter", "*")], catalog)
        stage.check(
            "lock-is-reproducible",
            again.to_json() == lock.to_json(),
            "resolving the same snapshot again yields a byte-identical lock",
        )
        explanation = lock.explain("acme.greeter")
        assert explanation is not None
        stage.check(
            "selection-is-explainable",
            any(c.origin == "<install-request>" for c in explanation.constraints),
            "the lock explains why each entry and version was selected, "
            "naming the operator request as an origin",
        )
        return stage

    async def stage_inspect(self) -> tuple[ExtensionInstallRecord, Stage]:
        """Inspect: manifest bytes decide; dependency order is enforced."""
        stage = self._stage("inspect")
        premature = await self._inspect(GREETER_1_0_0)
        stage.check(
            "missing-dependency-rejected",
            premature.state is ExtensionState.REJECTED
            and "missing dependency: acme.notary" in (premature.failure_reason or ""),
            f"inspecting greeter before its dependency is active is "
            f"REJECTED: {premature.failure_reason}",
        )
        record = await self._inspect(NOTARY_1_0_0)
        stage.evidence["notary-1-0-0"] = {
            "install_id": record.install_id,
            "state": str(record.state),
            "requested_permissions": list(record.requested_permissions),
            "authority_delta": list(record.authority_delta),
        }
        stage.check(
            "candidate-parked-for-decision",
            record.state is ExtensionState.AWAITING_AUTHORIZATION,
            "a compatible candidate is parked AWAITING_AUTHORIZATION — inspection never installs",
        )
        displayed = await self.service.permissions_in_snapshot(record)
        stage.check(
            "permissions-from-immutable-snapshot",
            displayed == record.requested_permissions,
            "the permissions shown to the operator are read through the "
            "digest-anchored manifest snapshot",
        )
        return record, stage

    async def stage_authorize_and_install(
        self, notary_record: ExtensionInstallRecord
    ) -> ExtensionInstallRecord:
        """Authorize + install: the only code-execution seam, after consent."""
        stage = self._stage("authorize-install")
        authorized = await self._authorize(
            notary_record, "zero-authority foundation tool; approved for ws-7"
        )
        stage.check(
            "grant-frozen-to-snapshot",
            authorized.state is ExtensionState.AUTHORIZED
            and authorized.granted_permissions == authorized.requested_permissions,
            "approval freezes the grant to exactly the inspected permission set",
        )
        active = await self._install(authorized)
        stage.check(
            "install-activates-only-after-checks",
            active.state is ExtensionState.ACTIVE,
            "install swaps the scope's active pointer only after digest "
            "re-verification and a truthful loader identity check",
        )
        loaded = await self._load(active)
        assert active.artifact_sha256 is not None
        stage.evidence["notary-1-0-0-active"] = {
            "install_id": active.install_id,
            "artifact_sha256": active.artifact_sha256,
            "loaded_module": f"proof_ext_{active.artifact_sha256[:12]}.acme_notary.plugin",
            "loaded_from": str(loaded.install_dir),
        }
        stage.check(
            "code-runs-only-from-artifact",
            loaded.install_dir.is_relative_to(self.install_root),
            "the loaded entrypoint lives under the install root — extracted "
            "artifact bytes, never a source-tree or editable path",
        )
        return active

    async def stage_invoke_and_observe(
        self, notary_active: ExtensionInstallRecord
    ) -> ExtensionInstallRecord:
        """Invoke through the context seam; observe the audit trails."""
        stage = self._stage("invoke-observe")
        seal_observation = self._invoke(notary_active, "seal", "audit-line-1")
        stage.check(
            "extension-invoked-through-seam",
            seal_observation.outcome == "ok",
            "the active extension's handler runs through the host context "
            "with caller/scope/grant provenance recorded",
        )
        greeter = await self._inspect(GREETER_1_0_0)
        greeter_authorized = await self._authorize(
            greeter, "zero-authority greeter; dependency now active"
        )
        greeter_active = await self._install(greeter_authorized)
        stage.check(
            "dependency-order-satisfied-install",
            greeter_active.state is ExtensionState.ACTIVE,
            "with acme.notary active, greeter inspects, authorizes and "
            "installs cleanly — the dependency discipline holds at both ends",
        )
        await self._load(greeter_active)
        greet = self._invoke(greeter_active, "greet", "workspace")
        stage.check(
            "scope-facts-are-caller-scoped",
            greet.outcome == "ok" and WORKSPACE in greet.result_repr,
            f"the greeter greets from the caller's own workspace "
            f"({WORKSPACE}) and from nothing else — the context exposes only "
            "its own scope",
        )
        probe = self._invoke(greeter_active, "probe_undeclared")
        stage.check(
            "undeclared-capability-denied",
            probe.outcome == "denied:undeclared-capability"
            and probe.capability_requests[-1]["outcome"] == "denied",
            "reaching for workspace.storage.write without a declaration is "
            "refused by the context fence and recorded as a denial",
        )
        stage.evidence["invocation_count"] = len(self.invocations)
        return greeter_active

    async def stage_denials(self) -> Stage:
        """Cross-Workspace probing is refused at the service boundary."""
        stage = self._stage("denials")
        active = await self.service.active(self.scope, "acme.notary")
        assert active is not None
        foreign_scope = ExtensionScope(org_id=ORG, workspace_id=WORKSPACE_B)
        crossed, decided = False, False
        try:
            await self.service.get(active.install_id, scope=foreign_scope)
            crossed = True
        except UnknownInstall:
            crossed = False
        try:
            await self.service.authorize(
                active.install_id,
                actor="operator:mallory",
                scope=foreign_scope,
                approve=True,
                reason="foreign workspace attempting to decide ws-7's install",
            )
            decided = True
        except UnknownInstall:
            decided = False
        stage.check(
            "cross-workspace-read-denied",
            crossed is False,
            "an operator scoped to ws-999 cannot see ws-7's install record "
            "(indistinguishable from a missing id)",
        )
        stage.check(
            "cross-workspace-decision-denied",
            decided is False,
            "a foreign workspace cannot authorize or deny another workspace's install",
        )
        stage.evidence["foreign_scope"] = foreign_scope.describe
        return stage

    async def stage_update_and_fence(self) -> Stage:
        """Update: same-authority upgrade; broader authority hits the fence."""
        stage = self._stage("update-fence")
        first = await self.service.active(self.scope, "acme.notary")
        assert first is not None
        first_history = await self.store.transitions_for(first.install_id)

        upgrade = await self._inspect(NOTARY_1_1_0)
        stage.check(
            "same-authority-upgrade-still-needs-a-decision",
            upgrade.state is ExtensionState.AWAITING_AUTHORIZATION
            and upgrade.authority_delta == (),
            "a same-authority upgrade is parked for an explicit decision, "
            "exactly like a first install",
        )
        upgraded = await self._authorize(upgrade, "same authority; reproducible rebuild")
        upgraded_active = await self._install(upgraded)
        now_active = await self.service.active(self.scope, "acme.notary")
        assert now_active is not None
        stage.check(
            "active-pointer-moved",
            upgraded_active.version == "1.1.0" and now_active.version == "1.1.0",
            "after approval the scope's active pointer names 1.1.0",
        )
        await self._load(upgraded_active)
        superseded_history = await self.store.transitions_for(first.install_id)
        stage.check(
            "superseded-version-still-queryable",
            len(superseded_history) == len(first_history) + 1
            and superseded_history[0].install_id == first.install_id
            and superseded_history[-1].to_state is ExtensionState.SUPERSEDED,
            "the superseded 1.0.0 record keeps its full audited transition "
            "trail, closed by an explicit SUPERSEDED row naming the actor — "
            "deactivation is not deletion",
        )

        broader = await self._inspect(NOTARY_2_0_0)
        stage.evidence["broader-request"] = {
            "install_id": broader.install_id,
            "requested_permissions": list(broader.requested_permissions),
            "authority_delta": list(broader.authority_delta),
        }
        stage.check(
            "broader-authority-named-in-delta",
            broader.authority_delta == (STORAGE_CAPABILITY,),
            "the upgrade that wants more authority names exactly the new "
            "permission in its authority delta",
        )
        fenced = False
        try:
            await self.service.install(
                broader.install_id,
                actor=OPERATOR,
                scope=self.scope,
                payload=self.artifacts[NOTARY_2_0_0],
            )
        except InvalidTransition:
            fenced = True
        stage.check(
            "install-before-reauthorization-fenced",
            fenced,
            "installing the broader version before an explicit decision is "
            "refused by the state machine",
        )
        still_active = await self.service.active(self.scope, "acme.notary")
        assert still_active is not None
        stage.check(
            "fence-left-prior-version-active",
            still_active.version == "1.1.0",
            "the fenced attempt left 1.1.0 active — no partial upgrade",
        )
        transferred = True
        try:
            await self.service.install(
                upgrade.install_id,
                actor=OPERATOR,
                scope=self.scope,
                payload=self.artifacts[NOTARY_2_0_0],
            )
        except ArtifactMismatch:
            transferred = False
        stage.check(
            "authorization-does-not-transfer-across-versions",
            transferred is False,
            "presenting 2.0.0's bytes to the 1.1.0 install id is an "
            "ArtifactMismatch; a grant never covers different bytes",
        )
        denied = await self.service.authorize(
            broader.install_id,
            actor=OPERATOR,
            scope=self.scope,
            approve=False,
            reason="broader authority not granted this quarter",
        )
        stage.check(
            "denied-upgrade-is-terminal",
            denied.state is ExtensionState.DENIED,
            "denial is terminal: the broader request can never reach ACTIVE "
            "without a fresh inspection",
        )
        after_denial = await self.service.active(self.scope, "acme.notary")
        assert after_denial is not None
        stage.check(
            "denial-kept-prior-version-active",
            after_denial.version == "1.1.0",
            "after denial the workspace still runs the last authorized version",
        )
        retry = await self._inspect(NOTARY_2_0_0)
        stage.check(
            "terminal-record-gates-nothing",
            retry.install_id != broader.install_id,
            "a denied record is terminal; a fresh request opens a new "
            "authorization track instead of resurrecting the old one",
        )
        approved = await self._authorize(
            retry, "storage write reviewed and granted for the notary audit log"
        )
        broader_active = await self._install(approved)
        stage.check(
            "reauthorized-upgrade-activates",
            broader_active.state is ExtensionState.ACTIVE
            and broader_active.granted_permissions == (STORAGE_CAPABILITY,),
            "with explicit re-authorization the upgrade activates and the "
            "grant is frozen to the new set",
        )
        await self._load(broader_active)
        sealed = self._invoke(broader_active, "seal", "audit-line-2")
        stage.check(
            "newly-granted-capability-usable",
            sealed.outcome == "ok" and sealed.capability_requests[-1]["outcome"] == "granted",
            "the same handler that would have been refused under the old "
            "grant now uses the granted capability",
        )
        stage.evidence["notary-final"] = {
            "install_id": broader_active.install_id,
            "version": broader_active.version,
            "granted": list(broader_active.granted_permissions),
        }
        return stage

    async def stage_post_install_lifecycle(self) -> Stage:
        """Post-install lifecycle (#954): disable, pin, rollback, remove.

        Every operation is an explicit, audited operator decision on the same
        governed records — none re-runs the loader, none widens a grant, and
        none ever deletes evidence.
        """
        stage = self._stage("post-install-lifecycle")
        active = await self.service.active(self.scope, "acme.notary")
        assert active is not None
        served_before = await self.store.installed_versions(self.scope)
        trail_len_before = len(await self.store.transitions_for(active.install_id))

        disabled = await self.service.disable(
            active.install_id,
            actor=OPERATOR,
            scope=self.scope,
            reason="suspending the notary for incident triage",
        )
        pointer_after_disable = await self.service.active(self.scope, "acme.notary")
        served_after_disable = await self.store.installed_versions(self.scope)
        stage.check(
            "disable-stops-serving-preserves-everything",
            disabled.state is ExtensionState.DISABLED
            and pointer_after_disable is None
            and "acme.notary" in served_before
            and "acme.notary" not in served_after_disable
            and served_after_disable.get("acme.greeter") == served_before.get("acme.greeter")
            and disabled.granted_permissions == active.granted_permissions,
            "disabling drops the active pointer so the version stops being "
            "served — this extension only — while the frozen grant and the "
            "audit trail stay intact and other extensions keep running",
        )

        reenabled = await self.service.enable(
            disabled.install_id,
            actor=OPERATOR,
            scope=self.scope,
            reason="triage clean; restoring service",
        )
        stage.check(
            "re-enable-reuses-the-frozen-activation",
            reenabled.state is ExtensionState.ACTIVE
            and reenabled.install_attempts == active.install_attempts
            and reenabled.granted_permissions == active.granted_permissions,
            "re-enabling re-serves the already-activated artifact under its "
            "frozen grant — no loader run, no authority change",
        )

        pinned = await self.service.set_pinned(
            reenabled.install_id,
            actor=OPERATOR,
            scope=self.scope,
            pinned=True,
            reason="holding 2.0.0 through the change freeze",
        )
        pin_rows = [
            row
            for row in await self.store.transitions_for(pinned.install_id)
            if row.reason.startswith("pin:")
        ]
        stage.check(
            "pin-is-an-audited-same-state-decision",
            pinned.pinned
            and pinned.state is ExtensionState.ACTIVE
            and bool(pin_rows)
            and pin_rows[-1].actor == OPERATOR,
            "pinning is a flag held by an explicit, audited same-state "
            "decision — the trail carries who and why without reading as a "
            "state change",
        )

        fenced = False
        try:
            await self.service.rollback(
                actor=OPERATOR,
                scope=self.scope,
                extension_id="acme.notary",
                to_version="1.1.0",
                reason="must be fenced while pinned",
            )
        except VersionPinned:
            fenced = True
        still_active = await self.service.active(self.scope, "acme.notary")
        stage.check(
            "pinned-version-fences-rollback",
            fenced
            and still_active is not None
            and still_active.version == "2.0.0"
            and still_active.pinned,
            "while the active version is pinned, rolling back to another "
            "version is fenced until an explicit unpin decision",
        )

        await self.service.set_pinned(
            pinned.install_id,
            actor=OPERATOR,
            scope=self.scope,
            pinned=False,
            reason="change freeze lifted",
        )
        restored = await self.service.rollback(
            actor=OPERATOR,
            scope=self.scope,
            extension_id="acme.notary",
            to_version="1.1.0",
            reason="2.0.0 misbehaves; returning to the last good notary",
        )
        retired = await self.store.latest_record(self.scope, "acme.notary", "2.0.0")
        stage.check(
            "rollback-restores-a-prior-authorized-version",
            restored.version == "1.1.0"
            and restored.state is ExtensionState.ACTIVE
            and retired is not None
            and retired.state is ExtensionState.DISABLED
            and STORAGE_CAPABILITY not in restored.granted_permissions,
            "rollback moves the active version back to a previously "
            "authorized version under its frozen grant — the broader 2.0.0 "
            "authority leaves the served set without executing anything",
        )

        oldest = await self.store.latest_record(self.scope, "acme.notary", "1.0.0")
        assert oldest is not None
        removed = await self.service.remove(
            oldest.install_id,
            actor=OPERATOR,
            scope=self.scope,
            reason="1.0.0 retired from the catalog",
        )
        still_queryable = await self.service.get(oldest.install_id, scope=self.scope)
        rollback_to_removed_refused = False
        try:
            await self.service.rollback(
                actor=OPERATOR,
                scope=self.scope,
                extension_id="acme.notary",
                to_version="1.0.0",
                reason="must be refused: removed is terminal",
            )
        except InvalidTransition:
            rollback_to_removed_refused = True
        stage.check(
            "removal-is-terminal-but-history-outlives-it",
            removed.state is ExtensionState.REMOVED
            and still_queryable.state is ExtensionState.REMOVED
            and rollback_to_removed_refused,
            "REMOVED never reactivates — a rollback to it is refused — yet "
            "the record, its grant and its trail stay queryable",
        )

        new_rows = (await self.store.transitions_for(active.install_id))[trail_len_before:]
        stage.check(
            "every-lifecycle-step-is-audited",
            bool(new_rows)
            and all(row.actor == OPERATOR and row.reason.strip() for row in new_rows)
            and all(
                row.from_state != row.to_state or row.reason.startswith(("pin:", "unpin:"))
                for row in new_rows
            ),
            "every lifecycle decision lands on the audit trail with an "
            "accountable actor and a recorded reason; same-state pin rows "
            "are the only rows that do not change state",
        )
        stage.evidence["lifecycle"] = {
            "disabled_install_id": disabled.install_id,
            "rollback_restored": {"version": restored.version, "install_id": restored.install_id},
            "removed_install_id": removed.install_id,
            "audited_rows": len(new_rows),
        }
        return stage

    async def stage_catalog_tamper_and_outage(self) -> Stage:
        """Catalog truth cannot rewrite installed truth; outage is survivable."""
        stage = self._stage("catalog-integrity")
        active = await self.service.active(self.scope, "acme.notary")
        assert active is not None and active.artifact_sha256 is not None
        active_digest = active.artifact_sha256

        tampered = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        for entry in tampered["entries"]:
            if entry["id"] == "acme.notary" and entry["version"] == "1.1.0":
                entry["package_sha256"] = "e" * 64
        self.catalog_path.write_text(json.dumps(tampered, sort_keys=True, indent=2))
        _, tampered_snapshot = load_private_catalog(self.catalog_path)
        stage.check(
            "tampered-snapshot-is-a-different-snapshot",
            tampered_snapshot != self.snapshot_sha256,
            "rewriting the catalog produces a new snapshot digest — "
            "provenance records which snapshot each install came from",
        )
        now_active = await self.service.active(self.scope, "acme.notary")
        assert now_active is not None and now_active.artifact_sha256 is not None
        stage.check(
            "tamper-cannot-rewrite-active-truth",
            now_active.artifact_sha256 == active_digest,
            "the active install still carries the artifact digest that was "
            "authorized, not the one the catalog now claims",
        )
        tampered_catalog, _ = load_private_catalog(self.catalog_path)
        tampered_lock = resolve_lock([RootRequest("acme.greeter", "*")], tampered_catalog)
        tampered_entry = tampered_lock.get("acme.notary")
        assert tampered_entry is not None
        stage.check(
            "tampered-snapshot-yields-tampered-pin-not-silent-reuse",
            tampered_entry.package_sha256 == "e" * 64,
            "resolution over the tampered snapshot pins the tampered "
            "identity, which the registry would refuse at materialization as "
            "a same-version different-bytes conflict — never a silent swap",
        )

        self.catalog_path.unlink()
        gone = False
        try:
            load_private_catalog(self.catalog_path)
        except FileNotFoundError:
            gone = True
        stage.check(
            "catalog-outage-blocks-only-discovery",
            gone,
            "with the catalog gone, discovery fails loudly — nothing else",
        )
        observation = self._invoke(active, "seal", "post-outage-line")
        stage.check(
            "installed-extension-survives-outage",
            observation.outcome == "ok",
            "the installed, digest-pinned extension still invokes with no catalog present",
        )
        history = await self.service.transitions(active.install_id, scope=self.scope)
        stage.check(
            "audit-trail-survives-outage",
            len(history) >= 4,
            "the activation audit trail stays queryable during the outage",
        )
        stage.evidence["active_version"] = active.version
        return stage

    async def stage_durable_restart(self) -> Stage:
        """Restart durability: the registry layer survives; locks reproduce."""
        stage = self._stage("durable-restart")
        assert self.lock is not None
        fetcher = PinnedArtifactFetcher(self.artifacts, self.manifests)

        async def fresh_store(path: Path) -> tuple[SqliteExtensionInstallStore, Any]:
            conn = await aiosqlite.connect(path)
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
            await store.register_publisher(self.publisher)
            return store, conn

        first, first_conn = await fresh_store(self.registry_db)
        records = await materialize_lock(self.lock, first, fetcher, now=EPOCH)
        await first_conn.close()
        materialized = {
            (record.identity.extension_name, record.identity.semantic_version) for record in records
        }
        stage.check(
            "lock-materializes-through-real-verification",
            materialized == {("acme.greeter", "1.0.0"), ("acme.notary", "1.1.0")},
            "the lock alone reinstalls the exact pinned identities through "
            "digest and signature verification",
        )

        reopened_conn = await aiosqlite.connect(self.registry_db)
        reopened = SqliteExtensionInstallStore(reopened_conn)
        history = await reopened.install_history("acme.notary")
        assert history, "materialized notary record must be queryable after restart"
        evidence = history[0].evidence
        stage.check(
            "history-survives-restart",
            {
                (record.identity.semantic_version, record.identity.package_sha256)
                for record in history
            }
            == {("1.1.0", sha256_hex(self.artifacts[NOTARY_1_1_0]))},
            "after closing and reopening the database, install history "
            "returns the identical identity",
        )
        stage.check(
            "trust-evidence-survives-restart",
            evidence.verified
            and evidence.verifier_key_fingerprint == self.publisher.signing_key_fingerprint
            and evidence.subject_sha256 == sha256_hex(self.artifacts[NOTARY_1_1_0]),
            "the minted trust evidence — key fingerprint, policy, subject "
            "digest — reads back from the durable row",
        )
        provenance = history[0].provenance
        stage.check(
            "catalog-provenance-survives-restart",
            provenance.catalog_url == CATALOG_SOURCE
            and provenance.catalog_snapshot_sha256 == self.snapshot_sha256,
            "each durable record keeps the catalog URL and snapshot digest it was installed from",
        )
        await reopened_conn.close()

        replica_path = self.scratch / "replica-registry.sqlite3"
        replica, replica_conn = await fresh_store(replica_path)
        replica_records = await materialize_lock(self.lock, replica, fetcher, now=EPOCH)
        await replica_conn.close()

        def identities(records_in: list) -> list:
            return sorted(
                (
                    record.identity.extension_name,
                    record.identity.semantic_version,
                    record.identity.package_sha256,
                    record.identity.manifest_sha256,
                )
                for record in records_in
            )

        stage.check(
            "lock-reproduces-ecosystem-on-clean-host",
            identities(records) == identities(replica_records),
            "a clean registry rebuilt from the lock holds the identical "
            "identity set — reproducibility, not best effort",
        )
        stage.note = (
            "Activation-state restart durability (the B2 activation store) is "
            "in-memory by design at this base commit; the durable registry "
            "layer (B1 + SQLite) is what restart proves here. The #954 "
            "post-install operations — disable, pin, rollback, remove — are "
            "reachable at the service layer and pinned by the "
            "post-install-lifecycle stage above, but their durability beyond "
            "the process lifetime is not provable at this base; the "
            "properties they must preserve — append-only records, denial "
            "leaves the prior version active, history queryable after "
            "deactivation — are pinned by the stages above."
        )
        return stage

    def stage_canonical_truth_untouched(self) -> Stage:
        """The extension subsystem has no path into canonical Goal/Run truth."""
        stage = self._stage("canonical-truth-boundary")
        extensions_dir = (
            Path(__file__).resolve().parents[1]
            / "packages"
            / "maistro-core"
            / "src"
            / "maistro"
            / "extensions"
        )
        forbidden: list[str] = []
        for source in sorted(extensions_dir.glob("*.py")):
            for line in source.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and any(
                    name in stripped for name in ("maistro.runs", "maistro.goals", "maistro.graph")
                ):
                    forbidden.append(f"{source.name}: {stripped}")
        stage.check(
            "no-import-path-into-canonical-truth",
            not forbidden,
            "no module under maistro/extensions imports maistro.runs, "
            "maistro.goals or maistro.graph — extension status has no write "
            "path into canonical Goal/Run truth by construction"
            + ("" if not forbidden else f" (found: {'; '.join(forbidden)})"),
        )
        stage.evidence["scanned_modules"] = sorted(p.name for p in extensions_dir.glob("*.py"))
        return stage

    # -- orchestration ---------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        self.stage_build_catalog()
        self.stage_discover()
        notary_record, _ = await self.stage_inspect()
        notary_active = await self.stage_authorize_and_install(notary_record)
        await self.stage_invoke_and_observe(notary_active)
        await self.stage_denials()
        await self.stage_update_and_fence()
        await self.stage_post_install_lifecycle()
        await self.stage_catalog_tamper_and_outage()
        await self.stage_durable_restart()
        self.stage_canonical_truth_untouched()
        return self.report()

    # -- report ------------------------------------------------------------------

    def deterministic_core(self) -> dict[str, Any]:
        """The wall-clock-free evidence: lock, checks, invocations."""
        return {
            "lock": self.lock.to_json() if self.lock is not None else None,
            "catalog_snapshot_sha256": self.snapshot_sha256,
            "stages": [
                {"name": stage.name, "checks": stage.checks, "note": stage.note}
                for stage in self.stages
            ],
            "invocations": [observation.core() for observation in self.invocations],
        }

    def report(self) -> dict[str, Any]:
        stages_json = [
            {
                "name": stage.name,
                "ok": stage.ok,
                "note": stage.note,
                "checks": stage.checks,
                "evidence": stage.evidence,
            }
            for stage in self.stages
        ]
        checks_total = sum(len(stage.checks) for stage in self.stages)
        checks_failed = sum(1 for stage in self.stages for check in stage.checks if not check["ok"])
        core = self.deterministic_core()
        return {
            "schema": PROOF_SCHEMA,
            "issue": "M9-J3 (#981)",
            "base_commit": _base_commit(),
            "scope": {"org_id": ORG, "workspace_id": WORKSPACE},
            "publisher": {
                "publisher_id": PUBLISHER_ID,
                "signing_key_fingerprint": self.publisher.signing_key_fingerprint,
            },
            "stages": stages_json,
            "invocations": [observation.to_json() for observation in self.invocations],
            "summary": {
                "stages": len(self.stages),
                "stages_ok": sum(1 for stage in self.stages if stage.ok),
                "checks_total": checks_total,
                "checks_failed": checks_failed,
            },
            "deterministic_core_sha256": sha256_hex(
                json.dumps(core, sort_keys=True).encode("utf-8")
            ),
            "wall_clock_note": (
                "audit timestamps (transition at, invocation at, registry "
                "installed_at) are wall-clock or sequence-advanced and are "
                "excluded from the deterministic core digest"
            ),
        }


def _base_commit() -> str:
    """The commit the proof ran against, for the lineage header."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the human-readable lineage document."""
    lines: list[str] = []
    lines.append("# Extension lifecycle proof — lineage")
    lines.append("")
    lines.append(
        f"Schema `{report['schema']}` · issue {report['issue']} · base `{report['base_commit']}`"
    )
    lines.append("")
    lines.append(
        "Every stage below was executed against the platform's production "
        "seams in one run of "
        "`python scripts/extension_lifecycle_proof.py --out <dir>`. The "
        "machine-readable twin of this document is `lineage.json` in the "
        "same directory; its deterministic core digest is "
        f"`{report['deterministic_core_sha256'][:16]}…`."
    )
    lines.append("")
    for stage in report["stages"]:
        marker = "✅" if stage["ok"] else "❌"
        lines.append(f"## {marker} {stage['name']}")
        lines.append("")
        for check in stage["checks"]:
            marker = "pass" if check["ok"] else "FAIL"
            lines.append(f"- {marker}: `{check['id']}` — {check['detail']}")
        for key, value in stage["evidence"].items():
            rendered = json.dumps(value, sort_keys=True, default=str)
            if len(rendered) > 220:
                rendered = rendered[:217] + "…"
            lines.append(f"  - evidence `{key}`: {rendered}")
        if stage.get("note"):
            lines.append("")
            lines.append(f"> Boundary note: {stage['note']}")
        lines.append("")
    lines.append("## Invocations observed")
    lines.append("")
    for observation in report["invocations"]:
        lines.append(
            f"- `{observation['invocation_id']}` {observation['extension']['id']} "
            f"{observation['extension']['version']} · {observation['handler']} · "
            f"{observation['outcome']} · caller `{observation['caller']}` · scope "
            f"{observation['scope']['org_id']}/{observation['scope']['workspace_id']}"
        )
    lines.append("")
    summary = report["summary"]
    lines.append(
        f"**Summary**: {summary['stages_ok']}/{summary['stages']} stages ok, "
        f"{summary['checks_total'] - summary['checks_failed']}/{summary['checks_total']} "
        "checks passed."
    )
    lines.append("")
    return "\n".join(lines)


async def _run_proof(scratch: Path) -> dict[str, Any]:
    proof = LifecycleProof(scratch)
    return await proof.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="directory for lineage.json/md")
    parser.add_argument(
        "--scratch",
        type=Path,
        default=None,
        help="keep the scratch directory here instead of a temp dir (debugging)",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the verdict line")
    args = parser.parse_args(argv)

    if args.scratch is not None:
        args.scratch.mkdir(parents=True, exist_ok=True)
        scratch, cleanup = args.scratch, False
    else:
        scratch = Path(tempfile.mkdtemp(prefix="extension-lifecycle-proof-"))
        cleanup = True

    try:
        report = asyncio.run(_run_proof(scratch))
    finally:
        if cleanup:
            shutil.rmtree(scratch, ignore_errors=True)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "lineage.json").write_text(
        json.dumps(report, sort_keys=True, indent=2), encoding="utf-8"
    )
    (args.out / "lineage.md").write_text(render_markdown(report), encoding="utf-8")
    summary = report["summary"]
    verdict = (
        "PROVED" if summary["checks_failed"] == 0 else f"FAILED ({summary['checks_failed']} checks)"
    )
    if not args.quiet:
        print(f"lineage: {args.out / 'lineage.md'}")
    print(
        f"{verdict}: {summary['stages_ok']}/{summary['stages']} stages, "
        f"{summary['checks_total'] - summary['checks_failed']}/{summary['checks_total']} checks"
    )
    return 0 if summary["checks_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
