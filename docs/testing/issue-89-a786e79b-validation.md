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

## Follow-up job `ac30894fe5be437cba88264a75c2cec3`

Frozen snapshot: issue #89 only; assigned HEAD `1a1f93583e3d`, base
`618954f0528090144683c308a18e19c6068d63f1` (= merge-base with
origin/develop, verified fresh); the same release/registry/coverage/vulture
gates and adjacent release tests. Prior rounds' claims were NOT trusted:
every named gate below was re-executed fresh at this head with CI's exact
arguments, and the production machinery was re-read from source. Worktree
entered clean and stayed clean through every probe (no tracked mutation;
the byte-mutation probe patches the fixture-loaded module in-process only,
plugin stored outside the tree in the job directory).

Dispatched states, resolved fresh:

- **"Validate ADR/spec front-matter: queued" is an in-flight run state, not
  a failure.** All seven `registry.yml` steps re-run at this head, exit 0:
  registry/lifecycle tests **194 passed**; `tools/lint_lifecycle.py`
  baseline 0; `maistro_registry.cli lint . --strict` **447 files, 0 errors /
  0 warnings** (199 pre-existing test-evidence debts);
  `check-citation-status-provenance.py` with `RATCHET_BASE_REV=origin/develop`
  **0 exceptions**; `check-adr-index.py` consistent; spec AC-Defined index
  regenerated, `git diff --exit-code docs/specs/README.md` clean;
  `check-adr-status-language.py` **0 contradictions**. No repair warranted.
- **PR #2536 Coverage-gate RED stays explained as a stale pushed head**:
  fresh ancestry check `git merge-base --is-ancestor 87ce1ab3de HEAD` holds
  (the fix is in the assigned HEAD) and `origin/develop` is an ancestor of
  HEAD, so the branch is current with the assigned base. Diff-coverage half
  re-proven: focused release battery **183 passed** under
  `coverage run --branch --source=scripts`;
  `check-diff-coverage.py <job>/coverage-release.xml --base 618954f0528090`
  → **ok**, 2 changed production files at/above 90% lines / 80% branch arcs,
  3 test files exempt by declaration. The hosted publish-set aggregate floor
  (six-plus CI producers, Postgres-backed legs) remains CI-executed only and
  UNVERIFIED locally.
- **exact-debt-ledger / vulture** (CI-exact `packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`): **1217 reviewed
  identities / 1217 findings**, unclassified 0, exit 0; `git diff --numstat
  origin/develop -- quality/ docs/testing/inventory/` empty — ledgers
  byte-identical, no unbanked identity, no amendment warranted.
- **Static battery**: `ruff check .`, `ruff format --check .` (3717 files),
  `check-release-consistency.py`, `check-workflow-inventory.py` (33
  workflows), `check-suite-inventory.py` (21/21 suites, 37818 unique node
  identities) all exit 0. No tests added or removed; inventory delta 0.
- **Byte-equivalence mutation probe re-derived fresh** (not copied): control
  `test_adopt_wheels_fails_closed_on_tampered_bytes` **1 passed** (exit 0);
  with `verify_dist` stubbed on the fixture-loaded module only via a
  process-local plugin, the same test **FAILED** with `assert 0 == 1` and
  `MUTANT ACTIVE: verify_dist bypassed on fixture module only` (exit 1,
  expected) — the regression genuinely reaches byte verification; mutant
  killed; tracked tree unchanged. Probe + control logs in the job directory.
- **Production behavior re-read from source** (not from prior notes):
  `scripts/promote_release.py:150-156` `REQUIRED_SOAK_CHECKS` = clean_install,
  real_model, security_hot_path, backup_restore, multi_replica_soak;
  `_validate_binding` (259) requires exact wheels/image digest match plus
  64-hex config digest and config reference; `validate_soak` (333) binds soak
  evidence to the promoted artifacts/configuration and rejects findings
  without `routed_issue` (306-330); `verify_dist` (351) sha256-compares the
  downloaded dist against the recorded candidate hashes, rejecting missing,
  mismatched and extra files. `.github/workflows/release.yml` anchors
  re-confirmed: candidate tags build (22-27), finals adopt the selected
  candidate's artifacts via `record-evidence` (304-310), `adopt-wheels`
  (328), `adopt-digests` (611) with soak evidence gating, and finals-only
  evidence upload; candidate rc publishes to TestPyPI only (452).
  `docs/adr/ADR-073126-c4e1` and `ADR-095` front matter: status Accepted.

