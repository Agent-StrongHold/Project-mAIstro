# Issue #89 validation — job `a786e79b94fa41d99bfb1bacfacfd46e`

## Round: assigned head `c99f086ee60e`, base `618954f052` (origin/develop)

Frozen scope: issue #89, the dispatched gate states ("Validate ADR/spec
front-matter: queued"; carried Coverage-gate RED from PR #2536), the exact
vulture ledger gate, and the standing operational soak contract. Worktree
entered clean at the exact starting head; the job directory supplied **no**
`check-*.log` files and an empty driver `checks` array, so every log cited
below is a fresh worker execution under
`/home/dev/maistro/jobs/a786e79b94fa41d99bfb1bacfacfd46e/` at this head.

### Dispatched gate states, resolved with fresh evidence

- **"Validate ADR/spec front-matter: queued" is an in-flight run state, not a
  failure.** All 7 `registry.yml` steps re-executed at this head, exit 0
  (`check-registry-local.log`): registry/lifecycle tests **194 passed**;
  `tools/lint_lifecycle.py` baseline 0; `maistro_registry.cli lint . --strict`
  **447 files, 0 errors / 0 warnings** (199 pre-existing test-evidence debts);
  `check-citation-status-provenance.py` with `RATCHET_BASE_REV=origin/develop`
  **0 exceptions**; `check-adr-index.py` consistent; AC-Defined index
  regenerated with `git diff --exit-code docs/specs/README.md` clean;
  `check-adr-status-language.py` **0 contradictions**. No repair warranted.
- **Coverage gate (publish-set floor + diff coverage)**: the captured RED at
  PR #2536's pushed head `5f6bff7d458f` stays fully explained — that tip is
  stale and predates its own fix. `git merge-base --is-ancestor 87ce1ab3de
  HEAD` holds (repair present), and `origin/develop` (618954f052) is an
  ancestor of HEAD, so the branch is current with the assigned base; only the
  remote branch advance is outstanding, and pushing is prohibited for this
  worker. Diff half re-proven at this head (`check-release-coverage-local.log`):
  release battery **703 passed** under
  `coverage run --branch --source=scripts`; `check-diff-coverage.py
  <xml> --base 618954f0528090144683c308a18e19c6068d63f1` → **ok**, 2 changed
  measured production files at/above 90% lines / 80% branch arcs, 3 test
  files exempt by declaration. The combined hosted publish-set floor (87%)
  still requires CI's six producers and remains UNVERIFIED locally.
- **exact-debt-ledger / vulture** (CI-exact args
  `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  **1217 reviewed identities / 1217 findings**, exit 0; `git diff --numstat
  origin/develop -- quality/ docs/testing/inventory/` empty — ledgers
  byte-identical, no amendment warranted (`check-vulture-local.log`).
- **Byte-equivalence mutation probe** (prior round's process-local plugin,
  re-run fresh): control exit 0; with `verify_dist` stubbed on the
  fixture-loaded module only, pytest exit 1 with `MUTANT ACTIVE` and the
  regression's own `assert 0 == 1` signature — mutant killed; `git status`
  clean afterwards, no tracked mutation (`check-byte-mutation-local.log`).
- **Static/adjacent battery**: `ruff check .`, `ruff format --check .`
  (3717 files), `check-release-consistency.py`, `check-workflow-inventory.py`
  (33 workflows), `check-suite-inventory.py` (21/21 suites) all exit 0
  (`check-static-local.log`). No tests added or removed this round —
  inventory delta 0, no inventory-note required.

### Acceptance disposition (unchanged)

All eight operational acceptance criteria of issue #89 remain exactly as the
prior rounds recorded: hosted candidate-only RC build, install /
real-model / security / backup-restore soak, #860 sustained multi-replica
workload, real invariant-finding routing, replacement RC/soak on deployed
runtime change, actual RC/final byte pair, external
package/image/signature/install verification, and real machine-readable
evidence binding are UNVERIFIED from this worktree. The gates that *require*
those inputs are implemented and test-pinned (`scripts/promote_release.py`
`SOAK_ARTIFACT`/`REQUIRED_SOAK_CHECKS`/`_validate_binding`/
`invalidates_invariant`→`routed_issue`/`validate_soak`/`verify_dist`;
`.github/workflows/release.yml` finals-only soak upload), and the promotion
path refuses to bypass them (mutant killed above). Producing the evidence is
the #860 lane's and the release owners' work under the protected,
tag-triggered pipeline with human approval; no source, test, workflow, gate,
grant, or ledger defect was reproduced this round.

Verdict: **BLOCKED on operational acceptance**, not on any local gate defect.
Writer handoff only — not integration approval and no GitHub mutation.

Progress: checked 1 issue, done 1 focused validation round, skipped 0,
unexpected errors 0.
