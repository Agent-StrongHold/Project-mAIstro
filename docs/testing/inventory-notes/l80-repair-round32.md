---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
  packages/maistro-rsi/tests: 0
  packages/maistro-evolve/tests: 0
---

# Issue #80 round 32 — repair the red `test` merge-queue gate: seed `python:3.12-slim` into the lane daemon before the rsi/evolve suite

Branch `auto-80`, incoming head `3c5250edef288b9550a7a1f2f0fd6f7dc0d906e9`,
issue #80, 2026-09-29. One workflow change, zero test/production changes.

## Root cause (actual evidence, not guesswork)

Merge-queue run
[36508346054](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/36508346054/job/109214750939)
failed exactly one step of the `test` job:
`uv run pytest packages/maistro-rsi/tests packages/maistro-evolve/tests`,
with **2 failed, 1444 passed, 6 skipped**:

- `test_swebench.py::TestRunSwebench::test_correct_fix_scores_full_marks` —
  `assert 0.0 == 1.0`
- `test_swebench.py::TestRunSwebench::test_malformed_response_fails_via_sandboxed_syntax_error`
  — detail was `isolated sandbox unavailable: Failed to create sandbox:
  Unable to find image 'python:3.12-slim' locally ... lookup
  registry-1.docker.io on 127.0.0.53:53: ... connection refused`

Mechanism, verified from the hosted job log:

1. The proxy-SWE-bench evaluator
   (`packages/maistro-evolve/src/maistro_evolve/benchmarks/sandbox_exec.py`)
   runs untrusted candidate code in the real core Docker sandbox whose
   default image is `python:3.12-slim`
   (`packages/maistro-core/src/maistro/config/settings.py:180`).
2. Every step after "Start a rootless Docker daemon for the conformance
   lane" inherits `DOCKER_HOST=unix://.../docker-l80/docker.sock` via
   `GITHUB_ENV` (job log line 1361) — including the rsi/evolve pytest step.
3. That daemon lives inside a rootlesskit netns where the host DNS stub
   (`127.0.0.53`) is unreachable, so its first-time registry pull dies with
   `connection refused`.
4. The evaluator **fails closed** by design when the sandbox cannot start
   (correct security posture; not weakened here), so the missing image turns
   into red tests.

This also matches round-29's run 36440932829 — twice is systematic, not a
flake, so the repair removes the registry dependency instead of retrying it.

## Fix

`.github/workflows/ci.yml`: new step "Seed python:3.12-slim into the lane
daemon (swebench sandbox image)" immediately before the rsi/evolve pytest
step. It pulls the image on the runner's rootful system daemon (explicit
`--host unix:///var/run/docker.sock`, 3 bounded attempts, `timeout 240`,
already cached there by the `Dockerfile.sandbox` `FROM python:3.12-slim`
build earlier in the job) and transfers it with
`docker ... save | docker load` — the load side inherits `DOCKER_HOST`, i.e.
the lane daemon the pytest step uses. This is the exact transfer pattern the
existing "Load the Builder sandbox image into the rootless daemon" step
uses.

No production code changed: the evaluator's fail-closed behavior and the
sandbox contract are untouched. No test changed: all three affected
inventories are unchanged (delta 0 above).

## Executed validation (this worktree, this round)

- **Named failing step argv, re-run in the hosted failing posture**
  (`DOCKER_HOST=unix:///run/user/1000/docker.sock` = rootless lane daemon,
  `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 PYTHONPATH=...`):
  **1446 passed, 6 skipped in 52.20s** (hosted: 2 failed).
- Seed mechanism proven locally on a lane daemon that did not have the
  image: `docker --host unix:///var/run/docker.sock pull python:3.12-slim`
  then `save | docker load` into `unix:///run/user/1000/docker.sock` →
  `python:3.12-slim` listed in the lane daemon's images.
- `packages/maistro-evolve/tests/benchmarks/test_swebench.py` against the
  lane daemon post-seed: **15 passed in 3.74s**.
- Exact driver gate argv (bootstrap trio + 13 rsi files, `-q -x`):
  **199 passed, 19 skipped in 30.27s**.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 2619 files
  already formatted.
- Vulture per-identity ledger (CI-repair instruction):
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → rc 0,
  **1402 reviewed identities → 1402 findings**, zero unbanked; no ledger
  amendment (no `src` change in this round).
- `scripts/check-suite-inventory.py` for `maistro-bootstrap/tests` (275),
  `maistro-rsi/tests` (801), `maistro-evolve/tests` (651) → all `ok`.
- `scripts/check-required-checks.py` → ok (33 PR checks);
  `scripts/check-workflow-write-safety.py` → ok (23 workflows).
- `ci.yml` parses (`yaml.safe_load`); the seed step sits at test-job step
  index 18, directly before its consumer at 19.

## Hosted acceptance evidence for #80 from the same run

Run 36508346054's `test` job — the job whose only red was the swebench pull
— executed this issue's own conformance lane green:

- Rootful ADR-093 Decision-2 refusal:
  `test_sandbox_refuses_a_rootful_unmapped_daemon` **1 passed in 1.33s**.
- Rootless-daemon escape suite: **18 passed, 1 skipped in 56.68s**
  (network/credential default-deny, seed exclusion of `.env`/`.git`, uid
  map, read-only mounts, timeout/cleanup, exhaustion).
- Memory-limit enforcement probe on the lane daemon: `memory.max` =
  **67108864** under a 64m limit.
- Full bootstrap suite: **272 passed, 3 skipped in 74.61s**.

## Residual risk

The seed step pulls on the rootful daemon; a cold runner with a registry
outage longer than 3 bounded attempts would still fail the step — explicitly,
with its cause in the step name, rather than as two opaque swebench
failures. The evaluator remains fail-closed; nothing about the sandbox
contract changed.
