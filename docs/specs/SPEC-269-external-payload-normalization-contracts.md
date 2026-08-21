---
id: SPEC-269
title: "External payload normalization contracts for tolerant tool clients"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related: []
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-269: External Payload Normalization Contracts

## Finding addressed

Atlassian client parsers tolerate nested REST and flattened MCP payload shapes in branch-heavy parsing functions. Tolerance is useful, but accepted shapes need fixtures and exact normalized outputs.

## Design

1. Define fixture payloads for Jira REST issue, flattened MCP Jira issue, Confluence REST page, flattened MCP Confluence page, and malformed payloads.
2. Add exact assertions on normalized dataclasses.
3. Extract small helpers for nested-or-flat fields if complexity remains high.
4. Treat unknown/malformed shapes as deterministic empty/default fields, not exceptions, unless the public contract says otherwise.
5. Document each accepted upstream shape with source/provider name.

## Acceptance criteria

- [ ] Jira nested and flattened shapes normalize to the same intended fields.
- [ ] Confluence nested and flattened shapes normalize to the same intended fields.
- [ ] Malformed shape behavior is deterministic and tested.
- [ ] Parser helpers stay pure and have no network dependency.
