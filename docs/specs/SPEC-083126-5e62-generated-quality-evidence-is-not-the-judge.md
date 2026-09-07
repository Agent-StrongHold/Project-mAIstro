---
id: SPEC-083126-5e62
title: "Generated quality evidence is not the judge after trusted-base migration"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-02
accepted: 2026-09-02
history:
  - status: Proposed
    date: 2026-09-02
  - status: Accepted
    date: 2026-09-02
  - status: AC Defined
    date: 2026-09-02
substrate:
  - maistro-engine#ADR-083126-5e62
implements:
  - maistro-engine#ADR-083126-5e62
related:
  - maistro-engine#ADR-082526-1899
  - maistro-engine#ADR-082926-25a2
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_autonomous_merge_quality_classes.py
source:
  - scripts/check-autonomous-merge.py
  - scripts/check-enqueue-merge-queue.py
ac-modules:
  AC-1: '@tool/check-enqueue-merge-queue'
  AC-2: '@tool/check-enqueue-merge-queue'
  AC-3: '@tool/check-enqueue-merge-queue'
  AC-4: '@tool/check-enqueue-merge-queue'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083126-5e62: Generated quality evidence is not the judge after trusted-base migration

- **Status:** Active
- **Decision:** ADR-083126-5e62
- **Implementation:** landed in #800 ahead of this spec

## Scope

The autonomous-merge policy's classification of `quality/**` edits: the
protected-base `quality/branch-independence.json` registry as the single
classification source, the YELLOW/RED outcomes `scripts/check-autonomous-merge.py`
derives from it, and the fail-closed rules for state the registry cannot
classify. The production executor is `scripts/check-enqueue-merge-queue.py`,
which loads the policy from the trusted base and applies it at merge-queue
admission; the `ac-modules` anchors name that reachable entry module because it
is the process that runs this decision's behavior in CI.

Out of scope: the risk classes themselves (ADR-083126-5e62 keeps YELLOW
human-only), and which future surfaces may migrate — each migration proves its
own trusted-base comparison authority before its registry entry changes.

## Why this spec exists

ADR-083126-5e62 was accepted in #800 together with its implementation and
tests, but no spec's `implements:` named it, so the decision landed in the
`taken ADRs with no spec` population and pushed `adrs_without_implementing_spec`
past its ceiling. This spec is that missing chain link: it declares the ADR's
acceptance section as measurable criteria bound to the tests #800 shipped,
rather than re-deciding anything. The criteria below restate the ADR's four
acceptance bullets one-for-one.

## Acceptance criteria

```gherkin
Feature: Generated quality evidence is not the judge after trusted-base migration

  @AC-1
  Scenario: A migrated base_derived surface is YELLOW with a distinct reason
    Given the protected-base registry classifies a quality surface as base_derived
    When the autonomous-merge policy assesses a change to that surface
    Then the risk is yellow and not eligible
    And the evidence reason names the base_derived surface

  @AC-2
  Scenario: Policy, legacy, unknown, malformed and ambiguous quality state stays RED
    Given a quality edit that is a specification, a legacy shared aggregate, an unclassified surface, a malformed registry, or an ambiguous classification
    When the autonomous-merge policy assesses the change
    Then the risk is red and not eligible
    And the reason states which fail-closed rule fired

  @AC-3
  Scenario: Merge groups carry YELLOW evidence after PR-time policy while RED stays blocked
    Given a merge-group candidate carrying base_derived quality evidence already admitted at PR time
    When the policy assesses it in merge-group mode
    Then the yellow evidence is carried
    And a trusted-surface change is still rejected regardless of branch identity

  @AC-4
  Scenario: Wiring-reads left the frozen legacy set behind proven provenance
    Given scripts/check-wiring-reads.py resolves its comparison baseline and authorizations from the trusted base
    When the branch-independence registry is read
    Then wiring-reads-baseline is classified base_derived
    And it is absent from the frozen legacy path set
```
