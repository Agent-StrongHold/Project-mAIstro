---
inventory-delta:
  packages/maistro-core/tests: +8
---
# 942-m9e-family-install

Issue #942 (EPIC M9-E) — the epic-level acceptance the family lanes could not
pin alone: **one external-style provider, connector and tool package can be
installed independently**, and the installed packages meet the epic's
cross-cutting criteria (canonical seams, secret authority, undeclared access
blocked, shared conformance).

**+8 `packages/maistro-core/tests/extensions/test_m9e_family_install.py`**
(`TestFamilyPackagesInstallIndependently` 4, `TestInstalledFamilySecuritySeams`
2, `TestRegistrationIsolationAndSharedConformance` 2), each driving production
seams only:

- **Governed install, per family (4)** — the three external-style packages
  (`acme.inference` provider, `acme.repo_feed` connector, `acme.notary` tool)
  each walk `ExtensionInstallService.inspect → authorize → install` as
  artifact bytes and load only from the installed artifact (digest-named
  import, plugin-identity check). The provider registers models into the
  canonical registry through `register_adapter_models` (conformance runs at
  registration; spec refuses secret-shaped fields). The connector passes
  `run_connector_conformance` and ingests through the host `SyncEngine` with
  full provenance. The tool's contract is parsed from the artifact's own
  `extension.json` bytes (digest-pinned), registers into
  `ExtensionToolCatalog`, and its state-changing handler executes through the
  canonical Invocation seam with run/node_run/attempt/workspace/actor
  attribution. All three install into one host as three distinct records with
  no cross-dependency.

- **Security seams on installed packages (2)** — the installed connector
  cannot sync an undeclared Workspace (refused before connector code runs, no
  records or checkpoints), the session refuses undeclared secret names, and a
  declared-but-unprovisioned name stays an operator `LookupError`. Plus the
  committed teeth for the activation identity pin: an artifact whose
  entrypoint misdeclares its id (plugin name `acme.evil` against an embedded
  contract declaring `acme-labs.notary`) passes inspect → authorize (bytes,
  not behavior) and is refused at activation — `ExtensionLifecycleError`, the
  record persists `FAILED` with the mismatch in `failure_reason`, and neither
  an active record nor a retained activation exists afterwards.

- **Isolation + shared suites (2)** — a lying adapter's package *installs*
  (the lifecycle authorizes bytes, not behavior) but its registration is
  refused by the shared provider suite with nothing recorded, while the
  connector install stays ACTIVE and conformant; the built-in reference
  adapter/connector and the external-style implementations pass the identical
  conformance runs (AC6, "where semantically equivalent").

Teeth evidence: the identity-mismatch refusal is a committed test
(`test_misdeclared_plugin_identity_is_refused_and_recorded_failed`), verified
live to fail when the loader's identity pin is disabled and pass when enabled.
The suite-level negatives (undeclared Workspace/secret, conformance-lying
adapter, secret-shaped spec field) are asserted inside the tests themselves.
Registration is also driven from the install-time activation itself — the
host loader captures what the governed install built
(`InstalledFamilyLoader.activations`) and every registration exercises that
captured object, never a re-load of the presented bytes.

Scope note: no production source changed; the epic lane's child SDKs (#961
provider, #963 connector, #964 tool/Skill, and their shared conformance) were
already merged at the base commit. This change only composes them through the
governed install lifecycle, which no prior suite did.
