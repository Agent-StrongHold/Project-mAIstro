# REPAIR-NOTES-292-round-r3.md

CI-repair verification for issue #292 (`auto-292`) at head `2b0e92e77651`.

## Validation re-derived

- `uv run ruff check .` -> All checks passed!
- `uv run ruff format --check .` -> 3364 files already formatted
- `uv run pytest packages/hive-conductor/backend/tests/test_cli_contract.py -q` -> 23 passed
- `uv run pytest packages/hive-conductor/backend/tests -q` -> 3792 passed, 23 skipped
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` -> ok (3815 nodes)
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` -> exit 0 (1326 reviewed identities -> 1326 findings; unclassified 0; never_allowlist 0)
- `uv run python scripts/check-ratchet-provenance.py` -> fails only on the reachability leg (`maistro.runs.admission_identity`: NEW unreachable module absent from trusted base and not previously authorized)
- `uv run python scripts/check-frontend-api-routes.py`, `check-frontend-typed-client.py`, `check-shipped-surface-truth.py`, `check-compliance.py`, `check-api-route-contracts.py`, `check-cross-package-imports.py`, `check-merge-markers.py` -> all exit 0

## Residual (owner-held, not repairable in this lane)

The `exact-debt-ledger` (vulture-ratchet) job fails solely because
`check-ratchet-provenance.py` delegates to the reachability ratchet, which
flags `maistro.runs.admission_identity` as a NEW unreachable module absent
from trusted base `e20e9f52ea94`. That module is byte-identical to develop and
is an intentionally inactive contract leaf (#1851). Under the two-merge rule,
a candidate cannot self-authorize the tolerance; the fix lives on `auto-881`
and must land on develop first. No `quality/vulture-baseline.json`,
`quality/reachability-baseline.json`, or grant edit was made in this lane.

## Conclusion

All #292 acceptance criteria are implemented and covered by
`test_cli_contract.py` and `tests/e2e/cli-page.spec.ts`; the remaining red is
the develop-side reachability residual, owner-held.