### Acceptance disposition (unchanged, third consecutive fresh round)

All eight operational acceptance criteria of issue #89 remain UNVERIFIED
from this worktree for the same reason as every prior round: they require a
hosted, protected, tag-triggered pipeline execution with a real candidate
tag/run and human release-environment approval. Pushing, tagging and
releases are prohibited GitHub mutations for this worker, so the evidence
chain (candidate build → soak incl. #860 multi-replica workload → external
verification → final adoption) cannot be produced here. No source, test,
workflow, gate, grant, or ledger defect was reproduced this round; the
locally-reachable machinery is proven by the fresh gate results above and
the killed byte-bypass mutant.

Verdict: **BLOCKED on operational acceptance** — unchanged from the two
prior fresh rounds. Writer handoff only; no push, tag, release, or GitHub
mutation performed.

Progress: checked 1 issue, done 1 focused validation round, skipped 0,
unexpected errors 0.

## Follow-up job `a7aef59ab17b40aab42d01bd613ae42c`

Frozen snapshot: issue #89 only; assigned starting HEAD
`ed67665d246226fb1ae610c94afd22cceaf89429`, base
`618954f0528090144683c308a18e19c6068d63f1`; existing release scripts,
release/registry/quality workflows and adjacent tests. This existing note is
this round's planned tracked edit unless a gate reproduces an actual defect.
Initial index/worktree clean. No driver `check-*.log` files were supplied in
the job directory. Prior result and history inspected: repeated rounds lack
operational release evidence, not an unimplemented source change. Writer role
assumed; no GitHub mutations, tags, fabricated evidence or speculative ledger
edits. Local validations below will be freshly executed, not inherited.

Initial fresh validation: registry workflow seven steps passed (194 tests;
447 files, zero lint errors/warnings), vulture 1217/1217 with no unclassified
identity, 183 focused release tests plus diff coverage passed; ruff,
format, release/workflow/suite inventory checks passed. Logs are in this job
directory. The saved PR #2536 review alleges that `dist` expires after
seven days while evidence lasts 90. Direct inspection disproved that allegation
at the assigned HEAD: `release.yml:395-402` already retains `dist` for **90**
days. The proposed repair was therefore explicitly skipped before making any
workflow/test change. `_artifact_id` still correctly rejects expired artifacts.
No ledger amendment is warranted by the clean exact-debt scan.

### Executed evidence and limits

Logs below are fresh worker runs in
`/home/dev/maistro/jobs/a7aef59ab17b40aab42d01bd613ae42c/`:

- `check-sync-local.log`: `uv sync --locked --extra dev`, exit 0.
- `check-registry-local.log`: all seven `registry.yml` validation steps,
  exit 0. Tests 194 passed; strict lint 447 documents, zero errors/warnings
  (199 existing test-evidence debts); lifecycle baseline zero; citation
  provenance uses immutable assigned base, zero exceptions; ADR index,
  regenerated spec index diff, and body status checks pass. Dispatched
  **queued** is not a reproduced failure.
- `check-vulture-local.log`: CI-exact `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`, exit 0, 1217 findings/1217 reviewed identities,
  zero unclassified. `git diff --numstat <assigned-base> -- quality/
  docs/testing/inventory/` empty. No grant/ledger/baseline changes.
- `check-release-coverage-local.log`: `uv run coverage run --branch
  --source=scripts -m pytest tests/test_promote_release.py
  tests/test_release_guard.py tests/test_check_license_inventory.py -x -q
  --timeout=120`, **183 passed**; XML generated in job directory; CI gate
  `check-diff-coverage.py <xml> --base
  618954f0528090144683c308a18e19c6068d63f1`, exit 0. Two production files
  measured above 90% lines/80% branch arcs, three test files exempt by existing
  policy. This does **not** prove the aggregate publish-set floor: its full
  CI producer population was not executed. That half remains UNVERIFIED.
