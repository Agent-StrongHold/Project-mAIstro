---
inventory-delta:
  packages/maistro-core/tests: 0
  packages/maistro-server/tests: 0
  tests/: 0
---

# auto-42 round 25 — migrate the tool_skill adapter onto the effect_scope seam

CI-repair round at head bc97ebcbc (349d0c016 + the clean origin/develop sync
b78637f52/fa6e28ae8). Four required checks failed at 349d0c016 — `test`,
`lint-and-type-check`, `coverage (no services)`, and the `Quality gate` — and
the prior verifier reproduced the root cause locally: all four break on ONE
stale adapter.

## What failed and why

`packages/maistro-core/src/maistro/extensions/tool_skill/execution.py` was
written (M9-E3, fdc61aa2c) against the Invocation seam's retired
`logical_effect: bool` keyword. The seam migrated to the explicit
`effect_scope: str | None` identity (#1194 line of work), so every
`invoke_extension_tool` call raised `TypeError: unexpected keyword argument
'logical_effect'` from inside `GovernedInvocationExecutionService.invoke`:

- `uv run mypy packages/maistro-core/src ...` (CI's exact multi-package
  command): `Found 2 errors in 1 file` — call-arg at the `invoke` and
  `latest_effect` call sites;
- `uv run pytest packages/maistro-core/tests`: 14 failed / 23 passed in
  `tests/extensions/test_tool_skill_execution.py` +
  `tests/extensions/test_tool_skill_conformance.py`;
- `coverage (no services)` failed at its first producer step
  (`coverage run ... -m pytest packages/maistro-core/tests`), which is the
  same 14 failures — the floor and diff steps never ran;
- the `Quality gate` failed at its `mypy --strict packages/maistro-core/src`
  step on the same two call-arg errors.

The earlier driver lane passed because its pytest list omitted
`packages/maistro-core/tests/extensions`.

## The repair

Renamed the adapter's keyword end to end (9 lines, no behavior change beyond
the seam's own semantics): `invoke_extension_tool(..., effect_scope=None)`
passes through to `invocations.invoke`, and the interruption re-reads
(`_cancellation_outcome`, `_latest_invocation`) pass the same scope to
`latest_effect` — the pattern `agent_delegate_remote.py` already uses
(`effect_scope=key`). No caller anywhere passed `logical_effect`, so no
call-site churn outside the adapter. Repo-wide grep: no `logical_effect=`
call kwarg remains under `packages/*/src`.

## Validation (CI's exact commands, local)

- `uv run pytest packages/maistro-core/tests/extensions/...` → 37 passed
  (was 14 failed / 23 passed);
- `uv run mypy <10 package srcs>` → `Success: no issues found in 1022 source
  files`; `uv run mypy --strict packages/maistro-core/src` → Success (after
  installing `maistro-evolve`/`maistro-rsi` editables; CI's `--all-extras`
  has them);
- full `coverage run --branch -m pytest packages/maistro-core/tests` →
  14125 passed, 978 skipped, 1 xfailed; maistro-server producer → 535 passed;
- `scripts/check-diff-coverage.py coverage.xml --base b78637f52` → ok
  (per-file 90% lines / 80% branches on every measured changed file);
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1328/1328, no ledger amendment needed;
- `scripts/check-suite-inventory.py` for core/server/root suites → all ok,
  no drift (this round adds no tests — deltas are 0 by construction);
- `scripts/check-execution-lifecycles.py` → ok; `uv run ruff check .` and
  `uv run ruff format --check .` → clean;
- `uv run pytest formal/` → 663 passed, 1 skipped.

Environmental, not gated here: the evolve `TestRunFunctionChecksDocker` /
swebench benchmark tests need a running Docker daemon (unreachable in this
worktree; the branch touches no evolve/rsi code vs base b78637f52), and the
acceptance-state ratchet's Postgres legs were validated live in rounds
17–20; this round changes no AC-marked test and no criterion claim.
