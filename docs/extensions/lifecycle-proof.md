# The extension lifecycle proof (M9-J3, issue #981)

One reproducible script, one test suite, and this document make the external
extension lifecycle reviewable end to end. The script runs the **whole
lifecycle** against the platform's real production seams and emits the
evidence as a machine-readable `lineage.json` and a per-run human-readable
`lineage.md`:

```console
uv run python scripts/extension_lifecycle_proof.py --out /tmp/lifecycle-lineage
# PROVED: 13/13 stages, 62/62 checks
```

The suite that pins the harness is
[`packages/maistro-core/tests/extensions/test_lifecycle_proof.py`](../../packages/maistro-core/tests/extensions/test_lifecycle_proof.py)
— including the two negative pins (artifact path escapes are refused; a
plugin that lies about its identity is recorded `FAILED` with nothing
active) and the determinism pin (two runs produce the identical
`deterministic_core_sha256`).

The proof is also a CI entry point, not only a test fixture: the Formal
Conformance workflow (`.github/workflows/formal-conformance.yml`) runs the
script directly on every PR, merge-group candidate, and protected-branch
push, and uploads the emitted lineage as a job artifact — so every candidate
re-proves the lifecycle against itself and the reachability gate sees a real
rooted entry point rather than test-only usage.

## What the lifecycle is, stage by stage

The proof's scenario is one operator (`operator:alice`) in one canonical
Workspace scope (`org-acme`/`ws-7`) installing a dependency-carrying
extension (`acme.greeter` → `acme.notary`) from a private organizational
catalog, invoking it, probing its fences, upgrading it, executing the
installed artifact inside a canonical Run, and restarting around it. Every
stage maps to a production seam — nothing in the script re-implements
platform behavior:

