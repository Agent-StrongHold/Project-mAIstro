"""The local public-SDK host harness and extension-family conformance runner
(M9-H2, #974).

A third-party extension project installs this distribution and runs its
conformance suite in its own CI, without cloning the MAIstro repository and
without a MAIstro deployment: the runtime is standard library only, the
contracts enforced are the public extension contracts (the versioned
`extension.json` manifest, the data-only entrypoint protocol, the
declaration→grant→context least-authority pipeline), and the result is a
machine-readable report that names the exact contract version, every
executed and skipped case, and — structurally — that a local harness result
is not platform certification.

Boundary, enforced and tested: the harness **loads** extension code; it is
never an extension's import. Extensions are subject, not consumer. The
public surface below is the whole seam:

- `contract` — the contract/vocabulary constants and `ContractError`;
- `manifest` — strict manifest validation (no code runs during it);
- `grants` — declaration → grant resolution (grant ⊆ declaration, always);
- `fixtures` — canonical identity/Workspace/Invocation test fixtures;
- `context` — the least-authority context a loaded handler receives;
- `lifecycle` — discover → validate → grant → load → invoke → release;
- `families` — the family plug-in registry and the conformance cases;
- `backends` — real-backend requirements: fail closed, never silently skip;
- `report` — the machine-readable report and its schema version;
- `runner` — `run_conformance`, the engine that ties it together;
- `reference` — the built-in reference subject, materialized on demand;
- `cli` — `maistro-ext-harness run`, the CI invocation shape.
"""

from __future__ import annotations

import importlib.metadata

from maistro_ext_harness.backends import Backend, BackendRegistry
from maistro_ext_harness.context import (
    ExtensionContext,
    IdentityView,
    InvocationView,
    WorkspaceView,
    build_context,
)
from maistro_ext_harness.contract import (
    CAPABILITIES,
    CONTRACT_VERSION,
    DATA_SCOPES,
    EFFECTS,
    FAMILIES,
    REPORT_SCHEMA,
    SUPPORTED_CONTRACT_MAJORS,
    ContractError,
)
from maistro_ext_harness.fixtures import (
    FIXTURE_PREFIX,
    FixtureSet,
    IdentityFixture,
    InvocationFixture,
    WorkspaceFixture,
    reference_fixtures,
)
from maistro_ext_harness.grants import Grant, GrantPolicy, GrantPolicyError, resolve_grants
from maistro_ext_harness.lifecycle import (
    DiscoveredExtension,
    EntrypointMissing,
    ExtensionHost,
    HandlerMissing,
    HandlerRaised,
    HostError,
    InvocationCancelled,
    LoadedExtension,
    SubjectNotDiscovered,
)
from maistro_ext_harness.manifest import (
    DependencyRef,
    EntrypointSpec,
    ExtensionManifest,
    ManifestRejected,
    load_manifest_bytes,
    load_manifest_file,
)
from maistro_ext_harness.reference import (
    REFERENCE_EXTENSION_ID,
    write_failing_probe_extension,
    write_reference_extension,
)
from maistro_ext_harness.report import (
    CERTIFICATION_NOTE,
    CaseRecord,
    CaseStatus,
    ConformanceReport,
    SubjectRecord,
)
from maistro_ext_harness.runner import RunRequest, run_conformance

try:
    __version__ = importlib.metadata.version("maistro-ext-harness")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - unbuilt checkout
    __version__ = "0.9.0-dev"

__all__ = [
    "CAPABILITIES",
    "CERTIFICATION_NOTE",
    "CONTRACT_VERSION",
    "DATA_SCOPES",
    "EFFECTS",
    "FAMILIES",
    "FIXTURE_PREFIX",
    "REFERENCE_EXTENSION_ID",
    "REPORT_SCHEMA",
    "SUPPORTED_CONTRACT_MAJORS",
    "Backend",
    "BackendRegistry",
    "CaseRecord",
    "CaseStatus",
    "ConformanceReport",
    "ContractError",
    "DependencyRef",
    "DiscoveredExtension",
    "EntrypointMissing",
    "EntrypointSpec",
    "ExtensionContext",
    "ExtensionHost",
    "ExtensionManifest",
    "FixtureSet",
    "Grant",
    "GrantPolicy",
    "GrantPolicyError",
    "HandlerMissing",
    "HandlerRaised",
    "HostError",
    "IdentityFixture",
    "IdentityView",
    "InvocationCancelled",
    "InvocationFixture",
    "InvocationView",
    "LoadedExtension",
    "ManifestRejected",
    "RunRequest",
    "SubjectNotDiscovered",
    "SubjectRecord",
    "WorkspaceFixture",
    "WorkspaceView",
    "build_context",
    "load_manifest_bytes",
    "load_manifest_file",
    "reference_fixtures",
    "resolve_grants",
    "run_conformance",
    "write_failing_probe_extension",
    "write_reference_extension",
]
