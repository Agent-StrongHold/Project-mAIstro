# M2 #448 deep review — head d024496d1 (all prior claims re-proven first-party)

Lane L448, job 2aabacfeb4f7490da6fb7bf8e304127e. This round is the
NEEDS-DEEP-REVIEW the prior implement round (77eb35dd) requested: every claim
in `.cursor/context/m2-448-1197-capture-7667b13a.md` was re-checked against
the tree and re-executed; nothing was taken on trust. No repair was needed —
the salvage commit d024496d1 is sound as written.

## Re-executed evidence (this worktree, this head)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 2887 files formatted.
- `uv run mypy packages/maistro-core/src packages/maistro-bootstrap/src` — 721 files, no issues.
- `uv run pytest packages/maistro-core/tests/sandbox packages/maistro-core/tests/tools/sandbox
  packages/maistro-core/tests/tools/test_microvm_sandbox.py packages/maistro-core/tests/config
  packages/maistro-bootstrap/tests -q` — 574 passed, 42 skipped (real-backend tiers absent on host).
- `PYTHONPATH=packages/maistro-rsi/src:packages/maistro-evolve/src uv run pytest
  packages/maistro-rsi/tests -q` — 975 passed.
- Gates, all green: `check-suite-inventory.py` (14 suites match), `check-promotion-surface.py`,
  `check-cross-package-imports.py`, `check-shell-execution.py`, `check-test-duplicates.py`,
  `check-dependency-namespaces.py`.
- Entry-order matrix re-run manually: all five entry points
  (`maistro.capabilities`/`maistro.runs`/`maistro.sandbox`/`maistro.tools.sandbox.microvm`/
  `maistro.tools.sandbox.docker`) import the sandbox protocol, `_capture`, and `maistro.runs.store`
  cleanly in fresh interpreters.

## Code-level verification of #1197's contract (read, not assumed)

- `_capture.py` retains ≤ limit bytes/stream, drains-and-discards beyond it (no full-pipe wedge),
  concurrent per-stream drains in both asyncio and threads flavors; ceiling clamp is pure.
- Reachable production paths all bounded: `SandboxContainer.exec` (merged stream),
  `MicroVMSandbox.exec` (byte-cut + notice at the launcher seam; launchers must honor the
  config per `MicroVMRunSpec`), `ContainerBuilderSandbox._exec` (`run_bounded`),
  RSI `LocalSandbox.exec` (`communicate_bounded` + process-group kill on timeout),
  bubblewrap and fake backends (structured `ExecResult.*_bytes/*_truncated` + audit log).
- `ExecResult` exposes retained byte counts and truncation truth; `SandboxSettings.max_output_bytes`
  pinned to the protocol default; env can lower, never raise past the ceiling.
- Test power confirmed structurally: real 16 MiB simultaneous emitters (a sequential drain would
  deadlock, and the test bounds elapsed), deterministic 30s sleeper for the kill path, retention
  asserted by exact equality (unbounded capture would return more than `limit` and fail).

## Documented, accepted exceptions (residual, not lane failures)

- `docker.py` `destroy()`/`create_sandbox()` lifecycle `communicate()` calls stay unbounded:
  host-controlled argv, workload not yet running (or already being torn down); image ref is
  trusted deployment config.
- `ContainerBuilderSandbox.sync_to_host()` buffers the container-side tar in host memory:
  workload-influenced *volume*, but it is a data-transfer channel (truncating corrupts the
  archive), not command stdout/stderr capture; disk-quota control belongs to #1198-class work.
- No production VMM launcher exists in-tree; the launcher seam is injected (#76 epic territory).

## Still open on #448 (unchanged, explicitly out of this lane)

- Gate B / reopened #76: `sandbox/wiring.py` registers only bubblewrap+fake; docker/microvm/
  server/bootstrap paths bypass the selector/policy authority — architecture epic.
- #1198 (mounts/TOCTOU), #1201/#1202/#1204, enterprise-closeout lane.
- #1197's "#80 conformance" acceptance item is Gate-B-scoped; #1197 itself stays open upstream
  (no issue mutations from this lane).
- Branch is 212 commits behind origin/develop; a develop sync will be needed at integration
  (not performed: the prior block was NEEDS-DEEP-REVIEW, not a sync conflict).
