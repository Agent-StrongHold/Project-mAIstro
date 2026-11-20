---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---
# CR1450 develop-sync M2-B1 reconciliation

Suite inventory delta: this round adds exactly one bootstrap test node — the
pre-existing branch-only `packages/maistro-bootstrap/tests/test_container_lane.py`
(opt-in rootless provisioning regression) — on top of develop tip. Verified
locally in the identical environment: origin/develop collects 277 bootstrap
nodes here (dev+bootstrap extras, WSL), this branch collects 278, and the
per-file diff is exactly `+1 test_container_lane.py` with every other file
collecting identically. The baseline's 317 is CI's ubuntu-runner collection;
the same 39-node environment gap reproduces on a detached worktree of
origin/develop itself (277 vs 317), so it is not a regression of this merge.

Branch auto-80 (PR #1450, M2-B5 real sandbox conformance and escape tests)
merged origin/develop twice this round: 157c3f61 (M1-E2) and f927334a (M2-B1,
"Ship a real supported unattended-isolation backend", #2241). No test counts
changed in this reconciliation; the deltas are conflict resolutions and the
re-pointing of branch-only CI/documentation onto the merged architecture.

## Conflict resolutions

- `quality/image-pins.json`, `Dockerfile`, `Dockerfile.research`,
  `tests/test_distribution_contract.py` (M1-E2 merge): develop's docker/cli
  v29.9.3 tag bump and 3.13.18/3.12.16 base-pin refresh notes kept; the
  branch's vendored `klauspost/compress@v1.20.2` patch and #1450 note
  sentences appended; `packages/maistro-bootstrap/tests/Dockerfile.sandbox`
  restored to the 3.12-slim row's `used_by`. The prior attempt's half-applied
  resolution had left duplicate JSON keys, a lost `tag` field, a swallowed
  `3.12.12-slim-bookworm` row, and stray blank lines inside RUN
  continuations; all repaired and re-validated with
  `scripts/check-image-pins.py` (RC=0) and
  `uv run pytest tests/test_distribution_contract.py` (6 passed).
- `builders/container_sandbox.py` + its two test files (M2-B1 merge):
  develop wins — the adapter now delegates to the canonical
  `maistro.sandbox` selector and refuses with `NoSuitableBackendError`
  without a vm-tier backend. The branch's Docker-internals escape suite
  targeted the implementation develop deleted; the superseded side is
  preserved outside the worktree (`/home/dev/Git/wt/cr-1450-ours-backup/`).
  Conformance/escape coverage now lives in
  `packages/maistro-core/tests/sandbox/` (escape conformance, Kata live
  conformance, launcher VM, single authority) plus develop's adapter tests.

## Reconciliation edits (no production-code changes)

- `.github/workflows/ci.yml` `sandbox-conformance`: the deleted
  `test_sandbox_refuses_a_rootful_unmapped_daemon` node is replaced by a
  fail-closed selector proof (the production adapter must raise
  `NoSuitableBackendError` on a runner with no vm-tier backend); the final
  whole-bootstrap-suite run under `DOCKER_HOST` — a duplicate of
  coverage-unit after the merge, since no bootstrap test consumes Docker —
  is replaced by the maistro-builders image-contract probe (non-root uid
  65532, `--network=none`) on the rootless lane. The rootless provisioning
  steps and `test_container_lane.py` are unchanged.
- `tests/test_unit_suite_execution_partition.py`: the
  `(ci.yml, sandbox-conformance)` `SERVICE_BACKED_JOBS` entry is removed
  with the whole-suite run it justified (±0; the allowlist is data, not
  tests).
- `docs/security/SANDBOX-SUPPORT-MATRIX.md`: the builder section now
  describes the canonical-selector adapter and points at the canonical
  suites; the superseded Docker-backend evidence is kept as a historical
  note.

## Validation at this head

- `uv run pytest packages/maistro-bootstrap/tests -x -q`: 276 passed,
  2 skipped (post-merge, pre-reconciliation edits); re-run after the edits
  together with tests/test_distribution_contract.py: 282 passed, 2 skipped.
- `uv run pytest tests/test_distribution_contract.py -q`: 6 passed.
- `uv run pytest tests/test_unit_suite_execution_partition.py -q`: 6 passed
  (after removing the `(ci.yml, sandbox-conformance)` allowlist entry and the
  whole-suite run it justified; the docker build context was re-spelled with
  a trailing slash so the suite-path scanner reads it as a continuation, not
  a whole-suite site).
- Fail-closed selector proof executed locally: with no evidenced backend the
  adapter raises `NoSuitableBackendError`; on this WSL host Kata+KVM are
  genuinely evidenced, so the production path legitimately selects a vm-tier
  backend (same detection that develop's Kata live lane relies on).
