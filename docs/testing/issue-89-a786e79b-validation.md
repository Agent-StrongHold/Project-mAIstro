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

## Follow-up job `ded50e34b0a7457191de297cdd3c933b`

Frozen snapshot: issue #89 only; assigned HEAD `64bd23280ba6`, base
`618954f0528090144683c308a18e19c6068d63f1`; existing release scripts,
release/registry/coverage workflow gates and adjacent release tests. This
existing note is the only planned tracked edit; no new tests or ledger edits
without a reproduced defect. Initial worktree and index were clean. No driver
`check-*.log` files were present in the supplied job directory.

The dispatch snapshot reports PR #2536 at `5f6bff7d458f`, not the assigned
local HEAD. Its front-matter check succeeded; its coverage check failed without
an output summary. Therefore neither the queued front-matter state nor the
old coverage result proves a current local defect. Prior rounds repeatedly
ended blocked because operational release/soak evidence is missing, not
because another source rewrite was needed. This round will retain that work,
re-run the named gates, and explicitly distinguish test proof from release
execution. Assumption: the writer role applies; no push, tag, release or
GitHub mutation is authorized.

Fresh results (logs under the supplied job directory):

- `uv sync --locked --extra dev`: exit 0. The prior coverage repair
  `87ce1ab3dee22c59ab8265cd93f86061a636af7f` resolves and is an ancestor of
  HEAD. `git diff --numstat 618954f052 -- quality/ docs/testing/inventory/`
  is empty; no ledger/inventory baseline changes.
- Registry workflow's full seven validation steps: exit 0, including **194
  tests passed**, strict lint **447 files / 0 errors / 0 warnings** (199
  reported existing test-evidence debts), zero citation exceptions, consistent
  ADR index and generated spec index, zero status contradictions. See
  `check-registry-local.log`. The citation gate used the immutable assigned
  base as `RATCHET_BASE_REV`.
- CI-exact vulture command: exit 0, **1217 reviewed identities / 1217
  findings**, unclassified 0. See `check-vulture-local.log`. There is no
  unbanked identity to repair; amending the ledger would be unsupported.
- `uv run ruff check .`, `uv run ruff format --check .` (3717 files),
  `check-release-consistency.py`, `check-workflow-inventory.py` (33), and
  `check-suite-inventory.py` (21 suites): all exit 0. See
  `check-static-local.log`. A guessed coverage workflow path
  `.github/workflows/coverage.yml` was not found and was skipped; the actual
  gate is in `.github/workflows/quality.yml:552,826-856`.

- Focused release battery:
  `uv run coverage run --branch --source=scripts -m pytest
  tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -x -q --timeout=120`: **183 passed**.
  `COVERAGE_FILE` was isolated in the job directory. After `coverage xml`,
  `check-diff-coverage.py <job>/coverage-release.xml --base
  618954f0528090144683c308a18e19c6068d63f1` passed: two production files
  measured, at least 90% lines / 80% branch arcs; three test files exempt by
  existing declaration. See `check-release-coverage-local.log`. This is NOT
  proof of the aggregate 87% publish-set floor: the combined CI producers
  were not run; that half remains UNVERIFIED.
- Byte-verification regression proof: the existing
  `test_adopt_wheels_fails_closed_on_tampered_bytes` passed normally. A
  process-local pytest plugin bypassed `verify_dist` on the fixture module
  only; the same test failed at `tests/test_promote_release.py:509` with
  `assert 0 == 1`, after reporting `MUTANT ACTIVE`. Pytest exit 1 was asserted
  by the probe driver. See `check-byte-mutation-local.log`. No tracked file
  was mutated by the probe. This demonstrates that the regression reaches
  byte verification rather than passing on an unrelated tree rejection.

No test additions/removals this round; inventory delta remains zero. No
production, workflow, policy, grant, or ledger edit was justified by these
results. Pytest emitted existing asyncio-loop-scope and AnyIO deprecation
warnings; no test failed except the deliberately killed mutant.

### Acceptance and operational handoff

Read the accepted release ADR `ADR-073126-c4e1` and branch ADR `ADR-095`:
`release.yml` remains the sole, protected, tag-triggered publisher; a human
release-environment decision is not replaceable by this local writer. The
existing exact-tree guard makes no metadata exception, which is stricter than
#89's permitted exception and consistent with the ADR. No competing execution
or authorization authority is introduced.

| #89 criterion | Fresh reachable-path evidence and remaining gap |
|---|---|
| RC built only from candidate commit | `release.yml:273-313` gates builds/recording to candidates; `test_record_evidence_freezes_the_candidate_identity` passed using a real temporary Git repository. Actual hosted candidate build UNVERIFIED. |
| Clean install, real model, security hot path, backup/restore | `promote_release.py:150-156,286-303` requires all checks with cited pass evidence; missing/failing/empty-reference cases passed. Actual soak executions UNVERIFIED. |
| #860 exact-RC sustained multi-replica workload, crash/restart, fencing/admission, pressure, duplicates | Pinned `multi_replica_soak` check and artifact-binding rejection tests passed. These do not run that workload or prove its subscenarios: UNVERIFIED. |
| Invariant-invalidating findings routed before promotion | `promote_release.py:306-330` and CLI rejection test passed. Actual finding review and filed/reclassified issues UNVERIFIED. |
| Runtime/source/config change needs new RC/applicable soak | `release_guard.py:190-253` compares entire trees; wrong-tree and stale wheel/image binding tests passed. Actual replacement RC/soak after changes UNVERIFIED. |
| Byte-equivalent final tag/tree and artifacts | Guard, wheel adoption and workflow no-final-build tests passed; byte bypass mutant killed above. Actual final/RC tree, wheel and image pairs UNVERIFIED. |
| External package/image/signature/install verification | Workflow contains clean-venv wheel verification, scan and signature verification steps; adjacent workflow tests passed. No external consumer verification executed: UNVERIFIED. |
| Machine-readable evidence bound to promoted artifacts/configuration | Binding validation tests passed; final evidence upload and release attachment are wired in `release.yml:938-1010`. Real release/soak evidence pair UNVERIFIED. |

**BLOCKED**, not merge-ready: the named local gates have no reproduced defect,
but actual release acceptance is not fulfilled by unit tests or a schema
validator. Next action is release-owner/#860 evidence production through the
existing shipping pipeline: select an exact candidate commit/tag/run, execute
and retain the required workload/checks, publish `soak-evidence.json` in the
required RC-run artifact contract, then verify and approve final adoption.
No candidate tag/run/artifact was supplied for that execution here; do not
guess one or manufacture a passing record. Hosted aggregate coverage also
requires its actual CI producers. No push or GitHub mutation performed.

Progress: checked 1 assigned issue; completed 1 focused local validation;
issue acceptance completed 0; skipped issues 0; unexpected gate failures 0.
