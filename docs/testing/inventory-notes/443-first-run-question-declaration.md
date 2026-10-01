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
