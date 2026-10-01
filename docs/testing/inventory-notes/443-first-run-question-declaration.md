---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-bootstrap/tests: +4
  packages/maistro-core/tests: +6
---
# Issue #443 — one declaration of the first-run questions

Both first-run wizards used to restate the same questions with disagreeing
defaults: `maistro-install` seeded `maistro-admin`/`maistro-user`, the SPA
seeded `admin`/`""`, and `SetupCompleteBody` fell back to `admin`/`user` — so
the provisioned admin's name depended on how the stack was started. The fix
puts one declaration at `maistro/config/first_run.py` and makes every reader
consume it.

## What the tests cover

`packages/hive-conductor/backend/tests/test_setup_first_run_questions.py` is
new (8 tests):

- **The parity test** builds the terminal wire payload
  (`build_bootstrap_credentials`) and the SPA wire payload (defaults seeded
  from `GET /v1/setup/questions` over the real HTTP boundary, passwords as
  the only explicit answers) and asserts the two dicts are *equal wholesale* —
  one assertion for both paths, not per-path literals.
- Crypto-profile mapping: `no_crypto` on both paths keeps the payloads
  identical; the mapping is total over the wizard's profile choices.
- The questions endpoint serves `FIRST_RUN_QUESTIONS` (shape, values, no
  credential material in a public response).
- `SetupCompleteBody` field defaults equal the served declaration defaults
  (with `optional_modules` deliberately defaulted to *none* at the seam — a
  missing key must not silently provision an identity root).
- Omitted `hardware_preset` resolves to the declared default (the terminal
  path's documented `auto` decision), and blank usernames are refused instead
  of provisioned.
- Full provisioning over HTTP: the terminal's staged no-crypto payload POSTs
  to `/v1/setup/complete` on a fresh instance and provisions accounts named
  by the declaration — the same byte-identical payload the SPA posts, so this
  provisioned state is the one both paths reach.

`packages/maistro-bootstrap/tests/test_credentials.py` gains 2 (payload
defaults traced to the declaration; `full_all_crypto` mapping) and rewrites 2
to reference the declaration instead of literals.

## Coverage-gate repair (this branch's CI round)

The merge-queue run of the first commit failed the diff-coverage gate on two
files, both now measured by the producers that own them:

- `packages/maistro-core/src/maistro/config/first_run.py` scored **0.0% of 22
  changed lines**: no `packages/maistro-core/tests` suite imports the
  declaration, and the coverage producers that measure
  `--source=packages/maistro-core/src/maistro` run only that package's suites
  (the module's consumers live in maistro-bootstrap and hive-conductor, whose
  producers measure their own trees only).
  `packages/maistro-core/tests/config/test_first_run.py` is new (+6): the
  crypto-profile mapping total over the declared choices and beyond the
  Literal, the seam-required set being exactly the two passwords, every
  declared default equal to the constant it names (and no credential
  material defaulted), the canonical key set in served order, and a
  `model_dump`/`model_validate` round-trip of the served shape.
- `packages/maistro-bootstrap/src/maistro_bootstrap/wizard.py` scored **40.0%
  of 5 changed lines** (the account-name prompts and the crypto-profile
  select with the declared default were never executed): the wizard's
  collector had no test.
  `packages/maistro-bootstrap/tests/test_wizard_first_run_prompts.py` is new
  (+2): a scripted-questionary run of `collect_answers_interactive` asserts
  the prompts read the declaration's labels/defaults/choices (and that
  operator answers override them), so the terminal collector is itself
  covered, not just the payload it stages.

Net bootstrap count: +4 (2 declaration-mapping tests in `test_credentials.py`
from the original change, 2 wizard-prompt tests from this repair).

## What moved elsewhere

`test_registration_policy.py` drops `hardware_preset` from the
missing-required-fields parametrize: the field now carries the declared
default, so omitting it is a valid statement of "auto", not a contract
violation. admin/user passwords stay required. Net backend count: +8 new,
−1 parametrize case.

## CI-repair round evidence (gate-repair job 513d25b1)

The merge-queue evaluation at 10f12dcb reported `integration-scope: failure`
with `docker-build: cancelled`. Diagnosis from the tree, not the scanner:

