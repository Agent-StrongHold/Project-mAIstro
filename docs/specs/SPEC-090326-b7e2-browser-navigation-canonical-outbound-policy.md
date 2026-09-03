---
id: SPEC-090326-b7e2
title: Browser navigation governed by the canonical outbound policy
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-03
accepted: 2026-09-03
history:
  - status: Proposed
    date: 2026-09-03
  - status: Accepted
    date: 2026-09-03
  - status: AC Defined
    date: 2026-09-03
substrate:
  - maistro-engine#155
implements: []
related:
  - maistro-engine#855
  - maistro-engine#ADR-082326-5386
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts: []
tests:
  - packages/maistro-core/tests/tools/browser/test_net_guard.py
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-090326-b7e2: Browser navigation governed by the canonical outbound policy

Evidence for issue #855, landed by PR #996 (Playwright route-layer enforcement).
ACs taken verbatim from the issue's acceptance checklist.

## Acceptance Criteria

```gherkin
Feature: Browser navigation governed by the canonical outbound policy

  @AC-1
  Scenario: Main-frame navigations checked pre-connection
    Given a browser main-frame navigation
    Then it is checked against the canonical outbound destination policy
    And the network connection is denied before it is allowed

  @AC-2
  Scenario: Redirect hops revalidated
    Given a navigation that follows redirects
    When a hop transitions public to loopback, private, link-local, or metadata
    Then that hop is denied at the transition

  @AC-3
  Scenario: Model-directed navigation governed
    Given autonomous navigation during search_web or browse
    When the model invents or clicks the destination itself
    Then the destination is governed the same as explicit navigation

  @AC-4
  Scenario: Subresource policy explicit
    Given browser subresource network requests
    Then dangerous schemes and private destinations are blocked
    And the decision is explicit rather than inherited silently

  @AC-5
  Scenario: DNS and alternate-notation bypass denied
    Given alternate IP notation, IPv6, hostname resolution, or redirect behavior
    Then private-address policy cannot be bypassed

  @AC-6
  Scenario: Internal destinations narrow
    Given browser access to a configured internal destination
    Then it requires a narrow host-owned allow policy
    And never model-level or request-level permission

  @AC-7
  Scenario: Auditable network evidence
    Given allowed or denied network effects
    Then the provider emits auditable evidence
    And does not log secrets or query contents unnecessarily
```
