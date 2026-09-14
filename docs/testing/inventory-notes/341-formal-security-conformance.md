---
inventory-delta:
  formal/: +52
  tests/: +3
---
# Issue 341 formal security conformance

The formal dangerous-tools model consumes the independently governed
`formal/fixtures/security_oracle.json` instead of importing implementation
constants or checking source-token counts. Its 23 adversarial command cases
cover the 22 detector rules, including the `rm -rf ~` weakening witness;
benign cases, tool cases, path cases, property samples, and runtime deletion
mutation checks add 52 collected formal nodes. The base-diff independence gate
and its three tests add 3 nodes under `tests/`.
