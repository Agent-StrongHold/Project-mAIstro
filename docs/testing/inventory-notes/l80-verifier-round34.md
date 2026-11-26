---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 34 — verifier: named `test` gate failure re-proven resolved at the merged head; conformance and drift evidence re-executed

Branch `auto-80`, head `6d6d4c5eafe4133beb0336a1d2b3fac782fae940` (unchanged;
evidence-only round, no production file touched), base
`e12e11288e18893a531b687fe14c8babd83a5da8` (develop tip, fully merged by
`8b741eebf`), issue #80 / PR #1450, 2026-10-25. Driver checks (job
`65d4a61261904ba8948690919cafcf36`) were green at this head: uv sync ok,
`ruff check .` ok, `ruff format --check .` ok (3516 files), bootstrap sandbox
pytest 33 passed / 20 skipped, bootstrap suite inventory ok.

## Named gate `test: failure` — resolution re-proven with CI's exact commands

The last merge-queue evaluation (`b63b62ec8`, run 40185225315, job
121144492342) failed the `Suite inventory matches collected node IDs`
step with `DRIFT tests/: expected 5888, collected 5889`. At the current head
the drift is gone by direct execution, not by argument:

- `python scripts/check-suite-inventory.py` (CI's exact argument set — no
  arguments) exits 0: `ok: 21 suite(s) match the recorded inventory`,
  including `ok tests/: 5994` and `ok packages/maistro-bootstrap/tests: 301`.
- `python scripts/check-test-duplicates.py` exits 0 (`no byte-identical test
  files`).
- The branch's only root-suite file vs develop is
  `tests/test_unit_suite_execution_partition.py` (+6 lines: one
  `SERVICE_BACKED_JOBS` frozenset entry plus comment; the file's six tests are
  un-parametrized), and `uv run pytest
  tests/test_unit_suite_execution_partition.py` = 6 passed. Collection of
  `tests/` at this head equals develop's recorded count exactly (5994), so the
  branch contributes zero collected nodes over the base.
- The repeated `RuntimeError: Event loop is closed` lines marked `##[error]`
  in the hosted log are warning annotations from aiosqlite's worker thread
  under `packages/maistro-server/tests/api/test_tasks_run_identity.py` — a
  file this branch never touches (absent from
  `git diff e12e11288..HEAD --stat`). Re-executed:
  `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-server/tests/api/test_tasks_run_identity.py -q` = 7 passed,
  1 warning, exit 0. Warnings do not fail steps; the job's only failed step
  was the inventory one, which now passes.
- Because the merge base equals develop tip, the merge queue's virtual merge
  of this branch is this tree. `origin/develop` has since advanced one commit
  (`37b649f36`, M3-B3 Canvas worker);
  `git merge-tree --write-tree HEAD origin/develop` exits 0 with no
  conflicting paths, and since the branch adds zero test nodes over the base,
  the virtual merge inherits develop tip's own consistent inventory.

`quality/` vs base is additive only (`git diff --numstat e12e11288 -- quality/`:
ac-state-notes/auto-80.json 17+/0-, image-inventory.json 9+/0-,
image-pins.json 2+/1- adding the `Dockerfile.sandbox` pin path; no
reachability/vulture/promotion rows touched). The larger numstat against the
newer `origin/develop` (`direct-dependency-exceptions` 7+/0-,
`reachability-dispositions` 3+/3-) is produced entirely by develop's own
`37b649f36`, which this branch does not carry.

## Conformance evidence re-executed at this head

- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-bootstrap/tests/test_container_lane.py -v --tb=short` =
  33 passed, 20 skipped. Skip split is by daemon posture: this host runs a
  rootful daemon, so `test_sandbox_refuses_a_rootful_unmapped_daemon`
  executed LIVE against it and passed — ADR-093 Decision 2 fail-closed
  refusal is real kernel-side evidence, not a mock. The 19 rootless-branch
  escape tests plus the lane test skip by design here.
- The hosted `sandbox-conformance` lane is `success` at `b63b62ec8`
  (run 40185225315), and
  `git diff b63b62ec8..HEAD --stat -- packages/maistro-bootstrap/
  scripts/ci-rootless-mountns.sh` is empty: the lane validated content that is
  byte-identical at this head. The only b63→HEAD deltas in CI config are
  develop's own (hive workspace-authority test step, the mutation-gate doc
  row in `.github/branch-protection.json`, rsi-runner buildx cache-scope
  rotation) — none touch the lane.
- Lane wiring verified in-tree: `sandbox-conformance` job at
  `.github/workflows/ci.yml:741` (rootful-refusal proof step, rootless daemon
  provisioning, delegated-cgroup memory proof), required check at
  `.github/branch-protection.json:52,118`, documented at
  `docs/ci/REQUIRED-CHECKS.md:114` ("every PR"), cited in SECURITY.md
  Known-Limitations item 8 (lines 374–379).
- The suites instantiate the production `ContainerBuilderSandbox` directly
  (`test_container_sandbox.py:45,128,151,170`), not a fixture or selector
  stub.
- Canonical gates re-run: `uv run ruff check .` = All checks passed!;
  mypy: CI's quality-mypy gate is `uv run mypy --strict
  packages/maistro-core/src` (untouched by this branch); `--strict` over the
  bootstrap tree reports only pre-existing findings — the
  `no-any-return` at `container_sandbox.py:803` is the identical `decode()`
  return develop already carries (line 382 at `e12e11288`), and the
  `import-untyped` rows are in unmodified files (`credentials.py`,
  `wizard.py`). Tooling note: naming `scripts/ci-rootless-mountns.sh` as an
  explicit ruff argument feeds the shell script to ruff as Python (29 syntax
  errors); CI's argument set (`ruff check .`) is unaffected and passes.

## Acceptance mapping (issue #80), unchanged and reachable

Filesystem/path-escape/namespace/network/device/host-socket/credential/
privilege attack coverage in `test_container_sandbox.py` (19 live-branch
tests) + `test_container_sandbox_hardening.py` (32 config/fail-closed tests,
all passing locally); network/credential default-deny proven live on the
hosted rootless lane and by `--network=none`/proxy-env blanking config
assertions; seed allowlist+denylist keeps `.env*`, `.git`, ssh/gpg/cloud
material out of the tar seed; non-root enforced via `--user 65532:65532` with
the single auditable pre-seed root chown and the uid-map boundary probe;
writable scope pinned to workspace + /tmp with read-only /dev/shm and
/dev/mqueue stubs; timeout kill (detached descendants), context cleanup,
every-stage seed-failure cleanup and memory exhaustion covered; the lane is a
required check and SECURITY.md item 8 cites the evidence.

No test files were added or modified this round (inventory-delta: 0). No
fixes/closes/resolves keywords in this note; no closure action taken.
