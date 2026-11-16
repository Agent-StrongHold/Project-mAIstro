---
inventory-delta:
  packages/maistro-canvas/tests: +3
  packages/maistro-server/tests: +1
---
# p0-1-principal-final-coverage

## What moved and why

- **canvas +3** — foreign-org guard tests on delete / latest / export
  (`test_{delete,latest_composite,export}_rejects_foreign_org_canvas_even_if_store_leaks`
  in `test_routes_org_paths.py`). They exist because the `CurrentUser` →
  `Principal` migration touched `maistro_canvas/auth.py` and the three canvas
  routes; the diff-coverage gate required the guarded branches to be exercised.
- **server +1** — `test_auth_off_admits_a_dev_principal` in `test_auth.py`:
  the auth-off sentinel path of `resolve_token_principal` (empty `api_keys` +
  `admin_api_keys` → dev principal) was reachable production behavior with no
  test; the migration made `Principal` the carrier, so the path is now pinned.
- Compensating edits, not count moves: `verify_api_key` assertions were
  rewritten off the burned `.token` attribute onto `user_id`, and the removed
  `principal.user_id != principal.token` assertion died with the attribute.

## Local gate reproduction (2026-11-16 verification round, head 64677f012a4d)

- `scripts/check-principal-identity.py` with CI's exact env
  (`RATCHET_BASE_REV=origin/develop`): ok — 4 tolerated → 0 current, none new.
- Diff-coverage gate reproduced locally: branch-coverage runs of the server
  (658 passed), canvas (584 passed), hive (4147 passed), privilege/fitness
  core selections, and the four root script tests under the changed
  `scripts/`, then `scripts/check-diff-coverage.py` vs base `f8a2df966a1d`:
  ok — all 17 changed measured files ≥90% lines / ≥80% branch arcs.
- Mutation gate: `mutation_critical.py --validate` ok (8 critical sources);
  target resolution reproduces the sole target
  `maistro/privilege.py` → `packages/maistro-core/tests`. The trusted merge
  base baseline has no entry for it, so per `mutation_pr_gate.py` the run is
  report-only and cannot fail the PR.

The aggregate 87% publish-set floor itself needs CI's full multi-producer
combine and was not reproduced locally; the branch deletes ~11k lines net, so
the risk direction is downward in denominator, not coverage.

## Second verification round (2026-11-16, head 03a40f495fa9 = develop f8a2df966 merged)

Issue test plan re-executed against the merged head:

- `scripts/check-principal-identity.py`: ok — 4 tolerated → 0 current, none new.
- `pytest packages/maistro-core/tests/fitness/test_principal_identity.py`
  `packages/maistro-server/tests/api/test_auth.py`: 39 passed.
- `pytest packages/hive-conductor/backend/tests/test_username_registry.py`:
  24 passed.

Driver check battery found one intermittent failure:
`test_concurrent_open_registration_claims_username_once`
(`test_registration_policy.py`) asserted 7×409 but observed 2×429 among the
eight simultaneous registrations. Diagnosis: the test's fresh
`AuthThrottle(_STRICTER.register)` kept production budgets
(per_client=5, per_account=3) that are *below* the contender count, and every
409 loser records a throttle failure (`routes/auth.py`); under machine load the
eight `check()` calls stagger, a late arrival reads a filled budget, and the
route lawfully answers 429. The test body was byte-identical on the develop
base, and the suite passed on re-run and in isolation — a pre-existing timing
flake, not a regression of this branch.

Repair (no collected count moved): the fresh throttle is now built with
`AuthLimits(per_client=8, per_account=8, global_failures=8)` — at most seven
failures can be recorded, so no scope can refuse, and the outcome depends on
the username-claim critical section alone. The route's real check/record path
stays exercised; the assertion set (1×200 / 7×409 / one row / one username) is
unchanged. Verified 5/5 passes under a 12-process CPU load on 20 cores, where
request runtimes stretched 2.1s → 5.8s — the staggered-arrival shape that
produced the 429s. Full hive battery re-run: 199 passed; suite inventory: ok.

## Third verification round (2026-11-16, head 9a08b7594b37 = throttle-decoupled test)

