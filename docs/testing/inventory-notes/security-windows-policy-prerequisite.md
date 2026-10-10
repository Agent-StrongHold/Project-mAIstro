---
inventory-delta:
  tests/: +3
---
# security-windows-policy-prerequisite

Adds static help-text and real relaunch-function regressions for the Windows
bootstrapper's approved script-execution prerequisite and removal of process
policy overrides. Adds one PowerShell harness test that invokes both real
command builders with process/registry operations mocked, checking ordinary
policy resolution, quoting, elevation, and resume arguments. The existing
Windows detection runner also executes this harness under both interpreters.
These mocks do not validate real Windows policy enforcement, UAC, or reboot.
