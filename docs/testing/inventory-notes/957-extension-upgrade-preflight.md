---
inventory-delta:
  packages/maistro-core/tests: +53
---

# #957 (M9-C3) — host-upgrade compatibility preflight

Implements the upgrade preflight for installed extensions
(`packages/maistro-core/src/maistro/extensions/preflight.py`, operator surface
`maistro extensions preflight`, lock-state read seam
`ExtensionInstallStore.all_installs` on both store legs). The preflight
evaluates the installed lock state against a target release's public contract
metadata (host version, enforced manifest-contract version, capability
vocabulary with deprecation/removal notes) and classifies every installed
extension as compatible, deprecated, migration-required, or blocking — from
data alone, without importing or activating anything from the target release.

**+53 `packages/maistro-core/tests/extensions/`** (collect-only verified on
this head; `test_preflight.py`, all names carry the acceptance criterion they
pin):

- public-contract-metadata structural test — the preflight module's only
  `maistro.*` import is `maistro.extensions.types` (AST-checked), plus a
  proof that a manifest naming a nonexistent entrypoint module still
  evaluates (no extension code is imported), plus a CLI run over a
  `mode=ro` SQLite connection that leaves the file byte-identical
  (evaluation writes nothing, activates nothing);
- exact-conflict naming — contract-major conflict names the pinned range and
  the target contract version; removed/unknown capabilities are named with
  their metadata; missing/mismatched dependencies are named with id, range,
  and the installed version; unreadable manifests block with the exact
  parse failure; transitive dependency conflicts name the chain;
- strict-policy gate — `can_proceed` is False under strict with an enabled
  blocker, True when the same blocker is disabled, True under permissive;
  the CLI exits non-zero exactly when the strict upgrade is refused;
- distinct verdicts — blockers and warnings are separate report collections
  and separate CLI sections; deprecation never masquerades as a blocker;
- reproducibility — canonical JSON is byte-identical across repeated
  evaluations, across independently built equal lock states, and across
  fresh read-only re-reads of a seeded SQLite database (the restart leg);
- representative version transitions (the CI fixture) — parametrized
  contract transitions (patch/minor/major/older-major/spanning-range/
  unbounded-range/exact-pin) plus capability removal/deprecation
  transitions and store-level `all_installs` coverage over memory and
  SQLite legs;
- range grammar unit tests — comparator math (`admits`), span detection
  (the pin-one-major authoring rule), and malformed version/range errors
  that name the offending text.

Fail-before evidence: muting the `STRICT` reference in `run_preflight`'s
`can_proceed` (always True) fails `test_strict_policy_cannot_proceed_with_enabled_blocker`
and the strict CLI test; making `_propagate_dependency_verdicts` a no-op
fails the two transitive tests; dropping the
`maistro.extensions.types`-only import guard would let a target-private
import pass `test_preflight_module_imports_only_public_contract_metadata`.
All mutations were reverted before commit.

Validation on this head: `pytest packages/maistro-core/tests/extensions`
97 passed (44 pre-existing + 53 new); mypy --strict six-package command
clean; `ruff check` / `ruff format --check` clean on the full tree;
vulture per-identity gate with CI arguments
(`RATCHET_BASE_REV=<base> scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`) passes 1343 ↔ 1343 with no
new identities (the CLI command and the `all_installs` seam are referenced in
`_vulture_whitelist.py` with rationale); `check-reachability.py` reports no
new unreachable modules (the package is wired through `maistro.cli`);
`check-extension-imports.py` passes.
