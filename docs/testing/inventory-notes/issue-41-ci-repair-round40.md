---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# Issue #41 CI-repair round 40: focused acceptance and coverage-producer validation

No production code or test identity changed in this validation-only round.

The supplied driver logs are not evidence of the reported coverage failure:
`check-1.log` reports only `All checks passed!`, and `check-3.log` reports the
focused suite passing. This round reran the ordinary task/chat acceptance seam:

```text
uv run pytest packages/maistro-server/tests/api/test_chat_completions.py \
  packages/maistro-server/tests/api/test_chat_completions_gate.py \
  packages/maistro-core/tests/test_container_chat_runs.py \
  packages/maistro-core/tests/tasks/test_idempotency.py \
  packages/maistro-core/tests/tasks/test_idempotency_durable.py \
  packages/maistro-core/tests/tasks/test_admission_commit_atomicity.py \
  packages/maistro-server/tests/api/test_tasks_idempotency.py -q -x
```

It passed: **210 passed, 1 skipped**. The exact required vulture ratchet also
passed with **1,342 reviewed identities**, **0 unclassified**, and **0
never-allowlisted**.

The CI-shaped publish-set coverage producer could not complete locally because
the required Docker daemon is unavailable. Its maistro-core and canvas portions
passed (**12,875 passed, 940 skipped, 1 xfailed**; **464 passed, 75 skipped**),
but the maistro-evolve portion then failed its Docker-backed sandbox tests with
`Cannot connect to the Docker daemon at unix:///var/run/docker.sock`. This is
environmental evidence, not a source-level coverage finding to repair.

Issue #41's declared closeout still requires #1845's real PostgreSQL
process-kill/multi-replica proof. The dispatched issue snapshot records #1845
as an open direct residual, so the parent acceptance is not established by this
round.