- The scope classifier is unaffected by this diff: `scripts/ci_merge_group_scope.py`
  over the branch's changed paths returns `{docker_build, hive_e2e,
  strike_ladder, wheel_imports} = true`, and `scripts/check-integration-scope.py`
  resolves that to exactly `docker-build, hive-conductor-e2e,
  hive-conductor-e2e-ui, strike-ladder, wheel-imports` — no fail-closed
  widening, no classification error.
- A `cancelled` conclusion on `docker-build` is a queue-supersession artifact
  (the ci.yml concurrency group cancels in-progress merge-group runs), not a
  build defect. The leg's substance was proven locally on this head:
  `docker build -f packages/hive-conductor/Dockerfile` (frontend + backend of
  this diff) and `docker build -f Dockerfile` (engine; copies
  `packages/maistro-core`, including `config/first_run.py`) both exited 0.
- The vulture per-identity ledger repair command
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) reports 1390 findings / 1390 reviewed
  identities, `unclassified: 0`, ratchet `base fa3391e5e -> candidate
  10f12dcb` — nothing unbanked, nothing to amend: the test-only
  `hardware_preset` parameter was deleted rather than suppressed, so the
  ledger sees its removal.
- Local battery at this head: `ruff check .` clean, `ruff format --check .`
  clean (2673 files), 35 bootstrap/core tests pass, 64 backend
  registration/setup tests pass, all three suite inventories match,
  `npm run build` (vite + tsc) succeeds, eslint on the changed frontend files:
  0 errors.

## CI-repair round evidence (repair job b7c938ab, same head bb8a8337)

Re-proved from the tree at the identical head (no code changed this round;
the gate failure has no tree-level fix, only a superseded queue run):

- Failure reproduced deterministically:
  `check-integration-scope.py --event-name merge_group --scope-json
  <resolved> --result docker-build=cancelled ...` exits 1 with exactly
  `docker-build: required but result was cancelled` — the sole implicated
  check; the scope resolution for this diff (both the prior queue base
  fa3391e5 and the new develop base fa2deb0a) is unchanged:
  `{docker_build, hive_e2e, strike_ladder, wheel_imports} = true` →
  required `[docker-build, hive-conductor-e2e, hive-conductor-e2e-ui,
  strike-ladder, wheel-imports]`.
- The cancelled leg's substance proven on this head: `docker build -f
  Dockerfile -t maistro-engine:test .` exit 0, `docker build -f
  packages/hive-conductor/Dockerfile -t hive-conductor:test .` exit 0, and
  the engine image ships the declaration
  (`site-packages/maistro/config/first_run.py` present in the built image).
  With `--result docker-build=success` the same aggregator invocation exits
  0: `ok: integration scope satisfied for merge_group`.
- Vulture per-identity ledger repair command re-run verbatim
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): 1390 findings / 1390 reviewed identities,
  `unclassified: 0`, ratchet `base fa3391e5e -> candidate bb8a8337`, exit 0
  — nothing unbanked, so no ledger amendment exists to make.
- Acceptance re-executed, not trusted: 35 bootstrap/core declaration tests
  and 64 backend registration/setup tests pass (including the wholesale
  terminal==SPA parity assertion and the over-HTTP provisioning test),
  `ruff check .` + `ruff format --check .` clean.

Residual: the red integration-scope check at bb8a8337 clears only by a fresh
merge-queue evaluation (a superseded run's cancelled child is never retried
in place); every producer it waits on passes on this tree.

## CI-repair round evidence (repair job 2c7a65e2, head ca7c74109)

The next merge-queue evaluation at this head resolved the integration-scope
leg but was itself cancelled mid-run; the named residuals are SAST
(bandit + semgrep + gitleaks) = cancelled and the vulture per-identity
ledger repair. Both addressed from the tree, not the scanner:

- A `cancelled` SAST conclusion is queue-supersession (ci.yml concurrency
group), not a finding — and each leg was executed locally at this head:
  - bandit (`uvx bandit -r packages/maistro-core/src
    packages/hive-conductor/backend packages/maistro-server/src -ll
    --confidence-level=medium -f json`): exit 0, **Medium+ findings: 0**
    (strict zero-baseline gate satisfied).
  - semgrep (`uvx semgrep --metrics off --config
    tools/semgrep/maistro-rules.yaml --config p/security-audit --config
    p/owasp-top-ten --config p/secrets --error` over all 14 changed files):
    exit 0, 324 rules, **0 findings**.
  - gitleaks (`gitleaks git --redact
    --log-opts=fa2deb0a..ca7c741 .`): exit 0, **no leaks found** over the
    branch's changed range.
- Vulture per-identity ledger repair command re-run verbatim
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): exit 0, 1390 findings / 1390 reviewed
  identities, `unclassified: 0`, ratchet `base fa2deb0a4515 -> candidate
  ca7c74109` — nothing unbanked, so no ledger amendment exists to make
  (the test-only `hardware_preset` parameter is deleted, and the ledger
  reflects the removal).
- Acceptance re-executed, not trusted, at this head: 35 bootstrap/core
  declaration tests and 64 backend registration/setup tests pass
  (including the wholesale terminal==SPA payload parity assertion and the
  over-HTTP provisioning test), `ruff check .` + `ruff format --check .`
  clean (2674 files), all three suite inventories match, `npm run build`
  (vite + tsc) succeeds, eslint on the changed frontend files: 0 errors
  (1 warning on the gateway model-list effect — context-only in this
  branch's diff, pre-existing code).
- No code change this round; note update only.
