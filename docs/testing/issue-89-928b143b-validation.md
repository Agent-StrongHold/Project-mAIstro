# Issue 89: bounded repair validation (928b143b)

## Frozen scope and starting state

- Only issue #89; supplied dispatch snapshot, branch `auto-89`, starting head
  `f168d59c86e5cb244790fedd835d2de6f7efcc41`, base
  `618954f0528090144683c308a18e19c6068d63f1`.
- Starting worktree clean; existing implementation and tests preserved.
- Scope: reproduce named front-matter, vulture and release diff-coverage gates;
  inspect release workflow/guards against all eight issue acceptance criteria.
- No GitHub mutation, fetch, push, release or live promotion is authorized.
- Prior runs produced commits but report operational acceptance blocked. This
  round will distinguish local gate results from missing real soak evidence,
  not create cosmetic code or ledger changes to address a queued check.
- Supplied job directory contains no `check-*.log` files at initial inspection.
  Fresh commands will write logs there. Prior result claims are not proof.

## Results

Fresh `uv sync --locked --extra dev`, exact dispatched vulture command,
`uv run ruff check .`, and `uv run ruff format --check .` all exited 0.
Logs: `check-sync.log`, `check-vulture.log`, `check-ruff.log`,
`check-format.log` in this job directory.

All seven registry workflow validation steps exited 0 (`check-registry.log`):
194 tests passed; lifecycle, strict registry lint, citation provenance against
the exact assigned base, ADR index, generated spec index/no diff, and body
status checks succeeded. The dispatched queued state is not a reproduced
front-matter failure.

Release-focused coverage producer exited 0: 703 tests passed, XML generated,
and `check-diff-coverage.py --base 618954f0528090144683c308a18e19c6068d63f1`
passed for both changed production files at 90% lines / 80% branch arcs
(`check-release-coverage.log`). This is the diff half only; the full hosted
87% publish-set floor remains UNVERIFIED, not inferred from these tests.

Adjacent gates exited 0 (`check-adjacent.log`): suite inventory (21 suites,
37,818 unique identities, zero duplicates), release consistency, workflow
inventory (33), workflow write-safety, documentation links (zero broken),
and `git diff --check`. No tests added or removed; no inventory delta required.
The quality ledgers and inventory baseline are byte-identical to the assigned
base (`check-dispatch-evidence.log`); there is no unbanked vulture identity to
repair or justify a ledger amendment.

A process-local pytest plugin bypassed the fixture-loaded `verify_dist`:
control test passed; mutant failed at `tests/test_promote_release.py:509`
with `assert 0 == 1` (`check-byte-mutation.log`). Probe wrapper exited 0 only
after requiring control exit 0, active injection, and mutant exit 1. No tracked
source was mutated. This confirms that the regression reaches byte verification
rather than passing on an unrelated tree rejection.

## Captured remote failure versus local state

`check-dispatch-evidence.log` records the supplied snapshot (no network calls):
PR #2536 head `5f6bff7d458f6d24f80a46a84983b6cf1b61ca1f` has completed/success
front-matter and completed/failure coverage checks. All refs were resolved
before ancestry checks. Existing coverage repair `87ce1ab3de` is an ancestor
of local HEAD (exit 0), but not of that captured remote head (exit 1).
The local diff gate passes freshly. This explains why re-running the local
repair loop cannot update the remote check; advancing the remote and obtaining
the full hosted result is an owner action, prohibited to this worker.
No front-matter failure or new local coverage/vulture defect was reproduced.

## Acceptance against reachable production behavior

Read accepted ADR-073126-c4e1 and ADR-095: the sole publishing path is protected,
tag-triggered `release.yml`; candidates come from `develop`, finals from
`main`, with immutable annotated tags and human release-environment approval.
No local publish, alternate authority or scheduler was introduced. Actual
release/soak evidence cannot be replaced by synthetic passing records.

| Criterion | Source and executed evidence | Remaining acceptance |
| --- | --- | --- |
| RC artifacts built only from candidate commit | `release.yml:279-316,577-586,642-651` candidate-only builds/identity recording; record/adoption tests in 703-test passing battery | Hosted exact-candidate build UNVERIFIED |
| Clean install, real-model, security hot path, backup/restore | `promote_release.py:150-156,286-303` requires each named passing check and citations; pinned-check/rejection tests pass | Actual functional soak UNVERIFIED |
| #860 exact-RC sustained multi-replica workload, crash/restart, admission/fencing, pressure, duplicate detection | `multi_replica_soak` required by gate; missing/failing checks and stale artifact bindings rejected in passing tests | Real representative workload and observations UNVERIFIED; this gate does not itself execute them |
| Invariant-invalidating findings filed/reclassified before promotion | `promote_release.py:306-329` validates boolean and routed issue syntax; rejection tests pass | Real issue filing, triage and contents UNVERIFIED |
| Runtime-affecting changes require new RC/applicable soak | `release_guard.py:190-247` enforces full git-tree equality to latest numeric RC; temporary-git rejection tests pass | Tracked-tree mechanism proven; deployed/external config equivalence and replacement soak UNVERIFIED |
| Final tag/tree and artifacts byte-equivalent to soaked RC | Tree guard, exact `verify_dist` hashes, finals adopt rather than rebuild; byte-bypass mutant killed | Actual RC/final artifact pair and registry manifest equality UNVERIFIED |
| External package/image/signature/install verification succeeds | Workflow clean-venv checks and digest signature verification wired; release tests pass | External consumer execution UNVERIFIED |
| Machine-readable soak evidence tied to promoted artifact/configuration | `promote_release.py:259-283,560-583` compares wheel/image bindings and requires config identity; binding tests pass | Real compatible evidence producer/transport and deployed-config binding UNVERIFIED |

`promote_release.py:44-57` explicitly requires the soak owner to supply an
Actions artifact named `soak-evidence` on the selected RC run with the strict
schema, not the #860 harness's native boolean record. `release.yml:946-955`
uploads that artifact only for finals, after adoption. The CLI tests inject
the download seam (`tests/test_promote_release.py:431-460`); they do not prove
the post-RC producer/transport exists or that any soak ran. Preserve this
fail-closed contract; do not weaken the schema to make a local test green.

## Disposition and handoff

**BLOCKED on operational acceptance**, not on a reproduced named local gate
failure. Only this validation note changed; existing implementation, tests,
workflow and quality policies are preserved. Release/soak owners must provide
the exact-RC functional and sustained workload evidence, route real findings,
complete the protected promotion, and verify externally published artifacts.
The full hosted 87% coverage floor also remains UNVERIFIED locally.

Progress: checked 1 issue; done 1 focused validation/handoff; skipped 0 assigned
items; unexpected validation errors 0. No push, tag, merge, GitHub mutation,
release execution or issue closure. A local documentation commit is handoff
only, not integration approval or issue completion.
