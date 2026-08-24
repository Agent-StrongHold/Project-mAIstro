---
id: SPEC-082126-7a31
title: Sentinel Tool-Argument Resource Limits
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-08-21
history:
  - status: Proposed
    date: 2026-08-21
  - status: Implemented
    date: 2026-08-21
substrate:
  - maistro-engine#ADR-073
implements:
  - maistro-engine#ADR-073
related:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-072
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/sentinel/test_argument_limits.py
ac-modules:
  AC-1: maistro.security.sentinel.policy
  AC-2: maistro.security.sentinel.policy
  AC-3: maistro.security.sentinel.argument_limits
  AC-4: maistro.security.sentinel.argument_limits
  AC-5: maistro.security.sentinel.argument_limits
  AC-6: maistro.security.sentinel.argument_limits
source:
  - SECURITY.md
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082126-7a31: Sentinel Tool-Argument Resource Limits

## Purpose

Bound the amount of structured argument data a model or caller may hand to a tool before Sentinel performs schema traversal or the tool executes. The control prevents oversized strings, encoded payloads, and deeply nested JSON structures from turning the tool boundary into a resource-exhaustion path.

## Decision

Sentinel enforces two independent limits after the cheap permission check and before schema validation:

1. maximum compact UTF-8 JSON bytes, default **100 KiB**;
2. maximum list/dict structural depth, default **32** container levels.

Depth is measured iteratively and checked before JSON serialization. Payloads that exceed depth therefore do not enter recursive schema/serialization work. Once depth is acceptable, size is measured using compact UTF-8 JSON. Non-JSON-compatible argument objects fail closed because model/tool-call arguments are a JSON contract.

Defaults live in `maistro.constants` and are also the deployment security baseline. A deployment may freely tighten them through:

- `MAISTRO_TOOL_ARGUMENT_MAX_BYTES`
- `MAISTRO_TOOL_ARGUMENT_MAX_DEPTH`

Because both are maxima, raising either value weakens the boundary. A larger ceiling is therefore refused unless the operator separately sets `ALLOW_UNSAFE_RESOURCE_OVERRIDES=true`. The unsafe flag is deliberately distinct from `DEBUG`: widening a security boundary must be an explicit policy statement, not a side effect of a generic development mode. Invalid, non-positive, or ambiguous policy values fail Sentinel construction rather than silently falling back. The effective limit that caused a denial is included in the Sentinel violation/audit detail.

This is an execution-boundary limit. HTTP request-body parsing has its own independent request-size boundary; this control does not claim to protect an upstream parser from a body that has already been materialized.

## Acceptance Criteria

```gherkin
Feature: Tool-argument resource limits

  @AC-1
  Scenario: Ordinary arguments preserve behavior
    Given a permitted tool call with ordinary JSON-compatible arguments
    When the arguments are within the byte and depth limits
    Then Sentinel continues to schema validation
    And the resource gate does not deny the call

  @AC-2
  Scenario: Oversized arguments are denied before execution
    Given a permitted tool call
    When compact UTF-8 JSON arguments exceed the configured byte maximum
    Then Sentinel denies the call
    And audit evidence records the measured size and configured maximum

  @AC-3
  Scenario: Excessive depth is denied before serialization
    Given deeply nested list or object arguments
    When structural depth exceeds the configured maximum
    Then Sentinel denies the call before JSON serialization or schema validation

  @AC-4
  Scenario: Encoded content cannot evade the byte ceiling
    Given a base64 or otherwise encoded payload stored in a JSON string
    When its encoded representation exceeds the configured maximum
    Then the call is denied by the same byte limit

  @AC-5
  Scenario: Deployment overrides cannot silently weaken the boundary
    Given an operator sets a positive tool-argument limit environment override
    When the override tightens the shipped maximum
    Then it becomes the effective deployment limit
    But when the override raises the maximum without an explicit unsafe-resource policy
    Then Sentinel construction fails loudly
    And an explicitly unsafe deployment may opt into the weaker maximum
    And invalid limit or unsafe-policy values fail construction loudly

  @AC-6
  Scenario: Non-JSON arguments fail closed
    Given a tool call contains values outside the JSON argument contract
    When the resource gate evaluates it
    Then Sentinel denies the call rather than bypassing the resource boundary
```

## Non-goals

- Replacing the HTTP request-body limit.
- Fixing unrelated schema-validation semantics.
- Defining global deployment resource floors for every subsystem; that broader policy belongs to the dedicated configuration-floor work.
- Introducing a second tool execution or capability path.
