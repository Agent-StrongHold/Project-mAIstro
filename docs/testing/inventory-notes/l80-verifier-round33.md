---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 33 — verifier: `test` gate failure root-caused (suite-inventory +1, resolved by the develop merge); conformance evidence re-executed

Branch `auto-80`, head `8b741eebfb60ab10b7fb4ecfb9b851681ccf2469` (unchanged;
evidence-only round), base `e12e11288e18893a531b687fe14c8babd83a5da8`
(develop tip), issue #80 / PR #1450, 2026-10-25. Driver checks (job
`a8cb3e92bb1847df9e863e980aeca5aa`) were green before this round: uv sync ok,
ruff check ok, ruff format ok, bootstrap sandbox pytest 33 passed / 20
skipped, bootstrap suite inventory ok.

## Named gate `test: failure` — root cause and local proof

Hosted run 40185225315 job 121144492342 (at `b63b62ec8b7a8d3b1dcfd37ec96a968367548ea6`)
failed exactly one step: `Suite inventory matches collected node IDs (C1/#286)`
with `DRIFT tests/: expected 5888, collected 5889`. The +1 node is this
branch's new `SERVICE_BACKED_JOBS` entry `(ci.yml, sandbox-conformance)` in
`tests/test_unit_suite_execution_partition.py`, whose baseline delta was not
yet recorded at that commit. The repeated `RuntimeError: Event loop is closed`
lines marked `##[error]` in the same log are
`PytestUnhandledThreadExceptionWarning` annotations from aiosqlite's worker
thread under `packages/maistro-server/tests/api/test_tasks_run_identity.py` —
a file this branch never touches; every step containing them completed
successfully, and the job's only failed step is the inventory one.

At the current head the develop merge carries the recorded delta: the exact CI
command `python scripts/check-suite-inventory.py` (no arguments) exits 0 with
`ok: 21 suite(s) match the recorded inventory`, including
`ok tests/: 5994`. Not weakened: `git diff e12e11288..HEAD --stat --
docs/testing/inventory/baseline.json` is empty at the counts level that
matters because the drift is absorbed by the merged baseline, and
`quality/` vs `origin/develop` is additive only
(`git diff --numstat origin/develop -- quality/`: 17+0, 9+0, 2+1 in
image-pins adding the `Dockerfile.sandbox` pin path — no ledger rows lost).

## Conformance evidence re-executed at this head

- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-bootstrap/tests/test_container_lane.py -v` = 33 passed,
  20 skipped. The skip split is by daemon posture: this host runs a rootful
  daemon, so `test_sandbox_refuses_a_rootful_unmapped_daemon` executed LIVE
  against it and passed — the ADR-093 Decision 2 fail-closed refusal is real
  kernel-side evidence, not a mock. The 19 rootless-branch escape tests plus
  the lane test skip by design here.
- The hosted `sandbox-conformance` lane (rootless daemon, full escape suite)
  is `success` at `b63b62ec8` (run 40185225315), and
  `git diff b63b62ec8..HEAD -- packages/maistro-bootstrap/
  scripts/ci-rootless-mountns.sh packages/maistro-bootstrap/tests/Dockerfile.sandbox`
  is empty — the lane validated that content byte-for-byte matches this head;
  the only ci.yml delta since is develop's hive-authority test step and an
  rsi-runner buildx cache-scope rotation, neither touching the lane.
- Canonical gates re-run at this head: `uv run ruff check .` pass;
  `uv run ruff format --check .` pass; the CI mypy argument set
  (10 src trees) = `Success: no issues found in 1106 source files`;
  `python scripts/check-merge-markers.py` ok;
  `uv run pytest tests/test_unit_suite_execution_partition.py` = 6 passed.

## Acceptance mapping (issue #80), all verified reachable

Filesystem/process/namespace/network/device/host-socket/credential/privilege
attack coverage in `test_container_sandbox.py` (19 live-branch tests) +
`test_container_sandbox_hardening.py` (32 config/fail-closed tests, all
passing locally); network/credential default-deny proven live on the hosted
rootless lane and by `--network=none`/proxy-env blanking config assertions;
seed allowlist+denylist keeps `.env*`, `.git`, ssh/gpg/cloud material out of
the tar seed (denylist in
`packages/maistro-bootstrap/src/maistro_bootstrap/builders/container_sandbox.py`);
non-root enforced via `--user 65532:65532` with the single auditable pre-seed
root chown and the uid-map boundary probe; writable scope pinned to
workspace + /tmp with read-only /dev/shm and /dev/mqueue stubs; timeout kill
(detached descendants), context cleanup, every-stage seed-failure cleanup and
memory exhaustion covered; the lane is a required check
(`.github/branch-protection.json`, `docs/ci/REQUIRED-CHECKS.md`) and
SECURITY.md §8 cites the evidence. The suite instantiates the production
`ContainerBuilderSandbox`, not a fixture.

PR body ("Refs #80") and every branch commit message were scanned: no
fixes/closes/resolves keywords; no closure action taken.
