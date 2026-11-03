---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 36 — develop tip `78133c093` merged; rootless conformance lane run live

Resolves the round-35 block: CI at `1e5e401241` was all `cancelled`
(runner shutdown), with the recurring root cause being develop drift —
develop had advanced one commit (`78133c093`, classifier decision
logging, #2335) past the branch's merge base `41deb105c`. Merged
`origin/develop` into `auto-80` as `9272b1ffa` with **zero conflicts**;
per the quality/JSON silent-loss rule, verified `git diff 41deb105c
1e5e40124 -- quality/vulture-baseline.json quality/reachability-baseline.json
quality/reachability-dispositions.json` is empty (branch never touched
them since the prior merge base), so the merge correctly takes develop's
row prunes and the merged files are byte-identical to `origin/develop`.

## Gate battery at merged head `9272b1ffa` (executed, exit codes checked)

- `uv run ruff check .` RC=0; `uv run ruff format --check .` RC=0 (3538 files)
- Container trio: 33 passed / 20 skipped against the rootful system daemon
  (29.1.3) — the 20 skips are the ADR-093 Decision 2 fail-closed posture,
  asserted live by `test_sandbox_refuses_a_rootful_unmapped_daemon` PASSED
- `packages/maistro-core/tests/classifier`: 93 passed (includes develop's
  new `test_engine_logging_connect.py`)
- `tests/test_unit_suite_execution_partition.py`: 6 passed
- `scripts/check-suite-inventory.py`: 21 suites match recorded inventory
- Vulture gate, CI-exact args (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): RC=0, 1253 reviewed identities = 1253 findings
- `check-radon-baseline` RC=0 (127=127); `check-reachability` /
  `check-reachability-dispositions` / `check-convergence-matrix` RC=0
  (1477 modules, 102 unreachable, 35 disposition groups)
- `check-ratchet-provenance` RC=0; `check-shipped-surface-truth` RC=0
- `check-image-inventory` + `check-image-pins` RC=0 (9 pins / 11 Dockerfiles)
- workflow-lint contract set RC=0: `check-required-checks`,
  `check-branch-protection`, `check-release-consistency`,
  `check-workflow-inventory`, `check-uv-setup`,
  `check-workflow-write-safety`, `check-install-functions`
- `node --test tests/ci/integration-scope.test.cjs`: 12 pass / 0 fail
- `check-doc-links` RC=0; `check-backlog-consistency` RC=0
- mypy (`maistro-core/src` + `maistro-bootstrap/src`): 852 files clean

## Positive conformance lane run live (previously CI-only evidence)

Reproduced the `sandbox-conformance` job locally against a real rootless
daemon (29.7.2, `SecurityOptions` includes `name=rootless`, leftover lane
from the round 19-32 provisioning; state-dir lock confirmed it is the
same daemon, so no second daemon was started):

1. `docker build --tag maistro-builders:latest --file
   packages/maistro-bootstrap/tests/Dockerfile.sandbox
   packages/maistro-bootstrap/tests` — built and loaded into the rootless daemon
2. cgroup v2 enforcement proof: `run --memory=64m` reads back
   `memory.max = 67108864` (enforced, not `max`)
3. `DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
   packages/maistro-bootstrap/tests`: **299 passed, 2 skipped** —
   the escape/conformance suite ran against real rootless containers.
   Skips are structural: the Windows-only escape proof, and the
   rootful-refusal test (no identity uid_map exists on a proven-rootless
   daemon) — the exact complement of the refusal that PASSED on the
   rootful daemon above.

No production or test code changed in this round; inventory delta is +0
across the board.
