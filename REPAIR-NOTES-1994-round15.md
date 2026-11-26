# cr1994 repair round (job ebb11aceb7234cf2b2cbd176651b3327)

Validation round at head `416406cf42facf74315ceeb8c89a55d67164c233`
(branch `feat/cutover-p0.1-principal-final`, base `bd96877ed8` = develop tip).
The branch carries the develop sync (`ec13fdbd2a`, resolving the #2110
Windows-execution-policy surfaces incl. `quality/public-routes.json`) and the
mutation-gate selector fix (`416406cf42`). No source changes were needed this
round; this note records executed evidence.

## Issue #1994 acceptance criteria — all proven at this head

- `uv run python scripts/check-principal-identity.py` → exit 0,
  "4 tolerated violations -> 0 current violations ... none new"
  (ratchet base 80c837d578c6, candidate 416406cf42fa).
- `uv run pytest packages/maistro-core/tests/fitness/test_principal_identity.py
  packages/maistro-server/tests/api/test_auth.py
  packages/hive-conductor/backend/tests/test_username_registry.py -q`
  → 63 passed.

## Gate repair evidence at this head

- Driver battery (9 checks, all exit 0; logs in the job directory): uv sync,
  `ruff check .`, `ruff format --check .`, targeted pytest batteries
  (canvas/server/core 299 passed + 91 skipped; hive-conductor 199 passed),
  `check-suite-inventory.py` for hive-conductor / canvas / core / server.
- `check-suite-inventory.py --suite tests` → ok, 6204 identities; matches the
  `tests/: +2` delta recorded in
  `docs/testing/inventory-notes/cr1994-mutation-selection-scoped-cov.md`.
- `uv run pytest tests/test_mutation_select_tests.py -q` → 31 passed (pins the
  mutation-gate selector argv contract and replays the ephemeral
  scratch-module failure end to end).
- Monorepo layout script → ok; `uv run mypy` with ci.yml's exact ten-package
  argument list → "Success: no issues found in 1131 source files".
- Fast ci.yml `lint-and-type-check` script steps run individually, all exit 0:
  check-merge-markers, check-cross-package-imports, check-extension-imports,
  check-frontend-api-routes, check-frontend-typed-client,
  check-api-route-contracts, check-deployment-claims, check-secret-field-labels,
  check-retired-guidance, check-compose-secrets, check-compose-resources,
  check-durable-table-inventory, check-promotion-surface,
  check-connection-credentials, check-owned-store-access, check-public-routes
  (the expiry noted in the fourteenth round is resolved by the develop sync),
  check-shell-execution, check-build-context.
- Mutation gate overlap reproduced with CI-exact resolution:
  `git diff --name-only origin/develop...HEAD -- packages --diff-filter=ACMR`
  → 46 files; trusted baseline read from merge-base
  `80c837d578c6a866f3d8114edb72dbca3def4d6e`;
  `mutation_critical.py --changed-from` → overlap on
  `packages/maistro-core/src/maistro/privilege.py`;
  `mutation_critical.py --validate` → "critical-file list OK"; diff artifact
  produced. The selection phase runs the full maistro-core suite under
  per-test coverage and the cosmic-ray exec then runs per-mutant sessions —
  the end-to-end run exceeded the bounded repair wall-clock window twice and
  is left to CI's 45-minute runner on push. The specific historical failure
  ("coverage json --show-contexts: No source for code") is proven fixed by the
  selector tests above.

## Still unproven locally (CI must re-run on push)

- `Mutation gate (changed critical lines)` end-to-end verdict (tooling fix
  proven; full mutant sweep not executed locally — see above).
- `Coverage gate (publish-set floor + diff coverage)` at this head (requires
  the six-plus coverage producers; no local execution this round).
- Full ci.yml `test` job breadth (turing/design/harness/sdk suites, root
  `tests/` run, hive full suite, frontend builds) — the PR-surface slices all
  pass; the fourteenth round additionally recorded diff coverage, vulture,
  mypy and governance gates proven at 7f9ac20cc0d8.
