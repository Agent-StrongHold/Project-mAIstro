---
id: ADR-092126-a28a
title: Retire body status lines — front matter is the only status
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-21
accepted: 2026-09-21
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-031
  - maistro-engine#ADR-097
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - tests/test_check_adr_status_language.py
ac-modules:
  AC-1: '@tool/check-adr-status-language'
  AC-2: '@tool/check-adr-status-language'
  AC-3: '@tool/check-adr-status-language'
  AC-4: '@tool/check-adr-status-language'
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-09-21
  - status: Accepted
    date: 2026-09-21
---

# ADR-092126-a28a: Retire body status lines — front matter is the only status

## Context

ADR-031 made front matter canonical: the lifecycle machine, the AC ladder, the
citation gate and `ADR-INDEX` all read `status:` there. But 63 ADRs and 20
specs also carried a `**Status:** X` line in their body, restating that value
in prose a few lines below the front matter that owns it.

Nothing consumed those lines. A survey of `scripts/`, `tools/` and
`packages/*/src` found exactly one reader: the gate written to police them.
Every other tool already read front matter. Their only function was to tell a
human reader something a machine would never act on.

They drifted, which is the predictable outcome of storing one fact twice:

- ADR-046 spent three weeks with `status: Superseded` in front matter and a
  body paragraph arguing the status stayed `Accepted` (#387). Different
  readers got different answers, and nothing could see it because nothing read
  the body's claims at all.
- #387 then found 28 more and banked them as a legacy tolerance.
- 19 specs said `Active` — a value not in the `Status` vocabulary at all —
  while their front matter said `AC Defined`. These were invisible for a year
  because the gate matched only the bare `**Status:**` spelling and every spec
  wrote the list-item form.

All 47 are now corrected and the ratchet's ledger is empty. That is the moment
to ask whether the duplication should exist, because the alternative to
retiring it is maintaining it forever: every status transition must remember to
edit two places, and the gate exists solely to catch the times someone does
not. The cost is recurring and the benefit is zero.

The scaffolding already agrees. `ADR-000-template.md` carries no body status
line, and neither the `/adr` nor the `/spec` skill emits one. Every document
that has one predates that convention.

## Decision

**A document's status lives in its front matter and nowhere else.** The
`**Status:** X` line is removed from the body of all 83 documents under
`docs/adr/` and `docs/specs/`, in both the bare and list-item spellings. The
surrounding header block (`**Date:**`, `**Deciders:**`, `**ADR:**`) is left
alone — this ADR is about the duplicated status, not about that block.

`scripts/check-adr-status-language.py` changes its first category from
*agreement* to *absence*: a body status line is a finding whatever it says,
because a line that agrees today is a line that drifts tomorrow. This is what
makes the retirement durable rather than a one-time sweep — without it, the
next author to reintroduce `**Status:** Accepted` under an Accepted ADR passes
CI and starts the clock again.

Categories 2 and 3 — replacement banners that name the wrong document, and
prose asserting an unqualified continuing status on a superseded one — are
unchanged. They police claims front matter cannot express, so they are not
duplication and are not retired.

The ledger and its provenance wiring stay. It remains the reviewed escape
hatch, and `check-adr-status-language-provenance.py`, the entry in
`quality/branch-independence.json` and the `check-ratchet-provenance.py`
registration all continue to apply unchanged.

## Consequences

### Positive

- One source of truth. A status transition edits front matter; there is no
  second place to forget.
- The drift class this gate was written for cannot recur. Absence is
  enforceable in a way agreement is not: agreement re-admits the duplication
  every time someone writes a line that happens to be correct.
- The check gets simpler to reason about. "No status line in the body" needs
  no status vocabulary, no multi-word values, no case folding — all of which
  were sources of defect in the agreement implementation.

### Negative / Trade-offs

- A reader skimming rendered Markdown no longer sees the status in the body
  text. They see it in the front matter, which most renderers display, and it
  is the value every tool acts on — but it is a real change in where the eye
  finds it.
- 83 documents change in one sweep. The diff is one deleted line each and no
  document's meaning changes, but it is a wide diff to review.
- A document that genuinely needs a status-like banner in its body — a
  superseded one, say — must express it as a banner (category 2 territory),
  not as a `**Status:**` line.

### Neutral

- The ratchet's ledger stays empty. Refilling it remains possible and remains
  an expansion requiring a landed grant (#534).
- No tooling migration is needed: nothing but this gate ever read these lines.

## Acceptance criteria

- [x] **AC-1** No file under `docs/adr/` or `docs/specs/` carries a body
      `**Status:**` line, in either the bare or the list-item spelling.
- [x] **AC-2** The gate reports a `body-status-line` finding for a body status
      line that *agrees* with its front matter. This is the criterion that
      makes the retirement durable rather than a one-time sweep, and the case
      the previous agreement check let through.
- [x] **AC-3** The gate reports the same finding whatever form or value the
      line carries: the list-item spelling, a disagreeing value, a value
      dressed up with trailing prose, and an empty one.
- [x] **AC-4** Categories 2 and 3 are unchanged — a banner naming a
      replacement the front matter does not record, and unqualified
      status-asserting prose on a superseded document, each still fail on
      their own, driven independently.
