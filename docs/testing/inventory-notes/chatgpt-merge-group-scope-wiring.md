---
inventory-delta:
  tests/: +12
---
# chatgpt-merge-group-scope-wiring

Twelve focused root-suite tests pin the integration-scope aggregate contract introduced for #655.

They preserve the full specialized CI requirement on pull requests and protected pushes while allowing merge-group candidates to omit only classifier-declared out-of-scope legs. Missing, malformed, incomplete, or non-boolean scope evidence fails closed to every specialized job. Hive selection requires both API and UI E2E jobs together, and any selected job must report `success`; an out-of-scope skipped job is acceptable only for merge-group evaluation.

No existing test was moved, renamed, parametrized, or deleted, so this slice changes root-suite collection by exactly +12 node IDs.
