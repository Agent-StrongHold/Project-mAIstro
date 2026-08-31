---
inventory-delta:
  tests/: +16
---
# chatgpt-merge-group-scope-wiring

Sixteen focused root-suite tests pin the integration-scope and merge-group execution-evidence contracts introduced for #655.

Thirteen preserve the full specialized CI requirement on pull requests and protected pushes while allowing merge-group candidates to omit only classifier-declared out-of-scope legs. Missing, malformed, incomplete, or non-boolean scope evidence fails closed to every specialized job. Hive selection requires both API and UI E2E jobs together, any selected job must report `success`, an out-of-scope skipped job is acceptable only for merge-group evaluation, and an out-of-scope job that nevertheless executes with a failing result remains blocking.

Three more prove that `gates-ran` keeps specialized execution evidence on pull requests, replaces those nine contexts with the unconditional `integration-scope` aggregate on merge-group candidates, and still requires the unconditional core CI checks there.

No existing test was moved, renamed, parametrized, or deleted, so this slice changes root-suite collection by exactly +16 node IDs.
