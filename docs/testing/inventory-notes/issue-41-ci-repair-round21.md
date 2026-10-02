---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 21: coverage producer recheck

No tests or production code were changed in this validation-only round.

The required vulture exact-debt-ledger command passed at `58e90c19a9c6` after
`uv sync --locked --all-extras`: 1,402 findings were classified, with zero
unclassified and zero never-allowlisted identities. There was therefore no
genuine dead identity to remove and no baseline amendment to make.

The exact `coverage-unit` producer was then retried with its documented
`REQUIRE_AUTH`, `MAISTRO_DRY_RUN`, `PYTHONPATH`, branch coverage, and
`pytest --timeout=30` settings. It did not complete in this shared worker
within the producer's 20-minute budget. Its first failures were S3 archive
fixture imports, rather than an issue #41 path. A focused reproduction showed
`packages/maistro-core/tests/archive/test_archive_conformance.py::
test_an_archived_record_comes_back_byte_identical[s3]` error while importing
`flask.globals` through `moto.server`; `pytest-timeout` interrupted that import
after 30 seconds. The focused command reported `1 passed, 1 error in 40.49s`.

This is evidence that the coverage producer remains unproven locally, not
proof that the CI gate has passed or that #41 code should be changed. Focused
current behavior evidence passed: the task/idempotency/spine suite reported
**416 passed, 127 skipped**, and the chat-admission, chat-to-graph E2E,
container chat-run, and server chat API suite reported **132 passed**. Driver
check-4 also reports **121 passed** for the shipped Hive boundary suite. The
coverage gate and external closure of #1176 remain unverified and must be
resolved on an uncongested CI runner before a merge-ready verdict.
