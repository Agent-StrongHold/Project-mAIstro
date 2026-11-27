# Issue 89 — focused repair validation (f178945f)

## Frozen scope and starting state

- Assignment: issue #89 only; branch `auto-89`, starting head
  `d74b21a11003143799a1972d2f4f1c100b385def`, supplied develop base
  `618954f0528090144683c308a18e19c6068d63f1` (both resolve locally).
- Snapshot: supplied `dispatch-context.json` in job
  `/home/dev/maistro/jobs/f178945f1236446c90d69d923de3161b`; no remote
  issue/PR re-enumeration or mutation. PR #2536 and #1672 are evidence only.
- Initial `git log --oneline -20`, `git diff --stat`, and `git status --short`
  inspected: existing implementation and prior validation commits preserved;
  initial worktree clean. Prior attempt result was BLOCKED, not release proof.
- Process one item: reproduce the named front-matter/vulture gates and focused
  promotion acceptance checks. Edit production/tests only for reproduced defects.
  Candidate scope: `scripts/promote_release.py`, `scripts/release_guard.py`,
  `.github/workflows/release.yml`, their existing tests/inventory notes and this
  validation report; the vulture ledger only if the required scan proves debt.
- No `check-*.log` files were supplied in this job directory at initial inspection.
  Local validation will create logs there; these are not driver evidence.
- Ambiguity: dispatch calls a queued front-matter check a failure, while prior
  attempts report green checks and stale remote coverage. Neither claim is taken
  as current proof. Reproduce locally before proposing repairs. Real published
  RC/soak/final evidence cannot be inferred from unit tests or gate success.

## Executed results

Fresh commands at the supplied head (logs in the job directory; exit 0):

- Exact required vulture invocation: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: 1217 findings / 1217 reviewed identities,
  unclassified 0, never-allowlist 0 (`check-vulture-local.log`). No ledger
  amendment is warranted.
- Every validation step in `.github/workflows/registry.yml`:
  registry/lifecycle tests 194 passed, lifecycle baseline 0, strict lint 447
  files / 0 errors / 0 warnings (199 existing test-evidence debts), citation
  ratchet against supplied base 0 exceptions, ADR index consistent, generated
  spec index zero diff, body-status 0 contradictions (`check-registry-local.log`).
  The dispatched queued status is not a reproduced failure.
- Focused release coverage battery, using `uv run coverage run --branch
  --source=scripts -m pytest` on `tests/test_promote_release.py`,
  `tests/test_release_guard.py`, `tests/test_check_release_consistency.py`,
  `tests/test_release_publish_metadata.py`, `tests/test_soak_compose_pressure.py`,
  `tests/release/`, `tests/test_verify_wheel_imports.py`,
  `tests/test_check_license_inventory.py`, `tests/test_check_compliance.py`
  with `--timeout=60 -x -q`: 703 passed. Coverage XML followed by
  `uv run python scripts/check-diff-coverage.py <job>/release-coverage.xml
  --base 618954f0528090144683c308a18e19c6068d63f1`: both changed measured
  files pass 90% lines / 80% branch arcs (`check-release-coverage-local.log`).
  This proves the diff half, not the full hosted combined publish-set floor.

- `uv run ruff check .` and `uv run ruff format --check .`: PASS (3717
  files). `check-suite-inventory.py`: 21/21 suites, 37818 unique identities,
  0 duplicates. Release consistency, workflow inventory (33), workflow write
  safety and doc links (3639 Markdown files, 0 broken links) all pass.
  `git diff --check` and the ledger/inventory-baseline diff against the supplied
  base are clean (`check-static-local.log`). No tests added/removed; inventory
  delta zero, so no new inventory-delta note or baseline edit is needed.

## Production acceptance review

Read accepted ADR-073126-c4e1 and ADR-095: the protected tag-triggered
`release.yml` is the only publisher; final artifacts must be the last RC's
validated artifacts. Local publication is not an alternative. No change to
`Goal -> Graph -> Run -> NodeRun -> Attempt`, execution/authorization/event
ownership, gates, grants, or ledgers is justified by the executed evidence.

