# cr1994 repair round 16 (job 4edffb5d568c4b96844714db8e17ca91)

Independent re-validation of the fifteenth-round evidence at the branch head
`0f66f953689757199d999fbcb13be2930d67edbf`
(`feat/cutover-p0.1-principal-final`, merge-base with `origin/develop`
`80c837d578c6a866f3d8114edb72dbca3def4d6e`). The prior round (job
`ebb11aceb…`) died on a provider rate limit mid-run; its deterministic checks
(9/9 exit 0) had all passed, and the fifteenth-round verify commit is intact.
This round re-executed every claim from scratch instead of trusting it. No
source changes were needed; nothing was weakened.

## Issue #1994 acceptance criteria — re-proven at this head

- `uv run python scripts/check-principal-identity.py` → exit 0,
  "4 tolerated violations -> 0 current violations ... none new"
  (ratchet base 80c837d578c6, candidate 0f66f9536897).
- `uv run pytest packages/maistro-core/tests/fitness/test_principal_identity.py
  packages/maistro-server/tests/api/test_auth.py
  packages/hive-conductor/backend/tests/test_username_registry.py -q`
  → 63 passed.
- CI `Quality / Principal identity` and `exact-debt-ledger` check-runs: SUCCESS
  at the pushed PR head `2f21a0ab16` (per the dispatch snapshot, 2026-11-25
  08:16Z runs) — the quality.yml principal-identity ratchet is green in CI.
- `quality/principal-identity-baseline.json` is empty (`tolerated: {}`);
  `AuthenticatedPrincipal` / `CurrentUser` / `HiveUser` /
  `_SubsystemIdentity` appear nowhere under `packages/*/src` or
  `packages/hive-conductor/backend` except two stale comment references
  (`maistro/auth/oauth.py:6`, `maistro/container.py:753`) and no nested
  `getattr(..., "user", ...)` principal read remains.

## Gate repair evidence re-proven at this head

- Driver battery on this job: 9/9 checks exit 0 (uv sync, `ruff check .`,
  `ruff format --check .`, canvas 299 passed + 91 skipped, hive-conductor
  199 passed, suite inventories for hive-conductor / canvas / core / server).
- `uv run pytest tests/test_mutation_select_tests.py -q` → 31 passed. The two
  `TestTheMeasuredScopeIsTheDeclaredSource` tests structurally pin the
  mutation-gate regression (bare `--cov` absent, exactly one scoped
  `--cov=<dir>`, `coverage json` carries `--ignore-errors`) and replay the
  ephemeral scratch-module "No source for code" failure end to end; both fail
  against the pre-fix argv in `416406cf42`'s parent.
- `uv run python scripts/check-suite-inventory.py --suite tests` → ok, 6204
  identities, matching the recorded `tests/: +2` delta.
- `uv run mypy` with ci.yml's exact ten-package argument list → "Success: no
  issues found in 1131 source files".
- `python scripts/check-merge-markers.py` → ok;
  `python scripts/check-public-routes.py` → ok, 12/12 declared and
  base-authorized (the fourteenth-round expiry note is resolved by the
  develop sync `ec13fdbd2a`);
  `bash scripts/verify-monorepo-layout.sh` → ok.

## Residual risk assessed this round

- `origin/develop` moved two commits past the branch's develop sync
  (`bd96877ed8` #2264, `8955cf07a2` #2304 python-3.15 runtime bump, the
  latter touching `packages/hive-conductor/Dockerfile` which this branch also
  edits). `git merge-tree` at the merge base reports 0 conflict markers and
  no both-modified hunks, so the CI merge ref is clean; container gates will
  exercise the combined Dockerfile. No local develop sync was performed: the
  prior block was a rate-limit death, not a sync conflict, and CI checks out
  the merge ref regardless.
- Still left to CI on push (unchanged from round 15, by design):
  the end-to-end Mutation gate sweep (tooling fix proven structurally and by
  end-to-end selector tests; the sweep needs CI's 45-minute runner), the
  Coverage gate's full multi-producer publish-set combine (diff-coverage
  component proven in rounds 12–14; the branch net-deletes ~11k lines), and
  the full ci.yml `test` job breadth (all PR-surface slices pass locally).
