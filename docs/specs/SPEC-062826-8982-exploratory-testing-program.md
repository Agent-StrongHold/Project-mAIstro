---
id: SPEC-062826-8982
title: "Exploratory testing program: session-log template and BACKLOG escalation path"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-28
substrate:
  - maistro-engine#ADR-031
related:
  - maistro-engine#SPEC-062826-1924
  - maistro-engine#SPEC-205
contracts: []
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062826-8982: Exploratory testing program

## Problem

Adversarial and state/IO-matrix testing (`maistro-engine#SPEC-062826-1924`) close gaps in
*automated, repeatable* coverage — fixed adversarial probe sets, full state×input grids,
Hypothesis property fuzzing. None of that replaces unscripted, charter-driven exploration: a
human or agent actually poking at a deliverable with no fixed input set, looking for the
invariant nobody thought to write a test for yet.

That kind of testing already happens in this codebase — informally, via the `run-formal` and
`verify-evolve` skills and ad-hoc debugging sessions — but with no log format and no defined path
from "I noticed something while poking at this" to a tracked backlog item or regression test. Two
concrete examples from this initiative's own Phase 0/Phase 3 work (the `ServiceKeyRegistry`
stale-key-mapping bug and the `AuthMiddleware` sibling-prefix-confusion bug) were found exactly
this way — through unscripted adversarial probing while building the *automated* test suites — and
would have been easy to fix-and-forget without anything connecting "what was poked," "what was
found," and "what test now locks it in."

## Design

### 1. Session log template

A single markdown file per session under `docs/exploratory-sessions/<YYYY-MM-DD>-<area-slug>.md`,
with front-matter (`date`, `tester`, `area`, `charter`) and two body sections: `Observations`
(chronological, concrete inputs/outputs) and a `Findings` table (`kind` ∈
`bug | gap | question | nit`, `escalated_to`, `follow_up_test`). Full template and finding-kind
definitions live in `docs/EXPLORATORY-TESTING.md` (the operational doc this SPEC's acceptance
criteria point at — kept separate from this SPEC so the day-to-day template can be edited without
touching front-matter/registry state).

### 2. Escalation path into BACKLOG.md

A finding needing tracked follow-up work beyond an immediate fix-in-place gets a `BACKLOG.md`
entry (next free `engine-NNN` id, in a `### Discovered gaps` subsection), cross-referenced both
ways: the BACKLOG entry links the session log, the session log's `escalated_to` column links the
BACKLOG id. A finding fixed immediately in the same change doesn't need a BACKLOG entry — the
`follow_up_test` column linking to the new regression test is sufficient provenance.

### 3. Skill integration

`run-formal` and `verify-evolve` (the two existing test-running skills closest to this codebase's
informal "/run"/"/verify" exploratory habit) each get a closing step pointing at
`docs/EXPLORATORY-TESTING.md`: when a run passes but still surfaces something worth a second look,
start a session instead of letting the observation evaporate at the end of the skill's report.

### 4. Proof of the loop closing

This SPEC ships with the loop already exercised, not just specified:

- Two retroactive session logs backfilling real findings from this initiative's earlier phases
  (`docs/exploratory-sessions/2026-06-28-service-key-registry-backfill.md`,
  `2026-06-28-auth-middleware-backfill.md`), each escalated to a new BACKLOG entry
  (`engine-110`, `engine-111`).
- One freshly-run, dogfooded session against a Phase 0/1 deliverable
  (`docs/exploratory-sessions/2026-06-28-task-status.md`, probing
  `tasks/status.py::can_transition`), whose finding produced a real follow-up test
  (`test_status.py::TestUnrecognizedCurrentDefaultsClosed`) landed in the same change.

## Non-goals

- Replacing or gating CI on exploratory sessions — this is a practice and a log format, not an
  automated check. Nothing in `ci.yml`/`quality.yml` enforces session-log presence.
- A registry/schema entry for session logs themselves — they're plain markdown, not ADR/spec
  front-matter, and are not walked by `maistro_registry`.

## Acceptance Criteria

- [x] `docs/EXPLORATORY-TESTING.md` exists and defines the session-log template, finding kinds,
      and the BACKLOG escalation path
- [x] `docs/exploratory-sessions/` exists with at least one dogfooded session log against a
      Phase 0/1 deliverable of `maistro-engine#SPEC-062826-1924`, with a real follow-up test
      landed
- [x] At least two historical findings are backfilled as session logs, each escalated to a new
      `BACKLOG.md` entry
- [x] `run-formal` and `verify-evolve` skill docs reference `docs/EXPLORATORY-TESTING.md`
- [x] `BACKLOG.md` carries the two new `engine-110`/`engine-111` entries, cross-linked to their
      session logs
