---
inventory-delta:
  packages/maistro-core/tests: +4
---

# #948 (EPIC M9-J) — public/private catalog distribution + canonical execution stages

Extends `scripts/extension_lifecycle_proof.py` (schema v2, 12 stages) with
the two epic-level links no sibling lane owned alone, and pins them in
`packages/maistro-core/tests/extensions/test_lifecycle_proof.py`:

- **`distribution` stage** — serves the proof's signed snapshot through the
  production #979 catalog service (`CatalogService`/`InMemoryCatalogStore`):
  publisher metadata on every listing row, search/publisher filtering,
  per-version detail anchored to the pinned artifact digest; the identical
  snapshot distributes to a second org as a public catalog; an org the
  distribution never reached sees nothing.
- **`canonical-execution` stage** — the installed, re-authorized notary 2.0.0
  artifact executes inside a canonical `Graph → Run → NodeRun → Attempt`
  (`AttemptExecutionService` over `PythonExecutionRuntime`); its declared
  effect crosses the governed `Capability → Provider → Binding → Invocation`
  seam; the canonical Invocation row carries the attempt correlation, the
  event stream carries extension provenance, and one artifact digest links
  catalog entry → install record → executed code.

**+4 `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`**
(collect verified; module total 11 → 15):

- `TestEpicCatalogDistribution` (2) — the distribution stage proves all five
  checks with distinct private/public org evidence; the pinned identities
  offered per consumer are byte-identical by construction (same entry
  objects), four rows, 64-char digests.
- `TestEpicCanonicalExecution` (2) — the canonical-execution stage proves
  all five checks and its evidence carries non-empty
  run/node-run/attempt/invocation ids with `attempt_status == "completed"`;
  the digest chain is re-derived independently (catalog entry == install
  record == built artifact bytes) so the link cannot pass vacuously.

Pre-existing pins updated in place: `EXPECTED_STAGES` gains
`distribution` + `canonical-execution`; the CLI contract pins schema
`maistro-extension-lifecycle-proof:v2`.

Validation on this head: `uv run pytest
packages/maistro-core/tests/extensions/test_lifecycle_proof.py -x -q` →
15 passed; script standalone `PROVED: 12/12 stages, 52/52 checks` with an
identical `deterministic_core_sha256` across two runs (the new stages'
uuid-bearing facts live in stage evidence only, which the deterministic
core excludes by construction).
