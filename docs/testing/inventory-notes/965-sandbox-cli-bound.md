---
inventory-delta:
  packages/maistro-core/tests: +2
---
# #965 repair — bounded Docker sandbox lifecycle subprocesses

CI repair for issue #965's `coverage (no services)` gate (quality.yml
coverage-unit at 538676f7d): the evolve swebench evaluator test
`test_malformed_response_fails_via_sandboxed_syntax_error` died on the 30s
pytest-timeout with the event loop parked in `selector.poll` behind an
unbounded `docker run` — a cold-runner registry stall, not a code regression
(the same evolve content passed on develop 30 minutes earlier; locally with a
warm image the class passes in 2.35s).

Two production changes in `maistro/tools/sandbox/docker.py`:

- `create_sandbox` bounds the `docker run` subprocess wait with
  `asyncio.wait_for(_LIFECYCLE_CLI_TIMEOUT_SECONDS)` (120s) and raises
  `RuntimeError` on timeout — the same fail-closed shape callers already
  handle for a refused `docker run` (e.g. evolve's
  `benchmarks/sandbox_exec.run_function_checks`).
- `SandboxContainer.destroy` bounds `docker rm -f` the same way; on timeout it
  logs `sandbox_destroy_timeout` and returns without raising, because the
  async-context-manager exit path calls destroy and best-effort cleanup must
  not hang or fail the caller.

quality.yml's coverage-unit job gains a pre-pull step for
`python:3.12-slim` (3 attempts, #204 pattern) so the first sandbox-using test
no longer pays registry latency inside a 30s per-test budget.

**+2 `packages/maistro-core/tests`**, in `tests/tools/sandbox/test_docker.py`,
both at the file's established `asyncio.create_subprocess_exec` mock boundary:

- `test_create_sandbox_times_out_stalled_docker_run`: a never-returning
  `docker run` proc makes `create_sandbox` raise `RuntimeError` within the
  (patched, 0.01s) lifecycle bound, and the spawned argv is still
  `docker run ...`.
- `test_destroy_survives_a_stalled_docker_rm_without_raising`: a stalled
  `docker rm` proc is swallowed (no raise) within the patched bound.

Both fail against the pre-change module (no bound to patch → AttributeError
red; with the constant absent the underlying wait is unbounded and the same
harness trips the 30s per-test timeout), so they pin the regression they name.

Validation on this head: `uv run pytest
packages/maistro-core/tests/tools/sandbox/test_docker.py -q` 27 passed; evolve
real-Docker legs (`tests/benchmarks/test_swebench.py::TestRunSwebench`,
`test_sandbox_exec.py`) re-run green against the bounded create/destroy;
`uv run python scripts/check-suite-inventory.py --suite
packages/maistro-core/tests` green after this note; ruff check/format clean;
`quality.yml` parses (`yaml.safe_load`).
