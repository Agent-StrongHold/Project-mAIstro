---
id: SPEC-267
title: "HTTP middleware auth, elevation, and request logging policy contracts"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-21
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-247
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-267: HTTP Middleware Policy Contracts

## Finding addressed

Auth and request logging middleware encode route policy with prefix checks and ad-hoc logging decisions. The behavior needs explicit route tables and sanitization tests.

## Design

1. Extract an auth route-policy table for public, authenticated, admin-blocked, and elevated routes.
2. Add boundary tests for exact and prefix matches, especially `/v1/*` additions.
3. Add tests for cookie auth, bearer auth, missing auth, admin chat block, and protected-operation elevation.
4. Define request logging sanitization rules for query params and user identifiers.
5. Avoid re-resolving users in logging when `request.state.user` is already set.

## Acceptance criteria

- [ ] Public/protected/admin/elevated route behavior is table-tested.
- [ ] New `/v1` routes must choose an auth policy.
- [ ] Request logs redact or omit sensitive query parameters.
- [ ] Request logging uses request state when available instead of re-reading session state.
