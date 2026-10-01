---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-bootstrap/tests: +2
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

## What moved elsewhere

`test_registration_policy.py` drops `hardware_preset` from the
missing-required-fields parametrize: the field now carries the declared
default, so omitting it is a valid statement of "auto", not a contract
violation. admin/user passwords stay required. Net backend count: +8 new,
−1 parametrize case.
