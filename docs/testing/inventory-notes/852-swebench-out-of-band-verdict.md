---
inventory-delta:
  packages/maistro-evolve/tests: +31
---
# Issue #852 out-of-band SWE-bench verdict (sandbox_exec)

Adds `packages/maistro-evolve/tests/benchmarks/test_sandbox_exec.py` with 31
focused tests for the rewritten `benchmarks/sandbox_exec.py` verdict path.

Motivation: the previous design concatenated candidate code into the evaluator
script, so a candidate printing `PASS` and raising `SystemExit(0)` received a
passing verdict without any assertion running (demonstrated live on
`develop@0fb3dc69`: control fix and exploit both returned `ok=True`).

The rewrite (same commit) enforces: candidate code runs only in disposable
per-case subprocesses (`python -I runner.py <fn> <base64-args>`); expected
values never enter the sandbox; the host grades each case from the sandbox
exit status plus a structured `{"ok": ..., "result": ...}` envelope compared
against host-owned expected values; canonicalization is type-strict
(`True != 1`, `"3" != 3`); failures return rubric-free detail.

Coverage tiers:

- Hermetic (no Docker): the exact production runner script is executed with
  the host interpreter against hostile candidate inputs — spoofed PASS
  markers, early `SystemExit`/`os._exit` traps, wrong bodies, syntax errors,
  missing functions, raising functions, unserializable results, datetime
  round-trips, stdout markers after results, and envelope-parsing/grading
  primitives including type confusion.
- Docker-gated (skipped when no `docker` binary): real
  `run_function_checks` end-to-end — correct implementation passes, spoofed
  marker fails, wrong body fails, empty cases fail closed, sandbox
  unavailable fails closed (import blocked).

No existing tests removed; `tests/benchmarks/test_swebench.py` still passes
unchanged against the new verdict path.
