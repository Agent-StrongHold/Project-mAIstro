---
inventory-delta:
  packages/maistro-core/tests: +21
---
# fix-m1-1164-bounded-event-payload-d9b7

#1164's remaining scrub item (AC-7): credential material is removed from
canonical Event `payload`/`provenance` at construction. No test was removed or
renamed, so the whole +21 is new coverage split across two files.

- `tests/security/test_redact.py`: +11 — a `TestRedactStructure` class for the
  new `redact_structure` walker. Covers both halves of the policy it composes
  (name-based classification, value-shape scanning) and, deliberately, the
  places they *disagree*: the identifier escape lets `key_arn`/`token_id`
  through, while `aws_access_key_id` is still redacted because the value half
  recognizes the shape independently of the name. The rest pin the properties
  the Event seam depends on — idempotence, deep-copy semantics, tuple and
  non-string-key preservation — plus a false-positive control asserting that
  digests, uuid4 ids and prose survive untouched.

- `tests/events/test_envelope.py`: +10 — a `TestPayloadSecretScrubbing` class.
  Nine tests, one of which (`test_no_backend_can_persist_a_credential`) runs
  against the file's existing memory/SQLite `store` fixture and so collects as
  two node IDs. These pin the *wiring* rather than the detector vocabulary:
  that the scrub happens at the one constructor every backend goes through,
  that a durable read-back cannot yield the credential, that the byte bound is
  enforced *before* the scrub runs (a 256 KiB value under a secret name must be
  rejected, not collapsed to `[REDACTED]` and admitted), that re-validating an
  already-scrubbed envelope is idempotent, and that `reconstruct_persisted_event`
  does not re-scrub a historical row.
