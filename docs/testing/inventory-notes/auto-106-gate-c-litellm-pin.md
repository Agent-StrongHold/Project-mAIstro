---
inventory-delta:
  tests/: +0
---
# Repair round @ b16b161e2 (branch auto-106) — Gate C "canonical clean install"

Assigned head `b16b161e2e8898d2b515f0dbd041bafa810eb5a7`, develop base
`9cc5d1aca141695d747b23bd06a12cce9d8f850d`. Job
`70ae5c3c812d4de4bad02cf1980ea85e` (phase `repair`). The worktree was clean
at the assigned head and the develop sync was already merged
(`b16b161e2` = merge of `bb5f165c2` with `9cc5d1aca`), so the round changed
exactly one production file: `docker-compose.yml`.

No test was added, removed, or edited, so no suite count moved: `tests/: +0`.

## Root cause of the Gate C failure (re-derived from the CI log, not assumed)

`gh api repos/Agent-StrongHold/Project-mAIstro/actions/jobs/119284002729`
(step 6, "Install and start through the documented path") failed; the job
log (`/tmp/gatec-119284002729.log`, fetched read-only with `gh api
.../actions/jobs/119284002729/logs`) shows the first error inside that step:

    litellm Error manifest unknown
    postgres  Interrupted
    langfuse  Interrupted
    Error response from daemon: manifest unknown

The failure is at **image pull time**, ~1s after `docker compose up` begins —
before any container starts and before any readiness assertion. The puller
was resolving `ghcr.io/berriai/litellm:main-latest`, the mutable tag that
`docker-compose.yml` line 164 carried at the assigned head. The tag itself
is gone upstream, not a runner blip:

- `docker manifest inspect ghcr.io/berriai/litellm:main-latest` →
  `manifest unknown` (reproduced locally in this round, hours after the CI
  failure).
- `docker manifest inspect ghcr.io/berriai/litellm@sha256:af8050ea45707c42a0572c5cceaa5cebaa89cee4c5cd0585cf879a529804b898`
  → resolves to a multi-arch OCI index (linux/amd64, linux/arm64 plus the
  attestation entries).

The branch's own Python changes are unrelated to this failure: the failing
pull happens before the engine image is built or started, and
`git diff 9cc5d1aca..HEAD --stat -- docker-compose.yml` was empty before
this repair.

## The repair

`docker-compose.yml` now pins the gateway proxy by digest:

    image: ghcr.io/berriai/litellm@sha256:af8050ea45707c42a0572c5cceaa5cebaa89cee4c5cd0585cf879a529804b898

