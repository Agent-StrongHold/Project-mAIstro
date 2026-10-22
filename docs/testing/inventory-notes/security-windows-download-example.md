---
inventory-delta:
  tests/: +1
---
# security-windows-download-example

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Adds one static Windows bootstrapper help regression: download to a local
file, inspect its contents, and require explicit execution after review.
The prior pipe-to-expression example fails this regression. Runtime installer
behavior and the existing PowerShell harness cases are unchanged.
