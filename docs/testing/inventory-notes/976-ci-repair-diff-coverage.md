---
inventory-delta:
  packages/maistro-core/tests: +2
---
# #976 CI-repair: diff-coverage floor on the two untested attribution paths

The merge-queue coverage gate at `021bfb9a821d` failed only on
`scripts/check-diff-coverage.py`: two #976-changed files in
`packages/maistro-core/src/maistro/capabilities` carried uncovered lines —
`binding.py` 83.3% of changed lines (the callable-`extension_attribution`
branch) and `governed_invocation.py` 75.0% (the `InvalidAttribution`
fail-soft path of `_extension_provenance`). Two cases close the gap:

- `test_resolved_binding_snapshots_a_method_declared_attribution`
  (`packages/maistro-core/tests/capabilities/test_binding_invocation.py`):
  a provider handle declaring identity the way `ProviderAdapterSpec` does —
  a method, not a materialized attribute — lands the exact identity in the
  `ResolvedBinding` snapshot, and a declaring-shaped handle that declines
  (`None`) leaves the wiring's config untouched. Covers `binding.py`'s
  callable branch plus its none-arc.
- `test_malformed_attribution_fails_soft_and_never_breaks_the_ledger`
  (`packages/maistro-core/tests/capabilities/test_provider_adapters.py`):
  a Binding snapshot carrying a future-format attribution payload still
  completes its effect, the durable Invocation row keeps the payload
  verbatim, the terminal audit event omits the `provenance["extension"]`
  fragment, and a warning names the binding. Covers the `except
  InvalidAttribution` fail-soft path in `_extension_provenance`.

Both were mutation-checked: breaking the callable branch, and re-raising
instead of logging, each fails exactly the new case. Two non-parametrized
async/sync cases = +2 nodes for `packages/maistro-core/tests`. No test was
removed or renamed. Local proof: `coverage run --branch
--source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests`, then `scripts/check-diff-coverage.py
coverage.xml --base origin/develop` reports every measured changed file at
or above 90% lines / 80% branch arcs (previously FAIL on the two files).
