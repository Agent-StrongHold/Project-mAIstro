---
inventory-delta:
  packages/maistro-core/tests: +11
---

# #981 (M9-J3) — the end-to-end extension lifecycle proof

Adds `scripts/extension_lifecycle_proof.py`: one reproducible harness that
drives discover → inspect → authorize → install → invoke → observe →
update → reauthorization-fence → restart durability against the production
seams (`resolve_lock`, `ExtensionInstallService`, the host loader seam, the
B1 SQLite registry), emitting `lineage.json` + `lineage.md`, and
`docs/extensions/lifecycle-proof.md`: the standing human-readable lineage
document mapping every stage to its production seam and stating the honest
boundaries (rollback/disable/remove are #954's surface, not reachable at
this base; the catalog service is #979; the out-of-tree reference repo is
#980).

**+11 `packages/maistro-core/tests/extensions/test_lifecycle_proof.py`**
(collect-only verified on this head):

- `TestFullLifecycleProof` (3) — all ten stages prove (42/42 checks, no
  stage silently skipped); the lineage is honest about the #954
  post-install boundary (the note is present and names rollback); every
  invocation observation carries the full provenance chain (caller, org,
  workspace, install id, artifact digest) and the undeclared-capability
  denial is an observed invocation.
- `TestProofDeterminism` (2) — the deterministic core digest is identical
  across two independent runs and the resolved lock evidence matches; the
  reported base commit is a real commit (the lineage is anchored).
- `TestNoSourceTreeBypass` (3) — loaded code originates only under the
  scratch install root, never under `packages/` or `extensions/` (the
  no-editable-install-bypass criterion); the loader refuses artifact
  path escapes (`../evil.py` never lands); a plugin lying about its
  identity is recorded FAILED with its reason and nothing active —
  mutation-checked: disabling either harness guard fails its test.
- `TestPostInstallHistoryTruth` (1) — denied and active records stay
  queryable, each with its full transition trail terminating in its own
  state (the append-only property #954's remove must preserve).
- `TestCommandLineContract` (2) — the CLI writes `lineage.json`/`lineage.md`
  and exits 0 when every check passes; exits 1 and renders the failing
  check when one fails (the harness reports failure rather than quietly
  passing).

Validation on this head: `uv run pytest
packages/maistro-core/tests/extensions -x -q` → 278 passed (267 pre-existing
+ 11 new); script runs standalone `PROVED: 10/10 stages, 42/42 checks` with
identical `deterministic_core_sha256` across runs.
