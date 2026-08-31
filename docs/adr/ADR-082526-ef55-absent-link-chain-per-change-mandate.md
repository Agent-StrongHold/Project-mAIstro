---
id: ADR-082526-ef55
title: "An absent link in the ADR → spec → AC chain is a per-change mandate, not only a ratchet"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082526-aef8
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/test_check_ac_state.py
ac-modules:
  AC-1: '@tool/check-ac-state'
  AC-2: '@tool/check-ac-state'
  AC-3: '@tool/check-ac-state'
  AC-4: '@tool/check-ac-state'
  AC-5: '@tool/check-ac-state'
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-ef55: An absent link in the ADR → spec → AC chain is a per-change mandate, not only a ratchet

## Context

The registry validates the chain for **breakage** — a reference that does not
resolve, a duplicate id, a `supersedes` cycle. It never asked whether a link
exists at all. `implements: []` is valid front matter, so a spec could name no
ADR and an ADR could be implemented by nothing, and both were clean. "Specs map
to ADRs" therefore meant "specs do not *mis*-map to ADRs", a much weaker claim
than the one a green build is read as supporting.

Three counters closed that gap — `specs_implementing_nothing`,
`adrs_without_implementing_spec`, `specs_declaring_no_criteria` — and each was
banked as a ratcheted ceiling in `quality/ac-state-ceilings.json`.

A ratchet compares **totals**, and that is not the same statement as "this
change did not add one". A PR that introduces one orphan spec while fixing an
unrelated legacy orphan leaves the count exactly where it was. The ceiling is
satisfied. A new absent link entered the repository and was paid for by an old
one that had nothing to do with it — the same silent-absorption failure the
criterion mandate already exists to stop one level down, reproduced at the
document level after the effort of arriving here.

Two populations, two rules, was already the settled shape for criteria: legacy
sits on a ceiling and falls over time; what a change creates gets zero
tolerance. The absence counters had only the first half.

## Decision

Compare the three populations **by document id** between the base revision and
the head, and fail on the set difference. A document that was not in a
population at the base and is in it at the head belongs to this change, whatever
else moved, so nothing nets off.

Three consequences follow from that choice.

**One derivation, not two.** The base side is `git show <base>:<path>`, where
there is no checkout to import from and no test that can be run, so the facts
must be text-only. The head side calls the *same* function rather than reading
the richer structures `collect_specs`/`collect_adrs` build. A fact derived one
way for head and another way for base can differ for reasons that have nothing
to do with the change, and every such difference would read as a violation the
PR introduced. `main`'s report gives up its inline copies and asks the same
function, so the number a reviewer reads and the set the gate compares cannot
drift apart.

**Corpus-wide, not per document.** Whether a decision is implemented is not a
property of the ADR: it depends on every spec's `implements:`, so deleting a
reference in one file can put a different file's decision into the population.
The comparison is over whole corpora for that reason.

**The ceilings stay.** The 76 orphan specs, 33 uncovered decisions and 7
criterion-less specs on `develop` remain grandfathered and continue to fall. A
gate that fired on all 76 at once would be turned off within a day, which is
worse than one that stops only what a change adds.

An unreadable base refuses rather than proceeding, exactly as the criterion
mandate does: an unreadable base makes every absent link look introduced, and a
gate that fires on everything gets turned off.

## Acceptance criteria

- [x] **AC-1** A change that adds a document to an absent-link population fails
  the mandate, and one that only removes documents from one does not.
- [x] **AC-2** A new violation cannot be paid for by fixing a legacy one: with
  the aggregate count unchanged, the introduced document is still reported.
- [x] **AC-3** Every counter the report ratchets for absence is carried by the
  mandate — a mandate covering two of three would make the third read as gated
  when it is not.
- [x] **AC-4** An unchanged corpus introduces nothing, so the mandate stays
  silent on a change that touches no document.
- [x] **AC-5** An unreadable base revision refuses rather than reporting the
  whole corpus as introduced.

## Consequences

### Positive
- #160's fifth mandate — "specs map to ADRs" — becomes a statement about the
  change under review rather than about a trend, which is what a merge button
  can be handed to.
- The report and the gate share one definition, so a counter cannot say one
  thing while the gate compares another.
- The remedy is printed per counter. A gate that reports a violation without
  its remedy gets worked around rather than satisfied.

### Negative / Trade-offs
- A PR that legitimately adds a spec before its ADR exists is now blocked until
  the decision is written down. That is the intended cost, and the escape hatch
  is deliberately not a flag: write the ADR, or leave it `Proposed`.
- Renaming a document's `id` reads as a new document to the chain, because id
  is the identity the comparison uses. A rename that also changes the id must
  satisfy the mandate on the new id.

### Neutral
- The mandate shares `--mandate BASE_REV` with the criterion mandate and one
  base walk. It does not need `--run-tests`, but the flag's contract is
  unchanged rather than split, so a CI misconfiguration cannot run half of it.
