---
inventory-delta:
  packages/maistro-bootstrap/tests: +5
---

# auto-57-argv0-executable-escape

Repair round for issue #57 (verify finding: `SandboxedShell.run_argv` validated
only `argv[1:]`, so the model-facing `run_command` tool could execute an
outside-root absolute executable, e.g. `argv[0]="/bin/echo"`, where the string
path always raised `SandboxEscapeError`).

`packages/maistro-bootstrap/src/maistro_bootstrap/builders/sandbox.py` now
path-checks the executable token too (`_check_paths(argv)`), matching the
`run()` string path. Five tests pin the boundary — all five were shown to FAIL
against the pre-fix code (run via a copy of the package with the vulnerable
`sandbox.py` restored from 1b1256154):

- `test_builders_sandbox.py::test_run_argv_blocks_outside_root_executable` —
  lexical block; failed pre-fix with `FileNotFoundError` (argv[0] reached the OS).
- `test_builders_sandbox.py::test_run_argv_outside_root_executable_never_runs` —
  side-effect proof with a safe relative argument; failed pre-fix (binary ran).
- `test_builders_sandbox.py::test_run_argv_still_runs_bare_and_in_root_executables` —
  no-overblock guard for bare PATH names and in-root executables.
- `test_agent_loop_command_contract.py::test_run_command_model_argv_cannot_execute_outside_root` —
  real `SandboxedShell` through `_dispatch_tool`; failed pre-fix (binary ran).
- `test_agent_loop_command_contract.py::test_run_command_still_dispatches_bare_executable_names` —
  legitimate bare-name dispatch through the real sandbox.

No tests were removed, skipped, or renamed; the two POSIX-gated additions skip
on Windows only (`/bin/touch`, `echo`, shebang scripts).
