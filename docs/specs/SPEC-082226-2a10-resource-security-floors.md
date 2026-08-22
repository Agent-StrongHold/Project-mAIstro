---
id: SPEC-082226-2a10
title: Configurable Resource Security Floors
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-08-22
history:
  - status: Proposed
    date: 2026-08-22
  - status: Implemented
    date: 2026-08-22
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-072
implements:
  - maistro-engine#ADR-038
related:
  - maistro-engine#ADR-073
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_resource_policy.py
  - packages/maistro-server/tests/api/test_resource_policy_health.py
ac-modules:
  AC-1: maistro.config.settings
  AC-2: maistro.config.settings
  AC-3: maistro.security.resource_policy
  AC-4: maistro.security.resource_policy
  AC-5: maistro.agents.circuit_breaker
  AC-6: maistro_server.api.health
source:
  - SECURITY.md
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082226-2a10: Configurable Resource Security Floors

## Purpose

Turn security-relevant runtime limits into explicit deployment policy without allowing routine tuning to silently weaken the protections the engine historically shipped.

## Decision

The active environment-backed `maistro.config.settings.Settings` owns the effective policy for the runtime paths that already consume it. The policy covers:

- global HTTP request body maximum;
- webhook body maximum;
- per-client requests per minute;
- per-client burst limit;
- LLM circuit-breaker failure threshold;
- LLM circuit-breaker recovery timeout.

The shipped values are both defaults and the declared safe baseline. Operators may always tighten them. The direction of tightening depends on the control:

- **smaller is tighter:** request body maximum, webhook body maximum, requests/minute, burst limit, circuit failure threshold;
- **larger is tighter:** circuit recovery timeout.

A value that crosses the baseline in the weaker direction is rejected during Settings validation. `ALLOW_UNSAFE_RESOURCE_OVERRIDES=true` is the sole explicit escape hatch for an unsafe/development deployment. `debug` does not imply permission to weaken policy. Non-positive values remain invalid even in unsafe mode.

The process-global LLM circuit breaker is constructed from validated Settings. Existing rate-limit, request-body, and webhook paths already read those same Settings fields. `/health/ready` exposes the effective values plus whether unsafe overrides are enabled.

The separate legacy/YAML config models are not given duplicate knobs in this change. Adding values there without a demonstrated runtime consumer would create inert security configuration, which this repository explicitly rejects.

## Acceptance Criteria

```gherkin
Feature: Config-driven resource security floors

  @AC-1
  Scenario: Shipped defaults equal the declared baseline
    Given no deployment overrides
    When Settings is constructed
    Then the effective resource policy contains the declared baseline values
    And unsafe overrides are disabled

  @AC-2
  Scenario: Operators may tighten every protected limit
    Given values stricter than the declared baseline
    When Settings is constructed
    Then the stricter policy is accepted

  @AC-3
  Scenario: Routine configuration cannot weaken the baseline
    Given any protected value crosses its baseline in the weaker direction
    And unsafe overrides are disabled
    When Settings is constructed
    Then startup validation fails and identifies the explicit unsafe override

  @AC-4
  Scenario: Unsafe development weakening is explicit
    Given ALLOW_UNSAFE_RESOURCE_OVERRIDES is enabled
    When a protected value is configured weaker than baseline
    Then Settings accepts it
    And the effective policy reports unsafe overrides enabled
    But non-positive resource values are still rejected

  @AC-5
  Scenario: Circuit breaker uses deployment policy
    Given validated circuit threshold and recovery values
    When the process LLM circuit is constructed
    Then those effective values govern the breaker

  @AC-6
  Scenario: Effective values are observable
    Given the server is running with validated resource policy
    When an operator reads the readiness diagnostic
    Then the response includes every effective protected value
    And it reports whether unsafe overrides are enabled
```

## Non-goals

- Treating generic performance-only HTTP pool sizes as security floors.
- Adding duplicate knobs to config models with no runtime consumer.
- Replacing subsystem-specific quotas or model-provider rate profiles.
- Making unsafe mode appropriate for production.
