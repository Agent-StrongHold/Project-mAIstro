---
inventory-delta:
  formal/: +51
---
# Issue 341 formal security conformance

The formal dangerous-tools model now consumes the independently governed
`formal/fixtures/security_oracle.json` instead of importing implementation
constants or checking source-token counts. Its 22 adversarial command cases,
benign cases, tool cases, path cases, property sample, and runtime deletion
mutation checks add 51 collected formal nodes net.
