---
inventory-delta:
  tests/: +9
---

# Build-evidence result contract

Adds nine focused root-suite cases for the fail-closed reusable-result contract:

- successful completed evidence round-trips against an independently expected identity;
- a recorded command failure can never be reused as green evidence;
- input-content drift invalidates previously completed evidence;
- result-key tampering is rejected;
- a result value that contradicts the exit code is rejected;
- non-finite duration metadata is rejected;
- boolean exit codes are rejected rather than being accepted as integers;
- the CLI can complete an identity and independently verify the resulting evidence; and
- completion mode refuses identity-generation arguments that would make the recorded result ambiguous.

This slice defines and tests the result envelope only. Producer/consumer workflow wiring remains a later #654 slice so this contract does not collide with active CI-topology work.