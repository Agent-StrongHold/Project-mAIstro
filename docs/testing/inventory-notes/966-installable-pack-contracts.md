---
inventory-delta:
  packages/maistro-core/tests: +62
---

# 966 — Installable domain-pack contracts over canonical objects (M9-F1)

Adds `packages/maistro-core/src/maistro/extensions/packs.py` (the pack
manifest subtype, version-addressable asset inventory, instantiation rules,
and the `InstallablePackRegistry` side-by-side install/disable surface) and
`packages/maistro-core/tests/extensions/test_pack_contracts.py` (+58 collected
node IDs; the extensions suite goes 153 → 215, +62 with the review-fix
regressions below), plus the four registry verbs
whose only in-tree consumers are this suite whitelisted in
`packages/maistro-core/src/_vulture_whitelist.py` with the
contract-ships-first rationale (the production driver is M9-F3, #968). No
canonical model, store, or gate changes; `quality/*.json` is untouched.

## What the tests actually assert (issue acceptance mapping)

- **AC-1 two out-of-tree packs, side-by-side, canonical objects** —
  `TestSideBySideInstall`: two publisher-namespaced packs install into one
  registry and each instantiates Graph/Persona/Rubric into the same
  Workspace as canonical models with distinct canonical identities; both
  packs' graph assets execute through the real `run_durable_graph` executor
  + `InMemoryDurableRunStore` (the established durable-runs pattern) and
  terminate `COMPLETED` with Run/NodeRun/Attempt lineage intact.
- **AC-2 version-addressable assets with provenance** —
  `TestVersionAddressableProvenance`: assets resolve at exact
  `(asset_id, version)`; multiple versions of one asset stay addressable
  with deterministic highest-version default; instantiated GraphTemplate
  metadata / Persona `source_template_*` + `extension_metadata` / Rubric
  `ProvenanceOrigin.PACK` + `pack_id` all carry publisher, version and the
  manifest digest; same-version reinstalls are idempotent.
- **AC-3 pack-local ids never become canonical ids** —
  `TestCanonicalIdentityWins`: minted `template_id`/`Persona.id`/
  `rubric_id` differ from the pack-local asset ids (which ride only in
  provenance), every instantiation mints a fresh identity, and
  caller-pinned canonical ids are honored.
- **AC-4 disable stops new use, deletes nothing** —
  `TestDisableStopsNewUseOnly`: disable refuses all three instantiation
  paths with the operator note surfaced; the record and its immutable
  manifest snapshot remain queryable unchanged; objects and Runs created
  before the disable still execute and complete afterward; `activate`
  restores new use; disable can pin one version while a sibling version
  stays active.
- **AC-5 dependencies through the M9 machinery** —
  `TestCompatibilityThroughM9Machinery`: `evaluate_pack_compatibility` is
  asserted equal to `evaluate_compatibility(pack_extension_view(m), policy)`
  (the M9 evaluator, not a second resolver); missing dependency, api-major
  mismatch, and unknown range grammar refuse the install with nothing
  recorded; dependencies on another installed pack and on a plain
  extension (capability provider) are satisfied.
- **AC-6 no private executor/store/authority** — `TestNoPrivateAuthority`:
  `executor`/`*_store`/`*_authority`/`permissions` keys are unknown-key
  rejections; an execution-state key (`run_id`) smuggled into a graph
  asset fails inspection through the canonical probe (the R12 runtime-state
  scan runs via a discarded scratch `GraphTemplate`); the registry holds
  only manifest records; rubric provenance names the pack as supplier
  (`authored_by` stays the caller's principal); a pack id outside its own
  publisher namespace is rejected.
- **Fail-closed parse matrix** — `TestManifestInspection`: envelope
  version/kind, unknown/missing keys, publisher-namespaced pack ids, strict
  semver, duplicate capabilities/dependencies/assets, kind-payload
  exclusivity, graph node/edge/entry structural rules, persona/rubric
  payload strictness, and canonical-model refusals (inverted numeric scale,
  veto naming a non-dimension) surfaced as typed
  `PackManifestRejected`.

## Review-fix regression tests (+8 over the initial +54)

Five Codex-review findings were fixed with one pinned regression each:

- `test_manifest_snapshot_is_deep_frozen` — the inspected manifest snapshot
  is deep-frozen (nested mappings/arrays included, rubric scales as frozen
  primitives), so a consumer cannot mutate an asset away from the bytes
  `source_sha256` anchors (3909069d9).
- `test_evidence_required_must_be_a_json_boolean` — a truthy string like
  `"false"` cannot invert rubric evidence requirements through Python
  truthiness (87f246b1d).
- `test_caller_rubric_bindings_are_revalidated` — caller-supplied
  `revision`/`goal_revision` are revalidated through `RubricSemantic.model_validate`
  because `model_copy(update=...)` skips constraint checks (f6e046b69).
- `test_pack_id_occupied_by_an_active_extension_is_rejected` — a pack id
  colliding with an active extension identity is refused before any record
  is written, so dependency resolution can never retarget to a different
  provider (addbdecde).
- `test_boolean_envelope_version_is_rejected[True]`/`[False]` plus two new
  `test_unknown_manifest_versions_fail_closed[True]`/`[False]` param cases —
  the JSON literals `true`/`false` cannot satisfy `manifest_version: 1`
  through Python's `bool == int` equality (`True == 1`); both the plain
  extension and domain-pack envelope parsers reject non-`int` versions
  explicitly (7273429a4).
- (no test: `637856737` fixed `_active_versions()` to aggregate per id with
  `_semver_key` — installs out of semver order now expose the same
  highest-active version to dependency resolution that unpinned lookups
  resolve to; behavior covered by `TestCompatibilityThroughM9Machinery`.)

## CI repair: supply-chain lock refresh (this note carries the round)

The merge queue failed `Supply chain (pip-audit)` on advisories that postdate
the lock, unrelated to this branch's diff (no dependency files touched by the
feature): `multidict==6.7.1 CVE-2026-104874` (fixed 6.9.1) and
`werkzeug==3.1.8 CVE-2026-102598` (fixed 3.1.9), both transitive (aiohttp /
flask). Repaired per the gate's own prescription by upgrading the lock
(`uv lock --upgrade-package multidict --upgrade-package werkzeug`; uv.lock
diff touches only those two stanzas) and re-proved locally with CI's exact
sequence (`uv sync --locked`, `uv pip install pip-audit`, freeze, `pip-audit
--strict --format=json`, `scripts/pip_audit_gate.py`): green, with only the
triaged `ecdsa PYSEC-2026-1325` remaining, plus
`scripts/check-dependency-namespaces.py` green. No test-count change from the
repair; the +58 above is the suite truth.

## Naming notes future lanes should not undo

- `PackAssetKind.GRAPH_TEMPLATE` (not `GRAPH`) and the string-keyed persona
  payload are deliberate: vulture's name-level matching would otherwise
  mark the banked `graph/types.py::GRAPH` and `personas/model.py::purpose`
  /`style_guidance` findings used and stale three ledger rows this lane
  may not prune (ledger edits are CI-repair-only). Same reason the registry
  reversal verb is `activate`, not `enable` (three banked security-store
  `enable` rows).
- `InstallablePackRegistry` is the in-memory reference authority for the
  contract rules; the Workspace-scoped activation/config/upgrade/disable
  lifecycle over durable storage is #968 and must not grow here.

## Repair round 3: develop sync merge (this note carries the round)

The lane brief's carried block (branch diverged from `origin/develop` while
`_vulture_whitelist.py` and `extensions/__init__.py` both grew import/
re-export blocks) resolved as a real merge: `origin/develop` (13 commits,
through 626683154) merged into `auto-966` and committed as bd7637433. Both
conflicts were additive on both sides and resolved by keeping both sides:
the pack-contract imports/`__all__` names (#966) alongside the resolution/
semver re-exports (#956), and both whitelist imports (`InstallablePackRegistry`,
`LockState` — each referenced by its own whitelist entries below them).
`quality/*.json` auto-resolved to develop's rows; verified row-lossless in
both directions (develop's `memory-advanced-retrieval` rationale is the newer
superset text; the four vulture rows develop drops correspond to code develop
itself fixed).

Re-proven on the merge head: vulture exact-debt 1332/1332 (develop's fixes
shrank the ledger by the same 4 rows); supply chain re-run with security.yml's
exact sequence (`uv sync --locked --all-extras`, `uv pip install pip-audit`,
freeze, `pip-audit --strict --format=json`, `scripts/pip_audit_gate.py`) —
gate exit 0, only the triaged `ecdsa PYSEC-2026-1325` remains; all 15 suites
match the recorded inventory (14307 in `packages/maistro-core/tests` — the
sum absorbed develop's 956/960/961 deltas additively, no new note needed);
extensions suite 329 passed, a2a/capabilities 904 passed, learnings/persistence
920 passed, pack-contracts + resolution + semver 146 passed; `check-merge-markers.py`,
`check-reachability.py`, `check-ratchet-provenance.py`,
`check-shipped-surface-truth.py`, `check-dependency-namespaces.py` all exit 0;
mypy maistro-core clean. No test-count change from this round; the deltas
above remain the suite truth.

## Repair round 2: boolean manifest_version (this note carries the round)

The prior round's NEEDS-DEEP-REVIEW blocker (`packs.py:901` accepted a JSON
boolean `manifest_version` because `True == 1`) is fixed by 7273429a4 in both
parsers (`manifest.py` envelope + `packs.py` pack envelope) with the four
collected node IDs above (2 new pack tests, 2 new manifest-matrix param
cases); probe-confirmed that `True`/`False` are rejected as
`unsupported manifest_version` while valid int-1 manifests still parse on
both paths. The supply-chain repair above was re-proven green on this head
with CI's exact sequence (`uv pip freeze --exclude-editable`,
`pip-audit --strict --format=json`, `scripts/pip_audit_gate.py`): only the
triaged `ecdsa PYSEC-2026-1325` remains, gate exit 0. No other test-count
change; +62 is the suite truth.