| Stage | Production seam exercised | What is proven |
|---|---|---|
| build-catalog | (proof-side data) | a private catalog file of digest-pinned, signed offerings; every manifest pins its artifact sha256 |
| distribution | `maistro.extensions.catalog_service.CatalogService` (#979) | the private org catalog serves publisher metadata, search/filter, and per-version manifest detail anchored to the pinned digests; the identical signed snapshot is seeded independently into a second organization's private catalog, which then serves the identical digest-anchored identity set, and an org that was never seeded sees nothing — per-org snapshot fidelity, not public distribution (the platform exposes no cross-org publish/consume seam) |
| discover | `maistro.extensions.resolution.resolve_lock` | one operator ask resolves transitively (`acme.notary ^1.0.0` → 1.1.0, never 2.0.0), pins full identity + catalog snapshot digest, is byte-reproducible, and explains its own selection |
| inspect | `ExtensionInstallService.inspect` | manifest-only evaluation; dependency order enforced (greeter before its dependency is `REJECTED`, truthfully recorded); candidates park in `AWAITING_AUTHORIZATION`; permissions display from the immutable snapshot |
| authorize-install | `authorize` + `install` + host loader | the grant freezes to the inspected set; activation runs only after every check; the loaded entrypoint lives under the install root — extracted artifact bytes, never a source-tree or editable path |
| invoke-observe | loaded entrypoint + host context | the handler runs through the grant-fenced context; scope facts are caller-scoped; an undeclared capability request is refused and recorded as a denial |
| denials | `ExtensionInstallService` scope containment | a foreign Workspace can neither read nor decide this scope's installs (`UnknownInstall`, indistinguishable from a missing id) |
| update-fence | authority delta + state machine | same-authority upgrade still needs an explicit decision; the broader-authority request names its delta; installing before re-authorization is fenced; denial is terminal and leaves the prior version active; grants never transfer across versions (`ArtifactMismatch`) |
| canonical-execution | `AttemptExecutionService` + `PythonExecutionRuntime` + `ExtensionHost`/`GovernedEffectRoute`/`GovernedInvocationExecutionService` | the installed, re-authorized artifact executes inside a canonical `Graph → Run → NodeRun → Attempt`; its declared effect crosses the governed `Capability → Provider → Binding → Invocation` seam; the canonical Invocation row carries the Run → NodeRun → Attempt correlation; the event stream carries the extension provenance; one artifact digest links catalog entry → install record → executed code |
| catalog-integrity | install records vs. snapshot digests | a tampered catalog is a different snapshot and cannot rewrite installed truth; a catalog outage blocks only discovery — installed extensions keep invoking and the audit trail stays queryable |
| disable-rollback-remove | `ExtensionInstallService.disable`/`resume`/`rollback`/`remove` (#954) | disabling stops new use structurally (the active pointer is cleared) while the record keeps its frozen grant and audited trail; resume re-crosses the loader seam with the same bound artifact; rollback restores the superseded 1.1.0, truthfully narrows authority back to its frozen grant (the storage reach is denied again), and cannot smuggle broader frozen authority; removal is terminal for authority yet preserves the record, its digests, grant, and full trail as historical evidence — first for the already-superseded 2.0.0, then for the record that *is* the active pointer, whose uninstall leaves the scope with no active version at all |
| durable-restart | `SqliteExtensionInstallStore` + `materialize_lock` | the lock alone reinstalls the exact pinned identities through real digest/signature verification; history, trust evidence, and catalog provenance survive restart; a clean registry rebuilt from the lock holds the identical identity set |
| canonical-truth-boundary | (structural check) | no module under `maistro/extensions` — the whole package, `tool_skill/` included — imports `maistro.runs` or `maistro.goals`, or `maistro.graph` beyond the declarative `maistro.graph.definitions` types the #966 pack contract instantiates; extension status has no write path into canonical Goal/Run truth by construction |

## Honest boundaries of this proof at its base commit

The proof states its limits in the lineage itself (`Stage.note`), and this
document repeats them:

- **Rollback / disable / remove are driven, not deferred.** The #954
  post-install lifecycle landed, and the `disable-rollback-remove` stage
  drives all four operator verbs on the production service seam. What
  restart does **not** prove is those activation pointers surviving a
  process restart — the B2 activation store is process-lifetime by design,
  and the lineage marks that boundary on `durable-restart`.
- **The private catalog file is proof-side data**, in a documented file
  format consumed through the production resolution layer. The catalog
  *service* (publisher metadata, search, serving) is the #979 module in
  `maistro.extensions.catalog_service`, and the `distribution` stage serves
  the same snapshot through it — both the file format and the service
  surface are exercised. The out-of-tree multi-family reference repository
  remains **#980**; the proof's artifacts are minimal honest stand-ins:
  bytes on disk, signed entries, snapshot-digested.
- **The catalog is per-org private; there is no public publish/consume seam
  yet.** The #979 catalog service exposes one private catalog per
  organization (`set_catalog` is the only write path), so the
  `distribution` stage proves the private listing/search/detail surface and
  *per-org snapshot fidelity* — two organizations seeded independently from
  the same publisher pairs serve identical digest-anchored identities —
  rather than public cross-org distribution, and an organization that was
  never seeded sees nothing, which is the property that is reachable
  today. The epic's public-catalog contract is optional scope and stays
  open.
- **Activation-state restart durability is in-memory by design** at this
  base (the B2 activation store documents itself as process-lifetime);
  restart durability is proven for the durable registry layer (B1 +
  SQLite), which is what outlives activations.
- **The extension context and artifact loader are the host seam.** The
  platform contract is that hosts supply them (`ExtensionCodeLoader`, the
  context object of the M9-A2 lifecycle contracts, #950). The proof's
  implementations are minimal hosts: the loader imports only from
  digest-pinned artifact bytes; the context exposes only the caller's own
  scope and the frozen grant. The `canonical-execution` stage drives the
  tool-family governed Invocation seam (`Capability → Provider → Binding →
  Invocation`, M9-E3) inside a real Attempt; provider/UI-family canonical
  routing beyond it arrives with the remaining M9-D/M9-E lanes; this proof
  pins the provenance chain — caller, scope, install id, artifact digest,
  grant, Run → NodeRun → Attempt — that such routing must carry.

## Epic acceptance (#948), mapped

| EPIC M9-J criterion | Where it is proven |
|---|---|
| a fresh install with no extension source in-tree consumes the reference catalog | every stage: artifacts are built as scratch bytes and consumed only through catalog → lock → governed install → artifact loader (`code-runs-only-from-artifact`, `test_loaded_code_originates_only_from_the_install_root`); nothing under `packages/` or `extensions/` is imported as extension code |
| operator inspects permissions/trust/version/dependencies before install | `inspect` (manifest-only evaluation, permission display from the immutable snapshot) + `distribution` (per-version detail with declared permissions and pinned digests, publisher metadata, search) |
| provider, connector/tool, Agent/Graph or domain/UI families installed and invoked through canonical seams | connector/tool: `acme.notary` and `acme.greeter` are tool-family manifests, installed through the governed path and invoked through the host context (`invoke-observe`) and the governed `Capability → Provider → Binding → Invocation` seam inside a canonical Attempt (`canonical-execution`); the provider/Agent-Graph/domain-UI families' own canonical routing remains with M9-D/M9-E (stated above, not claimed) |
| update requiring broader authority triggers explicit re-authorization | `update-fence`: the delta names the new permission, install-before-decision is fenced, denial is terminal, grants never transfer across versions |
| rollback/disable/remove truthful, historical evidence preserved | `disable-rollback-remove`: disable clears the active pointer but keeps the frozen grant and audited trail; resume re-crosses the loader seam with the same bound artifact; rollback restores the superseded version and truthfully narrows authority (a rollback that would smuggle the broader frozen grant is refused); removal is terminal for authority, idempotent, and preserves the record's digest, grant, manifest snapshot, and full trail as historical evidence, including the removal of the active record itself, which clears the active pointer and leaves no runtime authority |
| catalog outage does not break installed pinned extensions | `catalog-integrity`: tampered snapshot ≠ installed truth; with the catalog gone, discovery fails loudly while the installed extension keeps invoking and the audit trail stays queryable |
| one public proof documents every canonical object/evidence link from catalog entry through executed Run/Invocation | this script + `lineage.json`/`lineage.md`: `distribution` anchors the catalog entry to its digests; `discover` pins the lock; `authorize-install` freezes the grant; `canonical-execution` proves one artifact digest links catalog entry → install record → code executed inside a canonical Run/Invocation, with attempt correlation on the Invocation row and extension provenance on the event stream |

## Acceptance criteria of #981, mapped

| Criterion | Where it is proven |
|---|---|
| no source-tree modification / editable-install bypass | `code-runs-only-from-artifact` + `test_loaded_code_originates_only_from_the_install_root`; artifacts are bytes in a scratch dir consumed through the governed path only |
| every operation retains canonical Workspace/caller/Run/Invocation and extension provenance | every transition carries actor/org/workspace/version/reason; every install record carries publisher, signature, digests, catalog URL + snapshot digest, trust evidence; every invocation observation carries caller, scope, install id, artifact digest, grant (`test_every_invocation_record_carries_canonical_provenance`) |
| extension cannot bypass Warden/security/egress/tenant policy | authority flows only from the declared manifest through the frozen grant (`grant-frozen-to-snapshot`, `undeclared-capability-denied`); cross-Workspace access is refused at the service boundary (`cross-workspace-read-denied`, `cross-workspace-decision-denied`); the loader refuses path escapes and identity lies |
| catalog/extension-specific statuses never override canonical Goal/Run truth | `canonical-truth-boundary` proves no import path from the extension subsystem into canonical run/goal truth; `tamper-cannot-rewrite-active-truth` proves catalog rewrites cannot rewrite installed truth |
| upgrade/remove/restart behavior matches durable registry state | `update-fence` (upgrade/fence/denial semantics), `disable-rollback-remove` (remove is terminal for authority — including removal of the active record, which clears the pointer — idempotent, and evidence-preserving), `durable-restart` (registry state survives restart and reproduces from the lock) |
| one reproducible script/test + human-readable lineage document | this script + `test_lifecycle_proof.py` + the generated `lineage.md` + this document |

## Determinism

Publisher keys are fixed test-only Ed25519 material, the install service
runs on a deterministic clock with sequential install ids, and resolution is
documented as deterministic — so the lineage's *core* (lock, checks,
invocation outcomes, digests, signatures, decisions) is byte-identical
across runs. Artifact zips carry fixed entry metadata (a fixed DOS epoch
timestamp, not the wall clock): ``ZipFile.writestr`` otherwise dates each
entry from ``time.localtime()``, and ZIP time's 2-second granularity made
identical sources hash differently depending on when the build started —
drift that every downstream digest inherited. ``TestProofDeterminism``
pins exactly this by forcing the second build into a different bucket.
Audit timestamps that production stores record internally are
excluded from the core digest and called out in the lineage. The core digest
is the reproducibility handle: two runs agreeing on it means the same
platform decision chain happened.
