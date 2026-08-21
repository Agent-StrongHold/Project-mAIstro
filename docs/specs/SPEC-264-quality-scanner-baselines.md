---
id: SPEC-264
title: "Quality scanner baselines, vulture ownership, and radon ratchets"
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
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-264: Quality Scanner Baselines

## Finding addressed

The deep dive found vulture output mixing framework false positives, dynamic public APIs, likely true positives, and unclassified dead-code candidates. Radon also identified complexity hotspots that need ratcheting rather than blanket failure.

## Problem

If scanner findings are always advisory, true positives are ignored. If all findings are blocking immediately, FastAPI decorators and dynamic tool entrypoints create noise. The repository needs reviewed baselines and a rule for failing only on new or unclassified findings.

## Design

1. Add a vulture allowlist file with one reason per symbol.
2. Classify every finding into one of:
   - framework false positive;
   - dynamic public API;
   - test gap;
   - remove/fix.
3. Make high-confidence local unused variables blocking after the initial baseline is triaged.
4. Store radon complexity baselines for current C/D/E hotspots.
5. Fail CI on new complexity regressions unless the owning spec documents why the complexity is intentional.
6. Link each accepted hotspot to a remediation spec or explicit non-action rationale.
7. Keep LLM-as-judge outputs advisory and never a replacement for deterministic scanner gates.

## Non-goals

This spec does not claim that completing the current scanner baseline makes the codebase perfect or exhaustively reviewed. It only turns the current known scanner/deep-dive findings into owned, repeatable quality gates. Future scans, new code paths, incidents, and deeper manual reviews may create new findings and new specs.

SPEC-264 is successful when the current baseline is classified and future regressions are visible; it is not a terminal quality certification.

## Acceptance criteria

- [x] Vulture allowlist exists and every entry has an owner/rationale (`quality/vulture-baseline.json`).
- [x] Current vulture findings are classified (every one of the 1012 repo-wide findings matches a reviewed rule; 0 unclassified, 0 unreachable-code).
- [x] New unclassified vulture findings fail CI (`scripts/check-vulture-baseline.py` wired into `.github/workflows/quality.yml`, Phase 20).
- [x] Radon baseline exists for current C/D/E findings (`quality/radon-baseline.json`, 77 entries keyed by qualified name).
- [x] New radon regressions fail CI or require spec-linked justification (`scripts/check-radon-baseline.py` wired into `.github/workflows/quality.yml`, Phase 20; module/project-average complexity remains xenon's count ratchet, since radon's per-block output has no module-aggregate notion).
- [ ] Scanner report links each negative finding to a spec or explicit non-action.
