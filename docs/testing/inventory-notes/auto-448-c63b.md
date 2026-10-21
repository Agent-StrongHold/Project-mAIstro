---
inventory-delta:
  packages/maistro-bootstrap/tests: +2
  packages/maistro-rsi/tests: +7
---
# auto-448-c63b

Lane L448 (issue #448, M2 initiative) — the #1197 slice: sandbox output
capture is bounded at the host on every reachable production execution path
(docker exec, microVM launcher result, bootstrap container builder, RSI local
sandbox, bubblewrap and fake backends). Every delta below is a new test
pinning a #1197 contract; no existing test was removed.

## packages/maistro-core/tests (+0, withdrawn 2026-10-19)

This note originally recorded +28 here, measured against the pre-sync branch
tree where `tests/sandbox/test_capture.py` was this branch's own new 18-test
file. The develop syncs (c9a18d300, a77e2edf9, fe5823181) then adopted
develop's per-stream sandbox capture policy, and the merge took develop's
9-test `tests/sandbox/test_capture.py` verbatim (`git diff origin/develop
HEAD -- packages/maistro-core/tests/sandbox/test_capture.py` is empty) —
develop's own ledger already counts its 9. The surviving branch-side
core increments this note describes (`test_import_layering.py` +3,
`test_docker.py` +4, `test_microvm_sandbox.py` +3) are counted, together
with the 18 helper contracts that superseded the vanished capture-file
tests, by `448-tools-capture-drain-helpers.md` (+28 — exactly the branch's
true increment over develop, verified by collection: pristine develop
collects 16503 = its own expected, this branch collects 16531). Keeping
+28 here as well double-booked 31 nodes and made the maistro-core ledger
drift −31 against every runner, so the core delta is withdrawn to 0.

What the original +28 described, at authoring time (historical — the file
fates above are now governed by develop's ledger and the 448-tools note):

- `tests/sandbox/test_capture.py` — new file, 18 tests: retention limit and
  truncation truthfulness of `read_stream_bounded`/`communicate_bounded`
  (asyncio) and `run_bounded`/`capture_fd_sync` (threads), both streams
  emitted simultaneously so a sequential drain would deadlock; the
  ceiling clamp (`clamped_output_limit` rejects non-positive, caps at
  `MAX_OUTPUT_BYTES_CEILING`); the `SandboxSettings.max_output_bytes`
  numeric-literal drift pin (`maistro.config` sits below `maistro.sandbox`);
  `ExecResult.truncation_summary()` as the audit reader of the truncated flag.
- `tests/sandbox/test_import_layering.py` — new file, 3 tests: the sandbox
  subsystem must stay import-light toward the execution stack — fresh
  interpreters enter via five packages (`maistro.capabilities`, `maistro.runs`,
  `maistro.sandbox`, `maistro.tools.sandbox.microvm`, `maistro.tools.sandbox.docker`)
  and every one must import all three cleanly; the lazy `StaleExecutionFence`
  re-export must resolve to the class `maistro.runs.store` actually raises;
  unknown facade names must still raise `AttributeError`.
- `tests/tools/sandbox/test_docker.py` — +4: exec output retained at the
  container's clamped limit with the truncation notice appended, no notice
  under the limit, ceiling clamp on the container, and `create_sandbox`
  passing `SandboxSettings.max_output_bytes` through to the container.
- `tests/tools/test_microvm_sandbox.py` — +3: launcher output beyond the
  limit is byte-cut and declared, untouched under the limit, and
  `from_settings` carries the configured bound.
- `tests/sandbox/backends/test_fake.py` — net 0: the timeout test was reshaped
  to stub `Popen.wait` (the `run_bounded` seam) instead of `subprocess.run`;
  same assertion, no count change.

## packages/maistro-rsi/tests (+7)

- `tests/test_capture_mirror.py` — new file, 5 tests: the RSI-local mirror
  (`maistro_rsi.sandbox._capture`, which must not import maistro-core on the
  promotion path) stays byte-pinned to the canonical
  `maistro.tools.sandbox._capture`: constants, clamp policy, notice text, and
  drain behavior are compared by importing both sides (test code is not on
  the promotion path).
- `tests/test_sandbox.py` — +2: `LocalSandbox.exec` retains at most the
  clamped limit of a merged stream (50 KB emitter vs 1 KB limit) and drains
  stdout+stderr concurrently (16 MB on both simultaneously — a sequential
  drain would wedge against a full pipe).

## packages/maistro-bootstrap/tests (+2)

- `tests/test_container_sandbox_output_bound.py` — new file, 2 tests: the
  builder sandbox exec path carries the protocol default and the ceiling
  clamp, without Docker (seam stubs only).
- `tests/test_container_sandbox_hardening.py` — net 0: the recorder gained a
  `run_bounded` stand-in so the exec-path tests exercise the bounded seam;
  no test added or removed.