Independent re-execution on the final head (prior round's worker died to a
provider error after its driver battery, leaving scratch artifacts; all of
that round's recorded checks returned 0):

- Issue test plan, re-run in full:
  `scripts/check-principal-identity.py` ok — 4 tolerated → 0 current, none
  new (plain and with CI's `RATCHET_BASE_REV=origin/develop`, resolving base
  f8a2df966a1d both ways; CI's invocation at `quality.yml` principal
  identity is exactly this script);
  `pytest packages/maistro-core/tests/fitness/test_principal_identity.py`
  1 passed;
  `pytest packages/maistro-server/tests/api/test_auth.py`
  `packages/hive-conductor/backend/tests/test_username_registry.py`
  62 passed.
- Coverage additions pass by node id: the three canvas foreign-org guards
  (`test_routes_org_paths.py -k foreign_org`, 3 passed) and
  `test_auth.py::TestExplicitPrincipalContract::test_auth_off_admits_a_dev_principal`
  (1 passed).
- Driver battery on this exact head: `uv sync --locked --extra dev`,
  `ruff check .`, `ruff format --check .`, targeted server/canvas/core
  pytest (199 passed), hive backend selection (199 passed), and all four
  suite-inventory gates (hive 4194, canvas 642, core 18435, server 671) —
  every returncode 0.
- Mutation gate re-validated without re-running mutants:
  `mutation_critical.py --validate` ok (8 critical sources); the sole
  changed critical target is still `maistro/privilege.py` →
  `packages/maistro-core/tests`; the trusted merge-base baseline has no
  entry for it, so per `mutation_pr_gate.py` the run is report-only and
  cannot fail the PR. No production file changed since the head where the
  diff-coverage gate was reproduced locally (17 changed measured files,
  ≥90% lines / ≥80% branch arcs, round one), so that evidence transfers
  unchanged; the aggregate publish-set floor still requires CI's
  multi-producer combine.
- Salvage resolution: the prior round's untracked scratch
  (`changed-py.txt`, `diff-map.txt`, `mutation-targets.tsv`,
  `trusted-mutation-baseline.json`, `mutation-artifacts/*.diff`) are
  byte-verified replicas of the mutation workflow's own steps
  (`git diff --name-only origin/develop...HEAD` and
  `git show <base>:quality/mutation-baseline.json`); they carry no unique
  repo content, are left untracked, and are safe to regenerate or delete.

Residual: a CI run on the pushed head remains the only direct proof of the
aggregate coverage floor; the branch has not been pushed from this
worktree, and pushing is out of scope for a repair attempt.

## Fourth verification round (2026-11-16, head 3e70a3cf72fb = unchanged)

Prior round's worker died to provider auth expiry after all driver checks
returned 0. Independent re-execution on the same head:

- `uv run ruff check .`: All checks passed!
- `uv run ruff format --check .`: 3561 files already formatted
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: 1238 reviewed
  identities -> 1238 findings, 0 unbanked
- `uv run python scripts/check-radon-baseline.py`: 126 C-or-worse blocks
  match baseline, 0 new/regressed/stale
- `uv run python scripts/check-principal-identity.py`: 4 tolerated -> 0
  current, none new
- `uv run python scripts/check-route-permissions.py`: 42 declared, 0
  undeclared, none new
- `uv run python scripts/check-reachability.py`: 88 unreachable, all
  dispositioned
- `uv run python scripts/check-reachability-dispositions.py`: OK, 30
  groups cover all 88 unreachable modules
- `uv run python scripts/check_direct_effects.py`: 49 sites, all
  dispositioned
- `uv run python scripts/check-durable-table-inventory.py`: 125 tables,
  each with declared retention
- `uv run python scripts/check-promotion-surface.py`: ok
- `uv run python scripts/check-workspace-retirement.py`: 85 tolerated
  importers match
- `uv run python scripts/check-model-egress.py`: 16 physical callers, no
  expansion
- `uv run python scripts/check_enumerations.py`: 1 tolerated gap, no new
- `uv run python scripts/check-contract-markers.py`: OK
- `uv run python scripts/check-compliance.py`: valid
- `python3 scripts/check-cross-package-imports.py`: 3548 files ok
- `python3 scripts/check-api-route-contracts.py`: 306 handlers, 0 canned
- `python3 scripts/check-merge-markers.py`: no conflict markers
- Driver battery (exact manifest checks): check-0 (uv sync) rc=0,
  check-1 (ruff check) rc=0, check-2 (ruff format) rc=0, check-3
  (targeted pytest: 299 passed, 91 skipped), check-4 (hive battery:
  199 passed), check-5..8 (suite inventory: all ok)
- `git merge-base --is-ancestor origin/develop HEAD`: confirmed

No code changes in this round; evidence-only verification.

## Fifth verification round (2026-11-16, head 644f5a084ef2, this worktree's HEAD)

Prior round's worker died to a provider error after its full driver battery
returned 0 on this exact head (its nine check logs: uv sync, ruff check,
ruff format, targeted server/canvas/core pytest 299 passed / 91 skipped,
hive battery 199 passed, four suite-inventory gates ok). Independent
re-execution, all on this head:

- Issue test plan, re-run in full: `scripts/check-principal-identity.py`
  ok — 4 tolerated → 0 current, none new, base f8a2df966a1d (plain and with
  CI's `RATCHET_BASE_REV=origin/develop`, identical result);
  `pytest packages/maistro-core/tests/fitness/test_principal_identity.py
  packages/maistro-server/tests/api/test_auth.py` — 39 passed;
  `pytest packages/hive-conductor/backend/tests/test_username_registry.py
  packages/hive-conductor/backend/tests/test_registration_policy.py` —
  81 passed (the throttle-decoupled race included, no 429s observed).
- Acceptance-claim greps on reachable production code:
  `quality/principal-identity-baseline.json` `tolerated` is `{}`; no
  `AuthenticatedPrincipal` / `CurrentUser` / `HiveUser` /
  `_SubsystemIdentity` class definitions remain under `packages/*/src` or
  `packages/hive-conductor/backend` (one historical comment mention in
  `maistro/container.py`); `hive routes/capabilities.py` resolves the
  approval actor via `request_principal(request)` /
  `principal_has_permission(principal, "approvals.resolve")` — the nested
  `state.user` read is gone (documented in-file at lines 297–302).
- Diff-coverage gate reproduced at THIS head, not transferred: branch
  coverage runs of the four producers that cover the 17 changed measured
  source files — server suite (1 timing-flake failure in
  `test_sigterm_shutdown.py::...test_stop_destroys_seeded_sandbox_and_restart_is_clean`,
  passes in isolation without coverage; file last touched by develop
  #2143, not this branch; 660 passed otherwise), canvas suite 587 passed,
  full hive suite 4165 passed, privilege/fitness/escape core selections
  29 passed; combined, then `scripts/check-diff-coverage.py coverage.xml
  --base f8a2df966a1d`: ok — every measured file ≥90% lines / ≥80% branch
  arcs, exit 0. The publish-set 87% floor still requires CI's
  multi-producer combine (PostgreSQL/MinIO producers included).
- Mutation gate re-proven with CI's exact commands:
  `mutation_critical.py --validate` ok (8 critical sources);
  `git diff --name-only origin/develop...HEAD -- packages
  --diff-filter=ACMR` + `mutation_critical.py --changed-from` resolves the
  sole target `maistro/privilege.py` → `packages/maistro-core/tests`,
  byte-identical to the worktree's untracked `mutation-targets.tsv`; the
  trusted merge-base baseline (`git show
  f8a2df966a1d:quality/mutation-baseline.json`) has `entries: {}`, and
  `scripts/mutation_pr_gate.py` marks an unbaselined source report-only
  (lines 303–324: it "can neither pass nor fail"), so the gate cannot fail
  this PR. The scratch artifacts are confirmed byte-identical replicas of
  this workflow's own steps and stay untracked.
- Vulture ledger with CI's exact args: `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — exit 0,
  1238 reviewed identities → 1238 findings, 0 unbanked.
- `uv run ruff check .`: All checks passed! · `uv run ruff format --check
  .`: 3561 files already formatted.
- CI state on the pushed PR head 0429476fddef (dispatch evidence): every
  quality.yml check success including "Quality / Principal identity",
  "Coverage gate (publish-set floor + diff coverage)", "Quality gate
  (Pillars 1–4, 7, 8)", and the second SAST run (Bandit/Gitleaks success);
  that head merged develop up to 78133c093, while this worktree's HEAD
  merges the newer develop tip f8a2df966 — CI has not yet run on content
  containing f8a2df966, which the next push will cover. Pushing remains
  out of scope for a repair attempt.

No code changes in this round; evidence-only verification.

## Sixth verification round (2026-11-16, head 28ef6871e4f7 = then-HEAD)

Prior round's worker died to a provider 429 after its full driver battery
returned 0 at this exact head (its nine check logs: uv sync, ruff check,
ruff format, targeted server/canvas/core pytest 299 passed / 91 skipped,
hive battery 199 passed, four suite-inventory gates ok). This round's
driver re-ran the identical battery at the same head — all nine
returncodes 0. Independent re-execution, all on this head:

- Issue test plan, re-run in full: `scripts/check-principal-identity.py`
  ok — 4 tolerated → 0 current, none new, base f8a2df966a1d, both plain
  and with CI's `RATCHET_BASE_REV=origin/develop` (origin/develop
  resolves to f8a2df966a1d and `git merge-base --is-ancestor` confirms it
  is an ancestor of HEAD);
  `pytest packages/maistro-core/tests/fitness/test_principal_identity.py
  packages/maistro-server/tests/api/test_auth.py` — 39 passed;
  `pytest packages/hive-conductor/backend/tests/test_username_registry.py`
  — 24 passed.
- Acceptance-claim greps re-run: no `class AuthenticatedPrincipal` /
  `CurrentUser` / `HiveUser` / `_SubsystemIdentity` definition remains
  under `packages/*/src` or `packages/hive-conductor/backend`;
  `quality/principal-identity-baseline.json` `tolerated` is `{}`;
  `hive routes/capabilities.py` resolves the approval actor via
  `request_principal(request)` /
  `principal_has_permission(principal, "approvals.resolve")` (lines
  299–318, the nested `state.user` read is gone).
- The acceptance tests this branch added pass by node id: the three
  canvas foreign-org guards (`test_routes_org_paths.py -k foreign_org`)
  and
  `test_auth.py::TestExplicitPrincipalContract::test_auth_off_admits_a_dev_principal`.
- Vulture ledger with CI's exact args (`check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  exit 0, 1238 reviewed identities → 1238 findings, 0 unbanked.
- `uv run ruff check .`: All checks passed! · `uv run ruff format --check
  .`: 3561 files already formatted.
- Mutation gate preflight: `mutation_critical.py --validate` ok (8
  critical sources). CI's exact target resolution
  (`git diff --name-only origin/develop...HEAD -- packages
  --diff-filter=ACMR` → `mutation_critical.py --changed-from`) was
  regenerated this round and is byte-identical to the worktree's
  untracked `changed-py.txt` / `mutation-targets.tsv`: the sole target
  stays `maistro/privilege.py` → `packages/maistro-core/tests`, and the
  trusted merge-base baseline (`git show
  f8a2df966a1d:quality/mutation-baseline.json`) has `entries: {}`, so
  per `mutation_pr_gate.py` the run is report-only and cannot fail the
  PR. The untracked scratch (`changed-py.txt`, `diff-map.txt`,
  `mutation-targets.tsv`, `trusted-mutation-baseline.json`,
  `mutation-artifacts/*.diff`) remains byte-verified replicas of the
  workflow's own steps and stays untracked, as resolved in rounds three
  and five.
- Diff-coverage evidence transfers unchanged: `git diff --name-only
  644f5a084..HEAD` contains only this inventory note, so the fifth
  round's reproduction at 644f5a084 (17 changed measured files ≥90%
  lines / ≥80% branch arcs) still describes HEAD's changed source set;
  the aggregate publish-set floor still requires CI's multi-producer
  combine.

No code changes in this round; evidence-only verification.

## Seventh verification round (2026-11-16, head 28ef6871e + this commit)

Prior round's worker died to a provider 429 after its green driver battery
at this head. This round re-proved the issue plan (ratchet 0 violations
plain and with `RATCHET_BASE_REV=origin/develop`; 39 + 24 pytest passes;
acceptance greps; vulture 1238→1238, 0 unbanked; ruff/format; mutation
targets byte-identical, merge-base baseline empty) and then closed the one
gap every prior round had left open: **Quality / Acceptance state was never
reproduced locally** — it needs Postgres, the full extras, `age-keygen`, and
the ~180 `ac`-marked tests.

Reproduced CI's job faithfully (native pg18 on the CI DSN, alembic head,
`uv sync --locked --all-extras` + editable `maistro-evolve` +
`pytest-timeout`, `age-keygen` present) and ran CI's exact PR command:

