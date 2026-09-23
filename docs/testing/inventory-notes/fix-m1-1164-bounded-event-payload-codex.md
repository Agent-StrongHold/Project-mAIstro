---
inventory-delta:
  packages/maistro-core/tests: +20
---
# fix-m1-1164-bounded-event-payload-codex

Answers the three review findings on the #1164 scrub
(`fix/m1-1164-bounded-event-payload`): a credential used as a mapping *key*
survived `redact_structure` (no field name classifies it, no value scan
reaches it); `effect_key` -- the join identifier every canonical capability
event carries -- classified as a credential name (`effect`/`key`) and was
replaced with `[REDACTED]`; and redaction can grow a field (an empty value
under a secret name becomes `[REDACTED]`) past the byte ceiling that was
checked only before the scrub.

**`maistro.security.redact.redact_structure`** now scans string mapping keys
for secret shapes, keeps two keys that redact to one label distinct with a
`#n` suffix rather than collapsing them, and recognises its own labels on
re-scrub so the walker stays idempotent (a label's segments would otherwise
classify as a credential name and swallow the value under it).
**`maistro.security.secret_policy`** gains a reviewed, deliberately narrow
`_IDENTIFIER_KEY_PREFIXES` set: a `key` immediately preceded by `effect`,
`idempotency`, `cache`, `partition`, `sort`, `routing`, `correlation`,
`dedupe`, `primary`, `foreign`, `parent`, `issue`, `project`, `cycle`,
`scope`, `occurrence`, `archive`, `index` or `lookup` is an identifier; a
strong family segment anywhere in the name still wins, and `access_key`,
`api_key`, `private_key`, `master_key` stay sensitive.
**`EventEnvelope.__post_init__`** re-runs `_check_field_bounds` on the
scrubbed `payload` and `provenance`, so the advertised ceiling holds for what
a backend actually sees; the pre-scrub check stays to bound the redactor's
work.

**Tests (+20, all in `packages/maistro-core/tests`).**
`tests/security/test_secret_policy.py` (+13 parametrized node ids): nine
identifier-style names survive (`effect_key`, `idempotency_key`,
`cache_key`, `partition_key`, `primary_key`, `parent_key`, `issue_key`,
`effectKey`, `idempotencyKey`); four stay sensitive (`effect_secret_key`,
`effect_token_key`, `access_key`, `master_key`).
`tests/security/test_redact.py` `TestRedactStructure` (+4): a secret-shaped
mapping key is scrubbed; two secret keys that share a label stay distinct;
scrubbed mapping keys are stable on a second pass; identifier-style key
names survive. `tests/events/test_envelope.py`
`TestPayloadSecretScrubbing` (+3): a credential used as a mapping key is
scrubbed at the envelope seam; a capability `effect_key` survives the
scrub; a payload the scrub grows past the ceiling is rejected with
`EventPayloadTooLarge` even though it passed the pre-scrub bound.

`packages/maistro-core/tests/security` + `tests/events` +
`tests/capabilities`: 1850 passed, 61 skipped, plus one pre-existing
environment-only failure (`test_log_redaction.py::test_install_is_idempotent`
fails identically on the unmodified branch when run from a secondary
worktree against the primary venv; CI's `test` job on 21d8d586 is green).
`ruff check`/`ruff format --check` clean; `mypy --strict` clean on the three
touched modules.
