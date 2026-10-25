---
inventory-delta:
  packages/maistro-core/tests: +61
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

**+58 `packages/maistro-core/tests/extensions/`** (collect-only verified on
this head; `test_preflight.py`, all names carry the acceptance criterion they
pin; +53 in the original implementation, +5 in the salvage repair round):

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

Repair round (+5): `test_propagation_reaches_transitive_dependents`,
`test_migration_required_propagates_transitively`,
`test_deprecated_dependency_does_not_migrate_its_dependents`,
`test_strict_policy_gates_on_propagated_blockers`,
`test_propagation_terminates_on_a_dependency_cycle` — the dependency-verdict
second pass now iterates to a fixpoint, so a verdict crosses every edge of a
chain (A→B→C) regardless of row order; termination on a dependency cycle is
asserted structurally (the pass stops when statuses stabilize) rather than by
wall-clock. `VersionRange` floor logic also moved to strongest-floor
conjunction semantics (`>=1.0.0,>=2.0.0` admits only majors >= 2) and
`run_preflight` gates the strict policy on the *propagated* rows, not the
pre-propagation ones. Fail-before evidence, verified by running the suite
against the pre-repair implementation: the four propagation tests and
`test_strict_policy_gates_on_propagated_blockers` fail there (single-pass
propagation, deprecation escalated via rank, strict gate read pre-propagation
rows); `test_propagation_terminates_on_a_dependency_cycle` passes on both
(it pins termination, which the old single pass had trivially) and
`test_version_range_span_detection_matches_the_authoring_rule` fails on the
old weakest-floor logic at the `>=1.0.0,>=2.0.0,<3.0.0` shadowing case.

Repair round 2 (+3): `test_cli_preflight_all_disabled_flag_proceeds_under_strict`
and `test_cli_preflight_all_disabled_conflicts_with_enabled` pin the CLI
`--all-disabled` flag (an explicitly empty enabled set must reach
`run_preflight` as `frozenset()`, not `None` — otherwise an all-disabled host
is unrepresentable and strict preflight blocks on disabled extensions), and
`test_cli_preflight_json_passes_markup_like_metadata_through` pins the JSON
output path against rich markup: manifest metadata and target notes are
publisher-controlled, so `[red]…[/red]` sequences were consumed and `[/]`
raised `MarkupError`, breaking the byte-reproducibility acceptance criterion
exactly when metadata carried markup-like text. `console.print` for `--json`
now runs with `markup=False, highlight=False`. Fail-before evidence: the new
markup test fails against the pre-fix CLI with `MarkupError("closing tag
'[/]' at position 603 has nothing to close")` (verified by temporarily
reverting the one-line fix; reverted after the run). The round also restores
`ruff format` conformance of the CLI module (the contradiction message
violated the line-length formatter rule as committed).

Validation on this head: `pytest packages/maistro-core/tests/extensions`
105 passed (44 pre-existing + 61 new); `ruff check` / `ruff format --check`
clean on the full tree; `check-suite-inventory.py --suite
packages/maistro-core/tests` green against the updated delta above.

Fail-before evidence: muting the `STRICT` reference in `run_preflight`'s
`can_proceed` (always True) fails `test_strict_policy_cannot_proceed_with_enabled_blocker`
and the strict CLI test; making `_propagate_dependency_verdicts` a no-op
fails the two transitive tests; dropping the
`maistro.extensions.types`-only import guard would let a target-private
import pass `test_preflight_module_imports_only_public_contract_metadata`.
All mutations were reverted before commit.

Earlier-round validation (pre-repair-2 head): `pytest
packages/maistro-core/tests/extensions` 97 passed (44 pre-existing + 53
new); mypy --strict six-package command
vulture per-identity gate with CI arguments
(`RATCHET_BASE_REV=<base> scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`) passes 1343 ↔ 1343 with no
new identities (the CLI command and the `all_installs` seam are referenced in
`_vulture_whitelist.py` with rationale); `check-reachability.py` reports no
new unreachable modules (the package is wired through `maistro.cli`);
`check-extension-imports.py` passes.