This is the same digest the sibling lane for #972 landed in
`f7ff9efb6` ("fix(infra,#972): pin litellm by digest; restore Gate C
canonical clean install"); the two branches therefore carry an identical
change and merge without conflict. The digest is the multi-arch build this
stack has been running for the past 11 days
(`LITELLM_RELEASE_TAG=v1.106.0-dev.3`, image built 2026-09-16) — the tested
line, not a new version choice — and it satisfies the digest-pinning intent
already recorded in `docs/specs/SPEC-072726-3439-installer-e2e-flow.md`
(Open questions: "`main-latest` is unpinned today; Phase 5 should pin the
LiteLLM image digest too").

## Local Gate C re-run on this tree (commands and outcomes)

`DOCKER_HOST=unix:///var/run/docker.sock`, worktree `/home/dev/Git/wt/auto-106`,
project name `auto-106` (no other lane's stack touched):

- `rm -f .env && rm -rf .maistro-install && docker compose down -v --remove-orphans`
  → clean starting state (no `.env`, no `.maistro-install`).
- `MAISTRO_SKIP_WIZARD=1 MAISTRO_INSTALL_CLI=0 MAISTRO_OPEN_BROWSER=0
  MAISTRO_AUTO_INSTALL_DEPS=0 MAISTRO_START_STACK=1 MAISTRO_BIND_HOST=127.0.0.1
  MAISTRO_PORT=8000 ./install.sh --skip-wizard --no-cli --no-open`
  → **exit 0** ("Engine healthy.", "Conductor healthy."), litellm pulled by
  digest and started.
- Gate C readiness assertions, verbatim from `.github/workflows/gate-c.yml`:
  `wait_ready http://127.0.0.1:8000/health/live` → 0;
  `wait_ready http://127.0.0.1:8000/health/ready` → 0;
  `wait_ready http://127.0.0.1:8101/health/ready` → 0;
  `alembic_version` = `065`, and the fail-closed grep
  `grep -Eq '^[0-9a-z_]+$'` → 0.
- "Record candidate and shipped image digest" step: engine image id
  `sha256:53235b1df36e7d75443b434903ddc883a9982dd1628530bd2e10645b3ccda86f`
  (non-empty, as the step asserts).
- The pinned gateway serves: `GET http://127.0.0.1:4000/health/liveliness`
  → 200; unauthenticated `GET /v1/models` → 401 (canonical rejection).
- The engine container runs **this branch's** code, so the canonical install
  path exercises the M4-I production surface:
  `docker compose exec -T maestro-engine python -c "from maistro.graph.verification import ResultState"`
  → ok, and `grep -c PlanPostStateMismatch
  /app/venv/lib/python3.13/site-packages/maistro/graph/durable_runs/authoritative_fold.py`
  → 2.
- Teardown: `docker compose down -v --remove-orphans` → all containers and
  volumes removed; `.env`/`.maestro-install` deleted; `git status` shows only
  the intended `docker-compose.yml` modification.

## Gates re-run at this head (after the compose change)

- `uv run ruff check .` → "All checks passed!"
- `uv run ruff format --check .` → "3426 files already formatted"
- `uv run python scripts/check-image-pins.py` → 8 pinned base/tool images,
  all registered (exit 0)
- `uv run python scripts/check-image-inventory.py` → "OK: every Dockerfile is
  inventoried, and every shipped image names live jobs" (exit 0)
- `uv run python scripts/check-compose-resources.py`,
  `scripts/check-compose-secrets.py`, `scripts/check-deployment-claims.py`,
  `scripts/check-install-functions.py` → exit 0
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → "1321 reviewed
  identities -> 1321 findings", exit 0 (no ledger edit needed)
- Focused M4-I suites (the 13 files of the issue's surface) → **166 passed**.

## Acceptance re-verification (re-derived, not inherited)

- Planted post-state mismatch halts and is durably explained:
  `test_output_mismatch_halts_with_plan_mismatch` asserts
  `record.run.error.startswith("PlanPostStateMismatch:")` with the
  description of the contradicted plan, while the accepted attempt stays
  `completed`.
- No conflation / unbounded loops: `test_taxonomy.py` (failed result → no
  state; unknown override raises), `test_non_retryable_nodes_do_not_escalate`,
  `test_escalation_never_exceeds_visit_budget`,
  `test_exhausted_ladder_accepts_shortfall_without_looping` — all green.
- Adaptive vs fixed baseline: `scripts/bench_m4i_adaptive_vs_fixed.py
  --output /tmp/m4i-bench-repro-auto106.json` reproduces
  `docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json` **byte-identically**
  (adaptive 5/6 @ 0.550¢ / 2800ms vs fixed-vision 5/6 @ 0.725¢ / 3000ms,
  failure cases recorded per arm).
- Mutation sensitivity (exit evidence "removing verification or forcing an
  always-success result causes the focused behavioral tests to fail"): the
  two seams were neutered from a plugin outside the tree (repo untouched):
  `_plan_mismatch_error → None` → **5 failed, 12 passed** (the mismatch-halt
  tests fail; the run completes instead of halting);
  `_visit_quality → None` (always-good quality) → **8 failed, 19 passed**
  (escalation never happens).

## Residual risk

- The `codex-code-review` inline comments left on PR #2217 (P1 import-cycle
  note on `verification/taxonomy.py` ↔ `graph/nodes/base.py`, plus P1/P2
  notes on `authoritative_fold.py` / `llm_summarize.py` / `routing.py`) are
  review evidence that this repair round did not address: they are code
  semantics, not the named Gate C gate failure, and touching the node
  registry would move vulture ledger identities. The import order that the
  note describes currently resolves in this tree
  (`import maistro.graph.verification` and
  `import maistro.graph.verification.taxonomy` both succeed from a cold
  interpreter), but the cycle is latent and should be broken in a
  follow-up round that owns the ledger.
