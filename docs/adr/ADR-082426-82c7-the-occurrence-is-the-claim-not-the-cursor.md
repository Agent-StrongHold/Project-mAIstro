---
id: ADR-082426-82c7
title: "A schedule firing is claimed by its occurrence, not by the cursor"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-24
accepted: 2026-08-24
history:
  - status: Proposed
    date: 2026-08-24
  - status: Accepted
    date: 2026-08-24
substrate:
  - maistro-engine#ADR-082126-f69c
implements: []
related:
  - maistro-engine#ADR-046
  - maistro-engine#ADR-081226-a66b
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-82c7: A schedule firing is claimed by its occurrence, not by the cursor

## Context

ADR-082126-f69c decided that recurrence produces Runs: a schedule is a definition, and
firing it admits a canonical Run. #46's first acceptance criterion puts a number on that —
**each firing has exactly one canonical `run_id`**.

`ScheduleRunAdmitter` got the durability half right and left the uniqueness half open. Its
ordering is create-the-Runs, then advance the cursor, chosen against the failure that
matters: a tick that stamped `last_fired_at` first and then failed would skip that
occurrence permanently and silently, because the next evaluation enumerates from the new
cursor and never looks back. Preferring a duplicate to a skip is right. Nothing bounded
the duplicate.

Two ways it happens, and they are the same missing thing:

- **A crash between creating the Run and stamping the cursor.** The Runs exist, the cursor
  did not move, and the next tick re-enumerates the occurrence and creates a second Run.
- **Two tickers on one schedule.** Nothing serialises read-evaluate-write. Both read the
  same `last_fired_at`, both enumerate the same occurrences, both create Runs, both stamp
  the cursor. Only `services/scheduler.py` drives the live path today and it is
  single-process — so this is latent rather than active, and "exactly one `run_id` per
  firing" is not a property that should depend on how many replicas are deployed.

The unit being claimed was the **cursor**, and a cursor is not the identity of an
occurrence. It is a high-water mark: it says where enumeration resumes, which is a
different question from which firings have happened.

## Decision

**1. `(schedule_id, scheduled_for)` is the identity of a firing, and the store enforces it.**

A scheduled Run already carries both in its provenance (#218). That pair becomes a claim:
the Run store refuses a second Run for an occurrence that already has one, with a typed
`DuplicateOccurrence`. Refused by the store rather than checked by the caller, because a
convention in the caller is exactly what two callers do not share.

**2. `catchup` is not part of the key.**

A backfill and an on-time fire for the same nominal time are the *same occurrence*. That
they were noticed at different moments is why the flag exists; it is not a reason to run
the work twice. The two collide, deliberately.

**3. The claim is on the Run, not in a claims table.**

An expression index over the Run's own provenance, partial on the two keys being present.
The alternative — a `schedule_occurrence_claims` table — was rejected for two reasons. It
is a second record of one fact, which can disagree with the first; and it outlives the Run
it describes, so retention deleting a Run would leave a claim asserting a firing whose only
evidence is gone. Indexing the Run makes the claim disappear exactly when the Run does,
which is the correct coupling: nothing is duplicated by re-admitting a firing whose record
was deliberately destroyed.

**4. A duplicate is consumed, not failed.**

Every other admission error stops the batch, because `record_fire` moves the cursor past
everything it covers and continuing would either lose the failure or duplicate the success.
A duplicate inverts that: the occurrence *did* fire, so it is owed to nobody. The admitter
counts it as consumed — the cursor may pass it — and reports it in `already_fired`, but
does **not** count it toward `max_runs`. The admitter that actually created the Run counts
that firing for itself; both counting it would exhaust a schedule at half the occurrences
it was configured for.

**5. The cursor becomes an optimisation.**

With occurrence identity durable, `last_fired_at` says where to resume enumerating so a
schedule does not re-derive its whole history every tick. It is no longer what makes firing
exactly-once. The create-then-advance ordering stays — a skip is still worse than a repeat
— but its "at worst a repeat" case is now refused rather than merely tolerated.

## Consequences

### Positive

- #46's first criterion becomes a property of the system rather than of the deployment
  topology. A second ticker is safe to run.
- The crash window between creating a Run and stamping the cursor stops producing a
  duplicate firing. It was the known cost of the ordering, and it is now paid.
- Two things that were both silently load-bearing — the cursor and the create-first
  ordering — are separated, and only one of them carries correctness.

### Negative / Trade-offs

- **An index over a payload expression.** It ties the index to the spelling of two
  provenance keys, which `runs.sources` owns and `occurrence_key` reads in one place. The
  alternative was two columns on `canonical_runs` that every non-scheduled Run would carry
  as NULL, for one admitter's benefit.
- **A schedule cannot deliberately fire an occurrence twice.** Nothing asks to today, and a
  re-run of the same nominal time is a retry of the existing Run — a new Attempt under it,
  which the claim does not touch. A genuine second firing would need an explicit
  re-admission path, and should, because it should be visible.
- Migration 015 fails on a database that already holds duplicate occurrences. That is the
  defect being closed, and failing loudly beats silently keeping both.

### Neutral

- `scheduled_for` is compared as the ISO-8601 string the admitter writes. Every producer
  gets it from `evaluate()`, and `datetime.isoformat()` is deterministic for a given
  aware instant, so two tickers computing one occurrence write one string.
- The reference in-memory store keeps a claim map instead of an index. It runs in a single
  event loop with no `await` between the check and the claim, so the two halves cannot
  interleave.
