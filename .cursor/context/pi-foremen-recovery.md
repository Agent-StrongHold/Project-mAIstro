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

## Coverage gate re-proven at head 99eda89ee (2026-10-26, verified round)

The cancelled CI run (job 121397566077, run 40240833368) never reported a gate
failure — it died to runner/agent budget exhaustion. The gate was re-proven
locally at the current head, after the two develop syncs (cbfa25c94, 99eda89ee
bringing develop to 78133c093), with CI's exact commands and base:

- Root producer, exact `quality.yml` argv: `coverage run --append --branch
  --source=scripts -m pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30
  -q` → 6098 passed / 139 skipped / 0 failed in 11m10s (RATCHET_BASE_REV set,
  as a PR run would).
- `coverage xml` then `scripts/check-diff-coverage.py coverage.xml --base
  78133c093e0a5cd0d2a7e8538afa703521c70d07` → exit 0: 9 changed
  `scripts/pi_recovery` modules measured, all ≥90% lines / ≥80% branch arcs;
  the 6 `tests/pi_recovery` files are exempt as evidence, by declaration.
- Publish-set floor (87%): structurally unaffected — `git diff --stat
  78133c093..HEAD -- packages/` is empty, and the floor is evaluated in the
  combine step before any scripts-producer data joins, from the three upstream
  producers whose measured trees are byte-identical to the base.
- `scripts/check-suite-inventory.py` → ok, 21 suites, `tests/: 6215` and root
  collection reproduces exactly 6215 (+177 = +85 `pi-foremen-recovery` + +92
  `pi-foremen-recovery-coverage`).
- Vulture ledger with CI's exact argv → 1253 reviewed identities = 1253
  findings, base resolved to 78133c093. Ruff check/format, check-test-duplicates
  and `tests/test_check_diff_coverage.py` (18) all green; `systemd-analyze
  --user verify` clean on all four shipped unit templates; `pytest
  tests/pi_recovery` 177 passed + 32 subtests in 2.1s.

No tree change was required this round: the repair of record remains 40ada5e6e
(92 offline cases), which survives both develop syncs. The only red surface is
still the default-branch `gates-ran` evaluator trap documented above.
