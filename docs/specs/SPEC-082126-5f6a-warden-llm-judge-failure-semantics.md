---
id: SPEC-082126-5f6a
title: Warden L3 Judge Failure Semantics
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
  - maistro-engine#ADR-072
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/warden/test_detector.py
  - packages/maistro-core/tests/security/test_llm_classifier.py
ac-modules:
  AC-1:
    - maistro.security.warden.detector
    - maistro.security.warden.llm_classifier
  AC-2:
    - maistro.security.warden.detector
    - maistro.security.warden.llm_classifier
  AC-3:
    - maistro.security.warden.detector
    - maistro.security.warden.llm_classifier
  AC-4:
    - maistro.security.warden.detector
    - maistro.security.warden.llm_classifier
  AC-5:
    - maistro.security.warden.detector
source:
  - SECURITY.md
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082126-5f6a: Warden L3 Judge Failure Semantics

## Purpose

Define the missing failure contract for ADR-073's optional L3 LLM judge. The judge is invoked only for tool-result content that passes deterministic Warden layers and only when an LLM client is configured.

The previous implementation treated provider failure or malformed classifier output as if the judge had returned `safe`. That silently widened the trust boundary precisely when the configured escalation control was unavailable.

## Decision

When the L3 judge is invoked, **only an exact normalized `safe` response clears the L3 check**.

The following outcomes are inconclusive and MUST fail closed through Warden's suspicious/non-clean enforcement path:

- provider/backend exception;
- timeout;
- missing or empty choices;
- malformed response structure;
- any response other than the exact tokens `safe` or `suspicious`;
- partial/prose classifications such as `safe, but ...`.

An inconclusive judge result is projected onto the suspicious enforcement path so existing Warden callers do not need a second decision universe. The result MUST retain an observable `reasoning_trace` identifying classifier failure or malformed output so operators can distinguish uncertainty from a genuine suspicious classification.

If no LLM judge is configured, Warden continues to rely on its deterministic layers. This spec does not make L3 mandatory.

## Acceptance Criteria

```gherkin
Feature: Warden L3 judge failure semantics

  @AC-1
  Scenario: Exact safe output clears the optional judge
    Given the L3 judge is configured and invoked for a tool result
    When the judge returns exactly "safe"
    Then Warden may return a clean verdict if earlier layers are also clean

  @AC-2
  Scenario: Provider failure fails closed
    Given the L3 judge is configured and invoked
    When the provider raises an error or timeout
    Then Warden returns a non-clean verdict
    And the reasoning trace records an inconclusive classification failure

  @AC-3
  Scenario: Malformed output fails closed
    Given the L3 judge is configured and invoked
    When the provider returns no usable classification
    Then Warden returns a non-clean verdict
    And the reasoning trace records malformed classifier output

  @AC-4
  Scenario: Partial classification is not treated as safe
    Given the L3 judge is configured and invoked
    When the model returns prose containing a safe-like answer rather than exactly "safe"
    Then Warden returns a non-clean verdict

  @AC-5
  Scenario: No configured judge preserves deterministic behavior
    Given no L3 judge client is configured
    When deterministic Warden layers find no threat
    Then Warden may return a clean verdict without attempting an LLM call
```

## Non-goals

- Choosing the L3 model or provider.
- Making L3 mandatory for all boundaries.
- Changing the deterministic regex, heuristic, or semantic layers.
- Defining product-wide Warden/Sentinel reachability; that remains convergence/security-path work.
