# Round-5 repair notes for issue #881 (`auto-881`, head `acde03d7`)

## What the driver reported

One failing gate at the merge-queue evaluation of head
`acde03d7e1015d65dd7f9e1f25203ea5fb82f4a9`:

- `Gate C — canonical clean install` — failure, job 119297332637,
  `##[error]Process completed with exit code 1.`

and one previous block: "worker left uncommitted work; preserved for salvage
review".

## Salvage review

The worktree at `acde03d7` was clean except one untracked file,
`.env.bak.881` (a credentials backup left by an earlier round). It is
preserved untouched and is gitignored; nothing was discarded. The prior
attempt (`891a154f`, result.json in its job dir) died on a provider 429
before making any edit, so there was no code salvage to integrate.

## Gate C root cause — upstream image tag, not this branch

The full job log (fetched via the API, read-only) shows the failing step:

- `Install and start through the documented path` (`./install.sh
  --skip-wizard --no-cli --no-open`) started 15:00:56.74Z and died
  1.4 s later at `docker compose up`: `litellm Error manifest unknown`,
  siblings `postgres/langfuse/postgres-layout-check Interrupted`. The whole
  job lasted 18 s — readiness, migrations, and every later step never ran.

Three independent facts show the failure is not caused by this branch:

1. `git diff 9cc5d1aca...HEAD -- docker-compose.yml` is empty — the compose
   file (and its `ghcr.io/berriai/litellm:main-latest` pin, a floating tag
   LiteLLM republishes continuously) is byte-identical to the develop base.
   The branch's only changes are docs, `formal/models/
   test_execution_lifecycle_state.py`, the nightly workflow's Postgres
   provisioning, and repair notes — none reach a docker pull.
2. `gh run list --workflow=gate-c.yml` shows 15 consecutive **success** runs
   across other branches/PRs before and after the failure (17:26Z through
   21:27Z on 2026-10-21, including the base commit `7f8683be` twice) — the
   tag resolves again; the CI pull hit a transient manifest-publication
   window.
3. `docker manifest inspect ghcr.io/berriai/litellm:main-latest` succeeds
   from this machine now (exit 0).

## Gate C proven locally — every assertion passes at this head

Ran the gate's exact flow against a throwaway copy of HEAD (`git archive
HEAD` to `/tmp/gatec-881`; host ports shifted — engine 18000, conductor
18100, litellm 14000 — because the shared `fleet-deploy-tree` stack already
holds loopback 8000/8101/4000 and must not be disturbed; the compose file,
env, and assertions are otherwise verbatim):

- Clean-start state (`rm -f .env .maistro-install`, compose down): OK.
- `MAISTRO_SKIP_WIZARD=1 MAISTRO_INSTALL_CLI=0 MAISTRO_OPEN_BROWSER=0
  MAISTRO_AUTO_INSTALL_DEPS=0 MAISTRO_START_STACK=1 MAISTRO_BIND_HOST=127.0.0.1
  ./install.sh --skip-wizard --no-cli --no-open` → exit 0; the same
  `litellm` pull that failed in CI succeeded; engine healthy, conductor
  healthy (installer's own polls).
- Workflow assertions, verbatim: engine `/health/live` PASS, engine
  `/health/ready` PASS, conductor `/health/ready` PASS, `alembic_version`
  = `065` (matches `^[0-9a-z_]+$`), final fail-closed engine + conductor
  ready PASS. Temp stack torn down afterwards (`down -v`, 0 containers left).

No product change is needed for this gate; a re-run of the merge queue
against the unchanged head is the fix, now with local proof it passes.

## Deliverable re-verified at this head (not assumed from earlier claims)

- `formal/models/test_execution_lifecycle_state.py` (the only formal/ delta
  vs `9cc5d1aca`): `pytest formal/models/test_execution_lifecycle_state.py
  --hypothesis-seed=0` against the live pgvector:pg18 (`pg881-formal`,
  schema at head `065`) → **3 passed in 5.55s**.
- Suite has teeth: the note's M2 mutant (`check_completion_is_earned` early
  return in a PYTHONPATH-shadowed copy) is caught — the earned-completion
  witness FAILs with the mutant applied and passes without it.
- Canonical execution model respected: the machine drives the real
  `PgRunStore` with transitions imported from `maistro.runs.lifecycle`
  (`RUN_TRANSITIONS` / `ATTEMPT_TRANSITIONS`) — no parallel scheduler.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean.
- Vulture ledger (CI-repair instruction, exact CI arguments):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → candidate matches base
  (1321 reviewed identities = 1321 findings); no amendment needed.
- `tests/test_postgres_health_checks.py` → 10 passed (the inventory note's
  `tests/: +1` node from the nightly workflow's Postgres service is real).
- `uv run python scripts/check-suite-inventory.py` → ok, 21/21 suites match
  the recorded inventory.

## Residual risk

Gate C remains exposed to the unpinned `litellm:main-latest` floating tag
(pre-existing on develop; digest-pinning it is a stack-owning change out of
this research issue's scope).
