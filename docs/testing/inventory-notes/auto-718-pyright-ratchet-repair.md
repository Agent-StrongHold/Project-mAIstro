# CI repair round — pyright ratchet 22 > 21 (head 664646d03 → this head)

Repair-only round for #718; no tests added or removed. The prior CI run
(`actions/runs/36312184427/job/108600150368`) failed the
"Quality gate (Pillars 1–4, 7, 8)" job. Root cause reproduced locally, not
guessed from the scanner: the job's `pyright (type cross-check — ratchet)`
step reported **22 errors against the PYRIGHT_BASELINE of 21**, and the one
branch-introduced error was ours:

- `packages/maistro-core/src/maistro/quota/recorder.py:93` —
  `await record_unreported(...)` where the hook came from
  `getattr(self._quota_tracker, "record_unreported", None)` narrowed by
  `callable(...)`, which pyright types as `Callable[..., object]` →
  `"object" is not awaitable`. `record_unreported` is intentionally not on
  the `QuotaTracker` protocol (protocols/quota.py declares `record_usage`,
  `record_invocation`), so the duck-typed lookup cannot be statically
  awaitable without a cast.
- All other 21 errors are pre-existing develop debt: every other reported
  site (`agents/artificer/strategy.py:198,201`, `agents/base.py:837`,
  `agents/strategies/react.py:215,218`,
  `capabilities/providers/subprocess_harness.py:155`, `cli/_builders_tui.py`,
  `identity/__init__.py`, `persistence/pg_learnings.py`,
  `persistence/pg_prompts.py`, `personas/scorer.py`,
  `security/warden/_regex.py`, `security/warden/detector.py`,
  `tools/browser/guard.py:223,225`) is byte-identical on `origin/develop`
  (verified via `git diff origin/develop...HEAD` — only `quota/recorder.py`
  and an unrelated `agents/base.py` turn-correlation hunk are branch-changed,
  and the base.py error line predates the branch).

Fix: guard with `is not None` and `cast("Callable[[str, str], Awaitable[None]]",
...)` at the single call site; runtime behaviour is unchanged for real
trackers (a non-None non-callable hook now fails loudly instead of being
silently skipped). After the fix: `check-pyright-report.py` reports
**21 errors (baseline: 21)** → gate exit 0.

Also this round (per lane brief): merged `origin/develop`
(`4f8339aa6`) into `auto-718` — the merge was clean, no conflicts; the
previous "develop sync conflict preserved in worktree" block referred to
state already resolved by merge `664646d03`.

## Validation executed this round (all exit 0 unless noted)

Quality-gate steps, in workflow order — `ruff check .`; `ruff format
--check .`; `check-radon-baseline.py`; `bump_version.py --check`;
`check-release-consistency.py`; `check-doc-links.py`; `check_enumerations.py`;
`vendor_ifeval.py --check`; `vendor_bfcl.py --check`; xenon 66 ≤ 77;
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` (1403 candidate-ledger identities == 1403 findings; the
branch had already pruned the identity develop's trusted 1404 ledger lost);
`check-reachability.py`; `check-credential-authority.py`;
`check-wiring-reads.py` (11 → 11 vs base 4f8339aa6);
`check-agent-store-writes.py`; `check-contract-markers.py`;
`check-convergence-matrix.py`; `check-reachability-dispositions.py`;
`check-security-inventory.py`; `check-image-inventory.py`;
`check-backlog-consistency.py`; `alembic upgrade head` against a real
pgvector/pg18; `check-ac-state.py --run-tests --ratchet --mandate
4f8339aa6...` (10 counters on ceiling, mandate clean);
`mypy --strict packages/maistro-core/src` (0 issues);
`check-pyright-report.py` (21 = 21); `pytest formal/` 663 passed / 1 skipped;
`check-execution-lifecycles.py`; `check-model-egress.py`;
`pytest packages/maistro-core/tests/fitness` 7 passed; interrogate floors 38/
45/63/46 all pass.

Focused suites: core quota/capabilities/governed 464 passed; server
api/pm-poc 23 passed; hive engine/legacy-dag/adapter/retirement 52 passed;
`tests/migrations` 96 passed with `MAISTRO_TEST_DATABASE_URL` against pg18;
`tests/persistence/test_pg_quota.py` + `test_sqlite_quota.py` 28 passed with
`MAISTRO_TEST_PG_DSN`; `check-suite-inventory.py` green for core, server and
hive suites.
