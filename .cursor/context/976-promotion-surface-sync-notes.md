# Lane L976 round notes — develop sync, promotion-surface repair, reference-extension proof

Branch `auto-976`, round starting at head `b5a07536d` (issue #976, M9-I1).
Previous round's notes are in git history (`4a2140c58` era); this file
records the state after the repair.

## What this round did

1. **Merged develop `e20e9f52` into the branch** (`d01033a75`). The branch
   was 999 commits behind; the merge reduced the review diff to exactly the
   13 #976 files. The 3 conflicts (CHANGELOG.md, `extensions/__init__.py`,
   `cli/_extensions.py`) were both-adds and resolved as unions.
   `git diff --numstat origin/develop -- quality/` is **empty** — no ledger
   rows were lost in the merge.

2. **Repaired the promotion-surface regression in code** (`b5a07536d`) — no
   ledger row, no grant, no gate weakened. Cause: `maistro.capabilities.*`
   imported `maestro.extensions.*` at module level, and the extensions
   package initializer pulls `isolation → sandbox → runs → graph →
   harness_executor → capabilities`; the closure exploded 272 → 661 modules
   (355 uncovered). Repair: the canonical attribution carrier moved **down**
   into the protected capabilities layer as
   `maistro/capabilities/providers/extension_attribution.py` (stdlib only),
   and `maistro.extensions.attribution` re-exports the same objects (one
   type, pinned by an identity test). The dependency direction is now the
   natural one: extensions use capabilities, never the reverse.
   Gate: `python3 scripts/check-promotion-surface.py` → **exit 0,
   "promotion surface: ok"**, closure back to 272 modules, no
   `maistro.extensions` module in it.

3. **Closed the reference-extension gap (AC-6)** with a real out-of-tree
   package instead of the fabricated "Acme" stand-in: the shipped
   `extensions/reference-gallery/packages/gallery-model-adapter` is driven
   through the canonical provider-adapter bootstrap, one governed call and
   the terminal audit event. The identity is bound to the artifact the host
   actually installed — the package's manifest digest and the digest of the
   wheel `uv build` produces from the shipped source (the same artifact the
   gallery's publish tool publishes). `ProviderAdapterSpec` gained one
   optional field, `extension_id`, so attribution can name the **package**
   (`gallery.model_adapter`) rather than only the host-scoped adapter id
   (`gallery-model-adapter`); empty keeps the previous behavior.

## Acceptance evidence (reachable production behavior)

| Criterion | Where it is proven |
|---|---|
| AC-1 exact extension/version/publisher + canonical caller/Workspace | `tests/capabilities/test_provider_adapters.py` (declared identity → Binding snapshot → Invocation evidence → terminal event provenance), `tests/extensions/test_attribution.py` (install-record identity, activation log, CLI rendering) |
| AC-2 metadata survives delegation / external hops | Provider/Agent hop: the carrier rides the Binding snapshot → Invocation → Event across the external call (`test_provider_adapters.py`). **Residual:** the carrier does not yet ride inside the a2a `DelegationContext` to a remote peer's provenance — seam: `maistro/a2a/delegation_context.py` + `maistro/graph/nodes/agent_delegate_remote.py` + the receiving admission in `maistro-server/api/a2a.py` |
| AC-3 no parallel correlation identity | `correlation_id == run_id` asserted on the terminal event; the carrier carries no id-shaped field; the extension id never enters the correlation namespace |
| AC-4 historical evidence readable after upgrade/ removal | The stored Invocation decodes the identity with no registry/catalog/installed package consulted (`attribution_from_payload` on durable evidence alone) |
| AC-5 no extension secrets by default | The carrier's field set is closed (no free-form slot); the Event envelope redacts provenance; the resolved credential never reaches the evidence (asserted) |
| AC-6 reference extension proof | `test_shipped_reference_extension_correlates_end_to_end` — the shipped gallery adapter, real digests, canonical bootstrap → governed call → event → cold decode |

## Re-validated after the repair (all green)

ruff check/format; mypy on `packages/maistro-core/src` (only the 5
pre-existing `maistro_bootstrap` import-not-found errors in untouched files);
capabilities + extensions suites (**1881 passed, 7 skipped**);
promotion-surface (exit 0); promotion-surface-provenance (273 modules, no
tolerance expansion); vulture with CI's exact args (1326 == 1326); radon
(134 == 134); reachability-dispositions (168 unreachable modules, all
dispositioned); suite inventory (`packages/maistro-core/tests`, delta
**+49**); cross-package-imports; extension-imports; shipped-surface-truth;
backlog-consistency.

Pre-existing failures that are **not** this change's: `check-reachability.py`
fails identically on `origin/develop` (its message is about built-but-never-wired
modules), and `check-vulture-baseline.py` under its *default* arguments (which
include `tests`) — CI invokes it with `packages/*/src --min-confidence 60
--exclude '*/third_party/*'`, which is green.
