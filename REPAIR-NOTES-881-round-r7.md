# Round-7 repair notes for issue #881 (`auto-881`, head `53b5e198c`)

Round-7 was a verify/repair pass at the exact head the previous round synced
to: `53b5e198c6f42c859f65d229734dcea03002d207` (the merge of develop's
`9ef97945e` into the round-6 head `f9dda5b88`). The worktree was clean at
start and stays clean apart from this note.

## Prior block: supervisor-side, not a repo defect

The previous attempt was blocked with "recovery budget exhausted:
launch/preflight: `Supervisor._zai_window_left_fraction() missing 1 required
positional argument: 'now'`". That symbol appears **nowhere in the
repository** — `grep -rln _zai_window_left_fraction` over the worktree (and
over the campaign tooling tree) matches only job prompt texts. It is a crash
in the campaign supervisor's own launch/preflight path, i.e. infrastructure,
and the recovery budget it exhausted was the supervisor's relaunch budget. No
repository change can or should address it; this round's job launched
normally, which is the resolution. The merge-queue evaluation that mattered
was **green** at this head ("CI GATE FAILURES …: green").

## CI at this exact head — all required checks executed and succeeded

Dispatch-captured check-runs for `53b5e198c` show every required gate
`success`, including the previously failing ones:

- `Gate C — canonical clean install` — **success** (the `acde03d7` failure was
  the upstream `litellm:main-latest` manifest window, root-caused in round 6;
  the re-run at this head passed).
- `exact-debt-ledger` — success.
- `formal-conformance` — success (this module's PR-budget home).
- `Quality / Hypothesis`, `Quality / Execution lifecycles`, `Quality /
  Vulture`, `Quality / Ruff`, `Quality / Mypy strict` — success.
- `gates-ran` status — `All required checks executed on this exact head`.

## Independent revalidation at this head (executed this round, not assumed)

The merge that produced `53b5e198c` touched none of the tested surfaces:
`git diff f9dda5b88..53b5e198c -- packages/maistro-core/src/maistro/runs
formal/ tests/test_postgres_health_checks.py
.github/workflows/formal-conformance.yml` is empty. Revalidated anyway:

- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3435 files already formatted.
- Fresh `alembic upgrade head` against pgvector:pg18
  (`pg881-formal`, 127.0.0.1:5570) → clean.
- `MAISTRO_TEST_PG_DSN=…5570/maistro_test uv run pytest
  formal/models/test_execution_lifecycle_state.py --hypothesis-seed=0` →
  **3 passed in 4.67s**; `--hypothesis-seed=3` → **3 passed in 13.07s**.
- I29's lease/fence model (the nightly's other Pg-backed model):
  `formal/models/test_run_lease_fence.py --hypothesis-seed=0` → **1 passed in
  9.10s**.
- `uv run pytest tests/test_postgres_health_checks.py` → **10 passed**
  (the inventory note's `tests/: +1`).
- `uv run python scripts/check-suite-inventory.py` → ok, **21/21** suites.
  `formal/models --collect-only` collects **670** nodes once
  `maistro-evolve` is installed in the venv (CI's formal job installs it;
  without it the two `rsi_*` modules error at import locally — environment
  only, not a tree defect). Both counts match the recorded inventory note.
- `uv run python scripts/check-formal-oracle-independence.py --base
  9ef97945e` (the develop merge-base CI resolves) → **OK**.
- Vulture, CI's exact arguments (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) → candidate matches base at this head:
  **1320 reviewed identities = 1320 findings** (the count moved from 1321
  with the merged M4-I epic, which removed whitelist identities on *both*
  sides of the comparison). No ledger amendment needed or made.
- **Teeth re-demonstrated (M2):** with a one-line early-return mutation of
  `check_completion_is_earned` in a `PYTHONPATH`-shadowed copy of
  `packages/maistro-core/src` (worktree untouched), the run fails exactly as
  the battery table claims —
  `FAILED …::test_completion_of_the_run_is_earned_by_its_latest_node_run`
  (`DID NOT RAISE InvalidLifecycleTransition`); unmutated run passes. Shadow
  copy deleted afterwards.

## Inventory notes

No delta changed: `formal/: +3` and `tests/: +1` remain exact at this head
(670 collected in `formal/`, 10 nodes in
`tests/test_postgres_health_checks.py`). No note amendment required beyond
this file.

## Residual risk

- `origin/develop` has advanced two commits past the merge base
  (`156be3ad4`, `c29e0ea7`). No develop-sync conflict was reported by the
  merge queue — its last evaluation at this head was green — so no sync was
  performed here; if the queue demands one, it is a follow-up round, and the
  tested surfaces show no known overlap with those commits.
- Gate C remains exposed to the unpinned `litellm:main-latest` floating tag
  (pre-existing on develop; documented in round 6, out of scope for this
  research issue).
- Disposition unchanged: **INCUBATE** with the three WATCH follow-ups in
  `docs/research/881-execution-lifecycle-state-machines.md`.
