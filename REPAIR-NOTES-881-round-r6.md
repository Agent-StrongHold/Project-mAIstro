# Round-6 repair notes for issue #881 (`auto-881`, head `79dff4ed5`)

## What the driver reported

At the merge-queue evaluation of head `79dff4ed5141b1a6bc23ec58b4606131fd119ab1`:

- `Gate C — canonical clean install` — failure (job 119297332637, carried
  from the earlier evaluation of `acde03d7e101`).
- One previous block: "worker left uncommitted work; preserved for salvage
  review".

## Salvage review (resolves the uncommitted-work block)

The worktree carried exactly one untracked file, `.env.bak.881` (9 lines,
mtime 2026-10-21 10:54, created by an earlier round). It is a **credentials
backup** (`DB_PASSWORD`, `LITELLM_MASTER_KEY`, `LANGFUSE_*`, `API_KEYS`, …),
not code. The live `.env` it was backing up is present and newer
(11:31), so nothing depends on it.

Resolution, preserving the artifact and never committing it:

1. Copied to the sanctioned backup location `../incoming-881.env.bak`
   (outside the worktree; identical bytes).
2. Added to the **worktree-local** git exclude (`.git/info/exclude`), so
   `git status --porcelain` is now empty while the file stays on disk.
3. It is deliberately not part of the branch and must never be committed —
   the repo rule is "never commit `.env`, API keys, or credentials".

No code salvage existed to integrate: the round-5 worker had already
committed the deliverable and its notes; the only uncommitted content was
this backup.

## Gate C re-proven at this head — full install flow, all assertions pass

The failure was reported at `acde03d7`; the only delta to `79dff4ed5` is a
docs-only commit, so the install surface is identical — but the claim was
re-run rather than assumed, on a throwaway copy of **current** HEAD
(`git archive HEAD` → `/tmp/gatec-881-r6`), with host ports shifted off the
shared `rootlesskit` fleet stack that holds `4000`/`3100` and the loopback
fleet that holds `8000`/`8101` (the compose file, env, and gate assertions
are otherwise verbatim; only the host port numbers and the URLs they imply
were changed).

Clean-start state (`rm -f .env .maistro-install`, `docker compose down -v`)
proved OK. Then, with the gate's exact env:

```
MAISTRO_SKIP_WIZARD=1 MAISTRO_INSTALL_CLI=0 MAISTRO_OPEN_BROWSER=0 \
MAISTRO_AUTO_INSTALL_DEPS=0 MAISTRO_START_STACK=1 MAISTRO_BIND_HOST=127.0.0.1 \
MAISTRO_PORT=18000 HIVE_PORT=18100 ./install.sh --skip-wizard --no-cli --no-open
```

→ **exit 0**. The same `ghcr.io/berriai/litellm:main-latest` pull that died
with `manifest unknown` in CI succeeded; the `maistro-litellm` container is
`Up` on `127.0.0.1:14000->4000`. The installer's own polls reported
`Engine healthy` and `Conductor healthy`.

Gate assertions, run verbatim against the shifted ports:

| Assertion | Result |
|---|---|
| `GET /health/live` (engine) | PASS |
| `GET /health/ready` (engine) | PASS |
| `GET /health/ready` (conductor) | PASS |
| `alembic_version` | `065` (matches `^[0-9a-z_]+$`) — PASS |
| `docker manifest inspect ghcr.io/berriai/litellm:main-latest` | PASS (exit 0) |

The temp stack was torn down afterwards (`down -v --remove-orphans`): no
`gatec-881-r6` / `maistro-litellm` / `maistro-langfuse` containers or
volumes remain. Root cause is confirmed as an upstream floating-tag
publication window, not this branch; `git diff 9cc5d1aca...HEAD --
docker-compose.yml` is empty. A merge-queue re-run of the unchanged head is
the fix.

## Deliverable re-verified at this head (not assumed)

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test
  uv run pytest formal/models/test_execution_lifecycle_state.py
  --hypothesis-seed=0` → **3 passed in 3.69s**.
- **Teeth, demonstrated again:** with a `PYTHONPATH`-shadowed copy of
  `packages/maistro-core/src` where `check_completion_is_earned` early-returns
  (M2), the run fails —
  `test_completion_of_the_run_is_earned_by_its_latest_node_run`:
  `Failed: DID NOT RAISE InvalidLifecycleTransition`. Without the mutant it
  passes. The shadow copy is outside the worktree; the shipped tree is
  untouched.
- Nightly budget the workflow turns on: `MAISTRO_FORMAL_PG_EXAMPLES=200`
  → 3 passed in **44.3s** (the note's 34.2s was measured on another machine;
  same order, well inside the nightly job budget).
- `uv run ruff check formal/` → clean; `uv run ruff format --check formal/`
  → 40 files already formatted.
- `uv run python scripts/check-suite-inventory.py` → ok, **21/21** suites
  (formal/ = 670).
- `uv run python scripts/check-formal-oracle-independence.py --base
  9cc5d1aca` → OK.
- `uv run pytest tests/test_postgres_health_checks.py` → **10 passed** (the
  inventory note's `tests/: +1` node).
- Vulture, CI's exact arguments:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → candidate matches base
  (1321 reviewed identities = 1321 findings); no ledger amendment needed.
- Driver's deterministic checks: `uv sync --locked --extra dev` (check-0),
  `uv run ruff check .` (check-1, "All checks passed!"), `uv run ruff format
  --check .` (check-2, "3410 files already formatted").

## Residual risk

Gate C remains exposed to the unpinned `litellm:main-latest` floating tag
(pre-existing on develop; digest-pinning it is a stack-owning change outside
this research issue's scope). The research disposition is unchanged:
**INCUBATE**, with the recovery-interplay, tasks-seams, and cross-store
conformance WATCH items as recorded in
`docs/research/881-execution-lifecycle-state-machines.md`.