| Issue acceptance | Reachable mechanism and executed evidence | Remaining operational proof |
| --- | --- | --- |
| RC artifacts only from candidate commit | `release.yml:273-312,577-590,642-653` checks out the tag, builds only on RC, records commit/tree/hash identity; record CLI tests in 703-test battery pass | Hosted exact-candidate build UNVERIFIED |
| Clean install, real model, security hot path, backup/restore soak | `promote_release.py:150-156,286-303` requires each named passing check with citations; pinned-set and rejection tests pass | Actual functional soak UNVERIFIED |
| #860 exact-RC sustained multi-replica workload, crash/restart, admission/fencing, pressure, duplicate detection | `multi_replica_soak` is pinned as required and bindings tested | Actual sustained workload and observations UNVERIFIED |
| Invariant-invalidating findings routed before promotion | `promote_release.py:306-328` rejects missing/malformed `routed_issue`; positive/negative tests pass | Actual filing/reclassification and issue contents UNVERIFIED |
| Code/runtime configuration changes require new RC and soak | `release_guard.py:190-247` rejects latest-RC tracked-tree mismatch; temporary git repository tests pass | External/deployed config equivalence and replacement soak UNVERIFIED |
| Byte-equivalent final tree/artifacts | Guard tests cover latest numeric annotated RC/tree identity; adopt-wheels tests verify real files/hashes; final image steps reuse digests, not builds | Actual RC/final pair and registry identity UNVERIFIED |
| External package/image/signature/install verification | Workflow clean-venv import and digest scan/sign/verify steps inspected; adjacent tests pass | External consumer verification UNVERIFIED |
| Machine-readable soak tied to promoted artifact/config | `promote_release.py:259-283,560-583` validates exact wheel/image bindings and config digest; binding tests pass | Real compatible producer/transport and deployed-config identity UNVERIFIED |

The implementation documents a cross-lane dependency at
`scripts/promote_release.py:44-57`: an Actions artifact named `soak-evidence`
with schema-1 `soak-evidence.json` must exist on the selected RC run.
`cmd_adopt_digests` fetches it there; `.github/workflows/release.yml:946-953`
uploads its own copy only on finals (RCs have not soaked yet).
`tests/test_promote_release.py:431-460` supplies fake GitHub transport, so green
unit tests are not evidence of a real producer. Do not replace actual binding
with the other lane's boolean record or manufacture successful soak results.

## Disposition

Named local failures do not reproduce. The supplied snapshot of PR #2536
records head `5f6bff7d458f6d24f80a46a84983b6cf1b61ca1f` (not the assigned
local head); no current hosted outcome is inferred from that older snapshot.
Full combined hosted publish-set coverage is also UNVERIFIED locally: this
round executes the focused diff half, not CI's other coverage producers.

The byte-verification bypass probe ran process-locally against the actual
`promote_mod` fixture: overriding `verify_dist` to accept all bytes makes
`test_adopt_wheels_fails_closed_on_tampered_bytes` fail at line 509 with
`assert 0 == 1`. The wrapper requires pytest's TESTS_FAILED status and exits 0
(`check-byte-mutation-local.log`). The original test passed in the 703-test
control run. This confirms the regression reaches the byte check, not merely
an earlier synthetic-tree rejection. No tracked source or tests were mutated.

Local git ancestry also confirms the captured PR head precedes existing repair
`87ce1ab3dee22c59ab8265cd93f86061a636af7f`, which is an ancestor of this
assigned head (both `git merge-base --is-ancestor` commands exit 0). The repair
is preserved, not reimplemented. Advancing the remote branch is outside this
worker's authority; no current hosted success is claimed.

**BLOCKED on operational acceptance**, not on any reproduced local gate
failure. No speculative production/test/ledger amendment is warranted. This
round changes only this focused report; prior implementation, test repairs and
inventory notes remain intact. A separate bounded report avoids extending the
already lengthy prior validation chronology and records only new executions.

Next: release/soak owners must provide compatible exact-RC evidence through the
protected shipping path, execute the real soak, route findings and verify the
externally published artifacts. No push, tag, merge or GitHub mutation performed.
Progress: checked 1 assigned issue, done 1 focused validation/handoff, skipped 0
assigned issues, unexpected validation errors 0. One file read requested an
offset beyond EOF; corrected to the reachable guard-test section (not a gate
failure). Final local commit is writer handoff only, never integration approval.
