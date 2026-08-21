---
id: SPEC-062126-757a
title: "Canvas tool action contracts, upload correctness, and reference persistence ownership"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-229
implements: []
supersedes:
  - maistro-engine#SPEC-070126-a3f1
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-757a: Canvas Tool Action Contracts

## Finding addressed

The code-quality deep dive identified `execute_canvas` as an over-broad dispatcher with branch-local state risks. The immediate concrete defect is the `upload` action using dimensions from `img` instead of the branch-local `upload_img`. Borderline findings include unused `reference_images`, `destroy_canvas`, character-reference helpers, and `CREATE_TABLE_SQL` ownership.

## Problem

Canvas tool actions currently share one broad function signature. Most parameters apply to only one action, so invalid combinations are easy to pass and branch-specific bugs are hard to test. Static analysis cannot distinguish dynamic tool entrypoints from dead helpers without an explicit contract.

## Design

1. Keep `execute_canvas(...)` as the public tool entrypoint, but make it a thin dispatcher.
2. Add action-specific request models or dataclasses for `generate`, `refine`, `reference`, `composite`, `text`, `upload`, and `list_layers`.
3. Move action bodies into private helpers with narrow inputs and exact return contracts.
4. Fix `upload` to use the decoded `upload_img` dimensions and persist those dimensions on the layer.
5. Decide `reference_images` ownership:
   - implement it in the reference/refine action if it is a real public input; or
   - remove it from the public signature if it is not supported.
6. Move `CREATE_TABLE_SQL` into a migration/schema ownership location or add a named initialization function that uses it.
7. Document dynamic public APIs in a vulture allowlist once their ownership is confirmed.

## Acceptance criteria

- [ ] `upload` with a non-square base64 image returns exact uploaded width and height.
- [ ] `execute_canvas` delegates each action to a named helper.
- [ ] Each action helper has focused unit tests with exact output assertions.
- [ ] Invalid action/input combinations return a typed error payload or fail validation before execution.
- [ ] `reference_images` is either implemented with tests or removed.
- [ ] Character-reference persistence SQL ownership is documented and tested, or dead code is removed.
