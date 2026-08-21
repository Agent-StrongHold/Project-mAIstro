---
id: SPEC-275
title: "Registry CLI shared command pipeline and golden outputs"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
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
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-275: Registry CLI Command Pipeline

## Finding addressed

The registry CLI repeated root discovery, markdown file discovery, frontmatter parsing, validation, and output/reporting behavior across commands. The shared load-and-validate pipeline now prevents `lint` and `generate` from drifting on discovery, missing-root, and empty-root behavior; remaining work is expanding golden output coverage as new validation rules land.

## Design

1. Keep the shared load-and-validate pipeline as the only root/file discovery path for root-scoped commands.
2. Keep command-specific rendering separate from validation rules.
3. Add golden CLI tests for new `lint`, `generate`, and future registry command behavior.
4. Assert stdout, stderr, and exit code for empty roots, invalid roots, duplicate IDs, dangling links, strict mode, and successful generation.
5. Keep file ordering deterministic across platforms.

## Acceptance criteria

- [x] `lint` and `generate` share the same root/file discovery and validation pipeline.
- [x] Golden CLI tests assert exact exit codes and key output lines for missing-root and errored-generate cases.
- [ ] Duplicate ID and dangling-link cases are covered.
- [ ] Strict mode behavior is tested independently from markdown discovery.
- [ ] Adding a new registry validation rule requires one shared-pipeline test.
