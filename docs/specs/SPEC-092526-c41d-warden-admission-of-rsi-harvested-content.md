---
id: SPEC-092526-c41d
title: Warden Admission of RSI-Harvested Content
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-09-25
accepted: 2026-09-25
implemented: 2026-09-25
history:
  - status: Proposed
    date: 2026-09-25
  - status: Accepted
    date: 2026-09-25
  - status: Implemented
    date: 2026-09-25
substrate:
  - maistro-engine#ADR-073
implements:
  - maistro-engine#ADR-073
related:
  - maistro-engine#ADR-072
  - maistro-engine#ADR-081226-034b
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-rsi/tests/test_harvest_boundary.py
  - packages/maistro-rsi/tests/test_harvest_entry_point.py
  - packages/maistro-rsi/tests/test_local_loop.py
  - packages/maistro-rsi/tests/test_scout.py
  - packages/maistro-rsi/tests/test_non_production_reachability.py
ac-modules:
  AC-1: maistro_rsi.harvest_boundary
  AC-2: maistro_rsi.harvest_boundary
  AC-3: maistro_rsi.harvest_boundary
  AC-4: maistro_rsi.harvest_boundary
  AC-5: maistro_rsi.harvest_boundary
  AC-6: maistro_rsi.harvest_boundary
  AC-7: maistro_rsi.__main__
  AC-8: '@flat/hive-conductor/services.rsi_execution_policy'
  AC-9: maistro_rsi.harvest_boundary
source:
  - SECURITY.md
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-092526-c41d: Warden Admission of RSI-Harvested Content

## Purpose

RSI harvest ingests content produced outside the trusted optimizer boundary: repository files,
PRs, patches, diffs, review and commit metadata, and evaluation artifacts. That material can
later be summarized, judged, transformed, or fed to model-driven improvement logic. ADR-073 puts
a Warden scanner at every trust boundary; before this spec existed, the inbound harvest boundary
of the RSI optimizer had no owner, so malicious instructions embedded in harvested text, keys,
filenames, or metadata could become trusted model/optimizer context before any promotion control
ran.

This leaf owns only the *content-admission* inspection at that inbound boundary. Branch
targeting, patch validation, quarantine, promotion, and containment remain owned by the RSI
issues that govern them; a clean Warden verdict is not a promotion decision.

## Decision

`maistro_rsi.harvest_boundary` is the one canonical seam every RSI harvest path crosses before
externally or candidate-controlled material reaches a model callable, durable trusted memory,
evaluator instructions, or executable transformation paths.

- The boundary scans a deterministic serialization of the **whole** value it is handed: mapping
  keys are content (recorded as key/value pairs so attacker-controlled keys cannot collide or
  vanish), as are nested values, path/filename strings, diff text, commit and review fields, and
  generated metadata. Non-JSON-native shapes — bytes, dataclasses, v1-style `.dict()` objects —
  are serialized rather than skipped or `str()`-placeholdered, because a serializer that drops a
  shape scans a placeholder while the real payload reaches the model.
- The Warden scan runs on the boundary identifier `rsi_harvest_input` with policy version
  `warden-rsi-harvest-v1` (audit metadata, not a user-configurable policy).
- Failure is fail-closed and truthful: no configured policy, a raising scanner, an audit sink
  that cannot record, or a sync seam that cannot run the async scanner safely all produce a
  refusal with an explicit unavailable/blocked outcome — never an allow-all admission because
  RSI happens to run isolated. On the synchronous in-loop seam, an audit sink whose write
  cannot be confirmed before `scan_sync` returns (an async sink on a live event loop) is
  itself reported as `audit_unavailable`: the scan-level reason is preserved as
  `scan_outcome` in the audit record, the record is still delivered on the live loop, and a
  failed scheduled write is redelivered once with a corrected annotation so a transiently
  failing sink still persists the truthful not-admitted outcome.
- Refusal prevents admission: the caller receives no admitted serialization, and guarded
  callables raise before the wrapped model callable is invoked.
- Audit evidence records the verdict against Workspace/Project/Run/Attempt, source repository
  (host and port kept, userinfo credentials and query strings stripped), base/head refs or
  artifact digest, policy version, and RSI campaign/candidate identity. An unparsable repository
  URL degrades to a named placeholder instead of an uncorrelatable blank.
- Quarantine and promotion are untouched: this boundary answers only whether harvested content
  may enter trusted context. The harvest command's promotion-side gates (containment-surface
  veto, stale-patch skip, doc-regression drop, release-tier policy) still apply to admitted
  content, and `#302`'s quarantine/approval remains independently required before any promotion.
- RSI activation defaults are unchanged: RSI stays a specialized, non-production-reachable
  package until its M5 containment gates (#552) are satisfied.

## Acceptance Criteria

```gherkin
Feature: Warden admission of RSI-harvested content

  @AC-1
  Scenario: Every harvest path crosses the Warden boundary before model context
    Given an RSI seam that sends externally or candidate-controlled content to a model callable
    When that seam runs on scout source, builder prompts, harvest metadata and patch bodies, or evolve mutator prompts
    Then the canonical harvest boundary scans the content first and a refusal raises before the model callable is invoked

  @AC-2
  Scenario: The scan covers the semantically consumed representation
    Given harvested content as text, patch bytes, nested values, mapping keys, filenames, or commit and review metadata
    When the boundary serializes the content for Warden
    Then every semantically visible part including keys, paths, diff text and non-JSON-native objects appears in the scanned string

  @AC-3
  Scenario: A refusal keeps content out of trusted context and records the truth
    Given Warden returns a non-clean verdict for harvested content
    When admission is attempted
    Then the content is not admitted, the recorded outcome is blocked, and no admitted serialization is handed back

  @AC-4
  Scenario: Unavailable Warden policy fails closed
    Given no configured Warden policy, a raising scanner, an unrecordable audit sink, or a sync seam that cannot run the async scanner
    When admission is attempted
    Then the content is refused with a truthful unavailable outcome instead of an allow-all admission

  @AC-5
  Scenario: Audit evidence correlates the verdict without leaking credentials
    Given an admission decision carrying workspace, project, run, attempt, repository, base, head, campaign, and candidate identity
    When the audit record is written
    Then the record carries the policy version, outcome, content digest and those identifiers with URL credentials and query data removed

  @AC-6
  Scenario: A payload stays blocked when it moves between representations
    Given one prompt-injection payload
    When it is presented as text, a nested value, a mapping key, a filename, or a review or commit-message field
    Then the canonical Warden refuses every representation

  @AC-7
  Scenario: A clean Warden verdict does not authorize promotion
    Given harvested content that the Warden boundary admitted
    When the harvest command applies its promotion-side gates
    Then content a promotion gate rejects is still dropped and admission alone opens nothing

  @AC-8
  Scenario: Landing the boundary does not change activation defaults
    Given the shipped engine product packages and the Conductor's RSI seams
    When the tree is scanned for RSI reachability and the execution policy is inspected
    Then no engine package imports the RSI surface, references stay confined to the gated Conductor surfaces, and the HTTP run gate still fails closed

  @AC-9
  Scenario: Removing or bypassing the boundary is detected
    Given the adversarial tests that observe the model callable and the activation pins
    When the boundary is removed, bypassed, or widened on any protected seam
    Then at least one of those tests fails
```

## Non-goals

- Owning quarantine, promotion, or convergence: #302 and the RSI containment issues keep them.
- Changing RSI activation defaults or making RSI production-reachable (#552).
- Choosing Warden's detection mechanisms or policy contents (ADR-073).
- Governing RSI *egress*; this leaf owns the inbound content boundary only.
