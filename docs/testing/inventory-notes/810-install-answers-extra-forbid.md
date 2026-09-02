---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-bootstrap/tests: +12
---

# 810-install-answers-extra-forbid

#810: unknown install-answer keys are validation errors, not silent defaults.

`InstallAnswersV1` moved to `ConfigDict(extra="forbid")`. Every new node ID
exists to prove a misspelled security field (`sandbox_profle`, `crypto_profil`,
`additonal_users`), an arbitrary unknown key, or a forbidden password field
fails validation **naming the key** — instead of being silently ignored while
the install falls back to defaults.

- `packages/maistro-bootstrap/tests` **+12**: ten in `test_schema.py` (parametrized
  typo trio, generic-unknown-key, the `extra=forbid` config pin, the
  merge-session path, two `describe_validation_error` formatter tests, and the
  no-implicit-aliases/AC-5 pin) and three in the new `test_cli_answers.py`
  (valid file plans; misspelled security key and password field exit 2 via
  `typer.BadParameter` naming the key, with no plan printed).
- `packages/hive-conductor/backend/tests` **+1**: `test_api.py` gains
  `test_install_session_unknown_key_is_422_naming_the_key` — POST
  `/v1/install/session` with a typo'd key is a 422 naming it, never a silent
  default or an opaque 500.

No tests were removed or renamed. Measured with `pytest --collect-only -q` per
suite; the two trees this change touches are the only ones whose counts moved.
