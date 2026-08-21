# Exploratory Testing

Charter-driven, unscripted probing of a deliverable by a human or agent — the
counterpart to the automated adversarial/matrix suites. Where a Hypothesis
property test or a state×input matrix proves a *known* invariant holds across
many inputs, exploratory testing's job is finding the invariant nobody wrote
down yet: poke the thing, see what breaks, decide what to do about it.

This has happened informally throughout the codebase's history via the `/run`
and `/verify` skills and ad-hoc debugging sessions. This doc gives that
practice a session-log format and an explicit escalation path into
[`BACKLOG.md`](../BACKLOG.md), so a finding doesn't evaporate once the
terminal scrolls past it.

See `maistro-engine#SPEC-062826-8982` for the design rationale and acceptance
criteria.

## When to run an exploratory session

- After landing a new state machine, trust boundary, or parser — before or
  alongside its adversarial/matrix tests, not instead of them.
- When a bug report or incident is vague ("something's wrong with X") and you
  need to characterize the actual behavior before you can write a targeted
  regression test.
- As a deliberate practice pass over an area that's never had one (see the
  per-area charter ideas in `CONTRIBUTING.md`'s "How to add a spec" section
  for picking a target).

## Session log template

One log per session, as a single markdown file under
`docs/exploratory-sessions/<YYYY-MM-DD>-<area-slug>.md`. Use this front-matter
block plus a short narrative:

```markdown
---
date: 2026-06-28
tester: <name or agent>
area: <module/file/feature under test>
charter: <one sentence — what you set out to probe and why>
---

## Observations

<What you tried, what you saw — terse, chronological, include exact inputs
and outputs for anything surprising.>

## Findings

| # | Kind | Description | Escalated to | Follow-up test |
|---|------|-------------|---------------|----------------|
| 1 | bug \| gap \| question \| nit | <one line> | `BACKLOG.md#engine-NNN` or "none" | `path/to/test_x.py::test_y` or "none" |
```

**Finding kinds:**

| Kind | Meaning |
|---|---|
| `bug` | Confirmed incorrect behavior. Fix it (per `CLAUDE.md`'s "fix what you find" standing instruction) or, if it's out of scope for the current change, file it. |
| `gap` | Behavior is arguably correct but untested — no regression lock exists. |
| `question` | Ambiguous intent; needs a decision from a human owner before it's a bug or a non-issue. |
| `nit` | Cosmetic/consistency observation, no action required. |

**The `follow_up_test` field is what closes the loop.** A finding that
produces a `bug` or `gap` should, in the same change or a tracked follow-up,
land a test at the path named in that column — turning "I noticed this once"
into "this is now locked in." A session that finds nothing actionable is
still worth logging: it's evidence the area was actually exercised, not
skipped.

## Escalating to BACKLOG.md

If a finding needs tracked follow-up work beyond an immediate fix+test, add
an entry to [`BACKLOG.md`](../BACKLOG.md) under the relevant repo section
(usually a new `### Discovered gaps` subsection if there isn't already an
open one for the area), using the next free `engine-NNN` id. Reference the
session log in the entry; reference the BACKLOG id back in the session log's
`Escalated to` column.

## Relationship to `/run` and `/verify`

The `run-formal` and `verify-evolve` skills already run targeted automated
suites and report pass/fail counts. When a run surfaces something the
automated assertions don't capture — a flaky-looking failure, an output that
"looks wrong" but technically passes, behavior worth poking at further — note
it and, if it's worth a deeper look, start an exploratory session using this
template rather than letting the observation evaporate at the end of the
skill's report.

## Existing sessions

See `docs/exploratory-sessions/` for the session log archive. Start there
before probing an area someone has already chartered, to avoid duplicate
ground-covering.
