---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 24: coverage-failure triage

No source or test change was made. The lane requested a repair for the named
coverage gate, but its job directory contains only the driver's lint, focused
pytest, and suite-inventory logs; it contains no coverage-gate output that
identifies a failed source line or producer. A speculative coverage edit would
not address evidence.

At `2b9a5b5c56ac`, the driver logs report:

- `ruff check .` and `ruff format --check .` passed;
- the focused task/Run/API battery passed (`428 passed, 134 skipped`);
- the focused Hive battery passed (`123 passed`); and
- all three affected suite inventories match their recorded counts.

The required exact vulture command also passed locally with 1,361 reviewed
identities and zero unclassified or never-allowlisted identities:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

The complete coverage producer cannot be validated in this worktree:
`DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`
exits 1 because the daemon is unavailable. The PostgreSQL and sandbox-backed
coverage producers therefore cannot be run or combined locally.

The acceptance closeout is independently blocked by the issue snapshot's
unresolved native sub-issue #1845. Its missing regression is visible in the
current suite: `test_a_complete_failure_still_returns_the_admitted_task` in
`packages/maistro-core/tests/tasks/test_idempotency.py` only asserts the first
response after a mocked completion failure; it does not recreate SQLite stores,
advance beyond the pending lease, and retry the same request. That scenario is
owned by #1845, so this #41 coverage-triage round does not make a false
completion claim.
