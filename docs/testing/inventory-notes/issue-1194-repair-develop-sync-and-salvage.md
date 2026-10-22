---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# issue-1194 repair round: develop sync merge 6c2b4df63 + salvage resolution

Repair round against `origin/develop@151bcfe2` (the lane's develop base). The
incoming develop commits (`9241324f` run-purge inventory, `151bcfe2` effect-door
ratchet grants) were merged into `auto-1194` as `6c2b4df63`; the merge was
conflict-free (ort), touching only `runs/retention_scope.py`,
`runs/sqlite_store.py` (comments), `runs/store.py` (docstring),
`sensitive_paths.py`, `ratchet-authorizations.json`, `CHANGELOG.md` and the
inventory scan test. No tests were added or removed (net +0).

## Uncommitted salvage resolved

The previous run left an uncommitted edit in
`packages/maistro-core/src/maistro/graph/durable_runs/attempt_executor.py`:
a `ReplaySemantics.EFFECT_KEY` probe inside `_execute_frontier` that called
`node.replay_effect_key(inputs, ctx)` and then `pass`ed. The block was not a
no-op in practice: `inputs` at that point is the resolved-inputs **dict**, and
`BaseNode.replay_effect_key` calls `inputs.model_dump(mode="json")` for
EFFECT_KEY kinds, so every durable execution of an EFFECT_KEY node
(`compliance.block`, `agent.delegate_remote`, ...) raised AttributeError and
29 durable-runs/HITL tests failed (verified: same tests pass in a clean
checkout of the identical tree without the stub). The enforcement the stub
gestured at already exists where it belongs — the node contract
(`BaseNode.replay_effect_key` records the key into `NodeResult.metadata`) and
the executor retry policy (`_may_revisit_after` refuses NON_RETRYABLE and
requires a recorded effect key plus logical Run/node identity for EFFECT_KEY).
The dead block was removed; the diff is preserved at
`~/Git/wt/incoming-1194.patch`.

## Pyright regression fixed in code, not baseline

`uv pip install pyright` (1.1.414) at this tree reports 22 errors vs the
ratchet baseline of 21; diffing against the same pyright at the base revision
`151bcfe2` shows exactly one new identity:
`runs/pg_store.py:679 reportArgumentType` (`PoolConnectionProxy` passed to
`_require_locked_parent_scope(conn: asyncpg.Connection)`). Fixed by retyping
the parameter `conn: Any`, matching the store's nine other connection-taking
helpers; error count returns to 21 and the ratchet passes without a
floor-raise.

## Gates run this round (all local, real Postgres pg18 on :18944)

- `uv run ruff check .` / `uv run ruff format --check .` — pass
- `uv run pytest packages/maistro-core/tests/graph -q` — 1477 passed
- `uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/capabilities packages/maistro-core/tests/a2a -q` (pg DSN set) — 1567+1467 passed
- `uv run alembic upgrade head` — applies through 043 (#1194 effect index)
- `scripts/check-ac-state.py --run-tests --ratchet --mandate 151bcfe2e...` — OK, every declared criterion proven
- `uv run mypy --strict packages/maistro-core/src` — clean (after `uv sync --all-extras`)
- pyright ratchet — 21 == baseline 21, gate exit 0
- `pytest formal/` — 663 passed (after installing maistro-evolve editable)
- fitness tests 9 passed; interrogate floors 38/45/63/46 all pass
- radon/xenon/doc-links/enumerations/vendored-provenance/release-consistency/version/reachability/credential-authority/wiring-reads/agent-store-writes/contract-markers/convergence/lifecycles/model-egress/reachability-dispositions/security-inventory/image-inventory/backlog-consistency — all pass
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — still FAILS on the two `a2a.py` route-handler identities by design: the grants exist in this branch's `quality/ratchet-authorizations.json` and the identities are banked in the candidate `quality/vulture-baseline.json`, but the gate reads authorizations **from the trusted base revision** (`merge-base(origin/develop, HEAD)`), where they cannot yet exist. That is the documented two-merge rule in `scripts/ratchet_provenance.py` ("a new grant does not take effect in the change that introduces it"); it self-heals once this branch lands and develop carries the grants. Nothing is genuinely dead to delete: both identities are live FastAPI routes implementing #1194's transport idempotency.
