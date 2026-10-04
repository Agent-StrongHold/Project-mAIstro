---
inventory-delta:
  tests/: +21
---
# auto-402-remove-maistro-access-token

## What this change is

#402: `MAISTRO_ACCESS_TOKEN` was a deployment setting Compose handed to the
engine while no production code read it — auth is `API_KEYS` +
`REQUIRE_AUTH`. Its one live role was as the interpolation source for the
conductor's `MAISTRO_ROUTER_API_KEY`. The variable now exists under its
consumer's name only:

- `docker-compose.yml`: the dead engine passthrough is gone; the conductor's
  key is required (`${MAISTRO_ROUTER_API_KEY:?...}`) instead of silently
  empty (`:-`), because an empty key means the Workspace bridge never starts
  (ADR-092326-97c4). `docker-compose.pm-poc.yml` likewise.
- `install.sh` writes `MAISTRO_ROUTER_API_KEY`; the repair path carries an
  existing `MAISTRO_ACCESS_TOKEN` value over (no rotation), deletes the dead
  line via the new `remove-key` helper, and the env contract validates the
  new name against `API_KEYS`.
- `docs/product/DEPLOYMENT-STANCE.md`'s auth checklist item now names the
  real gate (`API_KEYS` / `REQUIRE_AUTH`).
- `scripts/check-compose-secrets.py` gained the inventory half of the
  acceptance criteria: every secret-named variable a tracked Compose file
  assigns or interpolates must have a production reader, a tracked
  `litellm_config.yaml` reference, or a reviewed third-party consumer
  (`_THIRD_PARTY_CONSUMERS`). A repeat of `MAISTRO_ACCESS_TOKEN` — a
  well-formed variable nothing reads — now fails CI instead of shipping.

## Where the +21 came from (13 + 8, measured by collection)

`tests/test_secret_env.py` +13: four tests for the new `remove-key` helper
(`TestRemoveKey`, including the `key=`-prefix non-match and the
no-op-on-absent contract); six collected under
`TestTheInstallerRenameMigration` — three new end-to-end drives of the real
`repair_existing_env` (legacy value carried to the new name with the dead
line gone, fresh-key generation registering itself in `API_KEYS`, existing
new name never overwritten) plus three inherited from `TestTheRealShellPath`,
re-run deliberately because that subclass widens the sourced-function set to
`random_secret` / `append_provider_placeholders` / `repair_existing_env` and
the mode/semantics assertions must hold against the wider extraction; and
three dash-value CLI tests under `TestTheCommandLine`.

`tests/test_check_compose_secrets.py` +8: the profile-pin class grew by one
(`test_the_dead_access_token_passthrough_is_gone`; the two renamed pins
replace, not add) and `TestASecretVariableMustHaveAReader` adds seven for the
unused-variable check — synthetic repo roots, so a corpus hit cannot leak in
from this tree; the real-tree case is pinned by the existing
`check.scan() == []` test, which now covers both halves of the gate, and by
`test_the_real_tree_has_no_unused_secret_variables`.

## The migration test exposed a real installer bug, fixed here

Driving `repair_existing_env` for real made a latent defect deterministic to
reproduce: `random_secret` emits urlsafe text, which starts with `-` one run
in 64, and argparse reads such an argv value as an option string —
`secret_env.py set-key: error: the following arguments are required: value`.
Measured flake rate matched ~1 − (63/64)^9 ≈ 13% per repair run (nine
generated values on that path). install.sh's `secret_env_run` call sites now
pass `--` before positionals, pinned by three CLI tests (`set-key` with a
dash value, with `--only-if-blank` in the spelling `fill_env_value` uses,
and `ensure-api-keys` with a dash token).
