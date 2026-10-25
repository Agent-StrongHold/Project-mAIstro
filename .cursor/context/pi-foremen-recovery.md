# Persistent Pi foremen and recovery

Optional operator tooling, not a product daemon or a second autonomous fleet.
Read [the runbook](../../docs/operations/pi-foremen.md) before operating it.

- `pi`: human control/recovery front door; recover the exact registered journal.
- `maistro`: operations, ownership and bounded stall diagnosis.
- `homie1`: one admitted repair with reproducible verification; idle if unassigned.
- Source: `scripts/pi_recovery/`; tests: `tests/pi_recovery/`.
- Native intercom messages, never terminal keystroke injection or destructive
  pane replacement. Liveness, delivery, progress and remote completion differ.
- Startup/pokes grant no implementation, publication, merge or service authority.
  Reconcile existing work/owners and full remote SHAs before effects; no replay.
- Repo-owned memory is this portable contract/runbook, not private conversations.
  Live IDs, assignments, journals, credentials and host evidence remain outside Git.

A clone provides code and instructions, not a running installation or restored
private memories. Nothing is armed by checkout, import, or test collection.

## CI status diagnosis (2026-10-25, verified round)

Every check run on head `c899163de` is success or legitimately skipped
(74 captured), and the Coverage gate (publish-set floor + diff coverage) was
reproduced locally: root suite 6092 passed / 139 skipped / 0 failed under
`coverage run --branch --source=scripts`, then
`scripts/check-diff-coverage.py coverage.xml --base origin/develop` exit 0
(all 9 changed `scripts/pi_recovery` modules ≥90% lines / ≥80% branch arcs).
The branch touches 0 files under `packages/`, so the publish-set floor is
structurally unaffected.

The only red surface is the required `gates-ran` commit status, stuck
`pending` ("Required execution evidence is still arriving"). Local simulation
of `scripts/check-gates-ran.py` over the captured head evidence returns exit 2
with exactly one absent check: **Mutation gate (changed critical lines)**.
Root cause, on the default branch, not this one:

- `.github/workflows/mutation.yml` triggers on `pull_request` with a
  `paths:` filter (`packages/**/*.py` + mutation governance artifacts) and has
  no `merge_group` trigger, so it can never produce a check run for a
  candidate whose diff matches no path — and never on a queue SHA at all.
- `scripts/check-gates-ran.py` `required_check_names()` keeps every
  PR-reachable job from `scripts/check-required-checks.py` `collect()` and
discards the row's recorded `paths` scope, so the mutation gate is demanded as
  execution evidence on every candidate. Absence is classified pending, never
  excused (it is not in `PATH_SCOPED_CHECKS`).
- `.github/branch-protection.json` documents the same trap for branch
  protection: a paths-filtered job cannot be required "without waiting on
  `Expected` forever".

By design the publisher evaluates with default-branch code, so no candidate
branch can repair its own `gates-ran` verdict. Operator repair options:
(a) teach the evaluator/measured-envelope to excuse the mutation gate when no
mutation-critical file changed (mirror `PATH_SCOPED_CHECKS` with a `mutation`
leg in `scripts/ci_merge_group_scope.py`), or (b) give mutation.yml a
`merge_group` trigger and drop the `paths:` filter, exactly as its own
branch-protection note prescribes before requiring it.
