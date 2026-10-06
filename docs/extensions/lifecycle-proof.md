# The extension lifecycle proof (M9-J3, issue #981)

One reproducible script, one test suite, and this document make the external
extension lifecycle reviewable end to end. The script runs the **whole
lifecycle** against the platform's real production seams and emits the
evidence as a machine-readable `lineage.json` and a per-run human-readable
`lineage.md`:

```console
uv run python scripts/extension_lifecycle_proof.py --out /tmp/lifecycle-lineage
# PROVED: 10/10 stages, 42/42 checks
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
catalog, invoking it, probing its fences, upgrading it, and restarting
around it. Every stage maps to a production seam — nothing in the script
re-implements platform behavior:

| Stage | Production seam exercised | What is proven |
|---|---|---|
| build-catalog | (proof-side data) | a private catalog file of digest-pinned, signed offerings; every manifest pins its artifact sha256 |
| discover | `maistro.extensions.resolution.resolve_lock` | one operator ask resolves transitively (`acme.notary ^1.0.0` → 1.1.0, never 2.0.0), pins full identity + catalog snapshot digest, is byte-reproducible, and explains its own selection |
| inspect | `ExtensionInstallService.inspect` | manifest-only evaluation; dependency order enforced (greeter before its dependency is `REJECTED`, truthfully recorded); candidates park in `AWAITING_AUTHORIZATION`; permissions display from the immutable snapshot |
| authorize-install | `authorize` + `install` + host loader | the grant freezes to the inspected set; activation runs only after every check; the loaded entrypoint lives under the install root — extracted artifact bytes, never a source-tree or editable path |
| invoke-observe | loaded entrypoint + host context | the handler runs through the grant-fenced context; scope facts are caller-scoped; an undeclared capability request is refused and recorded as a denial |
| denials | `ExtensionInstallService` scope containment | a foreign Workspace can neither read nor decide this scope's installs (`UnknownInstall`, indistinguishable from a missing id) |
| update-fence | authority delta + state machine | same-authority upgrade still needs an explicit decision; the broader-authority request names its delta; installing before re-authorization is fenced; denial is terminal and leaves the prior version active; grants never transfer across versions (`ArtifactMismatch`) |
| catalog-integrity | install records vs. snapshot digests | a tampered catalog is a different snapshot and cannot rewrite installed truth; a catalog outage blocks only discovery — installed extensions keep invoking and the audit trail stays queryable |
| durable-restart | `SqliteExtensionInstallStore` + `materialize_lock` | the lock alone reinstalls the exact pinned identities through real digest/signature verification; history, trust evidence, and catalog provenance survive restart; a clean registry rebuilt from the lock holds the identical identity set |
| canonical-truth-boundary | (structural check) | no module under `maistro/extensions` imports `maistro.runs`, `maistro.goals`, or `maistro.graph` — extension status has no write path into canonical Goal/Run truth by construction |

## Honest boundaries of this proof at its base commit

The proof states its limits in the lineage itself (`Stage.note`), and this
document repeats them:

- **Rollback / disable / remove are not reachable at the base commit.** The
  post-install lifecycle is issue **#954**'s surface (`TRANSITIONS` gives
  `ACTIVE` no outgoing edges by design until it lands). What the proof pins
  today are exactly the properties those operations must preserve when they
  arrive: records are append-only, a denied upgrade leaves the prior
  authorized version active, and history stays queryable after
  deactivation. The lineage marks the boundary on `durable-restart`.
- **The private catalog here is proof-side data**, in a documented
  file format consumed through the production resolution layer. The catalog
  *service* (publisher onboarding, search, serving) is sibling issue
  **#979**; the out-of-tree multi-family reference repository is **#980**.
  The proof's catalog is the minimal honest stand-in: bytes on disk, signed
  entries, snapshot-digested.
- **Activation-state restart durability is in-memory by design** at this
  base (the B2 activation store documents itself as process-lifetime);
  restart durability is proven for the durable registry layer (B1 +
  SQLite), which is what outlives activations.
- **The extension context and artifact loader are the host seam.** The
  platform contract is that hosts supply them (`ExtensionCodeLoader`, the
  context object of the M9-A2 lifecycle contracts, #950). The proof's
  implementations are minimal hosts: the loader imports only from
  digest-pinned artifact bytes; the context exposes only the caller's own
  scope and the frozen grant. Provider/Agent-family canonical routing
  (Run/Invocation-integrated dispatch) arrives with the M9-D/M9-E lanes;
  this proof pins the provenance chain — caller, scope, install id,
  artifact digest, grant — that such routing must carry.

## Acceptance criteria of #981, mapped

| Criterion | Where it is proven |
|---|---|
| no source-tree modification / editable-install bypass | `code-runs-only-from-artifact` + `test_loaded_code_originates_only_from_the_install_root`; artifacts are bytes in a scratch dir consumed through the governed path only |
| every operation retains canonical Workspace/caller/Run/Invocation and extension provenance | every transition carries actor/org/workspace/version/reason; every install record carries publisher, signature, digests, catalog URL + snapshot digest, trust evidence; every invocation observation carries caller, scope, install id, artifact digest, grant (`test_every_invocation_record_carries_canonical_provenance`) |
| extension cannot bypass Warden/security/egress/tenant policy | authority flows only from the declared manifest through the frozen grant (`grant-frozen-to-snapshot`, `undeclared-capability-denied`); cross-Workspace access is refused at the service boundary (`cross-workspace-read-denied`, `cross-workspace-decision-denied`); the loader refuses path escapes and identity lies |
| catalog/extension-specific statuses never override canonical Goal/Run truth | `canonical-truth-boundary` proves no import path from the extension subsystem into canonical run/goal truth; `tamper-cannot-rewrite-active-truth` proves catalog rewrites cannot rewrite installed truth |
| upgrade/remove/restart behavior matches durable registry state | `update-fence` (upgrade/fence/denial semantics), `durable-restart` (registry state survives restart and reproduces from the lock); remove is #954's open surface — documented above, not claimed |
| one reproducible script/test + human-readable lineage document | this script + `test_lifecycle_proof.py` + the generated `lineage.md` + this document |

## Determinism

Publisher keys are fixed test-only Ed25519 material, the install service
runs on a deterministic clock with sequential install ids, and resolution is
documented as deterministic — so the lineage's *core* (lock, checks,
invocation outcomes, digests, signatures, decisions) is byte-identical
across runs. Audit timestamps that production stores record internally are
excluded from the core digest and called out in the lineage. The core digest
is the reproducibility handle: two runs agreeing on it means the same
platform decision chain happened.