- First run FAILED — not on the bound but on **unbanked improvement**:
  measured `design_coverage 44.4608` while the tree's own (untracked,
  never-committed) note banked `39.8641` from an earlier degraded run. The
  judged bound (base fold granted to 39.641 by
  `ratchet-authorizations.json` `ac-state/design_coverage@39.641`) passed;
  the acceptance and chain mandates both passed (11 criteria added or
  newly claimed since the PR base 78133c093, 0 unproven; no new absent
  links). Because `banked_bound()` folds the worktree, and CI checks out
  only committed files, the next push would have failed this required gate
  either way: without the note the committed fold (44.2377, granted to
  39.641) still reads 44.4608 as unbanked slack on a PR run. The stale
  note was a CI failure in waiting, not scratch.
- Remedy per the gate's own instruction: `check-ac-state.py --run-tests
  --ratchet --bank` re-banked the branch note at the honest measured
  value (`design_coverage 44.4608`, ceilings unchanged at
  31/0/0/0/137/2/0/76/7/0, `measured_with_tests: true`). Folded by `max`,
  this tightens the floor future branches inherit — recording an
  improvement, never weakening a gate.
- Re-run of CI's exact PR invocation
  (`--run-tests --ratchet --mandate 78133c093`, `RATCHET_BASE_REV=origin/develop`):
  **rc=0** — ratchet OK (all counters on their bounds), acceptance mandate
  OK, chain mandate OK. The committed note is the only tree change in this
  round.

Residual: CI's own run on the pushed head remains the final word (its
runner measures the same corpus with the same pg18 service; a flaky
`ac`-marked test would show as a regression against the just-banked floor).
Pushing is out of scope for a repair attempt.

## Eighth verification round (2026-11-16, head c82361149bcb = current HEAD)

Prior round's worker died to the wall-clock deadline AFTER its full driver
battery returned 0 at this exact head (nine check logs: uv sync rc=0,
ruff check rc=0, ruff format rc=0, targeted server/canvas/core pytest
299 passed / 91 skipped, hive battery 199 passed, four suite-inventory
gates ok). It left only the documented untracked scratch. Independent
re-execution at this head, without inheriting any prior round's claims:

- Issue test plan, re-run in full at HEAD: `scripts/check-principal-identity.py`
  ok — 4 tolerated → 0 current, none new (baseline resolves to base
  f8a2df966a1d); `pytest fitness/test_principal_identity.py` +
  `server/api/test_auth.py` — 39 passed; `pytest
  hive/backend/tests/test_username_registry.py` — 24 passed; the branch's
  own additions pass by node id (3 canvas foreign-org guards;
  `test_auth_off_admits_a_dev_principal`).
- Vulture ledger with CI's exact args: 1238 reviewed identities → 1238
  findings, 0 unbanked, rc=0.
- Mutation gate re-derived from source, not transferred:
  `mutation_critical.py --validate` ok (8 critical sources); CI's exact
  target resolution regenerated (`git diff --name-only
  origin/develop...HEAD -- packages --diff-filter=ACMR` →
  `--changed-from`) and is byte-identical to the untracked
  `changed-py.txt` / `mutation-targets.tsv` — sole target
  `maistro/privilege.py` → `packages/maistro-core/tests`; the trusted
  merge-base baseline (`git show f8a2df966a1d:quality/mutation-baseline.json`)
  has `entries: {}`, and `scripts/mutation_pr_gate.py` (lines 303–324)
  makes an unbaselined source "report-only" — the gate cannot fail this
  PR. `git merge-base --is-ancestor origin/develop HEAD` confirmed.
- Acceptance-claim greps at HEAD: no `class AuthenticatedPrincipal` /
  `CurrentUser` / `HiveUser` / `_SubsystemIdentity` definition remains
  under `packages/*/src` or `packages/hive-conductor/backend`;
  `quality/principal-identity-baseline.json` `tolerated` is `{}`;
  `hive routes/capabilities.py` resolves the approval actor via
  `request_principal(request)` / `principal_has_permission(principal,
  "approvals.resolve")` (lines 299–318).
- The last commit's AC-state note is committed and readable
  (`quality/ac-state-notes/feat-cutover-p0-1-principal-final.json`:
  design_coverage 44.4608, measured_with_tests true); only that JSON and
  this note changed since 644f5a084, so the fifth round's local
  diff-coverage reproduction (17 changed measured files ≥90% lines /
  ≥80% branch arcs) still describes HEAD's changed source set.
- Stale-CI reconciliation (dispatch evidence for pushed head 0429476fddef,
  all runs 2026-10-26): the named RED gates' most recent recorded results
  are success — Coverage gate ×2, Quality gate (Pillars) at 11:50:17,
  Quality / Ruff ×2, Quality / Principal identity ×2; the 11:32/11:51
  failures completed in ≤6 s (aggregator re-run against cancelled
  siblings — infra, not findings). SAST: Bandit + Gitleaks succeeded;
  Semgrep was twice *cancelled* by concurrency, which alone fails the
  combined "SAST (bandit + semgrep + gitleaks)" require-step; local
  semgrep with the repo's `tools/semgrep/maistro-rules.yaml` over the
  branch's changed trees (privilege, server, canvas, hive backend):
  245 files, 0 findings. Mutation gate: report-only as derived above.
  No CI run exists yet on content containing develop f8a2df966 + the
  seven later commits; that push is the integration reviewer's act.
- Salvage resolution re-confirmed: the untracked scratch is a byte
  replica of the workflow's own steps (`changed-py.txt` regenerated this
  round, diff-identical; `trusted-mutation-baseline.json` content
  identical to the merge-base baseline); it stays untracked.

No code changes in this round; evidence-only verification.

