---
inventory-delta:
  tests/: +1
---
# security-windows-policy-prerequisite

Adds one static help-text regression for the Windows bootstrapper's approved
script-execution prerequisite: read policies, stop if execution is disallowed,
then download, inspect, and explicitly run only in an approved setup. It guards
against policy-changing and encoded/remote-evaluation shortcuts in the help.
This does not test PowerShell execution or alter the installer runtime.
