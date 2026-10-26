---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 35 — verifier: develop tip `f52b8522b` merged conflict-free; every gate re-executed at the merged head; refusal branch re-proven live

Branch `auto-80`, start head `af2690300216c8897da3868c461994548f569168`,
merged develop tip `f52b8522be605d4a81e5a605b7b286496016aa1d` (GitHub
`mergeable_state: behind`, no conflict; `git merge-tree --write-tree` exited 0
before the merge). Resulting head: the merge commit of this round, committed
locally only. Issue #80 / PR #1450, 2026-10-26.

## Develop sync

- `git merge origin/develop --no-edit` — clean, zero conflicts
  (merge commit `b3e500f5f` at validation time).
- Per the quality-gates rule ("quality/*.json merge cleanly while losing
  rows"), diffed ledgers against `origin/develop` after the merge:
  `git diff --numstat origin/develop -- quality/` shows additions only
  (`ac-state-notes/auto-80.json` +17, `image-inventory.json` +9,
  `image-pins.json` +2/−1 — the PR's own registered rows). No
  vulture/radon/promotion rows lost.

## Gates re-executed at the merged head (this round's own runs)

- `uv sync --locked --extra dev` ok; `uv run ruff check .` — All checks
  passed; `uv run ruff format --check .` — 3536 files already formatted.
- Container trio
  (`test_container_lane.py` + `test_container_sandbox.py` +
  `test_container_sandbox_hardening.py`): **33 passed / 20 skipped**,
  reproduced 4× sequentially.
- Refusal branch live: the lane image was absent locally at round start, so
  the whole sandbox module skipped (tri-state fails safe, by design). Built
  it exactly as the CI lane does (`docker build --tag maistro-builders:latest
  --file packages/maistro-bootstrap/tests/Dockerfile.sandbox
  packages/maistro-bootstrap/tests`), after which the posture probe
  positively observed the identity map `0 0 4294967295` and
  `test_sandbox_refuses_a_rootful_unmapped_daemon` **PASSED live** against
  the rootful daemon, with **0 leftover** `maistro-builders` containers
  (cleanup assertion exercised, not vacuous).
- Full bootstrap suite: **280 passed / 21 skipped = 301**, matching the
  recorded inventory exactly.
- `uv run python scripts/check-suite-inventory.py` (CI's exact no-argument
  form): ok, 21/21 suites match, including `tests/: 6038` and
  `packages/maistro-bootstrap/tests: 301`.
- `uv run python scripts/check-image-inventory.py` — OK (10 Dockerfiles,
  all dispositioned); `uv run python scripts/check-image-pins.py` — OK
  (9 pinned base/tool images, all registered).
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  f52b8522be605d4a81e5a605b7b286496016aa1d` — 0 criteria added/unproven,
  0 chain violations.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) —
  exit 0, 1256 reviewed identities matched, no ledger amendment needed.
- `uv run pytest tests/test_unit_suite_execution_partition.py` — 6 passed.

## Findings investigated this round

1. **`check-workflow-inventory.py` reports 1 finding** (devskim declared
   triggers vs actual `on:` keys). Triage: both gate inputs
   (`quality/workflow-inventory.json`, `.github/workflows/devskim.yml`) are
   byte-identical to `origin/develop` (`git diff HEAD origin/develop --`
   empty for both), so the finding pre-exists on develop and is not
   introduced by this branch. It is also absent from the driver's named CI
   gate failures (reported green).
2. **Concurrent pytest runs can false-fail the refusal test's
   leftover-container assertion.** Reproduced deliberately: two simultaneous
   `test_sandbox_refuses_a_rootful_unmapped_daemon` processes against one
   daemon — one run's refused container lands between the other's
   before/after `docker ps` snapshots, producing a spurious "refused entry
   left a sandbox container behind". This is cross-process interference on a
   shared daemon, not reachable CI behavior: the sandbox-conformance lane
   runs the suite once, serially, in a single job. Recorded so future lanes
   do not issue parallel pytest invocations when gathering evidence here.

## Conclusion

All M2-B5 acceptance evidence re-proven at the merged head: real production
`ContainerBuilderSandbox` conformance and escape suite, fail-closed
rootful-daemon refusal proven live, rootless provisioned-daemon lane in CI
with the cgroup v2 `memory.max == 67108864` enforcement proof, suite
inventory exact (301), all quality gates green. No production or test file
changed in this round (inventory delta 0).
