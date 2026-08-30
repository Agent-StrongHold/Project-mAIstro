---
id: ADR-082526-cb51
title: "The diff gate declares what it measures; absent from the report is a failure, not a skip"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_check_diff_coverage.py
ac-modules:
  AC-1: '@tool/check-diff-coverage'
  AC-2: '@tool/check-diff-coverage'
  AC-3: '@tool/check-diff-coverage'
  AC-4: '@tool/check-diff-coverage'
  AC-5: '@tool/check-diff-coverage'
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-cb51: The diff gate declares what it measures; absent from the report is a failure, not a skip

## Context

The per-file diff-coverage gate reads `coverage.xml` and scores the lines a
change touched. For any changed file the report did not mention it did nothing
and said nothing:

```python
lines = coverage.get(filename)
if not lines:
    continue  # outside the measured scope
```

The comment was accurate and the behaviour was not safe. "Outside the measured
scope" was inferred from the *absence of a record*, and a record can be absent
for two completely different reasons:

- nobody measures that tree — no coverage producer runs over it;
- somebody meant to measure it and the measurement did not happen — a mistyped
  `--source`, a producer whose artefact uploaded empty, a namespace-package
  directory `coverage` declined to walk.

Those are opposite situations and they produced the same green tick. The second
is the one that matters: a gate that cannot distinguish "not in scope" from "the
measurement broke" reports success for a change nothing exercised, which is the
exact failure a diff gate exists to prevent, one level up from the aggregate
floor it replaced.

The scope itself was also implicit. `--source` flags scattered across
`quality.yml` were the definition of what the gate covered, and the script's
docstring said so — "that list is the exemption list". That reading makes every
package with no producer silently exempt, which is how `maistro-server`,
`maistro-turing`, `maistro-design` and `hive-conductor` sat outside the gate
while a green tick was read as covering them.

## Decision

The gate declares its own scope, and absence inside that scope fails.

`MEASURED_ROOTS` in `scripts/check-diff-coverage.py` lists every tree whose
Python files are scored, in the same shape `quality.yml` passes to
`coverage run --source=`. `EXEMPT` lists the paths deliberately not scored, each
with its reason. A changed file is then one of four things, and the gate says
which:

- **measured** — scored against the per-file line and branch floors;
- **exempt** — named in the output with the reason it is exempt;
- **unmeasured** — no producer reaches it, named so the hole stays visible;
- **ignored** — not Python.

A measured file with no record in `coverage.xml` is a **failure**. That is the
whole change in one line: the case that used to be silent is now the loudest.

The four packages #163 names become producers for the diff gate only. They are
appended after the publish-set floor is evaluated, so the floor's denominator is
untouched — the ordering that makes this safe is already load-bearing in
`quality.yml` and is preserved. `maistro-turing` contributes two roots, `src/`
and `backend/`: the package carries a second FastAPI service, and measuring one
half would leave the other silently unscored, which is the shape of the problem
being fixed.

The declaration is checked against the workflow. A declaration nobody verifies
drifts the first time a producer is added, and drift here is silent by
construction in both directions — a declared root with no producer fails every
PR that touches it, and a producer with no declaration leaves the package
unscored.

## Acceptance criteria

- [x] **AC-1** Every package #163 item 6 names is in the measured scope, each
  named individually rather than counted.
- [x] **AC-2** A changed file under a measured root that the coverage report
  does not mention fails the gate.
- [x] **AC-3** A changed file no producer reaches is reported as unmeasured
  rather than failed — out of scope is not the same as broken.
- [x] **AC-4** Every exemption states a reason.
- [x] **AC-5** The declared roots and the workflow's `--source` flags are the
  same set.

## Consequences

### Positive
- "Coverage passed" on a PR now means the files it touched were measured, or
  says which ones were not. Neither was true before.
- The exemption list is one reviewable declaration rather than an emergent
  property of flags in a workflow (#163 item 5).
- 218 files under `packages/hive-conductor/backend` alone enter the gate's
  scope, having been invisible to it.

### Negative / Trade-offs
- The coverage-gate job grows four pytest runs. They are cheap next to the
  publish-set suites, and the alternative is a gate that does not cover the
  packages it claims to.
- A package added to `MEASURED_ROOTS` before its producer exists fails every PR
  that touches it. That is deliberate: the failure is loud and immediate rather
  than a quiet gap, and the drift test catches it before merge.

### Neutral
- Test files under a measured root (`packages/hive-conductor/backend/tests`,
  91 of them) are exempt by declaration. Scoring a test file's own coverage
  measures nothing.
- The aggregate publish-set floor is unchanged and still runs. The two answer
  different questions and neither subsumes the other (#163 item 4).