- `check-static-local.log`: `uv run ruff check .`, `uv run ruff format
  --check .` (3717 files), `check-release-consistency.py`,
  `check-workflow-inventory.py` (33), `check-suite-inventory.py` (21 suites,
  37818 unique identities), all exit 0. Prior coverage repair `87ce1ab3de`
  and assigned base verified ancestors of HEAD; saved PR #2536 head remains
  `5f6bff7d458f`, not this checked local HEAD. No claim that its old hosted
  coverage failure proves or disproves the unexecuted aggregate floor.
- `check-byte-mutation-local.log` / `check-byte-mutant-output.log`: existing
  tampered-wheel CLI regression passes normally; process-local `verify_dist`
  bypass makes it fail with `assert 0 == 1` (exit 1, expected), proving the
  regression reaches byte verification. Initial probe incorrectly used a
  `trylast` hook, after the test; it returned 0 and the probe driver correctly
  failed. Corrected to a wrapper applying the mutation before the test; the
  mutant was then killed. Plugin lives outside the tree; no tracked code
  mutated. No test added/removed, inventory delta zero.

Read Accepted ADR-073126-c4e1 and ADR-095: sole publisher remains tag-triggered
`release.yml`, protected branch promotion and human release approval. Exact
full-tree equality is stricter than the issue's allowed metadata exception,
consistent with those ADRs; no authority bypass or competing runtime added.
An initially guessed release-ADR filename was not found and skipped; the
actual path was resolved from the directory listing before reading it.

### Every issue acceptance criterion

| Criterion | Reachable behavior / executed evidence | Operational result |
|---|---|---|
| RC artifacts only from candidate commit | `release.yml:273-310` candidate-only build and identity recording; real temporary Git repository identity test passed in the 183-test battery. | Hosted candidate build UNVERIFIED. |
| Clean install, real-model, security hot path, backup/restore | `promote_release.py:150-156,286-303` requires checks with passing status and nonempty citations; missing/failing/citation rejection tests passed. | Actual soak checks UNVERIFIED. |
| #860 exact-RC sustained multi-replica workload, crash/restart, admission/fencing, resource pressure, duplicates | Pinned `multi_replica_soak` requirement plus stale wheel/image binding tests passed; validator is not a workload runner. | Sustained workload and each subscenario UNVERIFIED. |
| Invariant-invalidating findings filed/reclassified before promotion | `promote_release.py:306-330` rejects absent routing, CLI rejection test passed. | Real finding triage/routing UNVERIFIED. |
| Runtime-affecting changes require new RC/applicable soak | `release_guard.py:190-253` compares complete Git trees; latest-RC/tree/configuration tests passed. | Deployed configuration and replacement RC/soak evidence UNVERIFIED. |
| Byte-equivalent final tree/artifacts | `verify_dist` hash verification, tree guard, no-final-build workflow tests passed; byte bypass mutant killed fresh. | Actual RC/final tree, wheels and image pair UNVERIFIED. |
| External package/image/signature/install verification | `release.yml:372-391,823-857` wires clean-venv import and digest signature/verification; workflow tests passed. | External consumer executions UNVERIFIED. |
| Machine-readable soak evidence tied to promoted artifact/configuration | `promote_release.py:259-284,333-348,567-589` binds wheel/image hashes and configuration reference/digest before promotion; CLI binding tests passed; workflow preserves evidence. | Real candidate/soak/promoted evidence chain UNVERIFIED. |

**BLOCKED on operational acceptance.** No current local source/gate defect
reproduced. Missing inputs: an authorized exact candidate tag/run/artifact,
actual check/workload evidence in the schema-1 `soak-evidence` artifact on
that RC run, external verification, and protected final promotion evidence.
The documented #860 native boolean-schema record alone cannot satisfy this
binding contract (`promote_release.py:49-59`); do not weaken the gate or
manufacture a passing record. Release owners/#860 must produce that evidence
through the canonical pipeline. Local unit tests and schema checks are not
substitutes. No push, tag, release, GitHub mutation, or integration approval.

Changed tracked file this round: this validation note only. Progress:
checked 1, done 1 focused validation/handoff, skipped issues 0, reproduced
gate errors 0; operational acceptance completed 0. Next: release-owner
execution and hosted aggregate coverage proof, not another speculative edit.
